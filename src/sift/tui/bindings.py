"""Keyboard binding composition from SiftConfig."""

from __future__ import annotations

from textual.binding import Binding

from ..config import KeysConfig


def build_bindings(keys: KeysConfig) -> list[Binding]:
    """Compose BINDINGS from config; show=False for movement keys."""
    return [
        Binding(keys.toggle, "toggle_current", "Toggle"),
        Binding(keys.toggle_visibility, "toggle_visibility", "Show/hide ext"),
        Binding(keys.toggle_extensions, "toggle_extensions", "Pane"),
        Binding(keys.toggle_actions, "toggle_actions", "Actions"),
        Binding(keys.toggle_units, "toggle_units", "Units"),

        Binding(keys.focus_view_filter, "focus_view_filter", "View"),
        Binding(keys.focus_selection_filter, "focus_selection_filter", "Selection"),

        Binding(keys.next_view, "next_view", "Next view"),
        Binding(keys.show_tree, "show_tree", show=False),
        Binding(keys.show_table, "show_table", show=False),
        Binding(keys.open_preview, "open_preview", "Preview"),

        Binding(keys.down_vim, "cursor_down", show=False),
        Binding(keys.up_vim, "cursor_up", show=False),
        Binding(keys.down_emacs, "cursor_down", show=False),
        Binding(keys.up_emacs, "cursor_up", show=False),

        Binding(keys.tree_left, "tree_left", show=False),
        Binding(keys.tree_right, "tree_right", show=False),
        Binding(keys.tree_collapse_all, "tree_collapse_all", show=False),
        Binding(keys.preview_wrap, "toggle_preview_wrap", show=False),

        Binding(keys.show_preview, "show_preview", show=False),
        Binding(keys.show_log, "show_log", show=False),
        Binding(keys.quit, "quit_app", "Quit"),
        Binding("ctrl+q", "ignore_ctrl_q", show=False, priority=True),
    ]
