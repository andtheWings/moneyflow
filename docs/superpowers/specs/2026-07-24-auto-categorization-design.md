# User-Defined Auto-Categorization — Design Spec

**Date**: 2026-07-24
**Branch**: `autocat`
**Status**: Draft

## Overview

Add a user-defined, approval-gated auto-categorization system for moneyflow
transactions. Users configure glob/keyword patterns that match text in transaction
fields (merchant, description, notes, etc.). When a pattern matches, the app
suggests a target category but does **not** commit it until the user explicitly
approves the suggestion.

This feature is intentionally scoped to the core personal-finance workflow: it
does not introduce shared-expense tracking or other peripheral concerns. It
builds on patterns already established by the Amazon backend's inherited
category handling and fits naturally into moneyflow's existing edit/commit
pipeline.

## Goals

- Reduce manual categorization work for recurring merchants and transactions.
- Keep the user in control: suggestions are visible and approval is required.
- Support both live backends (SimpleFIN, Monarch, etc.) and imported/local data.
- Allow patterns to be managed both by hand in config and through the TUI.
- Surface ambiguous matches so users can refine pattern ordering and specificity.

## Non-Goals

- Automatic commit of suggested categories without approval.
- Machine-learning or heuristic categorization.
- Shared-expense tracking or splitting.
- Pattern sharing between profiles.

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                       data_manager.py                       │
│  Loads transactions from active backend into Polars DF      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                 data/category_patterns.py                   │
│  CategoryPatternMatcher                                     │
│  - reads patterns from profile config.yaml                  │
│  - loads patterns via pattern_store                         │
- evaluates glob/keyword patterns against DF text fields   │
│  - adds suggested_category + matching_patterns columns      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      tui/app.py / table                     │
│  Renders inline suggestion indicator                        │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│       tui/screens/category_suggestion_review.py             │
│  Batch approve/reject suggestions with multi-match flags    │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                 data/commit_orchestrator.py                 │
│  Applies approved suggestions as normal category edits      │
└─────────────────────────────────────────────────────────────┘
```

**Existing code modified**:

- `moneyflow/data/data_manager.py`: invoke matcher after loading transactions.
- `moneyflow/tui/app.py` and transaction table widget: render suggestion indicator.
- `moneyflow/tui/keybindings.py`: add shortcuts for suggestion review and pattern management.
- `moneyflow/tui/app_controller.py`: wire new screens.

**New code**:

- `moneyflow/data/category_patterns.py`: pattern engine.
- `moneyflow/data/pattern_store.py`: load/save patterns from profile `config.yaml`.
- `moneyflow/tui/screens/category_suggestion_review.py`: batch review screen.
- `moneyflow/tui/screens/category_patterns_screen.py`: pattern management screen.
- Tests in `tests/test_category_patterns.py`, `tests/test_pattern_store.py`, and
  `tests/screens/test_category_suggestion_review.py`.

## Data Model

### `CategoryPattern`

A frozen dataclass representing one rule.

```python
@dataclass(frozen=True)
class CategoryPattern:
    pattern: str                       # glob/keyword, e.g. "*WHOLEFDS*"
    category: str                      # target category name
    fields: tuple[str, ...] = ("merchant", "description", "notes")
    only_when_uncategorized: bool = True
    enabled: bool = True
    description: str | None = None
```

### Pattern evaluation rules

- Patterns are evaluated in the order they appear in config.
- The first enabled match determines `suggested_category`.
- All enabled matches are recorded in `matching_patterns` (a list of matching
  pattern strings) for review.
- Matching is case-insensitive.
- `fields` names map to text columns in the transaction DataFrame such as
  `merchant`, `description`, and `notes`. Exact column names are resolved by the
  matcher. An explicit `fields: ["merchant"]` limits matching to merchant only.
- `only_when_uncategorized: true` means the pattern only fires when the existing
  category is empty or `"Uncategorized"`. Users can set it to `false` to allow
  overriding backend-assigned categories.

## Config Format

Profile `config.yaml` gains a top-level `category_patterns` list, kept separate
from `fetched_categories`:

```yaml
version: 1
fetched_categories: { ... }
category_patterns:
  - pattern: "*WHOLEFDS*"
    category: "Groceries"
    fields: ["merchant", "description"]
    only_when_uncategorized: true
    enabled: true
    description: "Whole Foods"

  - pattern: "SPOTIFY *"
    category: "Subscriptions"
    fields: ["merchant"]
    only_when_uncategorized: true
    enabled: true
```

Both hand-editing and in-app editing target the same `category_patterns` list.
The `fetched_categories` key remains reserved for backend category structure.

## UI & Approval Workflow

### Inline indicator

When a transaction has a non-empty `suggested_category` that differs from its
current `category`:

- The transaction table shows a subtle indicator, e.g. `→ Groceries` next to the
  current category.
- Pressing `s` on the selected row opens a small action menu:
  - Accept suggestion
  - Reject suggestion
  - Open review screen

### Batch review screen

Opened via a global shortcut (`S`) or from the inline action menu.

Columns:

- Date, merchant, amount.
- Current category.
- Suggested category.
- Match badge, e.g. `3 patterns` — expandable to show the matched patterns in
  evaluation order. This helps the user spot overly broad patterns or ordering
  problems.
- Accept/reject toggle per row.
- Bulk actions: accept all, reject all, accept visible, reject visible.

Rejected suggestions are persisted per transaction ID in a small
`rejected_suggestions.yaml` file inside the profile directory so a refresh does
not re-prompt for the same suggestion. A "clear rejected suggestions" action in
the pattern management screen resets this state.

### Pattern management screen

Opened via a global shortcut (`P`).

Allows the user to:

- Add, edit, delete, enable/disable, and reorder patterns.
- Test a pattern against the current transaction set live before saving.
- See how many transactions a pattern matches.
- Clear rejected-suggestion history.

## Error Handling

- **Invalid glob patterns**: validated when saved. The UI highlights the pattern
  and shows the compilation error.
- **Unknown target category**: suggestions are still generated, but the review
  screen marks the category as unknown. The user can create the category first,
  edit the pattern, or reject the suggestion.
- **No matches**: no suggestion columns are added; this is silent and not an error.
- **Backend read-only**: suggestions do not touch the backend. Existing commit
  logic handles backends that cannot write.
- **Reordering edge cases**: if two patterns suggest different categories for the
  same transaction, the first match wins. The multi-match badge in the review
  screen makes this visible.

## Testing Strategy

- **Pattern engine unit tests** (`tests/test_category_patterns.py`):
  - glob matching against merchant/description/notes.
  - case-insensitive matching.
  - `only_when_uncategorized` behavior.
  - first-match wins and multi-match recording.
  - invalid pattern handling.

- **Store tests** (`tests/test_pattern_store.py`):
  - load/save `category_patterns` from profile `config.yaml`.
  - merge with default empty list.
  - preserve other config keys.

- **Data manager integration tests**:
  - matcher is invoked after backend load.
  - suggested columns are added to the cached DataFrame.

- **TUI pilot tests**:
  - review screen renders suggestions and multi-match badges.
  - accepting a suggestion calls commit orchestrator.
  - pattern management screen adds a pattern and persists it.

- **End-to-end smoke test**:
  - Load the existing synthetic dataset.
  - Add a pattern that matches a known synthetic merchant.
  - Verify the suggestion appears, approve it, and verify the category change
    propagates through commit/state.

## Open Questions

None. Design ready for implementation planning.
