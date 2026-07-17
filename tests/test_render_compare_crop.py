# -*- coding: utf-8 -*-
"""render / compare / crop 测试：真实小编译 + 合成图 + 错误路径。"""
import subprocess

import pytest
from PIL import Image

import compare
import crop
import render


TINY_TEX = ("\\documentclass[margin=2pt]{standalone}\n"
            "\\usepackage[american]{circuitikz}\n"
            "\\begin{document}\\begin{circuitikz}\n"
            "\\draw (0,0) to[R] (2,0);\n"
            "\\end{circuitikz}\\end{document}\n")
BAD_TEX = ("\\documentclass{standalone}\\begin{document}"
           "\\undefinedmacro\\end{document}\n")


# ---------------------------------------------------------------- render

def test_pick_engine():
    assert render.pick_engine("abc", "auto") == "pdflatex"
    assert render.pick_engine("电路", "auto") == "lualatex"
    assert render.pick_engine("电路", "pdflatex") == "pdflatex"


def test_pick_engine_ignores_comments():
    assert render.pick_engine("% 中文注释\n\\draw (0,0);", "auto") == "pdflatex"
    assert render.pick_engine("\\node {电阻}; % 注释", "auto") == "lualatex"


def test_render_ok(tmp_path):
    tex = tmp_path / "t.tex"
    tex.write_text(TINY_TEX, encoding="utf-8")
    out = tmp_path / "t.png"
    assert render.main([str(tex), "-o", str(out), "--dpi", "150"]) == 0
    im = Image.open(str(out))
    assert im.width > 50 and im.height > 10


def test_render_also_renders_matching_debug_tex(tmp_path):
    tex = tmp_path / "circuit.tex"
    debug_tex = tmp_path / "circuit.debug.tex"
    tex.write_text(TINY_TEX, encoding="utf-8")
    debug_tex.write_text(TINY_TEX, encoding="utf-8")
    out = tmp_path / "circuit.png"
    assert render.main([str(tex), "-o", str(out), "--dpi", "150"]) == 0
    assert (tmp_path / "circuit.debug.png").exists()


def test_render_compile_fail(tmp_path, capsys):
    tex = tmp_path / "bad.tex"
    tex.write_text(BAD_TEX, encoding="utf-8")
    out = tmp_path / "bad.png"
    rc = render.main([str(tex), "-o", str(out)])
    captured = capsys.readouterr().out
    assert rc == 2 and not out.exists()
    assert "COMPILE FAIL" in captured
    assert "完整 log" in captured
    body = [l for l in captured.splitlines()
            if l.startswith("  ")]  # 摘要行
    assert 0 < len(body) <= 10


def test_render_missing_file(tmp_path):
    assert render.main(["no.tex", "-o", str(tmp_path / "x.png")]) == 3


def test_render_engine_not_found(tmp_path, monkeypatch):
    tex = tmp_path / "t.tex"
    tex.write_text(TINY_TEX, encoding="utf-8")

    def boom(*_a, **_k):
        raise FileNotFoundError("pdflatex")
    monkeypatch.setattr(render.subprocess, "run", boom)
    assert render.main([str(tex), "-o", str(tmp_path / "t.png")]) == 3


def test_render_timeout(tmp_path, monkeypatch):
    tex = tmp_path / "t.tex"
    tex.write_text(TINY_TEX, encoding="utf-8")

    def slow(cmd, **_k):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(render.subprocess, "run", slow)
    assert render.main([str(tex), "-o", str(tmp_path / "t.png"),
                        "--timeout", "1"]) == 3


@pytest.mark.parametrize("engine", ["pdflatex", "lualatex"])
def test_latex_runs_with_shell_escape_disabled(tmp_path, monkeypatch, engine):
    tex = tmp_path / "t.tex"
    tex.write_text(TINY_TEX, encoding="utf-8")
    seen = {}

    class Result:
        returncode = 0

    def capture(cmd, **_kwargs):
        seen["cmd"] = cmd
        return Result()

    monkeypatch.setattr(render.subprocess, "run", capture)

    assert render.run_latex(engine, str(tex), 30) == 0
    assert seen["cmd"].count("-no-shell-escape") == 1
    assert "-shell-escape" not in seen["cmd"]


def test_summarize_log():
    log = "junk\n! Undefined control sequence.\nl.3 \\undefinedmacro\nmore\n"
    lines = render.summarize_log(log)
    assert lines[0].startswith("!") and len(lines) <= 10
    assert render.summarize_log("no error")[0].startswith("(log")


# ---------------------------------------------------------------- compare

@pytest.fixture
def two_pngs(tmp_path):
    from PIL import ImageDraw
    a = Image.new("RGB", (400, 300), (255, 255, 255))
    ImageDraw.Draw(a).rectangle([50, 50, 150, 100], outline=(0, 0, 0), width=3)
    b = Image.new("RGB", (380, 290), (255, 255, 255))
    ImageDraw.Draw(b).rectangle([60, 55, 160, 105], outline=(0, 0, 0), width=3)
    pa, pb = tmp_path / "a.png", tmp_path / "b.png"
    a.save(str(pa))
    b.save(str(pb))
    return pa, pb


def test_compare_side(tmp_path, two_pngs):
    pa, pb = two_pngs
    out = tmp_path / "cmp.png"
    assert compare.main([str(pa), str(pb), "-o", str(out)]) == 0
    im = Image.open(str(out))
    assert im.height == 1200 + compare.BANNER_H
    assert im.width > 1200  # 两幅 4:3 图并排


def test_compare_overlay(tmp_path, two_pngs):
    pa, pb = two_pngs
    out = tmp_path / "ov.png"
    assert compare.main([str(pa), str(pb), "-o", str(out),
                         "--mode", "overlay"]) == 0
    im = Image.open(str(out))
    # overlay 尺寸 = 原图内容 bbox（矩形 50,50-150,100 线宽 3 => 约 104x54）
    assert 90 < im.width < 120 and 40 < im.height < 70
    colors = im.getcolors(maxcolors=100000)
    assert any(px[0] > px[1] + 40 for _cnt, px in colors)  # 有偏红像素


def test_compare_both(tmp_path, two_pngs):
    pa, pb = two_pngs
    out = tmp_path / "both.png"
    assert compare.main([str(pa), str(pb), "-o", str(out), "--mode", "both"]) == 0
    assert Image.open(str(out)).height > 1200 + compare.BANNER_H


def test_compare_missing_input(tmp_path, two_pngs):
    pa, _pb = two_pngs
    assert compare.main([str(pa), "no.png", "-o", str(tmp_path / "x.png")]) == 3


# ---------------------------------------------------------------- crop

def test_crop_basic(tmp_path, two_pngs):
    pa, _pb = two_pngs
    out = tmp_path / "c.png"
    rc = crop.main([str(pa), "-o", str(out), "--rect", "50,50,150,100",
                    "--pad", "10", "--scale", "2"])
    assert rc == 0
    im = Image.open(str(out))
    assert im.size == (240, 140)  # (100+20)*2 x (50+20)*2


def test_crop_ruler(tmp_path, two_pngs):
    pa, _pb = two_pngs
    out = tmp_path / "cr.png"
    rc = crop.main([str(pa), "-o", str(out), "--rect", "50,50,150,100",
                    "--pad", "0", "--scale", "2", "--ruler"])
    assert rc == 0
    im = Image.open(str(out))
    assert im.size == (200 + crop.RULER_MARGIN, 100 + crop.RULER_MARGIN)


def test_crop_bad_rect(tmp_path, two_pngs):
    pa, _pb = two_pngs
    assert crop.main([str(pa), "-o", str(tmp_path / "x.png"),
                      "--rect", "10,10"]) == 3
    assert crop.main([str(pa), "-o", str(tmp_path / "x.png"),
                      "--rect", "100,100,50,50"]) == 3


def test_crop_missing_image(tmp_path):
    assert crop.main(["no.png", "-o", str(tmp_path / "x.png"),
                      "--rect", "0,0,10,10"]) == 3


def test_crop_clamps_to_image(tmp_path, two_pngs):
    pa, _pb = two_pngs
    out = tmp_path / "cl.png"
    rc = crop.main([str(pa), "-o", str(out), "--rect", "380,280,500,400",
                    "--pad", "0", "--scale", "1"])
    assert rc == 0
    assert Image.open(str(out)).size == (20, 20)
