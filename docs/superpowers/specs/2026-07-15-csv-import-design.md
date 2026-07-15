# Generalized CSV Import Engine — Design Spec

**Date**: 2026-07-15
**Branch**: `import`
**Status**: Draft

## Overview

Build a generic CSV import engine that allows importing transaction histories from
various financial institutions via institution-specific column-mapping definitions.
A library of mappings grows incrementally (starting with Chase). Each institution
gets its own isolated SQLite-backed profile, with future overlay/merging possible
via cross-backend matching (precedent: `AmazonLinker`).

## Architecture

```text
CLI (moneyflow import <institution> <path>)
                │
                ▼
┌─────────────────────────────────────────┐
│         importers/engine.py             │
│  import_csv(path, mapping, backend)     │
│  1. glob files by mapping.file_pattern  │
│  2. polars.read_csv() — all strings    │
│  3. Apply InstitutionMapping:          │
│     rename columns, parse dates,        │
│     flip amount sign, generate IDs      │
│  4. Dedup vs existing IDs               │
│  5. Batch INSERT into CsvFinanceBackend │
└───────────────────┬─────────────────────┘
                    │
┌───────────────────▼─────────────────────┐
│       backends/csv_backend.py           │
│       CsvFinanceBackend                 │
│  FinanceBackend subclass                │
│  institution_name → db file path        │
│  SQLite schema, CRUD, import_history    │
└───────────────────┬─────────────────────┘
                    │
┌───────────────────▼─────────────────────┐
│    importers/mappings/<institution>.py  │
│    InstitutionMapping dataclass         │
│    chase.py, bofa.py, ...               │
└─────────────────────────────────────────┘
```

**Existing code**: `AmazonBackend` and `import_amazon_orders` are NOT modified.
`CsvFinanceBackend` is a new class that reuses Amazon's proven SQLite pattern (same
table shape + extras JSON blob). Amazon may be migrated to use the new engine later
as a thin wrapper, but that is out of scope for this spec.

## InstitutionMapping Data Model

A frozen dataclass — each institution is one module exporting one instance.

```python
@dataclass(frozen=True)
class InstitutionMapping:
    name: str                      # "chase"
    display_name: str              # "Chase"
    file_pattern: str              # "Chase*.csv"
    id_prefix: str                 # "chase_"
    date_fmt: str | None           # "%m/%d/%Y" (None = ISO 8601 attempt)

    column_map: dict[str, str]     # CSV header → transaction field
    # Example: {"Transaction Date": "date", "Description": "merchant",
    #           "Amount": "amount", "Category": "category",
    #           "Type": "type", "Memo": "notes"}

    amount_sign: int               # 1 or -1 (Chase credit: 1, expenses already negative)
    skip_rows: int                 # Header rows to skip at top of file

    dedup_fields: tuple[str, ...]  # Fields that uniquely identify a transaction
    extra_columns: tuple[str, ...] # Non-standard columns to preserve in JSON blob

    date_columns: tuple[str, ...] | None  # None = parse "date" from column_map
    id_fields: tuple[str, ...]            # Fields concatenated into txn ID
                                          # Default: same as dedup_fields

    currency: str                  # "USD" — stored for future multi-currency
    default_category: str          # "Uncategorized"
    default_category_id: str       # "cat_uncategorized"
```

**Standard fields** that every mapping MUST produce (after column_map renaming):
`date`, `merchant`, `amount`. Other standard fields (`notes`, `category`) are optional
and fall back to defaults if unmapped.

### Example: Chase Mapping

```python
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
    amount_sign=1,       # Chase credit: expenses already negative
    skip_rows=0,
    dedup_fields=("date", "amount", "merchant"),
    extra_columns=("post_date", "category", "type", "notes"),
    date_columns=("date",),
    id_fields=("date", "amount", "merchant", "notes"),
    currency="USD",
    default_category="Uncategorized",
    default_category_id="cat_uncategorized",
)
```

## CsvFinanceBackend

A `FinanceBackend` subclass parameterized by institution name.

**Storage**: SQLite database at `{profile_dir}/{institution_name}_transactions.db`.
Schema mirrors Amazon's `transactions` table plus an `extras` JSON blob column for
institution-specific fields.

```sql
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    merchant TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    category_id TEXT NOT NULL DEFAULT 'cat_uncategorized',
    account TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    extras TEXT NOT NULL DEFAULT '{}',     -- JSON blob for extra columns
    hideFromReports INTEGER NOT NULL DEFAULT 0,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE import_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    skipped_count INTEGER NOT NULL,
    import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Interface** (implements `FinanceBackend` ABC):

- `get_backend_type()` → `"csv_{institution_name}"` (e.g. `"csv_chase"`)
- `get_display_labels()` → institution-aware labels
- `get_transactions()` → list of standard transaction dicts with extras from JSON
- `update_transaction(transaction_id, merchant_name, category_id, hide_from_reports)`
- `delete_transaction(transaction_id)`
- `get_import_history()` → all import runs for this institution
- `get_database_stats()` → total txns, date range, total amount
- `get_currency_symbol()` → `"$"` by default; overrideable per institution

**Constructor**: `CsvFinanceBackend(profile_dir, config_dir, institution_name)`
 — lazy schema initialization on first DB access.

## Engine: `import_csv()`

```python
def import_csv(
    path: str,
    mapping: InstitutionMapping,
    backend: CsvFinanceBackend,
    *,
    force: bool = False,
) -> dict[str, int]:
```

**Flow**:

1. Glob `**/{mapping.file_pattern}` under `path`
2. Filter out files already recorded in `import_history` (unless `force=True`)
3. `pl.read_csv(each_file, infer_schema_length=0)` + `pl.concat(all_dfs)`
4. Skip `mapping.skip_rows` leading rows
5. Rename columns via `mapping.column_map`; drop unmapped columns
6. Parse dates via `mapping.date_fmt` (or `strp·time` auto-detection if `None`)
7. Flip sign: `amount = amount * mapping.amount_sign`
8. Generate `id` = `{mapping.id_prefix}{mapping.id_fields joined by '_'}`
   — cleaned (slugs, no special chars)
9. Handle duplicate IDs within the same batch (append `_seq` suffix)
10. Dedup: skip rows whose `id` already exists in DB (except when `force=True`)
11. Serialize `mapping.extra_columns` into JSON `extras` blob per row
12. Batch INSERT into `backend` (transaction-wrapped)
13. Record import history row per file
14. Return `{"imported": N, "duplicates": N, "skipped": N}`

## Multi-Currency Design

No full multi-currency implementation in v1. Design provisions:

- `InstitutionMapping.currency` stored as string (e.g. `"USD"`) — metadata only
- An institution like a UK bank would be its own mapping with `currency="GBP"`
- No per-transaction currency column in the SQLite schema or Polars DataFrame
- `FinanceBackend.get_currency_symbol()` already varies per backend; a GBP backend
  returns `"£"`
- Future amount conversion can hook into the engine or DataFrame layer without
  schema changes — adding a nullable `currency` column to the Polars schema later
  is backward-compatible

## CLI Integration

```
$ moneyflow import chase ~/Downloads/
$ moneyflow import chase ~/Downloads/ --force
$ moneyflow import list                      # show available institution mappings
$ moneyflow chase                            # launch TUI for chase profile
```

Implementation: `moneyflow import <institution>` → lookup `INSTITUTION_MAPPINGS`
registry → `CsvFinanceBackend(profile_dir, config_dir, institution)` → `import_csv()`.

`moneyflow <institution>` → `launch_csv_mode(institution)` → same path as
`launch_amazon_mode()`.

## TUI Integration

`moneyflow chase` → creates `CsvFinanceBackend("chase")` → standard `MoneyflowApp`
flow with `backend_type="csv_chase"`. All existing TUI features (category editing,
sorting, filtering, views) work automatically. Category groups use the built-in
defaults from `categories.py`.

## Mapping Registry

```python
# moneyflow/importers/mappings/registry.py
from .chase import chase_mapping

INSTITUTION_MAPPINGS: dict[str, InstitutionMapping] = {
    "chase": chase_mapping,
    # "bofa": bofa_mapping,  # future
}
```

Adding a new institution = one file in `mappings/` + one line in the registry.

## File Layout

```
moneyflow/
├── importers/
│   ├── __init__.py
│   ├── amazon_orders_csv.py          # Untouched
│   ├── engine.py                     # import_csv() + InstitutionMapping dataclass
│   └── mappings/
│       ├── __init__.py
│       ├── registry.py               # INSTITUTION_MAPPINGS dict
│       └── chase.py                  # chase_mapping instance
├── backends/
│   ├── amazon.py                     # Untouched
│   └── csv_backend.py                # CsvFinanceBackend class
tests/
├── test_amazon_orders_importer.py    # Untouched
├── test_csv_importer_engine.py       # Engine unit tests
├── test_csv_backend.py               # Backend unit tests
└── data/
    └── chase_sample.csv              # Anonymized test fixture
```

## Testing Strategy

1. **`InstitutionMapping` validation** — required fields, column_map correctness,
   date_fmt parsing, ID generation preview
2. **`CsvFinanceBackend`** — schema creation, CRUD, get_transactions() output format,
   import_history recording (modeled after `test_amazon_orders_importer.py`)
3. **`import_csv()` engine** with mock mapping + backend:
   - Column renaming from CSV headers
   - Date parsing across formats
   - Amount sign flipping
   - ID generation and batch deduplication
   - Force flag re-import
   - Skip already-imported files
   - Edge cases: empty CSV, header-only CSV, missing columns, malformed dates,
     duplicate IDs within a batch
4. **Integration**: Chase sample CSV → `CsvFinanceBackend` → `DataManager` →
   verify DataFrame shape and values

## What This Spec Does NOT Cover

- Migrating Amazon to use the new engine (future work)
- Cross-backend transaction overlay/merging (future work, but AmazonLinker pattern
  exists as precedent)
- Amount conversion between currencies (future work)
- CSV export (already exists via `exporter.py`)
- GUI-based import wizard (CLI only for v1)
