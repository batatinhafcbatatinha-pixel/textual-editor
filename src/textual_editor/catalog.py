"""The catalog of widgets which can be placed in a design."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from textual.widget import Widget

from textual_editor.model import Node

PropKind = Literal["text", "multiline", "int", "float", "bool", "choice", "list", "path"]

_UNSET = object()


@dataclass(frozen=True)
class PropSpec:
    """A widget property shown in the properties panel."""

    name: str
    """Property name (stored in `Node.props`)."""
    kind: PropKind = "text"
    default: Any = ""
    """Value given to new widgets."""
    arg: int | str | None = None
    """Positional index or keyword of the constructor argument (None for an attribute set after construction)."""
    choices: tuple[str, ...] = ()
    omit: Any = _UNSET
    """Don't pass the argument when the value equals this (the widget's own default)."""
    label: str = ""

    @property
    def title(self) -> str:
        return self.label or self.name.replace("_", " ").capitalize()

    def to_python(self, value: Any) -> Any:
        """Convert a stored value to the value passed to the widget."""
        kind = self.kind
        if kind == "bool":
            return bool(value)
        if kind == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return int(self.default or 0)
        if kind == "float":
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(self.default or 0)
        if kind == "list":
            if isinstance(value, str):
                value = [item.strip() for item in value.split(",") if item.strip()]
            return list(value)
        if kind == "path":
            return value or None
        if kind == "multiline":
            return str(value).replace("\\n", "\n")
        return "" if value is None else str(value)


COMMON_ATTRIBUTES = (
    PropSpec("border_title", default="", omit=""),
    PropSpec("tooltip", default="", omit=""),
)
"""Attributes every widget has."""


@dataclass(frozen=True)
class WidgetSpec:
    """How to create one kind of widget."""

    type: str
    category: str
    module: str = "textual.widgets"
    container: bool = False
    props: tuple[PropSpec, ...] = ()
    styles: dict[str, str] = field(default_factory=dict)
    """Default styles for new widgets."""
    description: str = ""
    convert: dict[str, Callable[[Any], Any]] = field(default_factory=dict)
    """Extra conversion of a property value before it is passed to the widget."""
    docked: bool = False
    """Docked by its default CSS (never positioned freely)."""

    @property
    def all_props(self) -> tuple[PropSpec, ...]:
        return (*self.props, *COMMON_ATTRIBUTES)

    def widget_class(self) -> type[Widget]:
        return getattr(importlib.import_module(self.module), self.type)

    def default_props(self) -> dict[str, Any]:
        return {prop.name: prop.default for prop in self.all_props}

    def value(self, prop: PropSpec, props: dict[str, Any]) -> Any:
        value = prop.to_python(props.get(prop.name, prop.default))
        if prop.name in self.convert:
            value = self.convert[prop.name](value)
        return value

    def arguments(self, props: dict[str, Any]) -> tuple[list[Any], dict[str, Any], dict[str, Any]]:
        """Get positional arguments, keyword arguments, and attributes for a widget."""
        positional: dict[int, Any] = {}
        keywords: dict[str, Any] = {}
        attributes: dict[str, Any] = {}
        for prop in self.all_props:
            value = self.value(prop, props)
            if prop.omit is not _UNSET and value == prop.to_python(prop.omit):
                if prop.arg is None or isinstance(prop.arg, str):
                    continue
            if prop.arg is None:
                attributes[prop.name] = value
            elif isinstance(prop.arg, int):
                positional[prop.arg] = value
            else:
                keywords[prop.arg] = value
        args = [positional[index] for index in sorted(positional)]
        return args, keywords, attributes

    def build(self, node: Node) -> Widget:
        """Create a live widget for a node."""
        args, keywords, attributes = self.arguments(node.props)
        widget = self.widget_class()(*args, id=node.id, **keywords)
        for name, value in attributes.items():
            setattr(widget, name, value)
        return widget

    def code(self, node: Node) -> tuple[str, dict[str, Any]]:
        """Python code for the constructor call, and attributes to set afterwards."""
        args, keywords, attributes = self.arguments(node.props)
        parts = [repr(arg) for arg in args]
        parts.append(f"id={node.id!r}")
        parts.extend(f"{key}={value!r}" for key, value in keywords.items())
        return f"{self.type}({', '.join(parts)})", attributes


def _options(values: list[str]) -> list[tuple[str, str]]:
    return [(value, value) for value in values]


def _numbers(values: list[str]) -> list[float]:
    numbers = []
    for value in values:
        try:
            numbers.append(float(value))
        except ValueError:
            pass
    return numbers


CONTAINER_STYLES = {"width": "30", "height": "8", "border": "round"}

WIDGETS: list[WidgetSpec] = [
    # Containers
    WidgetSpec("Container", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Generic container (vertical layout)"),
    WidgetSpec("Vertical", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Stacks children vertically"),
    WidgetSpec("Horizontal", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Places children side by side"),
    WidgetSpec("Grid", "Containers", "textual.containers", True,
               styles={**CONTAINER_STYLES, "grid-size": "2 2"}, description="Grid layout"),
    WidgetSpec("VerticalScroll", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Vertical layout with a scrollbar"),
    WidgetSpec("HorizontalScroll", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Horizontal layout with a scrollbar"),
    WidgetSpec("Center", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Centers children horizontally"),
    WidgetSpec("Middle", "Containers", "textual.containers", True, styles=dict(CONTAINER_STYLES),
               description="Centers children vertically"),
    # Basic
    WidgetSpec("Label", "Basic", props=(PropSpec("text", default="Label", arg=0),),
               description="A line of text"),
    WidgetSpec("Static", "Basic", props=(PropSpec("content", "multiline", "Static text", arg=0),),
               description="Text (supports markup)"),
    WidgetSpec("Button", "Basic", props=(
        PropSpec("label", default="Button", arg=0),
        PropSpec("variant", "choice", "default", arg="variant",
                 choices=("default", "primary", "success", "warning", "error"), omit="default"),
    ), description="A clickable button"),
    WidgetSpec("Markdown", "Basic", props=(
        PropSpec("markdown", "multiline", "# Title\\n\\nSome *Markdown* text.", arg=0),
    ), styles={"width": "40", "height": "auto"}, description="Rendered Markdown"),
    WidgetSpec("Digits", "Basic", props=(PropSpec("value", default="12:34", arg=0),),
               description="Large digits"),
    WidgetSpec("Rule", "Basic", props=(
        PropSpec("orientation", "choice", "horizontal", arg="orientation",
                 choices=("horizontal", "vertical"), omit="horizontal"),
        PropSpec("line_style", "choice", "solid", arg="line_style",
                 choices=("solid", "heavy", "thick", "double", "dashed", "ascii", "blank", "hidden"),
                 omit="solid"),
    ), styles={"width": "30"}, description="A separator line"),
    WidgetSpec("Placeholder", "Basic", props=(PropSpec("label", default="Placeholder", arg=0),),
               styles={"width": "20", "height": "5"}, description="A placeholder box"),
    # Input
    WidgetSpec("Input", "Input", props=(
        PropSpec("value", default="", arg="value", omit=""),
        PropSpec("placeholder", default="Type here", arg="placeholder", omit=""),
        PropSpec("password", "bool", False, arg="password", omit=False),
    ), styles={"width": "30"}, description="Single line text input"),
    WidgetSpec("TextArea", "Input", props=(PropSpec("text", "multiline", "", arg=0),),
               styles={"width": "40", "height": "8"}, description="Multi-line text editor"),
    WidgetSpec("Checkbox", "Input", props=(
        PropSpec("label", default="Checkbox", arg=0),
        PropSpec("value", "bool", False, arg=1),
    ), description="A checkbox"),
    WidgetSpec("RadioButton", "Input", props=(
        PropSpec("label", default="Option", arg=0),
        PropSpec("value", "bool", False, arg=1),
    ), description="A radio button"),
    WidgetSpec("Switch", "Input", props=(PropSpec("value", "bool", False, arg="value", omit=False),),
               description="An on/off switch"),
    WidgetSpec("Select", "Input", props=(
        PropSpec("options", "list", ["One", "Two", "Three"], arg=0, label="Options (comma separated)"),
        PropSpec("prompt", default="Select", arg="prompt", omit="Select"),
    ), styles={"width": "30"}, convert={"options": _options}, description="A dropdown"),
    # Display
    WidgetSpec("ProgressBar", "Display", props=(
        PropSpec("total", "float", 100.0, arg="total"),
        PropSpec("show_eta", "bool", False, arg="show_eta", omit=True),
    ), description="A progress bar"),
    WidgetSpec("Sparkline", "Display", props=(
        PropSpec("data", "list", ["1", "4", "2", "8", "5", "7", "3"], arg=0, label="Data (comma separated)"),
    ), styles={"width": "30", "height": "3"}, convert={"data": _numbers}, description="A small chart"),
    WidgetSpec("LoadingIndicator", "Display", styles={"width": "10", "height": "3"},
               description="Animated loading dots"),
    WidgetSpec("Header", "Display", props=(
        PropSpec("show_clock", "bool", False, arg="show_clock", omit=False),
    ), description="App header (docked at the top)", docked=True),
    WidgetSpec("Footer", "Display", description="Key bindings (docked at the bottom)", docked=True),
    # Media (from the textual fork)
    WidgetSpec("Image", "Media", props=(
        PropSpec("image", "path", "", arg=0, label="Image file"),
        PropSpec("fit", "choice", "contain", arg="fit", choices=("contain", "cover", "fill"), omit="contain"),
    ), styles={"width": "24", "height": "8"}, description="An image (Sixel or half blocks)"),
    WidgetSpec("Video", "Media", props=(
        PropSpec("source", "path", "", arg=0, label="Video file"),
        PropSpec("autoplay", "bool", False, arg="autoplay", omit=False),
        PropSpec("loop", "bool", False, arg="loop", omit=False),
    ), styles={"width": "40", "height": "12"}, description="A video with audio"),
]

CATALOG: dict[str, WidgetSpec] = {spec.type: spec for spec in WIDGETS}

CATEGORIES: list[str] = list(dict.fromkeys(spec.category for spec in WIDGETS))


def get_spec(widget_type: str) -> WidgetSpec:
    return CATALOG[widget_type]


def is_container(widget_type: str) -> bool:
    return widget_type == "Screen" or (widget_type in CATALOG and CATALOG[widget_type].container)
