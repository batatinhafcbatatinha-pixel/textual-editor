"""Side panels: the widget palette, the document tree, and the properties editor."""

from __future__ import annotations

from typing import Any

from textual import events, on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.geometry import Offset
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Label, Select, Static, Switch, Tree

from textual_editor.catalog import CATALOG, CATEGORIES, WIDGETS, PropSpec, is_container
from textual_editor.model import ROOT_ID, Document, Node
from textual_editor.styles import STYLE_GROUPS, STYLES

# -- Palette -------------------------------------------------------------------


class PaletteItem(Static, can_focus=True):
    """A widget type which can be dragged on to the canvas (or added with enter / double click)."""

    def __init__(self, widget_type: str) -> None:
        super().__init__(widget_type, classes="palette-item")
        self.widget_type = widget_type
        self.tooltip = CATALOG[widget_type].description
        self._dragging = False
        self._start: Offset | None = None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        self._start = event.screen_offset
        self._dragging = False
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._start is None:
            return
        if not self._dragging and event.screen_offset == self._start:
            return
        self._dragging = True
        self.screen.show_ghost(self.widget_type, event.screen_offset)  # type: ignore[attr-defined]

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._start is None:
            return
        self._start = None
        self.release_mouse()
        if self._dragging:
            self._dragging = False
            self.screen.hide_ghost()  # type: ignore[attr-defined]
            self.post_message(Palette.Dropped(self.widget_type, event.screen_offset))

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2:
            self.post_message(Palette.Add(self.widget_type))

    def key_enter(self) -> None:
        self.post_message(Palette.Add(self.widget_type))


class Palette(VerticalScroll):
    """The list of widgets."""

    class Dropped(Message):
        """A widget type was dragged to a screen position."""

        def __init__(self, widget_type: str, screen_offset: Offset) -> None:
            super().__init__()
            self.widget_type = widget_type
            self.screen_offset = screen_offset

    class Add(Message):
        """Add a widget type to the selected container."""

        def __init__(self, widget_type: str) -> None:
            super().__init__()
            self.widget_type = widget_type

    def compose(self):
        for category in CATEGORIES:
            yield Label(category, classes="palette-category")
            for spec in WIDGETS:
                if spec.category == category:
                    yield PaletteItem(spec.type)


# -- Document tree ---------------------------------------------------------------


class DocumentTree(Tree[str]):
    """The hierarchy of the design."""

    class Selected(Message):
        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    def __init__(self, **kwargs) -> None:
        super().__init__("Screen", data=ROOT_ID, **kwargs)
        self.show_root = True
        self.guide_depth = 3
        self._syncing = False
        self._synced_id: str | None = None

    def show_document(self, document: Document, selected: str | None) -> None:
        self._syncing = True
        self._synced_id = selected
        try:
            self.clear()
            self.root.data = ROOT_ID
            self.root.set_label(f"Screen  [dim]{document.title}[/]")
            nodes = {ROOT_ID: self.root}

            def add(parent_tree, node: Node) -> None:
                for child in node.children:
                    label = f"{child.type}  [dim]#{child.id}[/]"
                    if child.children or is_container(child.type):
                        tree_node = parent_tree.add(label, data=child.id, expand=True)
                        add(tree_node, child)
                    else:
                        tree_node = parent_tree.add_leaf(label, data=child.id)
                    nodes[child.id] = tree_node

            add(self.root, document.root)
            self.root.expand()
            if selected in nodes:
                # Line numbers are known after the tree is refreshed
                self.call_after_refresh(self.move_cursor, nodes[selected])
        finally:
            self.call_after_refresh(lambda: self.call_after_refresh(self._end_sync))

    def _end_sync(self) -> None:
        self._syncing = False

    @on(Tree.NodeSelected)
    @on(Tree.NodeHighlighted)
    def _node_selected(self, event: Tree.NodeSelected | Tree.NodeHighlighted) -> None:
        event.stop()
        # Only when the user moves in the tree (not when it's rebuilt or synced)
        node_id = event.node.data
        if (
            self.has_focus
            and not self._syncing
            and node_id is not None
            and node_id != self._synced_id
        ):
            self._synced_id = node_id
            self.post_message(self.Selected(node_id))


# -- Properties ---------------------------------------------------------------------


class PropertiesPanel(VerticalScroll):
    """Edits the properties and styles of the selected node."""

    class Changed(Message):
        """A field was edited."""

        def __init__(self, node_id: str, field: str, value: Any) -> None:
            super().__init__()
            self.node_id = node_id
            self.field = field
            """"id", "doc:<name>", "prop:<name>" or "style:<name>"."""
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.node_id: str | None = None
        self._fields: dict[str, Widget] = {}
        self._pending: dict[str, Any] = {}
        self._timer: Timer | None = None

    # -- Building the form -------------------------------------------------

    async def show_node(self, document: Document, node_id: str | None, rebuild: bool = False) -> None:
        node = document.find(node_id) if node_id else None
        if node is None:
            self.node_id = None
            await self.remove_children()
            await self.mount(Label("Nothing selected", classes="properties-empty"))
            return
        if node_id == self.node_id and not rebuild:
            self._update_values(document, node)
            return
        self.flush()
        self.node_id = node_id
        self._fields = {}
        widgets: list[Widget] = []
        parent = document.parent_of(node.id)
        free_child = parent is not None and document.is_free(parent)
        container = is_container(node.type)

        widgets.append(Label(f"{node.type}", classes="properties-title"))
        if node.id == ROOT_ID:
            widgets.append(self._section("App"))
            widgets.append(self._text_field("doc:title", "Title", document.title))
            widgets.append(self._text_field("doc:class_name", "Class name", document.class_name))
            widgets.append(self._section("Design size"))
            widgets.append(self._text_field("prop:width", "Width", str(node.props.get("width", 80))))
            widgets.append(self._text_field("prop:height", "Height", str(node.props.get("height", 24))))
            widgets.append(
                self._bool_field("prop:free_layout", "Free layout", bool(node.props.get("free_layout", True)))
            )
        else:
            spec = CATALOG[node.type]
            widgets.append(self._section("Widget"))
            widgets.append(self._text_field("id", "Id", node.id))
            for prop in spec.all_props:
                widgets.append(self._prop_field(prop, node.props.get(prop.name, prop.default)))

        for group in STYLE_GROUPS:
            specs = [
                style
                for style in STYLES
                if style.group == group
                and (not style.containers_only or container)
                and (not style.free_only or free_child)
            ]
            if not specs:
                continue
            widgets.append(self._section(group))
            for style in specs:
                field = f"style:{style.name}"
                value = node.styles.get(style.name, "")
                if style.kind == "choice":
                    widgets.append(self._choice_field(field, style.name, value, style.choices))
                else:
                    widgets.append(
                        self._text_field(field, style.name, value, placeholder=style.placeholder)
                    )

        with self.app.batch_update():
            await self.remove_children()
            await self.mount_all(widgets)
        self.scroll_home(animate=False)

    def _section(self, title: str) -> Label:
        return Label(title, classes="properties-section")

    def _row(self, field: str, title: str, editor: Widget) -> Widget:
        self._fields[field] = editor
        error = Label("", classes="field-error")
        error.display = False
        return Vertical(
            Label(title, classes="field-label"), editor, error, classes="field"
        )

    def _text_field(self, field: str, title: str, value: str, placeholder: str = "") -> Widget:
        return self._row(
            field, title, Input(str(value), placeholder=placeholder, compact=True, name=field)
        )

    def _bool_field(self, field: str, title: str, value: bool) -> Widget:
        self._fields[field] = switch = Switch(value, name=field)
        return Horizontal(switch, Label(title, classes="field-label"), classes="field field-bool")

    def _choice_field(self, field: str, title: str, value: str, choices: tuple[str, ...]) -> Widget:
        options = [(choice or "(default)", choice) for choice in choices]
        select: Select[str] = Select(
            options,
            value=value if value in choices else Select.NULL,
            allow_blank=True,
            compact=True,
            name=field,
        )
        return self._row(field, title, select)

    def _prop_field(self, prop: PropSpec, value: Any) -> Widget:
        field = f"prop:{prop.name}"
        if prop.kind == "bool":
            return self._bool_field(field, prop.title, bool(value))
        if prop.kind == "choice":
            return self._choice_field(field, prop.title, str(value), prop.choices)
        if prop.kind == "list":
            text = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
            return self._text_field(field, prop.title, text)
        placeholder = "use \\n for new lines" if prop.kind == "multiline" else ""
        return self._text_field(field, prop.title, "" if value is None else str(value), placeholder)

    def _update_values(self, document: Document, node: Node) -> None:
        """Update field values (e.g. after a drag) without rebuilding the form."""
        for field, editor in self._fields.items():
            if editor.has_focus or field in self._pending:
                continue
            value = self._current_value(document, node, field)
            if isinstance(editor, Input):
                if editor.value != value:
                    with editor.prevent(Input.Changed):
                        editor.value = value
            elif isinstance(editor, Switch):
                with editor.prevent(Switch.Changed):
                    editor.value = bool(value)

    def _current_value(self, document: Document, node: Node, field: str) -> Any:
        kind, _, name = field.partition(":")
        if field == "id":
            return node.id
        if kind == "doc":
            return str(getattr(document, name))
        if kind == "style":
            return node.styles.get(name, "")
        value = node.props.get(name, "")
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        if isinstance(value, bool):
            return value
        return "" if value is None else str(value)

    # -- Errors -------------------------------------------------------------

    def set_error(self, field: str, message: str | None) -> None:
        editor = self._fields.get(field)
        if editor is None or editor.parent is None:
            return
        editor.set_class(message is not None, "-invalid")
        for child in editor.parent.children:
            if isinstance(child, Label) and child.has_class("field-error"):
                child.update(message or "")
                child.display = message is not None

    # -- Events -------------------------------------------------------------

    def _queue(self, field: str, value: Any, delay: float = 0.4) -> None:
        self._pending[field] = value
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(delay, self.flush)

    def flush(self) -> None:
        """Send pending changes."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        pending, self._pending = self._pending, {}
        if self.node_id is None:
            return
        for field, value in pending.items():
            self.post_message(self.Changed(self.node_id, field, value))

    @on(Input.Changed)
    def _input_changed(self, event: Input.Changed) -> None:
        event.stop()
        # Only edits by the user (ignore values set when the form is built)
        if event.input.name and event.input.has_focus:
            self._queue(event.input.name, event.value)

    @on(Input.Submitted)
    def _input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input.name:
            self._pending[event.input.name] = event.value
            self.flush()

    @on(Switch.Changed)
    def _switch_changed(self, event: Switch.Changed) -> None:
        event.stop()
        if event.switch.name:
            self._pending[event.switch.name] = event.value
            self.flush()

    @on(Select.Changed)
    def _select_changed(self, event: Select.Changed) -> None:
        event.stop()
        name = event.select.name
        if name:
            value = "" if event.value is Select.NULL else event.value
            self._pending[name] = value
            self.flush()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        if self._pending:
            self.flush()
