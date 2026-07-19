# -*- coding: utf-8 -*-
"""Same-job state transitions and atomic targets are concurrency-safe."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import json
import os
import subprocess
import shutil
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"
SOURCE_A = ROOT / "tests" / "golden" / "A" / "golden.png"


def test_job_lock_serializes_same_job_critical_sections(tmp_path):
    import kirchhoff_eye.pipeline as pipeline

    active = 0
    maximum = 0
    guard = threading.Lock()

    def worker():
        nonlocal active, maximum
        with pipeline._job_lock(tmp_path):
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.05)
            with guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _index: worker(), range(2)))

    assert maximum == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows msvcrt cross-process regression")
def test_windows_job_lock_serializes_independent_processes(tmp_path):
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from kirchhoff_eye.pipeline import _job_lock\n"
        "with _job_lock(Path(sys.argv[1])):\n"
        " print('locked', flush=True)\n"
        " time.sleep(0.25)\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        for _index in range(2)
    ]
    results = [process.communicate(timeout=10) for process in processes]

    assert [process.returncode for process in processes] == [0, 0], results
    assert [stdout.strip() for stdout, _stderr in results] == ["locked", "locked"]


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel mutex regression")
def test_windows_job_lock_needs_no_racy_lock_file_initialization(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline

    monkeypatch.setattr(
        os, "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Windows job locking must not initialize a byte-lock file")
        ),
    )

    with pipeline._job_lock(tmp_path):
        pass

    assert not (tmp_path / ".kirchhoff-eye.lock").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows msvcrt initialization race regression")
def test_windows_job_lock_initialization_is_race_free(tmp_path):
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from kirchhoff_eye.pipeline import _job_lock\n"
        "ready,start,job = map(Path, sys.argv[1:])\n"
        "ready.touch()\n"
        "while not start.exists(): time.sleep(0.001)\n"
        "with _job_lock(job): time.sleep(0.01)\n"
    )
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for round_number in range(20):
        round_dir = tmp_path / ("round-%02d" % round_number)
        round_dir.mkdir()
        start = round_dir / "start"
        ready_paths = [round_dir / "ready-1", round_dir / "ready-2"]
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(ready), str(start), str(round_dir / "job")],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                env=environment,
            )
            for ready in ready_paths
        ]
        deadline = time.monotonic() + 10
        while not all(path.exists() for path in ready_paths):
            if time.monotonic() >= deadline:
                pytest.fail("cross-process lock workers did not become ready")
            time.sleep(0.005)
        start.touch()
        results = [process.communicate(timeout=10) for process in processes]

        assert [process.returncode for process in processes] == [0, 0], results


@pytest.mark.parametrize("operation", ["build", "review", "approve", "repair"])
def test_lifecycle_operations_enter_the_job_lock(tmp_path, monkeypatch, operation):
    import kirchhoff_eye.pipeline as pipeline

    calls = []

    @contextmanager
    def lock_probe(output):
        calls.append(output)
        raise RuntimeError("lock probe")
        yield

    monkeypatch.setattr(pipeline, "_job_lock", lock_probe)
    if operation == "build":
        rc = pipeline.build(str(tmp_path / "candidate.json"), str(tmp_path))
    elif operation == "review":
        rc = pipeline.review(str(tmp_path), str(tmp_path / "review.json"))
    elif operation == "approve":
        rc = pipeline.approve(str(tmp_path))
    else:
        rc = pipeline.repair(
            str(tmp_path), str(tmp_path / "candidate.json"), str(tmp_path / "patches.json")
        )

    assert rc == pipeline.EXIT_ENV
    assert calls == [tmp_path.resolve()]


def test_atomic_copy_uses_a_unique_target_side_temp_file(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline

    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    target = tmp_path / "target.txt"
    seen = []
    original = shutil.copy2

    def copy_spy(src, dst, *args, **kwargs):
        if Path(dst).parent == target.parent and Path(dst) != target:
            seen.append(Path(dst))
        return original(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy_spy)
    pipeline._atomic_copy(source, target)
    pipeline._atomic_copy(source, target)

    assert len(seen) == 2
    assert seen[0] != seen[1]


def test_json_write_uses_a_unique_target_side_temp_file(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline

    target = tmp_path / "state.json"
    seen = []
    original = Path.replace

    def replace_spy(self, destination):
        if Path(destination) == target:
            seen.append(self)
        return original(self, destination)

    monkeypatch.setattr(Path, "replace", replace_spy)
    pipeline._write_json(target, {"value": 1})
    pipeline._write_json(target, {"value": 2})

    assert len(seen) == 2
    assert seen[0] != seen[1]

@pytest.mark.tex
def test_concurrent_reviews_serialize_to_one_immutable_winner(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    latest = state["rounds"][0]
    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))

    def assessment(verdict, claims):
        return {
            "version": "kirchhoff-electrical-assessment/1.0",
            "candidate_ir_sha256": latest["ir_sha256"],
            "audit_sha256": latest["electrical_audit_sha256"],
            "verdict": verdict, "summary": "concurrent review probe", "claims": claims,
        }

    clean = {
        "round": 1,
        "regions": [{"name": item["name"], "conclusion": "no_difference", "summary": "clean"}
                    for item in ir["regions"]],
        "differences": [], "electrical_assessment": assessment("pass", []),
    }
    difference = {
        "round": 1,
        "regions": [
            {"name": item["name"],
             "conclusion": "differences" if index == 0 else "no_difference",
             "summary": "difference" if index == 0 else "clean"}
            for index, item in enumerate(ir["regions"])
        ],
        "differences": [{
            "id": "D1", "region": ir["regions"][0]["name"],
            "location": "grid (2,2)", "category": "wrong_position",
            "description": "R1 label position differs", "patch_operation": "MOVE",
            "ir_path": "/components/1/label_at",
        }],
        "electrical_assessment": assessment("requires_repair", [{
            "id": "AIC1", "severity": "warning", "basis": "source_evidence",
            "ir_paths": ["/components/1/label_at"],
            "description": "The source review requires a label repair.",
            "assumptions": ["The comparison is reliable."], "confidence": 0.99,
            "disposition": "repair_ir", "linked_difference_id": "D1",
            "rationale": "Use the reviewed repair workflow.",
        }]),
    }
    clean_path = tmp_path / "clean.json"
    difference_path = tmp_path / "difference.json"
    clean_path.write_text(json.dumps(clean), encoding="utf-8")
    difference_path.write_text(json.dumps(difference), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda path: main(["review", str(job), str(path)]),
            (clean_path, difference_path),
        ))

    assert sorted(results) == [0, 2]
    final = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert final["rounds"][0]["reviewed"] is True
    assert len(final["rounds"][0]["differences"]) in (0, 1)
    assert (job / "DELIVERY.md").is_file()
