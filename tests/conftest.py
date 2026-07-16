# -*- coding: utf-8 -*-
"""pytest 共用夹具：金样装载、validate CLI 运行器。"""
import copy
import json
import os
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

GOLDEN_A = os.path.join(ROOT, "tests", "golden", "A", "ir.json")
GOLDEN_B = os.path.join(ROOT, "tests", "golden", "B", "ir.json")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def golden_a():
    return copy.deepcopy(_load(GOLDEN_A))


@pytest.fixture
def golden_b():
    return copy.deepcopy(_load(GOLDEN_B))


@pytest.fixture
def vrun(tmp_path, capsys):
    """把 IR dict 落盘并跑 validate_ir.main，返回 (exit_code, 报告 dict)。"""
    import validate_ir

    def _run(ir, phase="full"):
        p = tmp_path / "ir.json"
        p.write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
        rc = validate_ir.main([str(p), "--phase", phase, "--json"])
        out = json.loads(capsys.readouterr().out)
        return rc, out
    return _run


def codes(out):
    return {f["code"] for f in out["findings"]}
