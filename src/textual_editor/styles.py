"""CSS properties editable in the properties panel."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Mapping

from textual.css.parse import parse_declarations

StyleKind = Literal["text", "choice", "path"]


@dataclass(frozen=True)
class StyleSpec:
    name: str
    """CSS property name."""
    group: str
    kind: StyleKind = "text"
    choices: tuple[str, ...] = ()
    placeholder: str = ""
    containers_only: bool = False
    free_only: bool = False
    """Only for children of a free (absolute) layout."""


STYLES: list[StyleSpec] = [
    StyleSpec("offset", "Position", placeholder="x y", free_only=True),
    StyleSpec("dock", "Position", "choice", ("", "top", "right", "bottom", "left")),
    StyleSpec("width", "Size", placeholder="auto, 20, 50%, 1fr"),
    StyleSpec("height", "Size", placeholder="auto, 5, 50%, 1fr"),
    StyleSpec("min-width", "Size", placeholder="e.g. 10"),
    StyleSpec("min-height", "Size", placeholder="e.g. 3"),
    StyleSpec("margin", "Spacing", placeholder="1 or 1 2 or 1 2 1 2"),
    StyleSpec("padding", "Spacing", placeholder="1 or 1 2 or 1 2 1 2"),
    StyleSpec("layout", "Layout", "choice", ("", "vertical", "horizontal", "grid"), containers_only=True),
    StyleSpec("grid-size", "Layout", placeholder="columns rows", containers_only=True),
    StyleSpec("grid-gutter", "Layout", placeholder="vertical horizontal", containers_only=True),
    StyleSpec("align", "Layout", placeholder="center middle", containers_only=True),
    StyleSpec("content-align", "Layout", placeholder="center middle"),
    StyleSpec("background", "Colors", placeholder="red, #ff0000, $primary, red 50%"),
    StyleSpec("color", "Colors", placeholder="white, $text"),
    StyleSpec("background-image", "Colors", "path", placeholder="path/to/image.png"),
    StyleSpec("background-image-fit", "Colors", "choice", ("", "cover", "contain", "fill")),
    StyleSpec("border", "Border", placeholder="round, solid red, heavy $accent"),
    StyleSpec("outline", "Border", placeholder="solid red"),
    StyleSpec("text-align", "Text", "choice", ("", "left", "center", "right", "justify")),
    StyleSpec("text-style", "Text", placeholder="bold, italic, underline"),
    StyleSpec("opacity", "Other", placeholder="0.5 or 50%"),
    StyleSpec("visibility", "Other", "choice", ("", "visible", "hidden")),
]

STYLE_GROUPS: list[str] = list(dict.fromkeys(spec.group for spec in STYLES))

_RE_VARIABLE = re.compile(r"\$([A-Za-z0-9_-]+)")


def substitute_variables(value: str, variables: Mapping[str, str]) -> str:
    """Replace `$variable` references with their values (unknown variables are kept)."""
    return _RE_VARIABLE.sub(lambda match: variables.get(match.group(1), match.group(0)), value)


def quote_path(name: str, value: str) -> str:
    """Quote values which must be CSS strings."""
    if name == "background-image" and value and value != "none":
        value = value.strip("\"'").replace("\\", "/")
        return f'"{value}"'
    return value


def declarations(styles: Mapping[str, str], variables: Mapping[str, str] | None = None) -> str:
    """Build CSS declarations from a styles mapping."""
    lines = []
    for name, value in styles.items():
        value = str(value).strip()
        if not value:
            continue
        value = quote_path(name, value)
        if variables is not None:
            value = substitute_variables(value, variables)
        lines.append(f"{name}: {value};")
    return " ".join(lines)


def validate(name: str, value: str, variables: Mapping[str, str] | None = None) -> str | None:
    """Validate a CSS declaration.

    Returns:
        An error message, or `None` if the declaration is valid (or empty).
    """
    value = value.strip()
    if not value:
        return None
    css = declarations({name: value}, variables)
    try:
        parse_declarations(css, read_from=("textual-editor", ""))
    except Exception as error:
        message = getattr(error, "message", None) or str(error)
        return re.sub(r"\[/?[a-z ]*\]", "", str(message)).strip() or "Invalid value"
    return None
