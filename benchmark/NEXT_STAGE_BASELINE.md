# Next-stage baseline — Kirchhoff-eye

Baseline date: 2026-07-18

## Repository state

- Repository: repository root (`.`)
- Baseline branch: `main`
- Baseline commit: `3368a4abee03baccb120f06edfbd05e17d561e47`
- Baseline tracked worktree: clean before next-stage implementation
- Interpreter used: external Miniconda Python 3.11 environment
- Environment isolation: inherited `PYTHONPATH` removed for external-Python verification

## Test and performance baseline

| Gate | Command | Result |
|---|---|---|
| Fast suite | `env -u PYTHONPATH '/e/Miniconda/python.exe' -m pytest tests -q -m 'not tex and not synthetic'` | 255 passed, 79 deselected, 35.91 s |
| Real TeX suite | `env -u PYTHONPATH '/e/Miniconda/python.exe' -m pytest tests -q -m tex` | 71 passed, 263 deselected, 157.26 s |
| Synthetic E2E | `env -u PYTHONPATH '/e/Miniconda/python.exe' -m pytest tests/test_synthetic_e2e.py -q -n auto` | 8 passed, 149.35 s |
| Source-backed pipeline benchmark | `env -u PYTHONPATH '/e/Miniconda/python.exe' benchmark/perf/benchmark_pipeline.py --runs 5 --warmup 1 --json` | P50 3.4069 s; P95 5.9668 s |

Pipeline stage P50 values at 120 DPI:

| Stage | Seconds |
|---|---:|
| validation | 0.0065 |
| serialization | 0.0081 |
| render | 3.0610 |
| layout | 0.00003 |
| compare | 0.2649 |
| persisted total | 3.3459 |

## Clean review / approve workflow baseline

A real source-backed job was built from Golden A at:

`out/baseline-clean-review`

The exact canonical flow completed successfully:

1. `build` created round 1 in `needs_review`.
2. A complete three-region review with zero differences was submitted.
3. `approve` rechecked live IR/source/comparison hashes and produced `approved`.

Readback evidence:

- final state: `approved`
- validation: `ok`, zero findings
- layout: `ok`, zero findings
- build total at 72 DPI: 1.8690 s
- approved IR SHA-256: `88593aaa282103a42f31d9cb985cc7310ff1736a59b222d4ef89fe5be909289d`

This is the deterministic workflow latency baseline. Human workstation correction time is tracked separately in the Paper baseline because the existing Paper panel requires manually authored JSON.

## Next-stage contract changes after baseline

Phase 1 adds only a separate perception evidence sidecar contract. Canonical `kirchhoff-ir/1.0`, validator, serializer, renderer, and review-state semantics remain unchanged.
