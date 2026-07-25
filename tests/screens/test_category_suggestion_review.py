"""Tests for the category suggestion review screen."""

import polars as pl
import pytest
from textual.widgets import DataTable

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

        def apply_suggested_category(self, txn_id, category_name):
            self.accepted.append((txn_id, category_name))

        def reject_suggested_category(self, txn_id):
            self.rejected.append(txn_id)

    app = FakeApp()
    async with MoneyflowApp().run_test() as pilot:
        await pilot.app.push_screen(CategorySuggestionReviewScreen(app.data_manager.df, app))
        screen = pilot.app.screen
        table = screen.query_one("#suggestions-table", DataTable)
        first_key = list(table.rows)[0]
        rendered = " ".join(str(cell) for cell in table.get_row(first_key))
        assert "Coffee Shops" in rendered
