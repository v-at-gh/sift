from __future__ import annotations

from sift.config import KeysConfig
from sift.tui.bindings import build_bindings


def test_all_core_actions_bound() -> None:
    bindings = build_bindings(KeysConfig())
    actions = {b.action for b in bindings}
    required = {
        "toggle_current",
        "toggle_visibility",
        "toggle_extensions",
        "toggle_units",
        "focus_view_filter",
        "focus_selection_filter",
        "next_view",
        "show_tree",
        "show_table",
        "show_preview",
        "show_log",
        "open_preview",
        "cursor_down",
        "cursor_up",
        "tree_left",
        "tree_right",
        "quit_app",
        "ignore_ctrl_q",
    }
    assert required <= actions


def test_quit_has_priority_ignore() -> None:
    bindings = build_bindings(KeysConfig())
    by_action = {b.action: b for b in bindings}
    assert by_action["ignore_ctrl_q"].priority
    assert by_action["ignore_ctrl_q"].key == "ctrl+q"


def test_config_overrides_reach_bindings() -> None:
    keys = KeysConfig(toggle="space", quit="ctrl+x")
    bindings = build_bindings(keys)
    by_action = {b.action: b for b in bindings}
    assert by_action["toggle_current"].key == "space"
    assert by_action["quit_app"].key == "ctrl+x"


def test_preview_wrap_binding() -> None:
    bindings = build_bindings(KeysConfig())
    by_action = {b.action: b for b in bindings}
    assert "toggle_preview_wrap" in by_action
    assert by_action["toggle_preview_wrap"].key == "w"
