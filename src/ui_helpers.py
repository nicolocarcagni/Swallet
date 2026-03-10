# ui_helpers.py
"""Reusable GTK4/libadwaita widget factory functions for Swallet."""
from __future__ import annotations

from gi.repository import Adw, Gtk, Gdk, GLib
from typing import Callable, Optional


def build_detail_row(
    title: str,
    value: str,
    css_classes: Optional[list[str]] = None,
) -> Adw.ActionRow:
    """Creates a standard detail ActionRow with a dim suffix label.

    Args:
        title: The row title (e.g. "Date & Time").
        value: The text shown on the right side.
        css_classes: Extra CSS classes for the value label (e.g. ["monospace"]).
    """
    row = Adw.ActionRow(title=title)
    label = Gtk.Label(
        label=value,
        selectable=True,
        wrap=True,
        max_width_chars=32,
        halign=Gtk.Align.END,
    )
    label.add_css_class("dim-label")
    if css_classes:
        for cls in css_classes:
            label.add_css_class(cls)
    row.add_suffix(label)
    return row


def build_copyable_row(
    title: str,
    value: str,
    copy_callback: Callable,
    css_classes: Optional[list[str]] = None,
) -> Adw.ActionRow:
    """Creates a detail ActionRow with a flat copy button as suffix.

    Args:
        title: The row title (e.g. "Transaction Hash").
        value: The text shown on the right side and copied on click.
        copy_callback: Function called with (button, value) on click.
        css_classes: Extra CSS classes for the value label.
    """
    row = Adw.ActionRow(title=title)
    label = Gtk.Label(
        label=value,
        selectable=True,
        wrap=True,
        max_width_chars=32,
        halign=Gtk.Align.END,
    )
    label.add_css_class("dim-label")
    if css_classes:
        for cls in css_classes:
            label.add_css_class(cls)
    row.add_suffix(label)

    copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
    copy_btn.add_css_class("flat")
    copy_btn.connect("clicked", copy_callback, value)
    row.add_suffix(copy_btn)
    return row


def copy_to_clipboard(window: Gtk.Window, text: str, toast_message: str) -> None:
    """Copy text to the system clipboard and show a toast notification.

    Args:
        window: The parent window (must support get_clipboard).
        text: The string to copy.
        toast_message: Message for the Adw.Toast.
    """
    clipboard = window.get_clipboard()
    clipboard.set_content(Gdk.ContentProvider.new_for_value(text))
    if hasattr(window, "show_toast"):
        window.show_toast(toast_message)
