"""Modal dialogs and the preview screen."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label

from textual_editor.builder import build_surface
from textual_editor.model import Document


class PathDialog(ModalScreen[str | None]):
    """Ask for a file path."""

    DEFAULT_CSS = """
    PathDialog { align: center middle; }
    PathDialog > Vertical {
        width: 70;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $panel;
    }
    PathDialog .dialog-title { text-style: bold; margin-bottom: 1; }
    PathDialog Horizontal { height: auto; align-horizontal: right; margin-top: 1; }
    PathDialog Button { margin-left: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, value: str = "", action: str = "OK") -> None:
        super().__init__()
        self.dialog_title = title
        self.value = value
        self.action_label = action

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.dialog_title, classes="dialog-title")
            yield Input(self.value, placeholder="path/to/file")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button(self.action_label, variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def accept(self) -> None:
        value = self.query_one(Input).value.strip()
        self.dismiss(value or None)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class PreviewScreen(Screen[None]):
    """Runs the design as a real (interactive) screen."""

    BINDINGS = [Binding("escape", "close", "Close preview", priority=True)]

    def __init__(self, document: Document) -> None:
        super().__init__()
        self.document = document

    def compose(self) -> ComposeResult:
        yield build_surface(self.document, self.app.get_css_variables(), design=False)
        if not any(node.type == "Footer" for node in self.document.root.walk()):
            yield Footer()

    def on_mount(self) -> None:
        self.title = self.document.title
        self.sub_title = "Preview (escape to close)"

    def action_close(self) -> None:
        self.dismiss(None)
