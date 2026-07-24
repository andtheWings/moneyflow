import pytest
from moneyflow.data.category_patterns import CategoryPattern, _compile_glob


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
