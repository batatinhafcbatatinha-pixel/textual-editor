"""The editor application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Offset
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, TabbedContent, TabPane, TextArea

from textual_editor.canvas import DesignCanvas, DragGhost, parse_offset
from textual_editor.catalog import CATALOG, is_container
from textual_editor.codegen import generate
from textual_editor.model import ROOT_ID, Document, Node
from textual_editor.panels import DocumentTree, Palette, PropertiesPanel
from textual_editor.screens import PathDialog, PreviewScreen
from textual_editor.styles import validate

MAX_UNDO = 200


class EditorScreen(Screen):
    """The main screen: palette, canvas, code and properties."""

    AUTO_FOCUS = "#editor-canvas"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="editor-main"):
            with Vertical(id="editor-left"):
                yield Label("Widgets", classes="panel-title")
                yield Palette(id="editor-palette")
                yield Label("Structure", classes="panel-title")
                yield DocumentTree(id="editor-tree")
            with TabbedContent(id="editor-center"):
                with TabPane("Design", id="editor-design-tab"):
                    yield DesignCanvas(id="editor-canvas")
                with TabPane("Code", id="editor-code-tab"):
                    yield TextArea.code_editor("", read_only=True, id="editor-code")
            with Vertical(id="editor-right"):
                yield Label("Properties", classes="panel-title")
                yield PropertiesPanel(id="editor-properties")
        yield Footer()
        yield DragGhost(id="editor-ghost")

    @property
    def canvas(self) -> DesignCanvas:
        return self.query_one(DesignCanvas)

    def _forward_event(self, event: events.Event) -> None:
        # Mouse events over the design go to the canvas, not to the widgets in the
        # design (so buttons aren't pressed, inputs aren't focused, etc.).
        if (
            isinstance(event, events.MouseEvent)
            and not event.is_forwarded
            and self.app.mouse_captured is None
        ):
            try:
                widget, _ = self.get_widget_at(event.x, event.y)
            except Exception:
                widget = None
            canvas = self.canvas
            if widget is not None and widget is not canvas.frame:
                if canvas.frame in widget.ancestors and not isinstance(
                    event, (events.MouseScrollDown, events.MouseScrollUp,
                            events.MouseScrollLeft, events.MouseScrollRight)
                ):
                    event._set_forwarded()
                    canvas.post_message(
                        event._apply_offset(-canvas.region.x, -canvas.region.y)
                    )
                    return
        super()._forward_event(event)

    def show_ghost(self, label: str, screen_offset: Offset) -> None:
        ghost = self.query_one(DragGhost)
        ghost.update(f"+ {label}")
        ghost.styles.offset = (screen_offset.x + 1, screen_offset.y)
        ghost.display = True

    def hide_ghost(self) -> None:
        self.query_one(DragGhost).display = False


class TextualEditor(App):
    """A visual, drag and drop, interface builder for Textual."""

    # Absolute, so subclasses defined in other modules still find it
    CSS_PATH = Path(__file__).parent / "editor.tcss"
    TITLE = "Textual Editor"

    BINDINGS = [
        Binding("ctrl+n", "new", "New"),
        Binding("ctrl+o", "open", "Open"),
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+e", "export", "Export .py"),
        Binding("f5", "preview", "Preview"),
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+y", "redo", "Redo"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.document = Document()
        self.selected: str | None = ROOT_ID
        self.path: Path | None = None
        self.dirty = False
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._initial_path = path

    def get_default_screen(self) -> Screen:
        return EditorScreen()

    @property
    def editor(self) -> EditorScreen:
        screen = self.screen_stack[0]
        assert isinstance(screen, EditorScreen)
        return screen

    async def on_ready(self) -> None:
        if self._initial_path:
            self.load(Path(self._initial_path))
        await self.refresh_design(rebuild_panel=True)

    # -- State -------------------------------------------------------------------

    def checkpoint(self) -> None:
        """Remember the current state for undo."""
        self._undo.append(self.document.to_json())
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
        self.dirty = True

    async def refresh_design(self, rebuild_panel: bool = False) -> None:
        """Update the canvas, tree, properties and code after a change."""
        editor = self.editor
        if self.selected is not None and self.document.find(self.selected) is None:
            self.selected = ROOT_ID
        await editor.canvas.show(self.document, self.selected)
        editor.query_one(DocumentTree).show_document(self.document, self.selected)
        await editor.query_one(PropertiesPanel).show_node(
            self.document, self.selected, rebuild=rebuild_panel
        )
        self._update_code()
        self._update_title()

    def _update_code(self) -> None:
        """Regenerate the code (only while the Code tab is shown)."""
        tabs = self.editor.query_one("#editor-center", TabbedContent)
        if tabs.active == "editor-code-tab":
            code = self.editor.query_one("#editor-code", TextArea)
            source = generate(self.document)
            if code.text != source:
                code.load_text(source)

    @on(TabbedContent.TabActivated)
    def _tab_activated(self) -> None:
        self._update_code()

    def _update_title(self) -> None:
        name = self.path.name if self.path else "untitled"
        self.sub_title = f"{name}{' *' if self.dirty else ''}"

    async def select(self, node_id: str | None) -> None:
        if node_id == self.selected:
            return
        self.selected = node_id
        editor = self.editor
        editor.canvas.select(node_id)
        editor.query_one(DocumentTree).show_document(self.document, node_id)
        await editor.query_one(PropertiesPanel).show_node(self.document, node_id)

    # -- Adding and moving ---------------------------------------------------------

    def target_container(self) -> str:
        """The container where a new widget goes (the selection, or its parent)."""
        node = self.document.find(self.selected or ROOT_ID)
        if node is None:
            return ROOT_ID
        if is_container(node.type):
            return node.id
        parent = self.document.parent_of(node.id)
        return parent.id if parent else ROOT_ID

    async def add_widget(
        self, widget_type: str, parent_id: str, offset: Offset | None = None, index: int | None = None
    ) -> None:
        spec = CATALOG[widget_type]
        parent = self.document.find(parent_id)
        if parent is None:
            return
        self.checkpoint()
        node = Node(
            type=widget_type,
            id=self.document.new_id(widget_type),
            props=spec.default_props(),
            styles=dict(spec.styles),
        )
        if self.document.is_free(parent) and not spec.docked:
            if offset is None:
                offset = Offset(2 + len(parent.children) % 10, 1 + 2 * (len(parent.children) % 8))
            node.styles = {"offset": f"{offset.x} {offset.y}", **node.styles}
        self.document.insert(parent_id, node, index)
        self.selected = node.id
        await self.refresh_design(rebuild_panel=True)

    def drop_index(self, parent_id: str, screen_offset: Offset, exclude: str | None = None) -> int | None:
        """Where to insert a node dropped on a container with a flow layout."""
        parent = self.document.find(parent_id)
        if parent is None or self.document.is_free(parent):
            return None
        canvas = self.editor.canvas
        layout = parent.styles.get("layout", "")
        horizontal = layout == "horizontal" or (
            not layout and parent.type in ("Horizontal", "HorizontalScroll")
        )
        index = 0
        for child in parent.children:
            if child.id == exclude:
                continue
            widget = canvas.widget_for(child.id)
            if widget is None:
                continue
            region = widget.region
            center = region.center
            if (screen_offset.x > center[0]) if horizontal else (screen_offset.y > center[1]):
                index += 1
        return index

    @on(Palette.Dropped)
    async def _palette_dropped(self, event: Palette.Dropped) -> None:
        canvas = self.editor.canvas
        parent_id = canvas.container_at(event.screen_offset)
        if parent_id is None:
            return
        await self.add_widget(
            event.widget_type,
            parent_id,
            canvas.frame_offset(event.screen_offset),
            self.drop_index(parent_id, event.screen_offset),
        )

    @on(Palette.Add)
    async def _palette_add(self, event: Palette.Add) -> None:
        await self.add_widget(event.widget_type, self.target_container())

    @on(DesignCanvas.Selected)
    async def _canvas_selected(self, event: DesignCanvas.Selected) -> None:
        await self.select(event.node_id)

    @on(DocumentTree.Selected)
    async def _tree_selected(self, event: DocumentTree.Selected) -> None:
        if event.node_id != self.selected:
            self.selected = event.node_id
            self.editor.canvas.select(event.node_id)
            await self.editor.query_one(PropertiesPanel).show_node(self.document, event.node_id)

    @on(DesignCanvas.Moved)
    async def _canvas_moved(self, event: DesignCanvas.Moved) -> None:
        node = self.document.find(event.node_id)
        if node is None:
            return
        self.checkpoint()
        offset = Offset(max(0, event.offset.x), max(0, event.offset.y))
        node.styles["offset"] = f"{offset.x} {offset.y}"
        await self.refresh_design()

    @on(DesignCanvas.Resized)
    async def _canvas_resized(self, event: DesignCanvas.Resized) -> None:
        node = self.document.find(event.node_id)
        if node is None:
            return
        self.checkpoint()
        node.styles["width"] = str(event.size.width)
        node.styles["height"] = str(event.size.height)
        await self.refresh_design()

    @on(DesignCanvas.Dropped)
    async def _canvas_dropped(self, event: DesignCanvas.Dropped) -> None:
        canvas = self.editor.canvas
        parent_id = canvas.container_at(event.screen_offset, exclude=event.node_id)
        node = self.document.find(event.node_id)
        if parent_id is None or node is None:
            return
        index = self.drop_index(parent_id, event.screen_offset, exclude=event.node_id)
        self.checkpoint()
        if not self.document.move(event.node_id, parent_id, index):
            return
        parent = self.document.find(parent_id)
        if parent is not None and self.document.is_free(parent):
            offset = canvas.frame_offset(event.screen_offset)
            node.styles["offset"] = f"{offset.x} {offset.y}"
        else:
            node.styles.pop("offset", None)
        await self.refresh_design(rebuild_panel=True)

    @on(DesignCanvas.Action)
    async def _canvas_action(self, event: DesignCanvas.Action) -> None:
        document = self.document
        node_id = self.selected
        if node_id is None:
            return
        node = document.find(node_id)
        parent = document.parent_of(node_id)
        if event.action == "select_parent":
            if parent is not None:
                await self.select(parent.id)
            return
        if node is None or parent is None:
            return  # The rest doesn't apply to the screen itself
        if event.action == "delete":
            self.checkpoint()
            document.remove(node_id)
            self.selected = parent.id
            await self.refresh_design(rebuild_panel=True)
        elif event.action == "duplicate":
            self.checkpoint()
            clone = document.duplicate(node_id)
            if clone is not None:
                if document.is_free(parent) and "offset" in clone.styles:
                    offset = parse_offset(clone.styles["offset"]) + (2, 1)
                    clone.styles["offset"] = f"{offset.x} {offset.y}"
                self.selected = clone.id
            await self.refresh_design(rebuild_panel=True)
        elif event.action == "nudge":
            self.checkpoint()
            if document.is_free(parent):
                offset = parse_offset(node.styles.get("offset")) + (event.dx, event.dy)
                offset = Offset(max(0, offset.x), max(0, offset.y))
                node.styles["offset"] = f"{offset.x} {offset.y}"
            else:
                index = parent.children.index(node) + (event.dx or event.dy)
                index = max(0, min(len(parent.children) - 1, index))
                parent.children.remove(node)
                parent.children.insert(index, node)
            await self.refresh_design()
        elif event.action == "grow":
            widget = self.editor.canvas.widget_for(node_id)
            if widget is None:
                return
            self.checkpoint()
            width, height = widget.region.size
            node.styles["width"] = str(max(1, width + event.dx))
            node.styles["height"] = str(max(1, height + event.dy))
            await self.refresh_design()

    # -- Properties --------------------------------------------------------------

    @on(PropertiesPanel.Changed)
    async def _property_changed(self, event: PropertiesPanel.Changed) -> None:
        if not self.screen_stack or self._exit_renderables or self._closing:
            return
        document = self.document
        node = document.find(event.node_id)
        panel = self.editor.query_one(PropertiesPanel)
        if node is None:
            return
        field, value = event.field, event.value
        kind, _, name = field.partition(":")

        if field == "id":
            if value == node.id:
                return
            snapshot = document.to_json()
            if not document.rename(node.id, str(value).strip()):
                panel.set_error(field, "Invalid or duplicate id")
                return
            self._push_undo(snapshot)
            if self.selected == event.node_id:
                self.selected = node.id
            panel.node_id = node.id
            panel.set_error(field, None)
            await self.refresh_design()
            return

        if kind == "style":
            value = str(value).strip()
            error = validate(name, value, self.get_css_variables())
            panel.set_error(field, error)
            if error is not None or node.styles.get(name, "") == value:
                return
            self.checkpoint()
            if value:
                node.styles[name] = value
            else:
                node.styles.pop(name, None)
        elif kind == "doc":
            if getattr(document, name) == value:
                return
            self.checkpoint()
            setattr(document, name, str(value))
        elif kind == "prop":
            if node.id == ROOT_ID and name in ("width", "height"):
                try:
                    value = max(10, int(str(value)))
                except ValueError:
                    panel.set_error(field, "Expected a number")
                    return
                panel.set_error(field, None)
            current = node.props.get(name)
            if current == value or (isinstance(current, list) and ", ".join(map(str, current)) == value):
                return
            self.checkpoint()
            node.props[name] = value
        else:
            return
        await self.refresh_design()

    def _push_undo(self, snapshot: str) -> None:
        self._undo.append(snapshot)
        self._redo.clear()
        self.dirty = True

    # -- Undo / redo ---------------------------------------------------------------

    async def action_undo(self) -> None:
        if not self._undo:
            self.notify("Nothing to undo", severity="warning")
            return
        self._redo.append(self.document.to_json())
        self.document = Document.from_json(self._undo.pop())
        self.dirty = True
        await self.refresh_design(rebuild_panel=True)

    async def action_redo(self) -> None:
        if not self._redo:
            self.notify("Nothing to redo", severity="warning")
            return
        self._undo.append(self.document.to_json())
        self.document = Document.from_json(self._redo.pop())
        self.dirty = True
        await self.refresh_design(rebuild_panel=True)

    # -- Files -------------------------------------------------------------------------

    async def action_new(self) -> None:
        self.checkpoint()
        self.document = Document()
        self.path = None
        self.selected = ROOT_ID
        self.dirty = False
        await self.refresh_design(rebuild_panel=True)

    def load(self, path: Path) -> bool:
        try:
            self.document = Document.from_json(path.read_text(encoding="utf-8"))
        except Exception as error:
            self.notify(f"Unable to open {path}: {error}", severity="error")
            return False
        self.path = path
        self.selected = ROOT_ID
        self.dirty = False
        self._undo.clear()
        self._redo.clear()
        return True

    @work
    async def action_open(self) -> None:
        value = await self.push_screen_wait(
            PathDialog("Open design (.json)", str(self.path or ""), "Open")
        )
        if value and self.load(Path(value).expanduser()):
            await self.refresh_design(rebuild_panel=True)
            self.notify(f"Opened {value}")

    def save(self, path: Path) -> None:
        try:
            path.write_text(self.document.to_json(), encoding="utf-8")
        except Exception as error:
            self.notify(f"Unable to save: {error}", severity="error")
            return
        self.path = path
        self.dirty = False
        self._update_title()
        self.notify(f"Saved {path}")

    @work
    async def action_save(self) -> None:
        self.editor.query_one(PropertiesPanel).flush()
        if self.path is None:
            value = await self.push_screen_wait(
                PathDialog("Save design as (.json)", "design.json", "Save")
            )
            if not value:
                return
            path = Path(value).expanduser()
            if not path.suffix:
                path = path.with_suffix(".json")
        else:
            path = self.path
        self.save(path)

    @work
    async def action_export(self) -> None:
        self.editor.query_one(PropertiesPanel).flush()
        default = (self.path.with_suffix(".py").name if self.path else f"{self.document.class_name.lower()}.py")
        value = await self.push_screen_wait(PathDialog("Export Python app", default, "Export"))
        if not value:
            return
        path = Path(value).expanduser()
        try:
            path.write_text(generate(self.document), encoding="utf-8")
        except Exception as error:
            self.notify(f"Unable to export: {error}", severity="error")
            return
        self.notify(f"Exported {path} (run it with: python {path})")

    def action_preview(self) -> None:
        self.editor.query_one(PropertiesPanel).flush()
        self.push_screen(PreviewScreen(self.document))


def run(path: str | None = None) -> None:
    TextualEditor(path).run()


def _cli() -> None:
    import sys

    run(sys.argv[1] if len(sys.argv) > 1 else None)
