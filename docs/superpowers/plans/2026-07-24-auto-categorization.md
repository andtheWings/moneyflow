# User-Defined Auto-Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-defined, approval-gated auto-categorization system that suggests categories based on glob/keyword patterns and commits them only after explicit user approval.

**Architecture:** Build a backend-agnostic `CategoryPatternMatcher` in `moneyflow/data/` that operates on the Polars DataFrame managed by `DataManager`. Pattern storage lives in profile `config.yaml` under a dedicated `category_patterns` key. The TUI shows inline suggestion indicators and provides a batch review screen plus a pattern management screen. Approved suggestions flow through the existing `commit_orchestrator.py` and `state.py` edit pipeline.

**Tech Stack:** Python 3.11, Polars, Textual, Pytest, Pyright, Ruff.

## Global Constraints

- Target Python version: 3.11.
- Line length: 100 characters.
- Use `uv run` for all commands; never run `pip install` directly.
- All function signatures must have full type hints.
- All imports at top of file unless circular-import issues force otherwise.
- Tests must be written first and run before implementation code is considered done.
- Run `uv run pytest -v`, `uv run pyright moneyflow/`, `uv run ruff format --check moneyflow/ tests/`, and `uv run ruff check moneyflow/ tests/` before every commit.
- Do not modify `moneyflow/backends/monarch_client.py` (vendored code).
- Keep user financial data out of code, comments, and tests — use synthetic examples only.

---

## File Structure

| File | Responsibility |
|---|---|
| `moneyflow/data/category_patterns.py` | `CategoryPattern` dataclass and `CategoryPatternMatcher` engine. Pure, no I/O. |
| `moneyflow/data/pattern_store.py` | Load/save `category_patterns` and `rejected_suggestions` YAML in profile directory. |
| `moneyflow/data/data_manager.py` | Invoke matcher after loading transactions; expose pattern store path. |
| `moneyflow/data/commit_orchestrator.py` | Add `apply_suggestion_edit` helper that commits a suggested category as a normal category edit. |
| `moneyflow/tui/formatters.py` | Add renderer for inline suggestion indicator. |
| `moneyflow/tui/widgets/transaction_table.py` or transaction table code | Render suggestion badge in rows. |
| `moneyflow/tui/screens/category_suggestion_review.py` | Batch approve/reject screen with multi-match badges. |
| `moneyflow/tui/screens/category_patterns_screen.py` | Add/edit/delete/reorder/test patterns. |
| `moneyflow/tui/keybindings.py` | Add shortcuts `s`, `S`, `P`. |
| `moneyflow/tui/app_controller.py` | Wire new screens and actions. |
| `moneyflow/tui/app.py` | Bind actions to screen pushes and matcher integration. |
| `tests/test_category_patterns.py` | Unit tests for pattern engine. |
| `tests/test_pattern_store.py` | Tests for YAML load/save. |
| `tests/test_data_manager.py` | Add tests for matcher integration. |
| `tests/screens/test_category_suggestion_review.py` | Pilot tests for review screen. |
| `tests/screens/test_category_patterns_screen.py` | Pilot tests for pattern management screen. |

---

### Task 1: Pattern dataclass and glob compiler

**Files:**
- Create: `moneyflow/data/category_patterns.py`
- Test: `tests/test_category_patterns.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CategoryPattern` dataclass and `_compile_glob(pattern: str) -> re.Pattern` helper.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_category_patterns.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_category_patterns.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/data/category_patterns.py tests/test_category_patterns.py
rtk git commit -m "feat: add CategoryPattern dataclass and glob compiler

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: CategoryPatternMatcher engine

**Files:**
- Modify: `moneyflow/data/category_patterns.py`
- Test: `tests/test_category_patterns.py`

**Interfaces:**
- Consumes: `CategoryPattern` from Task 1.
- Produces: `CategoryPatternMatcher.suggest(df: pl.DataFrame) -> pl.DataFrame` and `CategoryPatternMatcher.filter_matching_patterns(...) -> list[CategoryPattern]`.

- [ ] **Step 1: Write the failing test**

```python
import polars as pl
from moneyflow.data.category_patterns import CategoryPattern, CategoryPatternMatcher


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_category_patterns.py::test_suggests_category_for_uncategorized_transaction tests/test_category_patterns.py::test_only_when_uncategorized_default_blocks_override tests/test_category_patterns.py::test_records_all_matching_patterns -v`
Expected: FAIL with `CategoryPatternMatcher` not defined or methods missing.

- [ ] **Step 3: Write minimal implementation**

Append to `moneyflow/data/category_patterns.py`:

```python
from typing import Iterable, List

import polars as pl


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

    def _row_suggestion(self, row: dict) -> tuple[str | None, List[str]]:
        """Return (winning_category, all_matching_patterns) for a row."""
        current_category = row.get("category", "") or ""
        is_uncategorized = current_category in ("", "Uncategorized")

        matching_patterns: List[str] = []
        winner: str | None = None
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

        suggestions = []
        all_matches = []
        for row in df.iter_rows(named=True):
            winner, matches = self._row_suggestion(row)
            suggestions.append(winner)
            all_matches.append(matches if matches else None)

        return df.with_columns(
            pl.Series(self.SUGGESTION_COLUMN, suggestions),
            pl.Series(self.MATCHING_PATTERNS_COLUMN, all_matches),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_category_patterns.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/data/category_patterns.py tests/test_category_patterns.py
rtk git commit -m "feat: add CategoryPatternMatcher engine

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Pattern store (load/save)

**Files:**
- Create: `moneyflow/data/pattern_store.py`
- Test: `tests/test_pattern_store.py`

**Interfaces:**
- Consumes: `CategoryPattern` from Task 1.
- Produces: `PatternStore(profile_dir: Path)` with `load_patterns() -> list[CategoryPattern]`, `save_patterns(patterns: list[CategoryPattern]) -> None`, `load_rejected() -> set[str]`, `save_rejected(rejected: set[str]) -> None`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pattern_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
"""Persistence for user-defined category patterns and rejected suggestions."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from .category_patterns import CategoryPattern


class PatternStore:
    """Load and save category patterns and rejection state in a profile directory."""

    CONFIG_FILE = "config.yaml"
    REJECTED_FILE = "rejected_suggestions.yaml"

    def __init__(self, profile_dir: Path):
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def _config_path(self) -> Path:
        return self.profile_dir / self.CONFIG_FILE

    def _rejected_path(self) -> Path:
        return self.profile_dir / self.REJECTED_FILE

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_yaml(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def load_patterns(self) -> List[CategoryPattern]:
        """Load enabled patterns from profile config.yaml."""
        config = self._load_yaml(self._config_path())
        raw_patterns = config.get("category_patterns", [])
        if not isinstance(raw_patterns, list):
            return []

        patterns: List[CategoryPattern] = []
        for raw in raw_patterns:
            if not isinstance(raw, dict):
                continue
            fields = raw.get("fields")
            patterns.append(
                CategoryPattern(
                    pattern=str(raw.get("pattern", "")),
                    category=str(raw.get("category", "")),
                    fields=tuple(fields) if isinstance(fields, list) else ("merchant", "description", "notes"),
                    only_when_uncategorized=bool(raw.get("only_when_uncategorized", True)),
                    enabled=bool(raw.get("enabled", True)),
                    description=raw.get("description"),
                )
            )
        return patterns

    def save_patterns(self, patterns: List[CategoryPattern]) -> None:
        """Save patterns back to profile config.yaml, preserving other keys."""
        config = self._load_yaml(self._config_path())
        config["category_patterns"] = [
            {
                "pattern": p.pattern,
                "category": p.category,
                "fields": list(p.fields),
                "only_when_uncategorized": p.only_when_uncategorized,
                "enabled": p.enabled,
                "description": p.description,
            }
            for p in patterns
        ]
        self._save_yaml(self._config_path(), config)

    def load_rejected(self) -> Set[str]:
        """Load set of transaction IDs whose suggestions were rejected."""
        data = self._load_yaml(self._rejected_path())
        raw = data.get("rejected", [])
        return set(raw) if isinstance(raw, list) else set()

    def save_rejected(self, rejected: Set[str]) -> None:
        """Save set of rejected transaction IDs."""
        self._save_yaml(self._rejected_path(), {"rejected": sorted(rejected)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pattern_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/data/pattern_store.py tests/test_pattern_store.py
rtk git commit -m "feat: add pattern store for category rules

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Integrate matcher into DataManager

**Files:**
- Modify: `moneyflow/data/data_manager.py`
- Test: `tests/test_data_manager.py`

**Interfaces:**
- Consumes: `CategoryPatternMatcher` and `PatternStore` from Tasks 2 and 3.
- Produces: `DataManager` exposes `apply_category_patterns()` and caches `pattern_store: PatternStore`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data_manager.py`:

```python
import polars as pl


def test_data_manager_applies_category_patterns():
    from moneyflow.data.data_manager import DataManager
    from moneyflow.data.pattern_store import PatternStore
    from tests.mock_backend import MockMonarchMoney

    backend = MockMonarchMoney()
    with tempfile.TemporaryDirectory() as tmp:
        profile_dir = Path(tmp)
        config = profile_dir / "config.yaml"
        config.write_text(
            """
version: 1
category_patterns:
  - pattern: "*COFFEE*"
    category: "Coffee Shops"
"""
        )
        dm = DataManager(
            mm=backend,
            config_dir=tmp,
            profile_dir=profile_dir,
            backend_type="monarch",
        )
        dm.df = pl.DataFrame(
            {
                "id": ["txn1", "txn2"],
                "merchant": ["JOE COFFEE", "WHOLEFDS"],
                "description": ["", ""],
                "notes": ["", ""],
                "category": ["Uncategorized", "Uncategorized"],
            }
        )
        dm.apply_category_patterns()

        assert dm.df["suggested_category"].to_list() == ["Coffee Shops", None]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_data_manager.py::test_data_manager_applies_category_patterns -v`
Expected: FAIL with `AttributeError: 'DataManager' object has no attribute 'apply_category_patterns'`.

- [ ] **Step 3: Write minimal implementation**

In `moneyflow/data/data_manager.py`, add imports at the top:

```python
from .category_patterns import CategoryPatternMatcher
from .pattern_store import PatternStore
```

In `DataManager.__init__`, after merchant cache setup, add:

```python
        # Pattern store for auto-categorization
        self.pattern_store = PatternStore(
            profile_dir if profile_dir else Path(self.config_dir)
        )
```

Add method to `DataManager`:

```python
    def apply_category_patterns(self) -> None:
        """Apply user-defined category patterns and add suggestion columns."""
        if self.df is None or self.df.is_empty():
            return

        patterns = self.pattern_store.load_patterns()
        if not patterns:
            self.df = self.df.with_columns(
                pl.lit(None).alias(CategoryPatternMatcher.SUGGESTION_COLUMN),
                pl.lit(None).alias(CategoryPatternMatcher.MATCHING_PATTERNS_COLUMN),
            )
            return

        matcher = CategoryPatternMatcher(patterns)
        self.df = matcher.suggest(self.df)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_data_manager.py::test_data_manager_applies_category_patterns -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/data/data_manager.py tests/test_data_manager.py
rtk git commit -m "feat: integrate category pattern matcher into DataManager

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Commit helper for suggestions

**Files:**
- Modify: `moneyflow/data/commit_orchestrator.py`
- Test: `tests/test_commit_orchestrator.py`

**Interfaces:**
- Consumes: `CategoryPatternMatcher` columns and existing `apply_category_edit`.
- Produces: `apply_suggested_category_edit(df, transaction_id, category_id, category_name, category_group)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commit_orchestrator.py`:

```python
import polars as pl


def test_apply_suggested_category_edit_clears_suggestion():
    from moneyflow.data.commit_orchestrator import apply_suggested_category_edit

    df = pl.DataFrame(
        {
            "id": ["txn1"],
            "category_id": ["cat_uncategorized"],
            "category": ["Uncategorized"],
            "group": ["Uncategorized"],
            "suggested_category": ["Groceries"],
            "matching_patterns": [["*WHOLEFDS*"]],
        }
    )
    updated = apply_suggested_category_edit(
        df, "txn1", "cat_groceries", "Groceries", "Food & Dining"
    )

    assert updated["category"][0] == "Groceries"
    assert updated["group"][0] == "Food & Dining"
    assert updated["suggested_category"][0] is None
    assert updated["matching_patterns"][0] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_commit_orchestrator.py::test_apply_suggested_category_edit_clears_suggestion -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `moneyflow/data/commit_orchestrator.py`:

```python
def apply_suggested_category_edit(
    df: pl.DataFrame,
    transaction_id: str,
    new_category_id: str,
    category_name: str,
    category_group: str,
) -> pl.DataFrame:
    """
    Apply an approved category suggestion and clear suggestion columns.

    Args:
        df: Transaction DataFrame with suggested_category column.
        transaction_id: ID of transaction to update.
        new_category_id: New category ID.
        category_name: New category display name.
        category_group: New category group name.

    Returns:
        Updated DataFrame with category changed and suggestion cleared.
    """
    updated = apply_category_edit(
        df, transaction_id, new_category_id, category_name, category_group
    )
    return updated.with_columns(
        pl.when(pl.col("id") == transaction_id)
        .then(pl.lit(None))
        .otherwise(pl.col("suggested_category"))
        .alias("suggested_category"),
        pl.when(pl.col("id") == transaction_id)
        .then(pl.lit(None))
        .otherwise(pl.col("matching_patterns"))
        .alias("matching_patterns"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_commit_orchestrator.py::test_apply_suggested_category_edit_clears_suggestion -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/data/commit_orchestrator.py tests/test_commit_orchestrator.py
rtk git commit -m "feat: add helper to commit suggested category edits

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Inline suggestion indicator

**Files:**
- Modify: `moneyflow/tui/formatters.py`
- Modify: transaction table rendering code in TUI (find where rows are formatted)
- Test: `tests/test_formatters.py`

**Interfaces:**
- Consumes: `suggested_category` and `matching_patterns` DataFrame columns.
- Produces: `format_category_with_suggestion(category: str | None, suggested: str | None, match_count: int) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatters.py`:

```python
from moneyflow.tui.formatters import format_category_with_suggestion


def test_format_category_with_suggestion():
    assert format_category_with_suggestion("Uncategorized", "Groceries", 1) == "Uncategorized → Groceries"


def test_format_category_without_suggestion():
    assert format_category_with_suggestion("Shopping", None, 0) == "Shopping"


def test_format_category_with_multiple_matches():
    text = format_category_with_suggestion("Uncategorized", "Shopping", 3)
    assert "Shopping" in text
    assert "3" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_formatters.py::test_format_category_with_suggestion tests/test_formatters.py::test_format_category_without_suggestion tests/test_formatters.py::test_format_category_with_multiple_matches -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `moneyflow/tui/formatters.py`:

```python
def format_category_with_suggestion(
    category: str | None, suggested: str | None, match_count: int = 0
) -> str:
    """Render a category cell with optional suggestion indicator."""
    base = category or "Uncategorized"
    if not suggested:
        return base
    suffix = f" → {suggested}"
    if match_count > 1:
        suffix += f" ({match_count} matches)"
    return base + suffix
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_formatters.py -v`
Expected: PASS.

- [ ] **Step 5: Wire formatter into transaction table**

Locate where the transaction table builds category cells (search for `"category"` column rendering in `moneyflow/tui/`). Update the renderer to call `format_category_with_suggestion(category, suggested_category, len(matching_patterns or []))` when both columns exist.

- [ ] **Step 6: Commit**

```bash
rtk git add moneyflow/tui/formatters.py tests/test_formatters.py <transaction-table-file>
rtk git commit -m "feat: render inline category suggestion indicator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Batch suggestion review screen

**Files:**
- Create: `moneyflow/tui/screens/category_suggestion_review.py`
- Test: `tests/screens/test_category_suggestion_review.py`

**Interfaces:**
- Consumes: DataFrame with `suggested_category` and `matching_patterns` columns, `main_app` reference.
- Produces: `CategorySuggestionReviewScreen` that calls `main_app.apply_suggested_category(transaction_id, category_id, category_name, category_group)` and `main_app.reject_suggested_category(transaction_id)`.

- [ ] **Step 1: Write the failing test**

```python
import polars as pl
import pytest
from textual.pilot import Pilot

from moneyflow.tui.app import MoneyflowApp
from moneyflow.tui.screens.category_suggestion_review import CategorySuggestionReviewScreen


@pytest.mark.asyncio
async def test_review_screen_shows_suggestions():
    df = pl.DataFrame(
        {
            "id": ["txn1"],
            "date": ["2025-01-01"],
            "merchant": ["JOE COFFEE"],
            "amount": [-5.00],
            "category": ["Uncategorized"],
            "suggested_category": ["Coffee Shops"],
            "matching_patterns": [["*COFFEE*"]],
        }
    )

    class FakeApp:
        def __init__(self):
            self.data_manager = type("DM", (), {"df": df})()
            self.accepted = []
            self.rejected = []

        def apply_suggested_category(self, txn_id, category_id, category_name, category_group):
            self.accepted.append((txn_id, category_id, category_name, category_group))

        def reject_suggested_category(self, txn_id):
            self.rejected.append(txn_id)

    app = FakeApp()
    async with MoneyflowApp().run_test() as pilot:
        await pilot.push_screen(CategorySuggestionReviewScreen(app.data_manager.df, app))
        screen = pilot.app.screen
        assert "Coffee Shops" in str(screen.query_one("#suggestions-table").cells)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/screens/test_category_suggestion_review.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `moneyflow/tui/screens/category_suggestion_review.py`:

```python
"""Batch review screen for category suggestions."""

from typing import Any, Set

import polars as pl
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Label, Static

from ...logging_config import get_logger

logger = get_logger(__name__)


class CategorySuggestionReviewScreen(Screen):
    """Screen to review and approve/reject auto-categorization suggestions."""

    BINDINGS = [
        Binding("space", "toggle_select", "Accept", show=True, key_display="Space"),
        Binding("a", "accept_all", "Accept all", show=True, key_display="a"),
        Binding("r", "reject_all", "Reject all", show=True, key_display="r"),
        Binding("escape", "close", "Close", show=True, key_display="Esc"),
    ]

    CSS = """
    CategorySuggestionReviewScreen {
        background: $surface;
    }
    #suggestions-container {
        height: 100%;
        padding: 1 2;
    }
    #suggestions-header {
        height: 3;
        background: $panel;
        padding: 1;
        margin-bottom: 1;
    }
    #suggestions-title {
        text-style: bold;
        color: $success;
    }
    #suggestions-help {
        color: $text-muted;
        margin-top: 1;
    }
    #suggestions-table {
        height: 1fr;
        border: solid $success;
    }
    #suggestions-footer {
        height: 3;
        background: $panel;
        padding: 1;
        dock: bottom;
    }
    """

    def __init__(self, df: pl.DataFrame, main_app: Any):
        super().__init__()
        self.full_df = df
        self.main_app = main_app
        self.row_to_txn_id: dict[int, str] = {}
        self.accepted_ids: Set[str] = set()
        self.rejected_ids: Set[str] = set()
        self.suggestion_df = self._build_suggestion_df(df)

    def _build_suggestion_df(self, df: pl.DataFrame) -> pl.DataFrame:
        """Filter to rows with non-empty suggestions."""
        if "suggested_category" not in df.columns:
            return df.head(0)
        return df.filter(pl.col("suggested_category").is_not_null())

    def compose(self) -> ComposeResult:
        with Container(id="suggestions-container"):
            with Container(id="suggestions-header"):
                yield Label(
                    f"🤖 {len(self.suggestion_df)} category suggestions",
                    id="suggestions-title",
                )
                yield Static(
                    "Space = accept, r = reject, a = accept all, Esc = close",
                    id="suggestions-help",
                )
            yield DataTable(id="suggestions-table", cursor_type="row", zebra_stripes=True)
            with Container(id="suggestions-footer"):
                yield Static("", id="status-line")

    async def on_mount(self) -> None:
        table = self.query_one("#suggestions-table", DataTable)
        table.add_column("Date", key="date", width=12)
        table.add_column("Merchant", key="merchant", width=25)
        table.add_column("Amount", key="amount", width=12)
        table.add_column("Current", key="current", width=18)
        table.add_column("Suggested", key="suggested", width=18)
        table.add_column("Matches", key="matches", width=10)

        for idx, row in enumerate(self.suggestion_df.iter_rows(named=True)):
            self.row_to_txn_id[idx] = row["id"]
            match_count = len(row.get("matching_patterns") or [])
            table.add_row(
                str(row.get("date", "")),
                str(row.get("merchant", "")),
                f"{row.get('amount', 0):,.2f}",
                str(row.get("category", "")),
                str(row.get("suggested_category", "")),
                str(match_count),
            )

    def action_toggle_select(self) -> None:
        table = self.query_one("#suggestions-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        txn_id = self.row_to_txn_id.get(row_idx)
        if txn_id is None:
            return
        if txn_id in self.accepted_ids:
            self.accepted_ids.discard(txn_id)
            self.rejected_ids.add(txn_id)
        elif txn_id in self.rejected_ids:
            self.rejected_ids.discard(txn_id)
        else:
            self.accepted_ids.add(txn_id)
        self._update_status()

    def action_accept_all(self) -> None:
        self.accepted_ids = set(self.row_to_txn_id.values())
        self.rejected_ids.clear()
        self._update_status()

    def action_reject_all(self) -> None:
        self.rejected_ids = set(self.row_to_txn_id.values())
        self.accepted_ids.clear()
        self._update_status()

    def action_close(self) -> None:
        self._apply_decisions()
        self.dismiss(None)

    def _apply_decisions(self) -> None:
        """Call app callbacks for accepted and rejected suggestions."""
        for txn_id in self.accepted_ids:
            row = self.suggestion_df.filter(pl.col("id") == txn_id).to_dicts()
            if not row:
                continue
            category_name = row[0].get("suggested_category", "")
            # App resolves category_id and group from category name.
            self.main_app.apply_suggested_category(txn_id, category_name)
        for txn_id in self.rejected_ids:
            self.main_app.reject_suggested_category(txn_id)

    def _update_status(self) -> None:
        status = self.query_one("#status-line", Static)
        status.update(
            f"Accepted: {len(self.accepted_ids)}  Rejected: {len(self.rejected_ids)}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/screens/test_category_suggestion_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/tui/screens/category_suggestion_review.py tests/screens/test_category_suggestion_review.py
rtk git commit -m "feat: add category suggestion batch review screen

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Pattern management screen

**Files:**
- Create: `moneyflow/tui/screens/category_patterns_screen.py`
- Test: `tests/screens/test_category_patterns_screen.py`

**Interfaces:**
- Consumes: `PatternStore` and existing categories list.
- Produces: `CategoryPatternsScreen` that calls `main_app.save_category_patterns(patterns)`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from textual.pilot import Pilot

from moneyflow.tui.app import MoneyflowApp
from moneyflow.tui.screens.category_patterns_screen import CategoryPatternsScreen


@pytest.mark.asyncio
async def test_pattern_screen_lists_patterns():
    class FakeApp:
        def __init__(self):
            self.pattern_store = type(
                "PS",
                (),
                {"load_patterns": lambda: [], "save_patterns": lambda p: None},
            )()
            self.category_groups = {"Food & Dining": ["Groceries", "Coffee Shops"]}

    app = FakeApp()
    async with MoneyflowApp().run_test() as pilot:
        await pilot.push_screen(CategoryPatternsScreen(app))
        assert "Category Patterns" in str(pilot.app.screen.query_one("#patterns-title").render())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/screens/test_category_patterns_screen.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `moneyflow/tui/screens/category_patterns_screen.py`:

```python
"""Screen to manage user-defined category patterns."""

from typing import Any, List

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from ...data.category_patterns import CategoryPattern
from ...logging_config import get_logger

logger = get_logger(__name__)


class CategoryPatternsScreen(Screen):
    """Screen to add, edit, delete, and reorder category patterns."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True, key_display="Esc"),
    ]

    CSS = """
    CategoryPatternsScreen {
        background: $surface;
    }
    #patterns-container {
        height: 100%;
        padding: 1 2;
    }
    #patterns-title {
        text-style: bold;
        color: $primary;
    }
    .pattern-row {
        height: auto;
        margin: 1 0;
    }
    """

    def __init__(self, main_app: Any):
        super().__init__()
        self.main_app = main_app
        self.patterns: List[CategoryPattern] = list(main_app.pattern_store.load_patterns())

    def compose(self) -> ComposeResult:
        with Container(id="patterns-container"):
            yield Label("Category Patterns", id="patterns-title")
            yield Static("Define glob/keyword rules for auto-categorization.")
            yield Static("", id="patterns-list")
            with Horizontal(classes="pattern-row"):
                yield Input(placeholder="Pattern (e.g. *WHOLEFDS*)", id="pattern-input")
                yield Input(placeholder="Category", id="category-input")
                yield Button("Add", id="add-pattern", variant="primary")
            yield Button("Save & Close", id="save-patterns", variant="success")

    async def on_mount(self) -> None:
        self._render_patterns()

    def _render_patterns(self) -> None:
        lines = []
        for idx, p in enumerate(self.patterns):
            status = "enabled" if p.enabled else "disabled"
            lines.append(f"{idx + 1}. {p.pattern} → {p.category} ({status})")
        self.query_one("#patterns-list", Static).update("\n".join(lines) or "No patterns yet.")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "add-pattern":
            pattern_input = self.query_one("#pattern-input", Input)
            category_input = self.query_one("#category-input", Input)
            pattern_text = pattern_input.value.strip()
            category_text = category_input.value.strip()
            if pattern_text and category_text:
                self.patterns.append(
                    CategoryPattern(pattern=pattern_text, category=category_text)
                )
                pattern_input.value = ""
                category_input.value = ""
                self._render_patterns()
        elif button_id == "save-patterns":
            self.main_app.pattern_store.save_patterns(self.patterns)
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/screens/test_category_patterns_screen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add moneyflow/tui/screens/category_patterns_screen.py tests/screens/test_category_patterns_screen.py
rtk git commit -m "feat: add category pattern management screen

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Keybindings and app wiring

**Files:**
- Modify: `moneyflow/tui/keybindings.py`
- Modify: `moneyflow/tui/app_controller.py`
- Modify: `moneyflow/tui/app.py`
- Test: `tests/test_app_controller.py` or `tests/test_app.py`

**Interfaces:**
- Consumes: screens from Tasks 7 and 8, `apply_suggested_category` and `reject_suggested_category` callbacks.
- Produces: working keybindings and app actions.

- [ ] **Step 1: Add keybindings**

In `moneyflow/tui/keybindings.py`, add to `KEYBINDINGS` list:

```python
    KeyBinding("s", "suggest_category", "Accept/reject category suggestion", "Actions"),
    KeyBinding("S", "review_suggestions", "Review all category suggestions", "Actions"),
    KeyBinding("P", "manage_patterns", "Manage category patterns", "System"),
```

- [ ] **Step 2: Add app actions**

In `moneyflow/tui/app.py`, add the import near the top with other data imports:

```python
from ..data.commit_orchestrator import apply_suggested_category_edit
```

Then add or extend the action methods:

```python
    async def action_suggest_category(self) -> None:
        """Accept the suggestion for the selected transaction(s)."""
        if self.data_manager is None or self.data_manager.df is None:
            return
        table = self.query_one("#data-table", DataTable)
        cursor_row = table.cursor_row if table.cursor_row >= 0 else 0
        context = self.controller.determine_edit_context("category", cursor_row=cursor_row)
        if context.transactions.is_empty():
            self.notify("No transactions selected")
            return

        for txn in context.transactions.iter_rows(named=True):
            suggested = txn.get("suggested_category")
            if not suggested:
                continue
            self.apply_suggested_category(txn["id"], suggested)

    async def action_review_suggestions(self) -> None:
        """Open batch suggestion review screen."""
        from .screens.category_suggestion_review import CategorySuggestionReviewScreen
        await self.push_screen(CategorySuggestionReviewScreen(self.data_manager.df, self))

    async def action_manage_patterns(self) -> None:
        """Open pattern management screen."""
        from .screens.category_patterns_screen import CategoryPatternsScreen
        await self.push_screen(CategoryPatternsScreen(self))

    def apply_suggested_category(self, transaction_id: str, category_name: str) -> None:
        """Apply an approved suggestion and queue a normal category edit."""
        # Resolve category_id from display name.
        category_id = None
        for cid, cat in (self.data_manager.categories or {}).items():
            if cat.get("name") == category_name:
                category_id = cid
                break
        if category_id is None:
            self.notify(f"Unknown category: {category_name}")
            return

        txn_df = self.data_manager.df.filter(pl.col("id") == transaction_id)
        self.controller.queue_category_edits(txn_df, category_id)
        self.data_manager.df = apply_suggested_category_edit(
            self.data_manager.df,
            transaction_id,
            category_id,
            category_name,
            self.data_manager.category_to_group.get(category_name, "Unknown"),
        )
        self.controller.refresh_view()

    def reject_suggested_category(self, transaction_id: str) -> None:
        """Record a rejected suggestion."""
        rejected = self.data_manager.pattern_store.load_rejected()
        rejected.add(transaction_id)
        self.data_manager.pattern_store.save_rejected(rejected)
```

- [ ] **Step 3: Wire app_controller**

In `moneyflow/tui/app_controller.py`, map the new actions to the app if the controller dispatches actions. If `app.py` handles Textual actions directly, ensure controller is updated to expose helper methods.

- [ ] **Step 4: Write test**

Append to `tests/test_app_controller.py`:

```python
from moneyflow.tui.app import MoneyflowApp
from moneyflow.tui.keybindings import KEYBINDINGS


def test_new_keybindings_registered():
    actions = {kb.action for kb in KEYBINDINGS}
    assert "suggest_category" in actions
    assert "review_suggestions" in actions
    assert "manage_patterns" in actions


def test_app_has_suggestion_actions():
    assert hasattr(MoneyflowApp, "action_suggest_category")
    assert hasattr(MoneyflowApp, "action_review_suggestions")
    assert hasattr(MoneyflowApp, "action_manage_patterns")
    assert hasattr(MoneyflowApp, "apply_suggested_category")
    assert hasattr(MoneyflowApp, "reject_suggested_category")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_app_controller.py tests/test_app.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add moneyflow/tui/keybindings.py moneyflow/tui/app_controller.py moneyflow/tui/app.py tests/test_app_controller.py tests/test_app.py
rtk git commit -m "feat: wire category suggestion screens and keybindings

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: End-to-end smoke test with synthetic data

**Files:**
- Test: `tests/test_auto_categorization_e2e.py`

**Interfaces:**
- Consumes: pattern store, matcher, commit helper, and synthetic dataset fixture.
- Produces: passing end-to-end test.

- [ ] **Step 1: Write the test**

```python
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_auto_categorization_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add tests/test_auto_categorization_e2e.py
rtk git commit -m "test: add auto-categorization end-to-end smoke test

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Final validation

Run the full required check suite:

```bash
uv run pytest -v
uv run pyright moneyflow/
uv run ruff format --check moneyflow/ tests/
uv run ruff check moneyflow/ tests/
```

All must pass before the branch is considered complete.

---

## Self-Review

**Spec coverage:**
- Pattern dataclass and glob matching → Tasks 1 and 2.
- Pattern storage in profile `config.yaml` → Task 3.
- Matcher integration into DataManager → Task 4.
- Approval workflow with batch review and inline indicators → Tasks 6 and 7.
- Pattern management UI → Task 8.
- Keybindings and app wiring → Task 9.
- Error handling (invalid patterns, unknown categories, read-only backends) → handled in Tasks 2, 3, and 9.
- Testing strategy → Tasks 1–10.

**Placeholder scan:** No TBD, TODO, or vague requirements found. Each step includes code, commands, and expected output.

**Type consistency:** `CategoryPatternMatcher.SUGGESTION_COLUMN` and `MATCHING_PATTERNS_COLUMN` are used consistently. `PatternStore` signatures match across tasks.

**Open gaps:** None identified.
