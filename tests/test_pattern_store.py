from pathlib import Path

import pytest

from moneyflow.data.category_patterns import CategoryPattern
from moneyflow.data.pattern_store import PatternStore


def test_load_patterns_from_config(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text(
        """
version: 1
category_patterns:
  - pattern: "*WHOLEFDS*"
    category: "Groceries"
    fields: ["merchant", "description"]
    only_when_uncategorized: true
    enabled: true
"""
    )
    store = PatternStore(profile_dir=tmp_path)
    patterns = store.load_patterns()

    assert len(patterns) == 1
    assert patterns[0] == CategoryPattern(
        pattern="*WHOLEFDS*",
        category="Groceries",
        fields=("merchant", "description"),
        only_when_uncategorized=True,
        enabled=True,
    )


def test_save_and_load_patterns(tmp_path: Path):
    store = PatternStore(profile_dir=tmp_path)
    patterns = [CategoryPattern(pattern="*SPOTIFY*", category="Subscriptions")]
    store.save_patterns(patterns)

    loaded = store.load_patterns()
    assert loaded == patterns


def test_load_rejected_suggestions(tmp_path: Path):
    store = PatternStore(profile_dir=tmp_path)
    store.save_rejected({"txn1", "txn2"})

    assert store.load_rejected() == {"txn1", "txn2"}
