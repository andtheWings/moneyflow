"""Tests for the category pattern management screen."""

import pytest
from textual.pilot import Pilot

from moneyflow.tui.app import MoneyflowApp
from moneyflow.tui.screens.category_patterns_screen import CategoryPatternsScreen


@pytest.mark.asyncio
async def test_pattern_screen_lists_patterns():
    class FakePatternStore:
        def load_patterns(self):
            return []

        def save_patterns(self, patterns):
            pass

    class FakeApp:
        def __init__(self):
            self.pattern_store = FakePatternStore()

    app = FakeApp()
    async with MoneyflowApp().run_test() as pilot:
        await pilot.app.push_screen(CategoryPatternsScreen(app))
        assert "Category Patterns" in str(pilot.app.screen.query_one("#patterns-title").render())
