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
    #suggestions-table > .datatable--cell-key-amount {
        text-align: right;
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
        self._refresh_flags()
        self._update_status()

    def action_accept_all(self) -> None:
        self.accepted_ids = set(self.row_to_txn_id.values())
        self.rejected_ids.clear()
        self._refresh_flags()
        self._update_status()

    def action_reject_all(self) -> None:
        self.rejected_ids = set(self.row_to_txn_id.values())
        self.accepted_ids.clear()
        self._refresh_flags()
        self._update_status()

    def action_close(self) -> None:
        self._apply_decisions()
        self.dismiss(None)

    def _refresh_flags(self) -> None:
        table = self.query_one("#suggestions-table", DataTable)
        for row_idx, txn_id in self.row_to_txn_id.items():
            if txn_id in self.accepted_ids:
                flag = "✓"
            elif txn_id in self.rejected_ids:
                flag = "✗"
            else:
                flag = " "
            table.update_cell_at((row_idx, 0), flag)

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
        status.update(f"Accepted: {len(self.accepted_ids)}  Rejected: {len(self.rejected_ids)}")
