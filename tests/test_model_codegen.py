from __future__ import annotations

import pytest

from textual_editor.catalog import CATALOG, WIDGETS
from textual_editor.codegen import generate
from textual_editor.model import ROOT_ID, Document, Node
from textual_editor.styles import validate


def make_node(document: Document, widget_type: str, **styles: str) -> Node:
    spec = CATALOG[widget_type]
    return Node(
        widget_type,
        document.new_id(widget_type),
        spec.default_props(),
        {**spec.styles, **{name.replace("_", "-"): value for name, value in styles.items()}},
    )


def sample_document() -> Document:
    document = Document(title="Sample", class_name="SampleApp")
    button = make_node(document, "Button", offset="2 1")
    button.props["variant"] = "primary"
    button.props["border_title"] = "Title"
    document.insert(ROOT_ID, button)
    panel = make_node(document, "Vertical", offset="10 5", background="$panel")
    document.insert(ROOT_ID, panel)
    document.insert(panel.id, make_node(document, "Label"))
    document.insert(panel.id, make_node(document, "Select"))
    return document


def test_ids_are_unique():
    document = Document()
    document.insert(ROOT_ID, Node("Button", document.new_id("Button")))
    assert document.new_id("Button") == "button2"
    assert document.new_id("VerticalScroll") == "vertical_scroll1"


def test_move_and_duplicate():
    document = sample_document()
    panel = document.root.children[1]
    assert document.move("button1", panel.id)
    assert [child.id for child in panel.children] == ["label1", "select1", "button1"]
    assert not document.move(panel.id, "label1")  # Not into its own descendant
    clone = document.duplicate(panel.id)
    assert clone is not None
    ids = [node.id for node in document.root.walk()]
    assert len(ids) == len(set(ids))


def test_rename():
    document = sample_document()
    assert document.rename("button1", "ok_button")
    assert not document.rename("ok_button", "label1")  # duplicate
    assert not document.rename("ok_button", "1bad")
    assert not document.rename(ROOT_ID, "other")


def test_json_round_trip():
    document = sample_document()
    assert Document.from_json(document.to_json()).to_dict() == document.to_dict()


def test_generated_code_compiles():
    source = generate(sample_document())
    compile(source, "generated.py", "exec")
    assert "class SampleApp(App):" in source
    assert "position: absolute;" in source
    assert "offset: 2 1;" in source
    assert "background: $panel;" in source
    assert "button1.border_title = 'Title'" in source
    assert "variant='primary'" in source


def test_every_widget_generates_code():
    document = Document()
    for spec in WIDGETS:
        document.insert(ROOT_ID, make_node(document, spec.type))
    compile(generate(document), "generated.py", "exec")


async def test_generated_app_runs(tmp_path):
    source = generate(sample_document())
    namespace: dict = {}
    exec(compile(source, "generated.py", "exec"), namespace)
    app = namespace["SampleApp"]()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        button = app.query_one("#button1")
        assert button.region.offset == (2, 1)
        assert button.border_title == "Title"
        assert app.query_one("#vertical1").region.offset == (10, 5)


@pytest.mark.parametrize(
    "name, value, valid",
    [
        ("width", "20", True),
        ("width", "50%", True),
        ("width", "banana", False),
        ("background", "$primary", True),
        ("border", "round red", True),
        ("offset", "3 4", True),
        ("background-image", "C:\\images\\a.png", True),
    ],
)
def test_validate(name, value, valid):
    variables = {"primary": "#0178D4"}
    assert (validate(name, value, variables) is None) == valid
