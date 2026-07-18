#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""render.py — .tex → .png（pdflatex/lualatex + pdftoppm，不用 ImageMagick）。

用法: render.py in.tex -o out.png [--dpi 300] [--engine auto|pdflatex|lualatex] [--timeout 120]
退出码: 0 成功 / 2 编译失败（stdout 给 ≤10 行错误摘要，完整 log 在 tex 旁）/ 3 环境或 IO 错误
--engine auto：tex 含非 ASCII → lualatex（配合 ctex），否则 pdflatex。
压缩 LaTeX log 是本工具的职责，不是模型的。
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys

import irlib

SUMMARY_MAX_LINES = 10


def pick_engine(tex_text, engine_arg):
    if engine_arg != "auto":
        return engine_arg
    return "lualatex" if irlib.tex_content_has_cjk(tex_text) else "pdflatex"


def summarize_log(log_text):
    """提取首个 '!' 错误 + 行号上下文，≤10 行。"""
    lines = log_text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith("!"):
            for l2 in lines[i:i + 6]:
                out.append(l2)
                if len(out) >= SUMMARY_MAX_LINES - 1:
                    break
            break
    if not out:
        out = ["(log 中未找到 ! 错误行，检查完整 log)"]
    return out[:SUMMARY_MAX_LINES]


def run_latex(engine, tex_path, timeout):
    workdir = os.path.dirname(os.path.abspath(tex_path)) or "."
    cmd = [engine, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
           os.path.basename(tex_path)]
    try:
        proc = subprocess.run(cmd, cwd=workdir, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except FileNotFoundError:
        sys.stderr.write("ERROR: 找不到 %s（应随 TeX Live 2026 在 PATH 上）\n" % engine)
        return irlib.EXIT_ENV
    except subprocess.TimeoutExpired:
        sys.stderr.write("ERROR: %s 编译超时\n" % engine)
        return irlib.EXIT_ENV
    return proc.returncode


def run_pdftoppm(pdf_path, out_png, dpi, timeout):
    base = out_png[:-4] if out_png.lower().endswith(".png") else out_png
    cmd = ["pdftoppm", "-png", "-r", str(dpi), "-singlefile", pdf_path, base]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except FileNotFoundError:
        sys.stderr.write("ERROR: 找不到 pdftoppm（应随 TeX Live 2026 在 PATH 上）\n")
        return irlib.EXIT_ENV, None
    except subprocess.TimeoutExpired:
        sys.stderr.write("ERROR: pdftoppm 超时\n")
        return irlib.EXIT_ENV, None
    return proc.returncode, base + ".png"


def render_one(tex_file, output, dpi=300, engine_arg="auto", timeout=120):
    try:
        with open(tex_file, "r", encoding="utf-8") as f:
            tex_text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        sys.stderr.write("ERROR: 无法读取 tex: %s\n" % e)
        return irlib.EXIT_ENV

    engine = pick_engine(tex_text, engine_arg)
    rc = run_latex(engine, tex_file, timeout)
    if rc == irlib.EXIT_ENV:
        return irlib.EXIT_ENV

    stem = os.path.splitext(os.path.abspath(tex_file))[0]
    pdf_path, log_path = stem + ".pdf", stem + ".log"
    if rc != 0 or not os.path.exists(pdf_path):
        log_text = ""
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                log_text = f.read()
        sys.stdout.write("COMPILE FAIL (%s)：\n" % engine)
        for line in summarize_log(log_text):
            sys.stdout.write("  %s\n" % line)
        sys.stdout.write("完整 log: %s\n" % log_path)
        return irlib.EXIT_ERROR

    rc2, png = run_pdftoppm(pdf_path, output, dpi, timeout)
    if rc2 != 0 or png is None or not os.path.exists(png):
        if rc2 != irlib.EXIT_ENV:
            sys.stderr.write("ERROR: pdftoppm 转换失败 (rc=%s)\n" % rc2)
        return irlib.EXIT_ENV
    if os.path.abspath(png) != os.path.abspath(output):
        os.replace(png, output)
    sys.stdout.write("OK %s -> %s (engine=%s, dpi=%d)\n"
                     % (os.path.basename(tex_file), output, engine, dpi))
    return irlib.EXIT_OK


def main(argv=None):
    irlib.ensure_utf8_io()
    ap = argparse.ArgumentParser(description=".tex -> .png 渲染")
    ap.add_argument("tex_file")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--engine", choices=("auto", "pdflatex", "lualatex"),
                    default="auto")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args(argv)

    jobs = [(args.tex_file, args.output)]
    if not args.tex_file.endswith(".debug.tex"):
        debug_tex = os.path.splitext(args.tex_file)[0] + ".debug.tex"
        if os.path.exists(debug_tex):
            debug_png = os.path.splitext(args.output)[0] + ".debug.png"
            jobs.append((debug_tex, debug_png))

    if len(jobs) == 1:
        return render_one(jobs[0][0], jobs[0][1], args.dpi, args.engine, args.timeout)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                render_one, tex_file, output, args.dpi, args.engine, args.timeout
            )
            for tex_file, output in jobs
        ]
        results = [future.result() for future in futures]
    if irlib.EXIT_ENV in results:
        return irlib.EXIT_ENV
    if any(result != irlib.EXIT_OK for result in results):
        return irlib.EXIT_ERROR
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
