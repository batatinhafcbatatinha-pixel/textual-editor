"""The design document: a tree of nodes, each describing one widget."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

ROOT_ID = "screen"
FORMAT_VERSION = 1


@dataclass
class Node:
    """A widget in the design."""

    type: str
    """Widget type (a key of the widget catalog)."""
    id: str
    """Unique id (also the widget's DOM id in generated code)."""
    props: dict[str, Any] = field(default_factory=dict)
    """Widget properties (constructor arguments and attributes)."""
    styles: dict[str, str] = field(default_factory=dict)
    """CSS declarations, mapping property name (e.g. "background") to value."""
    children: list[Node] = field(default_factory=list)

    def walk(self) -> Iterator[Node]:
        """Iterate over this node and all descendants (depth first)."""
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "props": dict(self.props),
            "styles": dict(self.styles),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        return cls(
            type=data["type"],
            id=data["id"],
            props=dict(data.get("props", {})),
            styles={key: str(value) for key, value in data.get("styles", {}).items()},
            children=[cls.from_dict(child) for child in data.get("children", [])],
        )

    def copy(self) -> Node:
        return Node.from_dict(self.to_dict())


def default_root() -> Node:
    return Node(
        type="Screen",
        id=ROOT_ID,
        props={"free_layout": True, "width": 80, "height": 24},
    )


@dataclass
class Document:
    """A design: the screen (root node) plus app settings."""

    root: Node = field(default_factory=default_root)
    title: str = "My App"
    class_name: str = "MyApp"

    # -- Queries -------------------------------------------------------------

    def find(self, node_id: str) -> Node | None:
        for node in self.root.walk():
            if node.id == node_id:
                return node
        return None

    def parent_of(self, node_id: str) -> Node | None:
        for node in self.root.walk():
            if any(child.id == node_id for child in node.children):
                return node
        return None

    def is_free(self, node: Node) -> bool:
        """Are the children of this node positioned freely (absolute offsets)?"""
        return node.id == ROOT_ID and bool(node.props.get("free_layout", True))

    def is_ancestor(self, ancestor_id: str, node_id: str) -> bool:
        """Is `ancestor_id` the node `node_id` or one of its ancestors?"""
        ancestor = self.find(ancestor_id)
        return ancestor is not None and any(n.id == node_id for n in ancestor.walk())

    # -- Ids -----------------------------------------------------------------

    def new_id(self, widget_type: str, reserved: set[str] | None = None) -> str:
        """Generate a unique id for a new node, e.g. "button3".

        Args:
            widget_type: Widget type, e.g. "Button".
            reserved: Additional ids which are taken.
        """
        base = re.sub(r"(?<!^)(?=[A-Z])", "_", widget_type).lower()
        used = {node.id for node in self.root.walk()} | (reserved or set())
        index = 1
        while f"{base}{index}" in used:
            index += 1
        return f"{base}{index}"

    def rename(self, node_id: str, new_id: str) -> bool:
        """Change a node's id. Returns False if the id is invalid or in use."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", new_id):
            return False
        if new_id != node_id and self.find(new_id) is not None:
            return False
        node = self.find(node_id)
        if node is None or node.id == ROOT_ID:
            return False
        node.id = new_id
        return True

    # -- Mutations -----------------------------------------------------------

    def insert(self, parent_id: str, node: Node, index: int | None = None) -> None:
        parent = self.find(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        if index is None:
            parent.children.append(node)
        else:
            parent.children.insert(index, node)

    def remove(self, node_id: str) -> Node | None:
        parent = self.parent_of(node_id)
        if parent is None:
            return None
        for index, child in enumerate(parent.children):
            if child.id == node_id:
                return parent.children.pop(index)
        return None

    def move(self, node_id: str, parent_id: str, index: int | None = None) -> bool:
        """Move a node to another parent. Returns False if not possible."""
        if self.is_ancestor(node_id, parent_id):
            return False  # Can't move a node inside itself
        node = self.remove(node_id)
        if node is None:
            return False
        self.insert(parent_id, node, index)
        return True

    def duplicate(self, node_id: str) -> Node | None:
        """Duplicate a node (with new ids) next to the original."""
        node = self.find(node_id)
        parent = self.parent_of(node_id)
        if node is None or parent is None:
            return None
        clone = node.copy()
        reserved: set[str] = set()
        for copy_node in clone.walk():
            copy_node.id = self.new_id(copy_node.type, reserved)
            reserved.add(copy_node.id)
        parent.children.insert(parent.children.index(node) + 1, clone)
        return clone

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "textual-editor",
            "version": FORMAT_VERSION,
            "title": self.title,
            "class_name": self.class_name,
            "root": self.root.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        if data.get("format") != "textual-editor":
            raise ValueError("Not a textual-editor design file")
        return cls(
            root=Node.from_dict(data["root"]),
            title=data.get("title", "My App"),
            class_name=data.get("class_name", "MyApp"),
        )

    @classmethod
    def from_json(cls, text: str) -> Document:
        return cls.from_dict(json.loads(text))
