# CSV Import Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic CSV import engine with pluggable institution mappings, starting with Chase credit card.

**Architecture:** A frozen `InstitutionMapping` dataclass defines per-institution column mappings, date formats, and dedup rules. A generic `CsvFinanceBackend` (FinanceBackend subclass) stores imported data in per-institution SQLite files. The `import_csv()` engine reads CSV with Polars, applies the mapping, and batch-inserts into the backend. A mapping registry and CLI command wires it together.

**Tech Stack:** Python 3.11+, Polars, SQLite3 (stdlib), Click, Textual, Pytest.

## Global Constraints

- Target Python version: 3.11
- All imports at top of file (no inline imports)
- Type hints on all function signatures
- Line length: 100 characters
- TDD: write failing test first, then implement
- Test coverage >90% on engine and backend
- Amazon code must NOT be modified
- No new dependencies (use stdlib + existing deps only)

---

### Task 1: InstitutionMapping Dataclass

**Files:**
- Create: `moneyflow/importers/__init__.py`
- Create: `moneyflow/importers/engine.py`
- Create: `tests/test_csv_importer_engine.py`

**Interfaces:**
- Produces: `InstitutionMapping` dataclass with fields: `name`, `display_name`, `file_pattern`, `id_prefix`, `date_fmt`, `column_map`, `amount_sign`, `skip_rows`, `dedup_fields`, `extra_columns`, `date_columns`, `id_fields`, `currency`, `default_category`, `default_category_id`, `encoding`, `debit_column`, `credit_column`
- Produces: `InstitutionMapping.validate()` — raises `ValueError` on invalid config

- [ ] **Step 1: Write failing test for InstitutionMapping**

```python
# tests/test_csv_importer_engine.py
"""Tests for CSV import engine and InstitutionMapping."""
import pytest
from datetime import date as date_type

from moneyflow.importers.engine import InstitutionMapping


class TestInstitutionMapping:
    def test_minimal_valid_mapping_passes_validation(self):
        mapping = InstitutionMapping(
            name="test_bank",
            display_name="Test Bank",
            file_pattern="test_*.csv",
            id_prefix="test_",
            date_fmt="%m/%d/%Y",
            column_map={
                "Date": "date",
                "Description": "merchant",
                "Amount": "amount",
            },
            amount_sign=1,
            skip_rows=0,
            dedup_fields=("date", "amount", "merchant"),
            extra_columns=(),
            date_columns=("date",),
            id_fields=("date", "amount", "merchant"),
            currency="USD",
            default_category="Uncategorized",
            default_category_id="cat_uncategorized",
            encoding="utf-8",
            debit_column=None,
            credit_column=None,
        )
        mapping.validate()  # Should not raise

    def test_missing_required_column_map_raises_value_error(self):
        mapping = InstitutionMapping(
            name="bad_bank",
            display_name="Bad Bank",
            file_pattern="*.csv",
            id_prefix="bad_",
            date_fmt=None,
            column_map={"Date": "date"},  # Missing amount and merchant
            amount_sign=1,
            skip_rows=0,
            dedup_fields=("date",),
            extra_columns=(),
            date_columns=None,
            id_fields=("date",),
            currency="USD",
            default_category="Uncategorized",
            default_category_id="cat_uncategorized",
            encoding="utf-8",
            debit_column=None,
            credit_column=None,
        )
        with pytest.raises(ValueError, match="Missing required.*amount"):
            mapping.validate()

    def test_both_amount_and_split_columns_raises_value_error(self):
        with pytest.raises(ValueError, match="amount.*debit.*credit|cannot specify both"):
            InstitutionMapping(
                name="conflict",
                display_name="Conflict",
                file_pattern="*.csv",
                id_prefix="c_",
                date_fmt=None,
                column_map={
                    "Date": "date",
                    "Description": "merchant",
                    "Amount": "amount",
                },
                amount_sign=1,
                skip_rows=0,
                dedup_fields=("date", "amount", "merchant"),
                extra_columns=(),
                date_columns=("date",),
                id_fields=("date", "amount", "merchant"),
                currency="USD",
                default_category="Uncategorized",
                default_category_id="cat_uncategorized",
                encoding="utf-8",
                debit_column="Debit",
                credit_column="Credit",
            )
```

- [ ] **Step 2: Create empty package files**

```bash
touch moneyflow/importers/__init__.py
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_csv_importer_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'moneyflow.importers.engine'`

- [ ] **Step 4: Implement InstitutionMapping dataclass**

```python
# moneyflow/importers/engine.py
"""Generic CSV import engine with pluggable institution mappings."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InstitutionMapping:
    """Per-institution column mapping and CSV parsing configuration."""

    name: str  # "chase_credit"
    display_name: str  # "Chase Credit Card"
    file_pattern: str  # "Chase*.csv"
    id_prefix: str  # "chase_"
    date_fmt: str | None  # "%m/%d/%Y" or None for ISO auto-detect

    column_map: dict[str, str]  # CSV header -> transaction field
    amount_sign: int  # 1 or -1
    skip_rows: int  # rows to skip at top of file

    dedup_fields: tuple[str, ...]  # fields that uniquely identify a transaction
    extra_columns: tuple[str, ...]  # non-standard columns to store in JSON blob

    date_columns: tuple[str, ...] | None  # None = parse "date" from column_map
    id_fields: tuple[str, ...]  # fields concatenated into txn ID

    currency: str  # "USD"
    default_category: str  # "Uncategorized"
    default_category_id: str  # "cat_uncategorized"

    encoding: str  # default "utf-8"
    debit_column: str | None  # for split Debit/Credit CSVs
    credit_column: str | None  # for split Debit/Credit CSVs

    def validate(self) -> None:
        """Raise ValueError if the mapping is missing required fields."""
        required_standard = {"date", "amount", "merchant"}
        mapped_values = set(self.column_map.values())

        if self.debit_column is not None and self.credit_column is not None:
            if "amount" in self.column_map:
                raise ValueError(
                    "Cannot specify both 'amount' column and split debit/credit columns"
                )
        elif self.debit_column is not None or self.credit_column is not None:
            raise ValueError(
                "Must specify both debit_column and credit_column, or neither"
            )
        else:
            missing = required_standard - mapped_values
            if missing:
                raise ValueError(f"Missing required column_map targets: {', '.join(sorted(missing))}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_csv_importer_engine.py -v`
Expected: 2 tests PASS, 1 FAIL (the split column validation test — need to fix it)

- [ ] **Step 6: Fix the split-column validation test**

The test expects a ValueError when both `amount` and `debit/credit` columns are specified, but the constructor creates the instance fine because validation is in `validate()`. Adjust the test:

```python
def test_both_amount_and_split_columns_raises_value_error(self):
    mapping = InstitutionMapping(
        name="conflict",
        display_name="Conflict",
        file_pattern="*.csv",
        id_prefix="c_",
        date_fmt=None,
        column_map={
            "Date": "date",
            "Description": "merchant",
            "Amount": "amount",
        },
        amount_sign=1,
        skip_rows=0,
        dedup_fields=("date", "amount", "merchant"),
        extra_columns=(),
        date_columns=("date",),
        id_fields=("date", "amount", "merchant"),
        currency="USD",
        default_category="Uncategorized",
        default_category_id="cat_uncategorized",
        encoding="utf-8",
        debit_column="Debit",
        credit_column="Credit",
    )
    with pytest.raises(ValueError, match="Cannot specify both"):
        mapping.validate()
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/test_csv_importer_engine.py -v`
Expected: all 3 PASS

- [ ] **Step 8: Commit**

```bash
git add moneyflow/importers/__init__.py moneyflow/importers/engine.py tests/test_csv_importer_engine.py
git commit -m "feat: add InstitutionMapping dataclass with validation"
```

---

### Task 2: CsvFinanceBackend

**Files:**
- Create: `moneyflow/backends/csv_backend.py`
- Create: `tests/test_csv_backend.py`

**Interfaces:**
- Produces: `CsvFinanceBackend(FinanceBackend)` class
- Constructor: `__init__(profile_dir: Path | None, config_dir: str | None, institution_name: str) -> None`
- `_ensure_db_initialized()` — lazy SQLite schema creation
- `_get_connection() -> sqlite3.Connection`
- `get_backend_type() -> str` — returns `"csv_{institution_name}"`
- `get_transactions(limit, offset, start_date, end_date, **kwargs) -> dict` — returns `{"results": [...]}`
- `update_transaction(transaction_id, merchant_name, category_id, hide_from_reports) -> dict`
- `delete_transaction(transaction_id) -> bool`
- `get_all_merchants() -> list[str]`
- `get_transaction_categories() -> dict`
- `get_transaction_category_groups() -> dict`
- `get_display_labels() -> dict`
- `get_import_history() -> list[dict]`
- `get_database_stats() -> dict`
- `login()` — no-op for local backends

**Step-by-step:**

- [ ] **Step 1: Write failing test for CsvFinanceBackend constructor and schema**

```python
# tests/test_csv_backend.py
"""Tests for CsvFinanceBackend."""
import sqlite3
from pathlib import Path

import pytest

from moneyflow.backends.csv_backend import CsvFinanceBackend


@pytest.fixture
def tmp_profile_dir(tmp_path):
    """Temporary profile directory."""
    profile = tmp_path / "profiles" / "csv_test"
    profile.mkdir(parents=True)
    return profile


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Temporary config directory."""
    config = tmp_path / "config"
    config.mkdir()
    return str(config)


@pytest.fixture
def chase_backend(tmp_profile_dir, tmp_config_dir):
    """Create a CsvFinanceBackend for Chase credit card."""
    return CsvFinanceBackend(
        profile_dir=tmp_profile_dir,
        config_dir=tmp_config_dir,
        institution_name="chase_credit",
    )


class TestCsvFinanceBackend:
    def test_get_backend_type(self, chase_backend):
        assert chase_backend.get_backend_type() == "csv_chase_credit"

    def test_db_path_derived_from_institution_name(self, chase_backend, tmp_profile_dir):
        expected = str(tmp_profile_dir / "chase_credit_transactions.db")
        assert chase_backend.db_path == expected

    def test_schema_is_created_on_first_connection(self, chase_backend):
        conn = chase_backend._get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        conn.close()
        table_names = {row[0] for row in tables}
        assert "transactions" in table_names
        assert "import_history" in table_names

    def test_transactions_table_has_correct_columns(self, chase_backend):
        conn = chase_backend._get_connection()
        cols = conn.execute("PRAGMA table_info(transactions)").fetchall()
        conn.close()
        col_names = {row[1] for row in cols}
        assert "id" in col_names
        assert "date" in col_names
        assert "amount" in col_names
        assert "merchant" in col_names
        assert "category" in col_names
        assert "category_id" in col_names
        assert "account" in col_names
        assert "notes" in col_names
        assert "extras" in col_names
        assert "hideFromReports" in col_names
        assert "imported_at" in col_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_csv_backend.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement CsvFinanceBackend**

```python
# moneyflow/backends/csv_backend.py
"""Generic CSV-backed FinanceBackend for imported transaction data."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from moneyflow.backends.base import FinanceBackend


class CsvFinanceBackend(FinanceBackend):
    """FinanceBackend that stores transactions in per-institution SQLite databases.

    Each institution gets its own SQLite file: {profile_dir}/{institution}_transactions.db.
    Extra CSV columns are stored as a JSON blob in the 'extras' column.
    """

    def __init__(
        self,
        *,
        profile_dir: Path | None = None,
        config_dir: str | None = None,
        institution_name: str,
    ) -> None:
        if profile_dir is None:
            profile_dir = Path.home() / ".moneyflow"
        self.institution_name = institution_name
        self.config_dir = config_dir or str(Path.home() / ".moneyflow")
        self.db_path = str(profile_dir / f"{institution_name}_transactions.db")
        self._db_initialized = False

    def _ensure_db_initialized(self) -> None:
        if self._db_initialized:
            return

        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                merchant TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Uncategorized',
                category_id TEXT NOT NULL DEFAULT 'cat_uncategorized',
                account TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                extras TEXT NOT NULL DEFAULT '{}',
                hideFromReports INTEGER NOT NULL DEFAULT 0,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                record_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_date ON transactions(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_merchant ON transactions(merchant)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_category ON transactions(category)")
        conn.commit()
        conn.close()
        self._db_initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        self._ensure_db_initialized()
        return sqlite3.connect(self.db_path)

    def _row_to_transaction_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        extras = json.loads(row["extras"] or "{}")
        return {
            "id": row["id"],
            "date": row["date"],
            "amount": row["amount"],
            "merchant": {"id": row["id"], "name": row["merchant"]},
            "category": {"id": row["category_id"], "name": row["category"]},
            "account": {"id": "", "displayName": row["account"]},
            "notes": row["notes"],
            "hideFromReports": bool(row["hideFromReports"]),
            "pending": False,
            "isRecurring": False,
            **extras,
        }

    def get_backend_type(self) -> str:
        return f"csv_{self.institution_name}"

    async def login(self, **kwargs: Any) -> None:
        pass  # No authentication needed for local SQLite

    async def get_transactions(
        self,
        limit: int = 100,
        offset: int = 0,
        start_date: str | None = None,
        end_date: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row

        conditions = []
        params: list[Any] = []
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        count_query = f"SELECT COUNT(*) FROM transactions WHERE {where_clause}"
        total = conn.execute(count_query, params).fetchone()[0]

        query = (
            f"SELECT * FROM transactions WHERE {where_clause} "
            "ORDER BY date DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()

        results = [self._row_to_transaction_dict(row) for row in rows]
        conn.close()
        return {"results": results, "totalCount": total}

    async def update_transaction(
        self,
        transaction_id: str,
        merchant_name: str | None = None,
        category_id: str | None = None,
        hide_from_reports: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row

        updates: list[str] = []
        params: list[Any] = []
        if merchant_name is not None:
            updates.append("merchant = ?")
            params.append(merchant_name)
        if category_id is not None:
            updates.append("category_id = ?")
            params.append(category_id)
        if hide_from_reports is not None:
            updates.append("hideFromReports = ?")
            params.append(int(hide_from_reports))

        if updates:
            params.append(transaction_id)
            conn.execute(
                f"UPDATE transactions SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"updateTransaction": {"transaction": {"id": transaction_id}}}
        return {"updateTransaction": {"transaction": self._row_to_transaction_dict(row)}}

    async def delete_transaction(self, transaction_id: str) -> bool:
        conn = self._get_connection()
        conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        deleted = conn.total_changes > 0
        conn.commit()
        conn.close()
        return deleted

    async def get_all_merchants(self) -> list[str]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT DISTINCT merchant FROM transactions ORDER BY merchant"
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]

    async def get_transaction_categories(self) -> dict[str, Any]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT DISTINCT category_id, category FROM transactions"
        ).fetchall()
        conn.close()
        categories = [
            {"id": row[0], "name": row[1], "group": {"id": "", "type": "expense"}}
            for row in rows
        ]
        return {"categories": categories}

    async def get_transaction_category_groups(self) -> dict[str, Any]:
        return {"categoryGroups": []}

    def get_display_labels(self) -> dict[str, str]:
        return {
            "merchant": "Description",
            "account": "Account",
            "accounts": "Accounts",
        }

    def get_import_history(self) -> list[dict[str, Any]]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM import_history ORDER BY import_date DESC"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_database_stats(self) -> dict[str, Any]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        date_range = conn.execute(
            "SELECT MIN(date) AS earliest, MAX(date) AS latest FROM transactions"
        ).fetchone()
        total_amount = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions"
        ).fetchone()[0] or 0.0
        conn.close()
        return {
            "total_transactions": total,
            "total_amount": total_amount,
            "earliest_date": date_range["earliest"],
            "latest_date": date_range["latest"],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_csv_backend.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Add more backend tests — insert, query, update, delete**

Extend `tests/test_csv_backend.py`:

```python
def test_insert_and_get_transactions(self, chase_backend):
    conn = chase_backend._get_connection()
    conn.execute(
        "INSERT INTO transactions (id, date, amount, merchant, extras) VALUES (?, ?, ?, ?, ?)",
        ("chase_001", "2024-01-15", -12.34, "EXAMPLE GIFT SHOP", '{"raw_category":"Gifts"}'),
    )
    conn.commit()
    conn.close()

    result = chase_backend.get_transactions(limit=10)
    assert result["totalCount"] == 1
    txn = result["results"][0]
    assert txn["id"] == "chase_001"
    assert txn["date"] == "2024-01-15"
    assert txn["amount"] == -12.34
    assert txn["merchant"]["name"] == "EXAMPLE GIFT SHOP"
    assert txn["raw_category"] == "Gifts"  # extras unwrapped
    assert txn["hideFromReports"] is False
    assert txn["pending"] is False
```

Note: Update `get_transactions` call to `await` in test:

```python
import asyncio

def test_insert_and_get_transactions(self, chase_backend):
    async def _run():
        conn = chase_backend._get_connection()
        conn.execute(...)
        conn.commit()
        conn.close()
        result = await chase_backend.get_transactions(limit=10)
        assert result["totalCount"] == 1
        ...

    asyncio.run(_run())
```

Actually, let's use `pytest-asyncio`. Check if installed. Since there's no `conftest.py` marker shown, I'll update the test to not be async by calling `get_transactions` through `asyncio.run()` pattern for cleaner tests.

- [ ] **Step 6: Add tests for update, delete, merchants, stats**

Add to `tests/test_csv_backend.py` (non-async, use `asyncio.run()` for now):

```python
def test_update_transaction(self, chase_backend):
    conn = chase_backend._get_connection()
    conn.execute(
        "INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
        ("chase_002", "2026-07-12", -20.0, "OLD MERCHANT"),
    )
    conn.commit()
    conn.close()

    async def _run():
        result = await chase_backend.update_transaction(
            "chase_002", merchant_name="NEW MERCHANT"
        )
        assert result["updateTransaction"]["transaction"]["merchant"]["name"] == "NEW MERCHANT"

    asyncio.run(_run())

    conn = chase_backend._get_connection()
    row = conn.execute("SELECT merchant FROM transactions WHERE id = ?", ("chase_002",)).fetchone()
    conn.close()
    assert row[0] == "NEW MERCHANT"

def test_delete_transaction(self, chase_backend):
    conn = chase_backend._get_connection()
    conn.execute(
        "INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
        ("chase_003", "2026-07-12", -10.0, "TO_DELETE"),
    )
    conn.commit()
    conn.close()

    async def _run():
        result = await chase_backend.delete_transaction("chase_003")
        assert result is True

    asyncio.run(_run())

    conn = chase_backend._get_connection()
    exists = conn.execute(
        "SELECT 1 FROM transactions WHERE id = ?", ("chase_003",)
    ).fetchone()
    conn.close()
    assert exists is None

def test_get_all_merchants(self, chase_backend):
    conn = chase_backend._get_connection()
    conn.execute("INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
                 ("m1", "2026-07-12", -1.0, "Merch A"))
    conn.execute("INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
                 ("m2", "2026-07-12", -2.0, "Merch A"))  # duplicate
    conn.execute("INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
                 ("m3", "2026-07-12", -3.0, "Merch B"))
    conn.commit()
    conn.close()

    async def _run():
        merchants = await chase_backend.get_all_merchants()
        assert merchants == ["Merch A", "Merch B"]

    asyncio.run(_run())

def test_get_import_history(self, chase_backend):
    conn = chase_backend._get_connection()
    conn.execute(
        "INSERT INTO import_history (filename, record_count, duplicate_count) VALUES (?, ?, ?)",
        ("test.csv", 100, 5),
    )
    conn.commit()
    conn.close()

    history = chase_backend.get_import_history()
    assert len(history) == 1
    assert history[0]["filename"] == "test.csv"
    assert history[0]["record_count"] == 100

def test_get_database_stats(self, chase_backend):
    conn = chase_backend._get_connection()
    conn.execute("INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
                 ("s1", "2026-01-01", -50.0, "M"))
    conn.execute("INSERT INTO transactions (id, date, amount, merchant) VALUES (?, ?, ?, ?)",
                 ("s2", "2026-12-31", -30.0, "M"))
    conn.commit()
    conn.close()

    stats = chase_backend.get_database_stats()
    assert stats["total_transactions"] == 2
    assert stats["total_amount"] == -80.0
    assert stats["earliest_date"] == "2026-01-01"
    assert stats["latest_date"] == "2026-12-31"
```

- [ ] **Step 7: Run all backend tests**

Run: `uv run pytest tests/test_csv_backend.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add moneyflow/backends/csv_backend.py tests/test_csv_backend.py
git commit -m "feat: add CsvFinanceBackend with SQLite storage"
```

---

### Task 3: import_csv() Engine

**Files:**
- Modify: `moneyflow/importers/engine.py`
- Modify: `tests/test_csv_importer_engine.py`

**Interfaces:**
- Produces: `import_csv(path: str, mapping: InstitutionMapping, backend: CsvFinanceBackend, *, force: bool = False) -> dict[str, int]`
- Returns: `{"imported": N, "duplicates": N, "skipped": N}`

- [ ] **Step 1: Write failing test for import_csv**

Add to `tests/test_csv_importer_engine.py`:

```python
import csv
from pathlib import Path

from moneyflow.backends.csv_backend import CsvFinanceBackend
from moneyflow.importers.engine import InstitutionMapping, import_csv


@pytest.fixture
def test_mapping():
    return InstitutionMapping(
        name="test_bank",
        display_name="Test Bank",
        file_pattern="test_*.csv",
        id_prefix="test_",
        date_fmt="%m/%d/%Y",
        column_map={
            "Transaction Date": "date",
            "Description": "merchant",
            "Amount": "amount",
        },
        amount_sign=1,
        skip_rows=0,
        dedup_fields=("date", "amount", "merchant"),
        extra_columns=(),
        date_columns=("date",),
        id_fields=("date", "amount", "merchant"),
        currency="USD",
        default_category="Uncategorized",
        default_category_id="cat_uncategorized",
        encoding="utf-8",
        debit_column=None,
        credit_column=None,
    )


@pytest.fixture
def test_csv_dir(tmp_path):
    """Create a directory with a test CSV file."""
    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
    csv_file = csv_dir / "test_data.csv"
    csv_file.write_text(
        "Transaction Date,Description,Amount\n"
        "1/15/2024,EXAMPLE GIFT SHOP,-12.34\n"
        "1/12/2024,EXAMPLE CAFE,-8.90\n"
    )
    return str(csv_dir)


@pytest.fixture
def test_backend(tmp_path):
    """Create a test CsvFinanceBackend."""
    profile = tmp_path / "test_profile"
    profile.mkdir()
    config = tmp_path / "test_config"
    config.mkdir()
    return CsvFinanceBackend(
        profile_dir=profile,
        config_dir=str(config),
        institution_name="test_bank",
    )


class TestImportCsv:
    def test_imports_csv_into_backend(self, test_csv_dir, test_mapping, test_backend):
        result = import_csv(test_csv_dir, test_mapping, test_backend)
        assert result["imported"] == 2
        assert result["duplicates"] == 0
        assert result["skipped"] == 0

        # Verify data in backend
        conn = test_backend._get_connection()
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.close()
        assert count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_csv_importer_engine.py::TestImportCsv::test_imports_csv_into_backend -v`
Expected: FAIL with `ImportError: cannot import name 'import_csv'`

- [ ] **Step 3: Implement import_csv**

Append to `moneyflow/importers/engine.py`:

```python
import json
import re
from pathlib import Path

import polars as pl
from moneyflow.backends.csv_backend import CsvFinanceBackend


def _slugify(text: str) -> str:
    """Convert a string into a safe identifier fragment."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(text))


def import_csv(
    path: str,
    mapping: InstitutionMapping,
    backend: CsvFinanceBackend,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Import CSV files matching the institution's file pattern into the backend.

    Args:
        path: Directory containing CSV files.
        mapping: InstitutionMapping defining column mapping and parsing rules.
        backend: CsvFinanceBackend to store imported transactions.
        force: If True, re-import already-imported files and skip dedup checks.

    Returns:
        dict with keys: imported, duplicates, skipped
    """
    mapping.validate()

    # 1. Find CSV files
    csv_files = sorted(Path(path).rglob(mapping.file_pattern))
    if not csv_files:
        raise FileNotFoundError(f"No files matching '{mapping.file_pattern}' found in {path}")

    # 2. Filter already-imported files
    imported_filenames: set[str] = set()
    if not force:
        history = backend.get_import_history()
        imported_filenames = {h["filename"] for h in history}

    new_files = [f for f in csv_files if f.name not in imported_filenames]

    # 3. Read all CSV files with Polars
    dfs = []
    for csv_file in (new_files if not force else csv_files):
        try:
            df = pl.read_csv(str(csv_file), infer_schema_length=0, encoding=mapping.encoding)
        except Exception as e:
            raise ValueError(f"Failed to read {csv_file}: {e}") from e
        dfs.append(df)

    if not dfs:
        return {"imported": 0, "duplicates": 0, "skipped": 0}

    combined = pl.concat(dfs)

    # 4. Skip leading rows
    if mapping.skip_rows > 0:
        combined = combined.slice(mapping.skip_rows)

    # 5. Drop trailing garbage rows (all required columns null or empty)
    target_cols = [mapping.column_map.get(c, c) for c in combined.columns if c in mapping.column_map]
    if target_cols:
        has_data = False
        for col in target_cols:
            renamed = mapping.column_map.get(col, col)
            if renamed in combined.columns:
                has_data = has_data | combined[renamed].is_not_null()
        combined = combined.filter(has_data)

    # 6. Handle split Debit/Credit columns
    if mapping.debit_column and mapping.credit_column:
        debit_col = mapping.debit_column
        credit_col = mapping.credit_column
        if debit_col in combined.columns and credit_col in combined.columns:
            debit = combined[debit_col].cast(pl.Float64, strict=False).fill_null(0)
            credit = combined[credit_col].cast(pl.Float64, strict=False).fill_null(0)
            combined = combined.with_columns((credit - debit).alias("amount"))
        elif "amount" not in set(mapping.column_map.values()):
            raise ValueError("debit_column/credit_column specified but not found in CSV")

    # 7. Rename columns
    combined = combined.rename(mapping.column_map, strict=False)

    # 8. Parse dates
    date_fields = mapping.date_columns or ("date",)
    for date_col in date_fields:
        if date_col in combined.columns:
            if mapping.date_fmt:
                combined = combined.with_columns(
                    pl.col(date_col)
                    .str.to_date(mapping.date_fmt, strict=False)
                    .cast(pl.String)
                    .alias(date_col)
                )
            else:
                # Try ISO 8601
                combined = combined.with_columns(
                    pl.col(date_col).str.to_date(strict=False).cast(pl.String).alias(date_col)
                )

    # Drop rows where date parsing failed
    for date_col in date_fields:
        if date_col in combined.columns:
            combined = combined.filter(pl.col(date_col).is_not_null())

    # 9. Flatten amount sign
    if "amount" in combined.columns:
        combined = combined.with_columns(
            (pl.col("amount").cast(pl.Float64, strict=False) * mapping.amount_sign).alias("amount")
        )

    # 10. Generate IDs from raw CSV field values
    existing_ids: set[str] = set()
    if not force:
        conn = backend._get_connection()
        rows = conn.execute("SELECT id FROM transactions").fetchall()
        conn.close()
        existing_ids = {row[0] for row in rows}

    skipped = 0
    duplicates = 0
    imported = 0

    conn = backend._get_connection()
    id_counts: dict[str, int] = {}

    try:
        rows_iter = combined.iter_rows(named=True)
        insert_batch: list[tuple] = []

        for row in rows_iter:
            # Generate ID from row data
            id_parts = []
            for field in mapping.id_fields:
                val = str(row.get(field, "")).strip()
                id_parts.append(val)
            raw_id = mapping.id_prefix + "_".join(_slugify(p) for p in id_parts)

            # Handle duplicate IDs within batch
            seq = id_counts.get(raw_id, 0) + 1
            id_counts[raw_id] = seq
            txn_id = f"{raw_id}_{seq}" if seq > 1 else raw_id

            if not force and txn_id in existing_ids:
                duplicates += 1
                continue

            # Extract standard fields
            date_val = str(row.get("date", ""))
            amount_val = float(row.get("amount", 0.0) or 0)
            merchant_val = str(row.get("merchant", ""))
            category_val = str(row.get("category", mapping.default_category))
            category_id_val = str(row.get("category_id", mapping.default_category_id))
            account_val = str(row.get("account", ""))
            notes_val = str(row.get("notes", ""))

            # Build extras JSON from extra_columns
            extras = {
                col: str(row.get(col, ""))
                for col in mapping.extra_columns
                if col in row
            }

            insert_batch.append((
                txn_id, date_val, amount_val, merchant_val,
                category_val, category_id_val, account_val, notes_val,
                json.dumps(extras),
            ))

            imported += 1

        # Batch INSERT
        if insert_batch:
            conn.executemany(
                """INSERT OR IGNORE INTO transactions
                   (id, date, amount, merchant, category, category_id, account, notes, extras)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                insert_batch,
            )
            conn.commit()
    finally:
        conn.close()

    # 11. Record import history
    import_conn = backend._get_connection()
    for csv_file in new_files:
        import_conn.execute(
            "INSERT INTO import_history (filename, record_count, duplicate_count, skipped_count) "
            "VALUES (?, ?, ?, ?)",
            (csv_file.name, imported, duplicates, skipped),
        )
    import_conn.commit()
    import_conn.close()

    return {"imported": imported, "duplicates": duplicates, "skipped": skipped}
```

- [ ] **Step 4: Run engine test**

Run: `uv run pytest tests/test_csv_importer_engine.py::TestImportCsv::test_imports_csv_into_backend -v`
Expected: PASS (or fix issues)

- [ ] **Step 5: Add more engine tests**
  - Test `force` flag re-imports
  - Test deduplication of already-imported IDs
  - Test already-imported files are skipped
  - Test amount sign flipping
  - Test trailing garbage row filtering
  - Test missing columns raises error

```python
def test_force_flag_reimports(self, test_csv_dir, test_mapping, test_backend):
    result1 = import_csv(test_csv_dir, test_mapping, test_backend)
    assert result1["imported"] == 2

    result2 = import_csv(test_csv_dir, test_mapping, test_backend)
    assert result2["imported"] == 0  # Already imported

    result3 = import_csv(test_csv_dir, test_mapping, test_backend, force=True)
    assert result3["imported"] == 2  # Forced re-import

def test_amount_sign_flipping(self, tmp_path, test_mapping, test_backend):
    csv_dir = tmp_path / "csvs2"
    csv_dir.mkdir()
    csv_file = csv_dir / "test_data.csv"
    csv_file.write_text("Transaction Date,Description,Amount\n7/12/2026,Buy Stuff,50.00\n")

    signed_mapping_attrs = {k: v for k, v in test_mapping.__dict__.items()}
    signed_mapping_attrs["amount_sign"] = -1  # Flip sign
    signed_mapping = InstitutionMapping(
        **signed_mapping_attrs,
        file_pattern="test_data.csv",
    )

    result = import_csv(str(csv_dir), signed_mapping, test_backend)
    assert result["imported"] == 1

    conn = test_backend._get_connection()
    amount = conn.execute("SELECT amount FROM transactions LIMIT 1").fetchone()[0]
    conn.close()
    assert amount == -50.0  # Flipped from 50.0

def test_trailing_empty_rows_filtered(self, tmp_path, test_mapping, test_backend):
    csv_dir = tmp_path / "csvs_trail"
    csv_dir.mkdir()
    csv_file = csv_dir / "test_data.csv"
    csv_file.write_text(
        "Transaction Date,Description,Amount\n"
        "7/12/2026,Real Transaction,-50.00\n"
        ",,,\n"
        ",,,\n"
    )

    result = import_csv(str(csv_dir), test_mapping, test_backend)
    assert result["imported"] == 1  # Only the real row, not blanks

def test_duplicate_ids_within_batch_get_suffixed(self, tmp_path, test_mapping, test_backend):
    csv_dir = tmp_path / "csvs_dup"
    csv_dir.mkdir()
    csv_file = csv_dir / "test_dup.csv"
    csv_file.write_text(
        "Transaction Date,Description,Amount\n"
        "7/12/2026,Coffee,-4.50\n"
        "7/12/2026,Coffee,-4.50\n"  # Same date, merchant, amount
    )

    dup_mapping_attrs = {k: v for k, v in test_mapping.__dict__.items()}
    dup_mapping_attrs["id_fields"] = ("date", "amount", "merchant")
    dup_mapping = InstitutionMapping(**dup_mapping_attrs, file_pattern="test_dup.csv")

    result = import_csv(str(csv_dir), dup_mapping, test_backend)
    assert result["imported"] == 2  # Both imported, suffixed

    conn = test_backend._get_connection()
    ids = conn.execute("SELECT id FROM transactions ORDER BY id").fetchall()
    conn.close()
    ids = [row[0] for row in ids]
    assert ids[0].endswith("_1") or ids[1].endswith("_2")
```

- [ ] **Step 6: Run all engine tests**

Run: `uv run pytest tests/test_csv_importer_engine.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add moneyflow/importers/engine.py tests/test_csv_importer_engine.py
git commit -m "feat: add import_csv engine function"
```

---

### Task 4: Chase Credit Card Mapping + Registry

**Files:**
- Create: `moneyflow/importers/mappings/__init__.py`
- Create: `moneyflow/importers/mappings/chase.py`
- Create: `moneyflow/importers/mappings/registry.py`
- Create: `tests/data/chase_sample.csv`

**Interfaces:**
- Produces: `chase_credit_mapping` — `InstitutionMapping` instance
- Produces: `INSTITUTION_MAPPINGS` — `dict[str, InstitutionMapping]`

- [ ] **Step 1: Create directory and test fixture**

```bash
mkdir -p moneyflow/importers/mappings
touch moneyflow/importers/mappings/__init__.py
```

Create `tests/data/chase_sample.csv`:

```csv
Transaction Date,Post Date,Description,Category,Type,Amount,Memo
1/15/2024,1/16/2024,EXAMPLE GIFT SHOP,Gifts & Donations,Sale,-12.34,
1/15/2024,1/16/2024,EXAMPLE ONLINE STORE,Shopping,Sale,-23.45,
1/12/2024,1/13/2024,EXAMPLE CAFE,Food & Drink,Sale,-8.90,
1/12/2024,1/13/2024,EXAMPLE MARKET,Groceries,Sale,-15.67,
1/10/2024,1/11/2024,EXAMPLE BOOK STORE,Shopping,Sale,-18.90,
```

- [ ] **Step 2: Create Chase credit card mapping**

```python
# moneyflow/importers/mappings/chase.py
"""Chase credit card CSV mapping."""
from moneyflow.importers.engine import InstitutionMapping

chase_credit_mapping = InstitutionMapping(
    name="chase_credit",
    display_name="Chase Credit Card",
    file_pattern="Chase*.csv",
    id_prefix="chase_",
    date_fmt="%m/%d/%Y",
    column_map={
        "Transaction Date": "date",
        "Post Date": "post_date",
        "Description": "merchant",
        "Category": "category",
        "Type": "type",
        "Amount": "amount",
        "Memo": "notes",
    },
    amount_sign=1,  # Chase credit: expenses already negative
    skip_rows=0,
    dedup_fields=("date", "amount", "merchant"),
    extra_columns=("post_date", "category", "type", "notes"),
    date_columns=("date",),
    id_fields=("date", "amount", "merchant", "notes"),
    currency="USD",
    default_category="Uncategorized",
    default_category_id="cat_uncategorized",
    encoding="utf-8",
    debit_column=None,
    credit_column=None,
)
```

- [ ] **Step 3: Create registry**

```python
# moneyflow/importers/mappings/registry.py
"""Registry of institution mappings."""
from .chase import chase_credit_mapping

INSTITUTION_MAPPINGS: dict[str, InstitutionMapping] = {
    "chase_credit": chase_credit_mapping,
}
```

- [ ] **Step 4: Run test — Chase CSV end-to-end**

Add to `tests/test_csv_importer_engine.py`:

```python
class TestChaseCreditIntegration:
    def test_import_chase_csv(self, tmp_path):
        from moneyflow.importers.mappings.registry import INSTITUTION_MAPPINGS

        mapping = INSTITUTION_MAPPINGS["chase_credit"]
        profile = tmp_path / "chase_profile"
        profile.mkdir()
        config = tmp_path / "chase_config"
        config.mkdir()
        backend = CsvFinanceBackend(
            profile_dir=profile,
            config_dir=str(config),
            institution_name="chase_credit",
        )

        # Copy sample CSV to test dir
        sample = Path(__file__).parent / "data" / "chase_sample.csv"
        csv_dir = tmp_path / "csvs"
        csv_dir.mkdir()
        import shutil
        shutil.copy(sample, csv_dir / "Chase1234_Activity.xlsx")  # intentional bad ext to test glob
        target = csv_dir / "Chase1234_Activity.csv"
        shutil.copy(sample, target)

        result = import_csv(str(csv_dir), mapping, backend)
        assert result["imported"] == 5
        assert result["duplicates"] == 0
        assert result["skipped"] == 0

        # Verify one transaction
        conn = backend._get_connection()
        row = conn.execute(
            "SELECT id, date, amount, merchant, category, notes, extras FROM transactions WHERE amount = -12.34"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[1] == "2024-01-15"
        assert row[3] == "EXAMPLE GIFT SHOP"
        assert row[4] == "Gifts & Donations"
        assert row[5] == ""  # Memo was empty
        extras = json.loads(row[6])
        assert extras["type"] == "Sale"
```

- [ ] **Step 5: Run test**

Run: `uv run pytest tests/test_csv_importer_engine.py::TestChaseCreditIntegration -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add moneyflow/importers/mappings/ tests/data/chase_sample.csv tests/test_csv_importer_engine.py
git commit -m "feat: add Chase credit card mapping and registry"
```

---

### Task 5: CLI Integration

**Files:**
- Modify: `moneyflow/cli.py`
- Modify: `moneyflow/tui/backend_config.py`
- Modify: `moneyflow/tui/app.py`

**Interfaces:**
- Adds: `moneyflow import <institution> <path>` CLI command
- Adds: `moneyflow <institution>` TUI launch
- Adds: `CSV_BACKEND_CONFIG` template in `backend_config.py`

- [ ] **Step 1: Add CSV backend config template**

Edit `moneyflow/tui/backend_config.py` — add after `SIMPLEFIN_CONFIG`:

```python
def get_csv_backend_config(institution_name: str) -> BackendConfig:
    """Create a BackendConfig for a CSV-backed institution."""
    return BackendConfig(
        backend_type=f"csv_{institution_name}",
        merchant_field_name="Description",
        grouping_modes=("merchant", "category"),
        show_quantity=False,
        show_price_per_item=False,
        has_accounts=False,
        has_groups=False,
        requires_auth=False,
    )
```

- [ ] **Step 2: Add import CLI command group and institution subcommand**

In `moneyflow/cli.py`, add after the last group or before `if __name__ == "__main__"`:

```python
@cli.group(name="import", invoke_without_command=True)
@click.pass_context
def import_group(ctx):
    """Import transactions from CSV files."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return


@import_group.command(name="list")
def import_list():
    """List available institution mappings."""
    from moneyflow.importers.mappings.registry import INSTITUTION_MAPPINGS

    click.echo("Available institution mappings:\n")
    for name, mapping in sorted(INSTITUTION_MAPPINGS.items()):
        click.echo(f"  {name:20s} {mapping.display_name}")
    click.echo()


@import_group.command(name="institution")
@click.argument("name")
@click.argument("path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force re-import of already-imported files")
@click.option("--config-dir", type=click.Path(), default=None, help=CONFIG_DIR_HELP)
def import_institution(name, path, force, config_dir):
    """Import CSV files for an institution.

    NAME is the institution identifier (e.g. 'chase_credit').
    PATH is the directory containing CSV files.
    """
    from pathlib import Path as PathLib

    from moneyflow.importers.engine import import_csv as do_import
    from moneyflow.importers.mappings.registry import INSTITUTION_MAPPINGS
    from moneyflow.backends.csv_backend import CsvFinanceBackend

    if name not in INSTITUTION_MAPPINGS:
        click.echo(f"Unknown institution: {name}", err=True)
        click.echo("Available:", err=True)
        for n in sorted(INSTITUTION_MAPPINGS.keys()):
            click.echo(f"  {n}", err=True)
        raise click.Abort()

    mapping = INSTITUTION_MAPPINGS[name]
    config = config_dir or str(PathLib.home() / ".moneyflow")
    profile = PathLib(config) / "profiles" / f"csv_{name}"
    profile.mkdir(parents=True, exist_ok=True)

    backend = CsvFinanceBackend(profile_dir=profile, config_dir=config, institution_name=name)

    click.echo(f"Importing {mapping.display_name} transactions from {path}...")

    try:
        stats = do_import(path, mapping, backend, force=force)

        click.echo(f"\n  Imported: {stats['imported']:,} new transactions")
        if stats["duplicates"] > 0:
            click.echo(f"  Duplicates: {stats['duplicates']:,} (already in database)")
        if stats["skipped"] > 0:
            click.echo(f"  Skipped: {stats['skipped']:,}")

        db_stats = backend.get_database_stats()
        click.echo("\nDatabase summary:")
        click.echo(f"  Total transactions: {db_stats['total_transactions']:,}")
        if db_stats["earliest_date"] and db_stats["latest_date"]:
            click.echo(f"  Date range: {db_stats['earliest_date']} \u2192 {db_stats['latest_date']}")
        click.echo(f"  Total amount: ${db_stats['total_amount']:,.2f}")

        click.echo(f"\n  Ready! Launch moneyflow:")
        click.echo(f"  $ moneyflow {name}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Import failed: {e}", err=True)
        raise click.Abort()
```

- [ ] **Step 3: Add per-institution TUI launch commands for CSV backends**

In `moneyflow/tui/app.py`, add after `launch_simplefin_mode`:

```python
def launch_csv_mode(
    institution_name: str,
    config_dir: Optional[str] = None,
    profile_dir: Optional[Path] = None,
) -> None:
    """Launch moneyflow for a CSV-backed institution.

    Args:
        institution_name: Institution identifier (e.g. 'chase_credit').
        config_dir: Config directory (default: ~/.moneyflow).
        profile_dir: Profile directory for institution data.
    """
    from moneyflow.backends.csv_backend import CsvFinanceBackend
    from moneyflow.tui.backend_config import get_csv_backend_config

    logger = setup_logging(console_output=False, config_dir=config_dir)
    logger.info(f"Starting moneyflow in CSV mode for {institution_name}")

    if profile_dir is None:
        profile_dir = Path.home() / ".moneyflow" / "profiles" / f"csv_{institution_name}"

    try:
        backend = CsvFinanceBackend(
            profile_dir=profile_dir,
            config_dir=config_dir,
            institution_name=institution_name,
        )
        config = get_csv_backend_config(institution_name)

        app = MoneyflowApp(
            demo_mode=False,
            backend=backend,
            config=config,
            profile_dir=profile_dir,
            backend_type=f"csv_{institution_name}",
        )
        app.title = f"moneyflow [CSV: {institution_name}]"

        app.run()
    except Exception:
        print("\n" + "=" * 80, file=sys.stderr)
        print("FATAL ERROR - moneyflow CSV mode crashed!", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("\n" + "=" * 80, file=sys.stderr)
        print("Please report this error with the traceback above.", file=sys.stderr)
        print("=" * 80 + "\n", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 4: Add top-level CLI command for each CSV institution**

In `moneyflow/cli.py`, add BEFORE the `if __name__ == "__main__":` line:

```python
@cli.group(invoke_without_command=True, name="chase_credit")
@click.pass_context
def chase_credit(ctx):
    """Chase Credit Card CSV import mode.

    Run 'moneyflow chase_credit' to launch the UI.
    Import data first: moneyflow import institution chase_credit <path>
    """
    if ctx.invoked_subcommand is not None:
        return

    from pathlib import Path

    from moneyflow.tui.app import launch_csv_mode

    config_dir = str(Path.home() / ".moneyflow")
    launch_csv_mode(institution_name="chase_credit", config_dir=config_dir)
```

- [ ] **Step 5: Verify CLI commands don't break**

```bash
uv run python -c "from moneyflow.cli import cli; print('CLI loads OK')"
```

- [ ] **Step 6: Run all existing tests to verify nothing is broken**

Run: `uv run pytest -v`
Expected: all existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add moneyflow/cli.py moneyflow/tui/backend_config.py moneyflow/tui/app.py
git commit -m "feat: add CLI and TUI integration for CSV import"
```

---

### Task 6: Integration Test + Verification

**Files:**
- Modify: `tests/test_csv_importer_engine.py` (add DataManager integration test)

**Step-by-step:**

- [ ] **Step 1: Add DataManager integration test**

Add to `tests/test_csv_importer_engine.py`:

```python
class TestDataManagerIntegration:
    def test_chase_csv_to_datamanager(self, tmp_path):
        """Full pipeline: Chase CSV -> CsvFinanceBackend -> DataManager -> DataFrame."""
        from moneyflow.data.data_manager import DataManager
        from moneyflow.importers.mappings.registry import INSTITUTION_MAPPINGS

        mapping = INSTITUTION_MAPPINGS["chase_credit"]
        profile = tmp_path / "profile"
        profile.mkdir()
        config = tmp_path / "config"
        config.mkdir()

        backend = CsvFinanceBackend(
            profile_dir=profile,
            config_dir=str(config),
            institution_name="chase_credit",
        )

        sample = Path(__file__).parent / "data" / "chase_sample.csv"
        csv_dir = tmp_path / "csvs"
        csv_dir.mkdir()
        import shutil
        shutil.copy(sample, csv_dir / "Chase_sample.csv")

        result = import_csv(str(csv_dir), mapping, backend)
        assert result["imported"] == 5

        dm = DataManager(backend=backend, backend_type="csv_chase_credit")

        all_txns = dm.fetch_all_data()
        assert len(all_txns["results"]) == 5

        df = dm._transactions_to_dataframe(all_txns["results"])
        assert df.height == 5
        assert "id" in df.columns
        assert "merchant" in df.columns
        assert "amount" in df.columns
        assert "date" in df.columns
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_csv_importer_engine.py::TestDataManagerIntegration -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -v
```

- [ ] **Step 4: Run type checker**

```bash
uv run pyright moneyflow/
```

- [ ] **Step 5: Run linter**

```bash
uv run ruff check moneyflow/ tests/
```

- [ ] **Step 6: Run formatter check**

```bash
uv run ruff format --check moneyflow/ tests/
```

- [ ] **Step 7: Fix any issues found**

- [ ] **Step 8: Run coverage check**

```bash
uv run pytest --cov=moneyflow.importers.engine --cov=moneyflow.backends.csv_backend --cov-report=term-missing
```

- [ ] **Step 9: Final commit**

```bash
git add -A
git commit -m "feat: add integration test and verification"
```
