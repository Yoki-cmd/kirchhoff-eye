# -*- coding: utf-8 -*-
"""The future perception frontend has an explicit, honest public boundary."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "references" / "perception-roadmap.md"


def test_perception_roadmap_documents_scope_architecture_and_status_policy():
    assert ROADMAP.exists()
    text = ROADMAP.read_text(encoding="utf-8").lower()

    for phrase in (
        "short edge >= 600 px",
        "<= 15 components",
        "<= 2 complex multi-terminal components",
        "preprocess",
        "symbol candidates",
        "wire graph",
        "junction/crossing candidates",
        "pin attachment evidence",
        "global consistency solver",
        "candidate ir",
        "review queue",
        "needs_human",
        "zero blocking topology ambiguity",
        "local finite-choice adjudication",
        "do not ask one whole-image call",
    ):
        assert phrase in text


def test_public_docs_link_the_roadmap_and_describe_bounded_perception_honestly():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "references/perception-roadmap.md" in readme
    assert "references/perception-roadmap.md" in skill
    assert "experimental bounded perception" in readme.lower()
    assert "does **not** claim autonomous arbitrary-image" in readme.lower()
    assert "needs_human" in readme


def test_perception_dependencies_remain_out_of_the_default_package():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()

    assert "opencv" not in pyproject
    assert "scipy" not in pyproject
    assert "networkx" not in pyproject
