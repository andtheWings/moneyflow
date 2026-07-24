"""User-defined category pattern engine."""

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import polars as pl


@dataclass(frozen=True)
class CategoryPattern:
    """A single user-defined categorization rule."""

    pattern: str
    category: str
    fields: Tuple[str, ...] = ("merchant", "description", "notes")
    only_when_uncategorized: bool = True
    enabled: bool = True
    description: Optional[str] = None


def _compile_glob(pattern: str) -> re.Pattern:
    """Convert a glob/keyword pattern to a case-insensitive regex."""
    escaped = re.escape(pattern)
    # Re-enable glob wildcards after escaping literal characters.
    escaped = escaped.replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(escaped, re.IGNORECASE)


def _field_text(row: dict, field: str) -> str:
    """Safely extract text from a row for a given field."""
    value = row.get(field)
    if value is None:
        return ""
    return str(value)


class CategoryPatternMatcher:
    """Evaluate category patterns against a transaction DataFrame."""

    SUGGESTION_COLUMN = "suggested_category"
    MATCHING_PATTERNS_COLUMN = "matching_patterns"

    def __init__(self, patterns: Iterable[CategoryPattern]):
        self.patterns = [p for p in patterns if p.enabled]
        self._compiled = {p: _compile_glob(p.pattern) for p in self.patterns}

    def _matches(self, pattern: CategoryPattern, row: dict) -> bool:
        """Return True if a pattern matches any configured field in the row."""
        regex = self._compiled[pattern]
        for field in pattern.fields:
            text = _field_text(row, field)
            if text and regex.search(text):
                return True
        return False

    def _row_suggestion(self, row: dict) -> tuple[Optional[str], List[str]]:
        """Return (winning_category, all_matching_patterns) for a row."""
        current_category = row.get("category", "") or ""
        is_uncategorized = current_category in ("", "Uncategorized")

        matching_patterns: List[str] = []
        winner: Optional[str] = None
        for pattern in self.patterns:
            if not self._matches(pattern, row):
                continue
            matching_patterns.append(pattern.pattern)
            if winner is None:
                if pattern.only_when_uncategorized and not is_uncategorized:
                    continue
                winner = pattern.category
        return winner, matching_patterns

    def suggest(self, df: pl.DataFrame) -> pl.DataFrame:
        """Add suggested_category and matching_patterns columns to df."""
        if df.is_empty():
            return df.with_columns(
                pl.lit(None).alias(self.SUGGESTION_COLUMN),
                pl.lit(None).alias(self.MATCHING_PATTERNS_COLUMN),
            )

        suggestions: List[Optional[str]] = []
        all_matches: List[Optional[List[str]]] = []
        for row in df.iter_rows(named=True):
            winner, matches = self._row_suggestion(row)
            suggestions.append(winner)
            all_matches.append(matches if matches else None)

        return df.with_columns(
            pl.Series(self.SUGGESTION_COLUMN, suggestions),
            pl.Series(self.MATCHING_PATTERNS_COLUMN, all_matches),
        )
