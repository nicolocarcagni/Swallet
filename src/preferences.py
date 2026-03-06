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

    # ── Change Master Password ───────────────────────────────
    @Gtk.Template.Callback()
    def on_change_password_clicked(self, btn):
        dialog = Adw.AlertDialog(
            heading="Change Master Password",
            body="Update the password used to encrypt your wallet.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("change", "Change Password")
        dialog.set_response_appearance("change", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        # Create a ListBox to hold the entry rows in a native "card" style
        list_box = Gtk.ListBox()
        list_box.add_css_class("boxed-list")
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        entry_old = Adw.PasswordEntryRow(title="Current Password")
        entry_new = Adw.PasswordEntryRow(title="New Password")
        entry_confirm = Adw.PasswordEntryRow(title="Confirm New Password")

        list_box.append(entry_old)
        list_box.append(entry_new)
        list_box.append(entry_confirm)

        dialog.set_extra_child(list_box)
        dialog.connect("response", self._on_change_password_response, entry_old, entry_new, entry_confirm)
        dialog.present(self)

    def _on_change_password_response(self, dialog, response, entry_old, entry_new, entry_confirm):
        if response != "change":
            return

        old_pw = entry_old.get_text()
        new_pw = entry_new.get_text()
        confirm_pw = entry_confirm.get_text()

        if not old_pw or not new_pw or not confirm_pw:
            self._show_toast("All fields are required.")
            return

        if new_pw != confirm_pw:
            self._show_toast("New passwords do not match.")
            return

        try:
            from .crypto import WalletAES, AppWallet
            with open(self.wallet_path, 'r') as f:
                encrypted = json.load(f)
            
            # Verify old password and recover private key
            priv_hex = WalletAES.decrypt(encrypted, old_pw)
            
            # Re-encrypt with new password
            new_encrypted = WalletAES.encrypt(priv_hex, new_pw)
            
            # Save to disk
            with open(self.wallet_path, 'w') as f:
                json.dump(new_encrypted, f)
            
            self._show_toast("Master password changed successfully.")
            
        except ValueError:
            self._show_toast("Incorrect current password.")
            return
        except Exception as e:
            self._show_toast(f"Error changing password: {e}")
            return

    # ── Reset Wallet ─────────────────────────────────────────
    @Gtk.Template.Callback()
    def on_reset_wallet_clicked(self, btn):
        dialog = Adw.AlertDialog(
            heading="Reset Wallet",
            body="Are you sure you want to delete your wallet? This action is irreversible and all local data will be wiped.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Delete Wallet")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        pw_entry = Gtk.PasswordEntry(
            show_peek_icon=True,
            placeholder_text="Verify Master Password",
            hexpand=True,
        )
        pw_entry.add_css_class("card")
        dialog.set_extra_child(pw_entry)

        dialog.connect("response", self._on_reset_password_response, pw_entry)
        dialog.present(self)

    def _on_reset_password_response(self, dialog, response, pw_entry):
        if response != "reset":
            return

        password = pw_entry.get_text()
        if not password:
            self._show_toast("Password cannot be empty.")
            return

        try:
            from .crypto import WalletAES, AppWallet
            with open(self.wallet_path, 'r') as f:
                encrypted = json.load(f)
            # Verify password
            WalletAES.decrypt(encrypted, password)
            
            # Delete file
            os.remove(self.wallet_path)
            
            # Clear session
            AppWallet.get().wallet_keys = None
            
            # Navigate back to setup in main window
            main_win = self.get_transient_for()
            if main_win and hasattr(main_win, 'check_wallet_state'):
                main_win.check_wallet_state()
            
            self.close()
            
        except ValueError:
            self._show_toast("Wrong password.")
            return
        except Exception as e:
            self._show_toast(f"Error resetting wallet: {e}")
            return
