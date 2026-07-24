"""User-defined category pattern engine."""

import re
from dataclasses import dataclass
from typing import Optional, Tuple


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
