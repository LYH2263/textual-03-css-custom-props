"""Tests for subtree scoped CSS custom properties.

These tests drive real applications with ``App.run_test`` and a Pilot, and
assert both resolved styles and visible / layout effects.
"""

from __future__ import annotations

import pytest

from textual import work
from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.lazy import Lazy, Reveal
from textual.widgets import Label, Static

PANEL_CSS = """
.panel {
    height: 3;
    border: tall $accent;
    width: $panel-w;
    color: $accent;
}
"""

RED = Color.parse("red")
GREEN = Color.parse("green")
PURPLE = Color.parse("purple")


def _border_color(widget: Static) -> Color:
    return widget.styles.border_left[1]


async def _settle(pilot) -> None:
    """Run enough frames for mounts and layout refreshes to settle."""
    for _ in range(5):
        await pilot.pause()


@pytest.mark.asyncio
async def test_same_stylesheet_rules_diverge_per_subtree() -> None:
    """One shared rule must produce different final values in two subtrees."""

    class PanelApp(App):
        CSS = PANEL_CSS

        def compose(self) -> ComposeResult:
            left = Static("left", id="left", classes="panel")
            left.set_custom_property("accent", "red")
            left.set_custom_property("panel-w", "20")
            right = Static("right", id="right", classes="panel")
            right.set_custom_property("accent", "green")
            right.set_custom_property("panel-w", "40")
            with Horizontal():
                yield left
                yield right

    app = PanelApp()
    async with app.run_test() as pilot:
        await _settle(pilot)
        left = app.query_one("#left", Static)
        right = app.query_one("#right", Static)

        # Final styles diverge despite the exact same rule / selectors.
        assert left.styles.color == RED
        assert right.styles.color == GREEN
        assert _border_color(left) == RED
        assert _border_color(right) == GREEN

        # Geometry declarations actually drive layout.
        assert left.region.width != right.region.width
        assert left.region.width == 20
        assert right.region.width == 40


@pytest.mark.asyncio
async def test_ancestor_update_recomputes_descendants_and_clear_restores() -> None:
    """Updating / clearing an ancestor property recomputes descendants.

    Includes a property value which itself references another ``$`` name.
    """

    class CascadeApp(App):
        CSS = """
        .leaf-a { color: $a; }
        .leaf-b { color: $base; }
        """

        def get_css_variables(self) -> dict[str, str]:
            variables = super().get_css_variables()
            variables["base"] = "purple"
            return variables

        def compose(self) -> ComposeResult:
            outer = Vertical(id="outer")
            # `a` references `base`, which is overridden in this subtree.
            outer.set_custom_property("a", "$base")
            outer.set_custom_property("base", "red")
            with outer:
                yield Label("a", id="leaf-a", classes="leaf-a")
                yield Label("b", id="leaf-b", classes="leaf-b")

    app = CascadeApp()
    async with app.run_test() as pilot:
        await _settle(pilot)
        outer = app.query_one("#outer", Vertical)
        leaf_a = app.query_one("#leaf-a", Label)
        leaf_b = app.query_one("#leaf-b", Label)

        assert leaf_a.styles.color == RED
        assert leaf_b.styles.color == RED

        # Update the indirectly referenced name; both leaves recompute.
        outer.set_custom_property("base", "green")
        await _settle(pilot)
        assert leaf_a.styles.color == GREEN
        assert leaf_b.styles.color == GREEN

        # Clearing the subtree override restores the global / theme value,
        # including through the transitive reference.
        outer.unset_custom_property("base")
        await _settle(pilot)
        assert leaf_a.styles.color == PURPLE
        assert leaf_b.styles.color == PURPLE


@pytest.mark.asyncio
async def test_nested_override_then_unset_restores_outer() -> None:
    """An inner subtree overrides the outer name; removing it restores outer."""

    class NestedApp(App):
        CSS = PANEL_CSS

        def compose(self) -> ComposeResult:
            outer = Vertical(id="outer")
            outer.set_custom_property("accent", "red")
            outer.set_custom_property("panel-w", "10")
            inner = Vertical(id="inner")
            inner.set_custom_property("accent", "green")
            inner.set_custom_property("panel-w", "10")
            with outer:
                yield Static("out", id="out-leaf", classes="panel")
                with inner:
                    yield Static("in", id="in-leaf", classes="panel")

    app = NestedApp()
    async with app.run_test() as pilot:
        await _settle(pilot)
        inner = app.query_one("#inner", Vertical)
        in_leaf = app.query_one("#in-leaf", Static)
        out_leaf = app.query_one("#out-leaf", Static)

        assert _border_color(in_leaf) == GREEN
        assert _border_color(out_leaf) == RED

        # Remove the inner override: the outer value becomes visible again.
        inner.unset_custom_property("accent")
        await _settle(pilot)
        assert _border_color(in_leaf) == RED
        assert _border_color(out_leaf) == RED


@pytest.mark.asyncio
async def test_custom_property_visible_to_lazily_mounted_nodes() -> None:
    """Nodes mounted later (Lazy) see the cascade current at mount time.

    Setting the property before composition versus setting it once mounted
    converges to the same final styles.
    """
    lazy_css = """
    .late-panel {
        height: 3;
        border: tall $accent;
        width: $panel-w;
    }
    .early-panel {
        height: 3;
        border: tall red;
    }
    """

    class LazyBeforeApp(App):
        CSS = lazy_css

        def compose(self) -> ComposeResult:
            root = Vertical(id="root")
            root.set_custom_property("accent", "red")
            root.set_custom_property("panel-w", "12")
            with root:
                yield Static("early", id="early", classes="early-panel")
                yield Lazy(Static("late", id="late", classes="late-panel"))

    class LazyAfterApp(App):
        CSS = lazy_css

        def compose(self) -> ComposeResult:
            with Vertical(id="root"):
                yield Static("early", id="early", classes="early-panel")
                yield Lazy(Static("late", id="late", classes="late-panel"))

        def on_mount(self) -> None:
            # Set after composition, but before the Lazy wrapper mounts its
            # replacement widget (which happens after the first refresh).
            root = self.query_one("#root", Vertical)
            root.set_custom_property("accent", "red")
            root.set_custom_property("panel-w", "12")

    before = LazyBeforeApp()
    async with before.run_test() as pilot:
        await _settle(pilot)
        late_before = before.query_one("#late", Static)
        early_before = before.query_one("#early", Static)
        assert _border_color(late_before) == RED
        assert _border_color(early_before) == RED
        assert late_before.region.width == 12
        late_border_before = late_before.styles.border_left
        late_width_before = late_before.region.width

    after = LazyAfterApp()
    async with after.run_test() as pilot:
        await _settle(pilot)
        late_after = after.query_one("#late", Static)
        early_after = after.query_one("#early", Static)
        assert _border_color(late_after) == RED
        assert _border_color(early_after) == RED
        assert late_after.region.width == 12
        assert late_after.styles.border_left == late_border_before
        assert late_after.region.width == late_width_before


@pytest.mark.asyncio
async def test_custom_property_visible_to_revealed_nodes() -> None:
    """Reveal mounts its children sequentially; each sees the current cascade."""

    reveal_css = """
    .revealed {
        height: 3;
        border: tall $accent;
        width: $panel-w;
    }
    """

    class RevealApp(App):
        CSS = reveal_css

        def compose(self) -> ComposeResult:
            root = Vertical(id="root")
            root.set_custom_property("accent", "green")
            root.set_custom_property("panel-w", "14")
            with root:
                with Reveal(Vertical(id="holder")):
                    yield Static("one", id="one", classes="revealed")
                    yield Static("two", id="two", classes="revealed")
                    yield Static("three", id="three", classes="revealed")

    app = RevealApp()
    async with app.run_test() as pilot:
        await _settle(pilot)
        for widget_id in ("one", "two", "three"):
            revealed = app.query_one(f"#{widget_id}", Static)
            assert _border_color(revealed) == GREEN
            assert revealed.region.width == 14


@pytest.mark.asyncio
async def test_worker_thread_change_converges_styles_and_layout() -> None:
    """A background @work thread mutating a custom property converges.

    The main thread styles AND geometry must update, not just a mapping.
    """

    class WorkerApp(App):
        CSS = PANEL_CSS

        def get_css_variables(self) -> dict[str, str]:
            variables = super().get_css_variables()
            variables["panel-w"] = "20"
            return variables

        def compose(self) -> ComposeResult:
            with Vertical(id="root"):
                yield Static("panel", id="panel", classes="panel")

        def on_mount(self) -> None:
            self._root = self.query_one("#root", Vertical)
            self.mutate_from_worker()

        @work(thread=True)
        def mutate_from_worker(self) -> None:
            self._root.set_custom_property("accent", "red")
            self._root.set_custom_property("panel-w", "40")

    app = WorkerApp()
    async with app.run_test() as pilot:
        panel = app.query_one("#panel", Static)
        await app.workers.wait_for_complete()
        await _settle(pilot)

        assert panel.styles.color == RED
        assert _border_color(panel) == RED
        # Layout converged on the main thread.
        assert panel.region.width == 40


@pytest.mark.asyncio
async def test_theme_switch_and_refresh_keep_subtree_overrides() -> None:
    """refresh_css / theme switch must keep non-conflicting overrides.

    A subtree property also wins over a same-named theme variable.
    """

    class ThemeApp(App):
        CSS = PANEL_CSS

        def get_css_variables(self) -> dict[str, str]:
            variables = super().get_css_variables()
            variables["panel-w"] = "20"
            return variables

        def compose(self) -> ComposeResult:
            left = Static("left", id="left", classes="panel")
            # Same name as a theme variable ($accent) and a non-conflicting
            # custom-only name ($extra-pad).
            left.set_custom_property("accent", "red")
            left.set_custom_property("extra-pad", "7")
            with Horizontal():
                yield left
                yield Static("right", id="right", classes="panel")

    app = ThemeApp()
    async with app.run_test() as pilot:
        await _settle(pilot)
        left = app.query_one("#left", Static)
        right = app.query_one("#right", Static)

        assert _border_color(left) == RED
        old_right_color = _border_color(right)
        assert old_right_color != RED

        # Switch theme (which triggers refresh_css internally) ...
        app.theme = "nord"
        await _settle(pilot)
        # ... and force an explicit refresh as well.
        app.refresh_css(animate=False)
        await _settle(pilot)

        # Subtree override of the same-named theme variable survives.
        assert _border_color(left) == RED
        assert left.styles.color == RED
        # The un-overridden subtree tracks the new theme.
        new_right_color = _border_color(right)
        assert new_right_color != old_right_color
        assert new_right_color != RED

        # A non-conflicting, custom-only property is still present.
        assert left.get_custom_property("extra-pad") == "7"
