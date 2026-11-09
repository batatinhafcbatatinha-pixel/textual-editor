"""Build live widgets from a design (used by the canvas and the preview)."""

from __future__ import annotations

from typing import Mapping

from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Static

from textual_editor.catalog import CATALOG, is_container
from textual_editor.codegen import node_styles
from textual_editor.model import Document, Node
from textual_editor.styles import declarations

DESIGN_ID = "_design_id"
"""Attribute set on live widgets in the canvas, with the id of their node."""


def apply_styles(widget: Widget, css: str) -> str | None:
    """Apply inline CSS to a widget. Returns an error message, or None."""
    if not css:
        return None
    try:
        widget.set_styles(css)
    except Exception as error:
        return getattr(error, "message", None) or str(error)
    return None


def _header_stand_in(document: Document, node: Node, variables: Mapping[str, str]) -> Widget:
    clock = "  [dim]12:34:56[/]" if node.props.get("show_clock") else ""
    widget = Static(f"[b]{document.title}[/]{clock}", id=node.id)
    widget.set_styles(
        "dock: top; width: 100%; height: 1; content-align: center middle;"
        f"background: {variables.get('panel', '#333333')};"
        f"color: {variables.get('foreground', '#e0e0e0')};"
    )
    return widget


def _footer_stand_in(document: Document, node: Node, variables: Mapping[str, str]) -> Widget:
    widget = Static("[b]Footer[/]  [dim]key bindings are shown here[/]", id=node.id)
    widget.set_styles(
        "dock: bottom; width: 100%; height: 1; padding: 0 1;"
        f"background: {variables.get('panel', '#333333')};"
        f"color: {variables.get('foreground', '#e0e0e0')};"
    )
    return widget


STAND_INS = {"Header": _header_stand_in, "Footer": _footer_stand_in}
"""Look-alikes used on the canvas (the real widgets show the editor's own title and keys)."""


def build_widget(
    document: Document,
    node: Node,
    parent: Node | None,
    variables: Mapping[str, str],
    design: bool,
) -> Widget:
    """Build the live widget for a node (and its children).

    Args:
        document: The design.
        node: The node to build.
        parent: The parent node.
        variables: Theme CSS variables (to resolve `$variables` in inline styles).
        design: Build for the design canvas (widgets are tagged with their node id).
    """
    spec = CATALOG[node.type]
    try:
        if design and node.type in STAND_INS:
            # Header and Footer show the editor's own title and bindings, so the
            # canvas shows look-alikes with the design's title.
            widget = STAND_INS[node.type](document, node, variables)
        elif is_container(node.type):
            children = [
                build_widget(document, child, node, variables, design)
                for child in node.children
            ]
            _args, keywords, attributes = spec.arguments(node.props)
            widget = spec.widget_class()(*children, id=node.id, **keywords)
            for name, value in attributes.items():
                setattr(widget, name, value)
        else:
            widget = spec.build(node)
    except Exception as error:
        widget = Static(f"{node.type}: {error}", id=node.id)
        widget.styles.border = ("heavy", "red")
    apply_styles(widget, declarations(node_styles(document, node, parent), variables))
    if design:
        setattr(widget, DESIGN_ID, node.id)
    return widget


def build_children(
    document: Document, variables: Mapping[str, str], design: bool
) -> list[Widget]:
    """Build the widgets for the children of the root (screen) node."""
    root = document.root
    return [build_widget(document, child, root, variables, design) for child in root.children]


class ScreenSurface(Container):
    """Stands in for the designed app's Screen (it gets the Screen's styles).

    Placed over an opaque background, so a translucent screen background looks
    like it does in the real app.
    """

    DEFAULT_CSS = """
    ScreenSurface {
        width: 100%;
        height: 100%;
    }
    """


def build_surface(document: Document, variables: Mapping[str, str], design: bool) -> ScreenSurface:
    """Build the screen surface with all the widgets of a design."""
    surface = ScreenSurface(*build_children(document, variables, design))
    apply_styles(surface, screen_css(document, variables))
    if document.is_free(document.root):
        surface.styles.layout = "vertical"
    return surface


def screen_css(document: Document, variables: Mapping[str, str]) -> str:
    """Inline CSS for whatever represents the screen."""
    return declarations(document.root.styles, variables)
