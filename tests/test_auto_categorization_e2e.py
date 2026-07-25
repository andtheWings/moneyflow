"""End-to-end smoke test for user-defined auto-categorization."""

from pathlib import Path

import polars as pl
import pytest

from moneyflow.data.category_patterns import CategoryPattern, CategoryPatternMatcher
from moneyflow.data.commit_orchestrator import apply_suggested_category_edit
from moneyflow.data.pattern_store import PatternStore


def test_auto_categorization_e2e(tmp_path: Path):
    store = PatternStore(profile_dir=tmp_path)
    store.save_patterns([CategoryPattern(pattern="*SYNTH MERCHANT*", category="Shopping")])

    df = pl.DataFrame(
        {
            "id": ["txn_synth_1", "txn_synth_2"],
            "merchant": ["SYNTH MERCHANT #1", "OTHER MERCHANT"],
            "description": ["", ""],
            "notes": ["", ""],
            "category_id": ["cat_uncategorized", "cat_uncategorized"],
            "category": ["Uncategorized", "Uncategorized"],
            "group": ["Uncategorized", "Uncategorized"],
        }
    )

    patterns = store.load_patterns()
    matcher = CategoryPatternMatcher(patterns)
    df = matcher.suggest(df)

    assert df["suggested_category"].to_list() == ["Shopping", None]

    df = apply_suggested_category_edit(
        df, "txn_synth_1", "cat_shopping", "Shopping", "Travel & Lifestyle"
    )

    assert df["category"][0] == "Shopping"
    assert df["group"][0] == "Travel & Lifestyle"
    assert df["suggested_category"][0] is None
