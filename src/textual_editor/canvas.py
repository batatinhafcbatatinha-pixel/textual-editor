"""The design canvas: shows the design with live widgets, and handles direct manipulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual import events
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.geometry import Offset, Size
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label

from textual_editor.builder import DESIGN_ID, ScreenSurface, build_surface
from textual_editor.catalog import CATALOG, is_container
from textual_editor.model import ROOT_ID, Document


def parse_offset(value: str | None) -> Offset:
    try:
        x, y = (int(float(part)) for part in str(value or "0 0").split()[:2])
        return Offset(x, y)
    except ValueError:
        return Offset(0, 0)


class DesignFrame(Container):
    """Represents the screen of the app being designed."""

    DEFAULT_CSS = """
    DesignFrame {
        box-sizing: content-box;
        border: tall $accent 60%;
        background: $background;
        layers: default;
    }
    DesignFrame .-design-selected {
        outline: heavy $warning;
    }
    """


@dataclass
class DragState:
    mode: Literal["move", "resize", "reparent"]
    node_id: str
    start: Offset
    start_offset: Offset
    start_size: Size
    moved: bool = False


class DesignCanvas(ScrollableContainer, can_focus=True):
    """Scrollable area holding the design frame."""

    DEFAULT_CSS = """
    DesignCanvas {
        align: center middle;
        background: $surface-darken-1;
        padding: 1 2;
    }
    DesignCanvas:focus { background-tint: $foreground 2%; }
    """

    BINDINGS = [
        Binding("delete,backspace", "delete", "Delete"),
        Binding("ctrl+d", "duplicate", "Duplicate"),
        Binding("escape", "select_parent", "Parent", show=False),
        Binding("up", "nudge(0,-1)", "Move", show=False),
        Binding("down", "nudge(0,1)", "Move", show=False),
        Binding("left", "nudge(-1,0)", "Move", show=False),
        Binding("right", "nudge(1,0)", "Move", show=False),
        Binding("shift+up", "grow(0,-1)", "Resize", show=False),
        Binding("shift+down", "grow(0,1)", "Resize", show=False),
        Binding("shift+left", "grow(-1,0)", "Resize", show=False),
        Binding("shift+right", "grow(1,0)", "Resize", show=False),
    ]

    # -- Messages (handled by the app, which owns the document) -------------

    class Selected(Message):
        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    class Moved(Message):
        """A node in a free layout was dragged to a new offset."""

        def __init__(self, node_id: str, offset: Offset) -> None:
            super().__init__()
            self.node_id = node_id
            self.offset = offset

    class Resized(Message):
        def __init__(self, node_id: str, size: Size) -> None:
            super().__init__()
            self.node_id = node_id
            self.size = size

    class Dropped(Message):
        """A node was dragged to a screen position (possibly into another container)."""

        def __init__(self, node_id: str, screen_offset: Offset) -> None:
            super().__init__()
            self.node_id = node_id
            self.screen_offset = screen_offset

    class Action(Message):
        """A keyboard action on the selected node."""

        def __init__(self, action: str, dx: int = 0, dy: int = 0) -> None:
            super().__init__()
            self.action = action
            self.dx = dx
            self.dy = dy

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.frame = DesignFrame(id="design-frame")
        self.surface = ScreenSurface()
        self.document: Document | None = None
        self.selected: str | None = None
        self._widgets: dict[str, Widget] = {}
        self._drag: DragState | None = None
        self._build_count = 0

    def compose(self):
        yield self.frame

    # -- Building ------------------------------------------------------------

    async def show(self, document: Document, selected: str | None) -> None:
        """Rebuild the canvas for a document."""
        self.document = document
        self.selected = selected
        root = document.root
        frame = self.frame
        frame.styles.width = int(root.props.get("width", 80))
        frame.styles.height = int(root.props.get("height", 24))
        self._build_count += 1
        surface = build_surface(document, self.app.get_css_variables(), design=True)
        with self.app.batch_update():
            await frame.remove_children()
            await frame.mount(surface)
        self.surface = surface
        self._index_widgets()
        self._update_selection()

    def _index_widgets(self) -> None:
        self._widgets = {ROOT_ID: self.surface}
        for widget in self.surface.walk_children(with_self=False):
            node_id = getattr(widget, DESIGN_ID, None)
            if node_id is not None:
                self._widgets[node_id] = widget
            # Widgets in the design must not take focus or input
            widget.can_focus = False

    def select(self, node_id: str | None) -> None:
        self.selected = node_id
        self._update_selection()

    def _update_selection(self) -> None:
        for node_id, widget in self._widgets.items():
            widget.set_class(node_id == self.selected and node_id != ROOT_ID, "-design-selected")

    def widget_for(self, node_id: str) -> Widget | None:
        return self._widgets.get(node_id)

    # -- Hit testing ---------------------------------------------------------

    def node_at(self, screen_offset: Offset, exclude: str | None = None) -> str | None:
        """Get the id of the node under a screen position (ROOT_ID for the frame itself).

        Args:
            screen_offset: Screen position.
            exclude: Ignore this node and its descendants (e.g. the node being dragged).
        """
        try:
            hits = [widget for widget, _ in self.screen.get_widgets_at(*screen_offset)]
        except Exception:
            return None
        for hit in hits:
            node_id = self._design_node(hit)
            if node_id is None:
                continue
            if exclude is not None and self.document is not None and node_id != ROOT_ID:
                if self.document.is_ancestor(exclude, node_id):
                    continue
            return node_id
        return None

    def _design_node(self, widget: Widget) -> str | None:
        node: Widget | None = widget
        while node is not None:
            node_id = getattr(node, DESIGN_ID, None)
            if node_id is not None:
                return node_id
            if node is self.surface or node is self.frame:
                return ROOT_ID
            if node is self:
                return None
            node = node.parent if isinstance(node.parent, Widget) else None
        return None

    def container_at(self, screen_offset: Offset, exclude: str | None = None) -> str | None:
        """The container which would receive a drop at a screen position."""
        document = self.document
        node_id = self.node_at(screen_offset, exclude)
        if document is None or node_id is None:
            return None
        while node_id is not None:
            node = document.find(node_id)
            inside_excluded = exclude is not None and document.is_ancestor(exclude, node_id)
            if node is not None and is_container(node.type) and not inside_excluded:
                return node_id
            parent = document.parent_of(node_id)
            node_id = parent.id if parent is not None else None
        return ROOT_ID

    def frame_offset(self, screen_offset: Offset) -> Offset:
        """Convert a screen position to an offset inside the frame's content."""
        content = self.surface.content_region
        return Offset(
            max(0, screen_offset.x - content.x), max(0, screen_offset.y - content.y)
        )

    # -- Mouse ---------------------------------------------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        self.focus()
        position = event.screen_offset
        node_id = self.node_at(position)
        if node_id is None:
            return
        event.stop()
        self.post_message(self.Selected(node_id))
        if node_id == ROOT_ID or self.document is None:
            return
        widget = self._widgets.get(node_id)
        parent = self.document.parent_of(node_id)
        node = self.document.find(node_id)
        if widget is None or parent is None or node is None:
            return
        region = widget.region
        if position == Offset(region.right - 1, region.bottom - 1):
            mode = "resize"
        elif (
            self.document.is_free(parent)
            and "dock" not in node.styles
            and not (node.type in CATALOG and CATALOG[node.type].docked)
        ):
            mode = "move"
        else:
            mode = "reparent"
        self._drag = DragState(
            mode, node_id, position, parse_offset(node.styles.get("offset")), region.size
        )
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        drag = self._drag
        if drag is None:
            return
        delta = event.screen_offset - drag.start
        if delta == Offset(0, 0) and not drag.moved:
            return
        drag.moved = True
        widget = self._widgets.get(drag.node_id)
        if widget is None:
            return
        if drag.mode == "move":
            widget.styles.offset = drag.start_offset + delta
        elif drag.mode == "resize":
            widget.styles.width = max(1, drag.start_size.width + delta.x)
            widget.styles.height = max(1, drag.start_size.height + delta.y)
        else:
            self.screen.show_ghost(drag.node_id, event.screen_offset)  # type: ignore[attr-defined]

    def on_mouse_up(self, event: events.MouseUp) -> None:
        drag = self._drag
        if drag is None:
            return
        self._drag = None
        self.release_mouse()
        if not drag.moved:
            return
        event.stop()
        delta = event.screen_offset - drag.start
        if drag.mode == "move":
            target = self.container_at(event.screen_offset, exclude=drag.node_id)
            if target is not None and target != ROOT_ID:
                # Dropped on a container: move it inside
                self.post_message(self.Dropped(drag.node_id, event.screen_offset))
            else:
                self.post_message(self.Moved(drag.node_id, drag.start_offset + delta))
        elif drag.mode == "resize":
            self.post_message(
                self.Resized(
                    drag.node_id,
                    Size(
                        max(1, drag.start_size.width + delta.x),
                        max(1, drag.start_size.height + delta.y),
                    ),
                )
            )
        else:
            self.screen.hide_ghost()  # type: ignore[attr-defined]
            self.post_message(self.Dropped(drag.node_id, event.screen_offset))

    # -- Keyboard actions ----------------------------------------------------

    def action_delete(self) -> None:
        self.post_message(self.Action("delete"))

    def action_duplicate(self) -> None:
        self.post_message(self.Action("duplicate"))

    def action_select_parent(self) -> None:
        self.post_message(self.Action("select_parent"))

    def action_nudge(self, dx: int, dy: int) -> None:
        self.post_message(self.Action("nudge", dx, dy))

    def action_grow(self, dx: int, dy: int) -> None:
        self.post_message(self.Action("grow", dx, dy))


class DragGhost(Label):
    """Follows the mouse while dragging something on to the canvas."""

    DEFAULT_CSS = """
    DragGhost {
        layer: ghost;
        position: absolute;
        display: none;
        padding: 0 1;
        background: $warning;
        color: $text-warning;
        text-style: bold;
    }
    """
