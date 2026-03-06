import os
import json
from gi.repository import Adw, Gtk, GLib, Gdk


@Gtk.Template(resource_path='/io/github/nicolocarcagni/Swallet/preferences.ui')
class PreferencesWindow(Adw.PreferencesWindow):
    __gtype_name__ = 'PreferencesWindow'

    entry_node_url = Gtk.Template.Child()
    btn_export_key = Gtk.Template.Child()

    def __init__(self, api_client, wallet_path, **kwargs):
        super().__init__(**kwargs)
        self.api_client = api_client
        self.wallet_path = wallet_path
        self.config_path = os.path.join(GLib.get_user_data_dir(), "swallet_config.json")
        self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    url = config.get("node_url", "https://sole.nicolocarcagni.dev")
                    self.entry_node_url.set_text(url)
                    self.api_client.set_node(url)
            except Exception as e:
                print(f"Failed to load config: {e}")
                self.entry_node_url.set_text("https://sole.nicolocarcagni.dev")
        else:
            self.entry_node_url.set_text("https://sole.nicolocarcagni.dev")

    def _save_config(self, url: str):
        try:
            with open(self.config_path, 'w') as f:
                json.dump({"node_url": url}, f)
        except Exception as e:
            print(f"Failed to save config: {e}")

    @Gtk.Template.Callback()
    def on_url_changed(self, entry):
        url = entry.get_text()
        self.api_client.set_node(url)
        self._save_config(url)

    # ── Export Private Key ───────────────────────────────────
    @Gtk.Template.Callback()
    def on_export_key_clicked(self, btn):
        """Prompt for master password, then reveal the private key."""
        dialog = Adw.AlertDialog(
            heading="Enter Master Password",
            body="Your password is needed to decrypt the private key.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("decrypt", "Decrypt")
        dialog.set_response_appearance("decrypt", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        # Add a password entry as extra child
        pw_entry = Gtk.PasswordEntry(
            show_peek_icon=True,
            placeholder_text="Master Password",
            hexpand=True,
        )
        pw_entry.add_css_class("card")
        dialog.set_extra_child(pw_entry)

        dialog.connect("response", self._on_export_password_response, pw_entry)
        dialog.present(self)

    def _on_export_password_response(self, dialog, response, pw_entry):
        if response != "decrypt":
            return

        password = pw_entry.get_text()
        if not password:
            self._show_toast("Password cannot be empty.")
            return

        try:
            from .crypto import WalletAES
            with open(self.wallet_path, 'r') as f:
                encrypted = json.load(f)
            priv_hex = WalletAES.decrypt(encrypted, password)
        except ValueError:
            self._show_toast("Wrong password.")
            return
        except Exception as e:
            self._show_toast(f"Decryption error: {e}")
            return

        self._show_key_dialog(priv_hex)

    def _show_key_dialog(self, priv_hex: str):
        """Display the private key with a warning and copy button."""
        dialog = Adw.AlertDialog(
            heading="Private Key",
            body="Keep this safe. Anyone with this key can steal your funds.",
        )
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.set_close_response("close")

        # Monospace label showing the key
        key_label = Gtk.Label(
            label=priv_hex,
            selectable=True,
            wrap=True,
            wrap_mode=2,  # WORD_CHAR
            max_width_chars=48,
        )
        key_label.add_css_class("monospace")

        copy_btn = Gtk.Button(label="Copy to Clipboard", halign=Gtk.Align.CENTER)
        copy_btn.add_css_class("pill")
        copy_btn.connect("clicked", self._on_copy_key_clicked, priv_hex)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(key_label)
        box.append(copy_btn)
        dialog.set_extra_child(box)

        dialog.present(self)

    def _on_copy_key_clicked(self, btn, priv_hex):
        clipboard = self.get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_for_value(priv_hex))
        self._show_toast("Private key copied to clipboard.")

    def _show_toast(self, message: str):
        toast = Adw.Toast.new(GLib.markup_escape_text(str(message)))
        self.add_toast(toast)
