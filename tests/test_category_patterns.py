import polars as pl
import pytest
from moneyflow.data.category_patterns import CategoryPattern, CategoryPatternMatcher, _compile_glob


def test_compile_glob_matches_substring():
    regex = _compile_glob("*WHOLEFDS*")
    assert regex.match("WHOLEFDS MARKET")
    assert regex.match("TST WHOLEFDS #1234")
    assert not regex.match("SPOTIFY")


def test_category_pattern_defaults():
    pattern = CategoryPattern(pattern="*SPOTIFY*", category="Subscriptions")
    assert pattern.fields == ("merchant", "description", "notes")
    assert pattern.only_when_uncategorized is True
    assert pattern.enabled is True
    assert pattern.description is None


def test_suggests_category_for_uncategorized_transaction():
    df = pl.DataFrame(
        {
            "id": ["txn1", "txn2"],
            "merchant": ["WHOLEFDS MARKET", "SPOTIFY USA"],
            "description": ["", ""],
            "notes": ["", ""],
            "category": ["Uncategorized", "Uncategorized"],
        }
    )
    patterns = [
        CategoryPattern(pattern="*WHOLEFDS*", category="Groceries"),
        CategoryPattern(pattern="*SPOTIFY*", category="Subscriptions"),
    ]
    matcher = CategoryPatternMatcher(patterns)
    result = matcher.suggest(df)

    assert result["suggested_category"].to_list() == ["Groceries", "Subscriptions"]


def test_only_when_uncategorized_default_blocks_override():
    df = pl.DataFrame(
        {
            "id": ["txn1"],
            "merchant": ["WHOLEFDS MARKET"],
            "description": [""],
            "notes": [""],
            "category": ["Shopping"],
        }
    )
    patterns = [CategoryPattern(pattern="*WHOLEFDS*", category="Groceries")]
    matcher = CategoryPatternMatcher(patterns)
    result = matcher.suggest(df)

    assert result["suggested_category"][0] is None


def test_records_all_matching_patterns():
    df = pl.DataFrame(
        {
            "id": ["txn1"],
            "merchant": ["AMAZON MARKETPLACE"],
            "description": [""],
            "notes": [""],
            "category": ["Uncategorized"],
        }
    )
    patterns = [
        CategoryPattern(pattern="*AMAZON*", category="Shopping"),
        CategoryPattern(pattern="*MARKETPLACE*", category="Online Shopping"),
    ]
    matcher = CategoryPatternMatcher(patterns)
    result = matcher.suggest(df)

    assert result["suggested_category"][0] == "Shopping"
    assert "*AMAZON*" in result["matching_patterns"][0]
    assert "*MARKETPLACE*" in result["matching_patterns"][0]
