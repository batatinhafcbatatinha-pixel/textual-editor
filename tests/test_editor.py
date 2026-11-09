from __future__ import annotations

from textual.geometry import Offset
from textual.widgets import Button, Input

from textual_editor.app import TextualEditor
from textual_editor.canvas import DesignCanvas
from textual_editor.model import ROOT_ID
from textual_editor.panels import PaletteItem, PropertiesPanel
from textual_editor.screens import PreviewScreen

SIZE = (160, 50)


def palette_item(app: TextualEditor, widget_type: str) -> PaletteItem:
    return next(item for item in app.screen.query(PaletteItem) if item.widget_type == widget_type)


async def wait_for(pilot, condition, timeout: float = 3.0) -> None:
    """Wait until `condition()` is true (the app handles changes asynchronously)."""
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await pilot.pause(0.05)
    assert condition()


async def settle(pilot) -> None:
    """Wait for the editor to build the design and finish layout."""
    await pilot.pause()
    await pilot.pause(0.1)


def frame_origin(app: TextualEditor) -> Offset:
    return app.editor.canvas.surface.content_region.offset


async def drag(pilot, source, start: Offset, end: Offset) -> None:
    """Drag from `start` (relative to `source`, or the screen) to `end` (screen)."""
    await pilot.mouse_down(source, offset=start)
    await pilot.hover(None, offset=(end.x - 1, end.y))
    await pilot.hover(None, offset=end)
    await pilot.mouse_up(None, offset=end)
    await pilot.pause()


async def add_by_drag(pilot, app: TextualEditor, widget_type: str, at: Offset) -> None:
    origin = frame_origin(app)
    await drag(pilot, palette_item(app, widget_type), Offset(1, 0), origin + at)


async def test_drag_from_palette_creates_widget():
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Button", Offset(10, 5))
        node = app.document.find("button1")
        assert node is not None
        assert node.styles["offset"] == "10 5"
        assert app.selected == "button1"
        widget = app.editor.canvas.widget_for("button1")
        assert widget is not None
        assert widget.region.offset == frame_origin(app) + (10, 5)
        # The code view is up to date when shown
        app.screen.query_one("#editor-center").active = "editor-code-tab"
        await pilot.pause()
        assert "Button('Button', id='button1')" in app.screen.query_one("#editor-code").text


async def test_design_widgets_are_inert():
    app = TextualEditor()
    pressed: list[Button.Pressed] = []
    app.on_button_pressed = pressed.append  # type: ignore[attr-defined]
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Input", Offset(2, 2))
        await add_by_drag(pilot, app, "Button", Offset(2, 8))
        button = app.editor.canvas.widget_for("button1")
        await pilot.click(button)
        await pilot.pause()
        assert not pressed
        assert app.selected == "button1"
        await pilot.click(app.editor.canvas.widget_for("input1"))
        assert app.selected == "input1"
        assert not isinstance(app.focused, Input) or app.focused.name  # Only property fields
        assert app.focused is app.editor.canvas


async def test_move_and_resize_by_dragging():
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Placeholder", Offset(4, 2))
        widget = app.editor.canvas.widget_for("placeholder1")
        start = widget.region.offset
        await drag(pilot, None, start + (2, 1), start + (8, 4))
        assert app.document.find("placeholder1").styles["offset"] == "10 5"

        widget = app.editor.canvas.widget_for("placeholder1")
        corner = Offset(widget.region.right - 1, widget.region.bottom - 1)
        await drag(pilot, None, corner, corner + (5, 2))
        node = app.document.find("placeholder1")
        assert (node.styles["width"], node.styles["height"]) == ("25", "7")


async def test_drop_into_container_and_back_out():
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Vertical", Offset(30, 2))
        await add_by_drag(pilot, app, "Label", Offset(2, 2))
        await add_by_drag(pilot, app, "Button", Offset(32, 4))  # Dropped inside the Vertical
        vertical = app.document.find("vertical1")
        assert [child.id for child in vertical.children] == ["button1"]
        assert "offset" not in vertical.children[0].styles

        # Drag the label into the vertical, before the button
        label = app.editor.canvas.widget_for("label1")
        vertical_region = app.editor.canvas.widget_for("vertical1").content_region
        await drag(pilot, None, label.region.offset, vertical_region.offset)
        assert [child.id for child in vertical.children] == ["label1", "button1"]

        # And the button back out on to the screen
        button = app.editor.canvas.widget_for("button1")
        await drag(pilot, None, button.region.offset + (1, 1), frame_origin(app) + (5, 15))
        assert [child.id for child in app.document.root.children] == ["vertical1", "button1"]
        assert app.document.find("button1").styles["offset"] == "5 15"


async def test_properties_edit_validate_undo_redo():
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Button", Offset(2, 2))
        panel = app.screen.query_one(PropertiesPanel)
        panel.post_message(PropertiesPanel.Changed("button1", "style:width", "banana"))
        await pilot.pause()
        assert "width" not in app.document.find("button1").styles
        assert panel._fields["style:width"].has_class("-invalid")

        panel.post_message(PropertiesPanel.Changed("button1", "style:background", "$success"))
        panel.post_message(PropertiesPanel.Changed("button1", "prop:label", "OK"))
        await wait_for(pilot, lambda: app.document.find("button1").props["label"] == "OK")
        await pilot.pause()
        node = app.document.find("button1")
        assert node.styles["background"] == "$success"
        assert node.props["label"] == "OK"
        assert str(app.editor.canvas.widget_for("button1").label) == "OK"

        await app.action_undo()
        assert app.document.find("button1").props["label"] == "Button"
        await app.action_redo()
        assert app.document.find("button1").props["label"] == "OK"

        panel.post_message(PropertiesPanel.Changed("button1", "id", "ok"))
        await wait_for(pilot, lambda: app.selected == "ok")
        assert app.document.find("ok") is not None
        assert app.selected == "ok"


async def test_keyboard_actions():
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Label", Offset(4, 4))
        app.editor.canvas.focus()
        await pilot.press("right", "right", "down")
        assert app.document.find("label1").styles["offset"] == "6 5"
        await pilot.press("ctrl+d")
        assert app.document.find("label2").styles["offset"] == "8 6"
        assert app.selected == "label2"
        await pilot.press("delete")
        assert app.document.find("label2") is None
        assert app.selected == ROOT_ID


async def test_palette_double_click_adds_to_selected_container():
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Horizontal", Offset(2, 2))
        await pilot.double_click(palette_item(app, "Switch"))
        await pilot.pause()
        assert [c.id for c in app.document.find("horizontal1").children] == ["switch1"]


async def test_save_load_and_preview(tmp_path):
    app = TextualEditor()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await add_by_drag(pilot, app, "Button", Offset(3, 3))
        path = tmp_path / "design.json"
        app.save(path)
        app.document.root.children.clear()
        assert app.load(path)
        await app.refresh_design(rebuild_panel=True)
        assert app.document.find("button1") is not None

        app.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        preview_button = app.screen.query_one("#button1", Button)
        assert preview_button.region.offset == (3, 3)
        await pilot.press("escape")
        assert not isinstance(app.screen, PreviewScreen)
        assert isinstance(app.editor.canvas, DesignCanvas)


async def test_example_design_renders():
    from pathlib import Path

    example = Path(__file__).parent.parent / "examples" / "login.json"
    app = TextualEditor(str(example))
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.document.title == "Login"
        assert app.editor.canvas.widget_for("button1") is not None
        await app.select("label1")
        await pilot.pause()
        app.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        await pilot.press("escape")
    assert app.return_code in (None, 0)
