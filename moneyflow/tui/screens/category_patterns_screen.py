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
