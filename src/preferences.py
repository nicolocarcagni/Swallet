import os
import json
import logging
from gi.repository import Adw, Gtk, GLib, Gdk

from .crypto import WalletAES, WalletKeys, AppWallet


@Gtk.Template(resource_path='/io/github/nicolocarcagni/Swallet/preferences.ui')
class PreferencesWindow(Adw.PreferencesWindow):
    __gtype_name__ = 'PreferencesWindow'

    entry_node_url = Gtk.Template.Child()
    group_wallets = Gtk.Template.Child()

    def __init__(self, api_client, wallet_path, **kwargs):
        super().__init__(**kwargs)
        self.api_client = api_client
        self.wallet_path = wallet_path
        self.config_path = os.path.join(GLib.get_user_data_dir(), "swallet_config.json")
        self._load_config()
        self.refresh_wallets_list()

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    url = config.get("node_url", "https://sole.nicolocarcagni.dev")
                    self.entry_node_url.set_text(url)
                    self.api_client.set_node(url)
            except Exception as e:
                logging.error(f"Failed to load config: {e}")
                self.entry_node_url.set_text("https://sole.nicolocarcagni.dev")
        else:
            self.entry_node_url.set_text("https://sole.nicolocarcagni.dev")

    def _save_config(self, url: str):
        try:
            with open(self.config_path, 'w') as f:
                json.dump({"node_url": url}, f)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    @Gtk.Template.Callback()
    def on_url_changed(self, entry):
        url = entry.get_text()
        self.api_client.set_node(url)
        self._save_config(url)

    # ── Master Password Prompt Helper ────────────────────────
    def _prompt_password(self, heading: str, body: str, callback, *args):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", "Confirm")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        
        pw_entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Master Password", hexpand=True)
        pw_entry.add_css_class("card")
        dialog.set_extra_child(pw_entry)
        
        dialog.connect("response", self._on_password_prompt_response, pw_entry, callback, args)
        dialog.present(self)
        
    def _on_password_prompt_response(self, dialog, response, pw_entry, callback, args):
        if response != "confirm":
            return
        password = pw_entry.get_text()
        if not password:
            self._show_toast("Password cannot be empty.")
            return


        try:
            with open(self.wallet_path, 'r') as f:
                encrypted = json.load(f)
            WalletAES.decrypt(encrypted, password)
        except Exception:
            self._show_toast("Incorrect password.")
            return

        callback(password, *args)

    def _save_wallet_state(self, password: str):

        keys_str = json.dumps(AppWallet.get().get_all_hex_keys())
        encrypted = WalletAES.encrypt(keys_str, password)
        with open(self.wallet_path, 'w') as f:
            json.dump(encrypted, f)

    def _sync_main_window(self):
        main_win = self.get_transient_for()
        if main_win:
            if hasattr(main_win, 'refresh_wallet_switcher'):
                main_win.refresh_wallet_switcher()
            if hasattr(main_win, 'show_dashboard'):
                main_win.show_dashboard()

    # ── Wallet Management ────────────────────────────────────
    def refresh_wallets_list(self):

        
        # Remove old rows securely by tracking them natively
        if hasattr(self, '_wallet_rows'):
            for r in self._wallet_rows:
                try:
                    self.group_wallets.remove(r)
                except Exception:
                    pass
        self._wallet_rows = []

        wallet_dict = AppWallet.get().wallets
        active_addr = AppWallet.get().current_address

        for address in wallet_dict.keys():
            short_addr = f"{address[:8]}...{address[-6:]}"
            subtitle = "Currently Active" if address == active_addr else ""
            
            row = Adw.ActionRow(title=short_addr, subtitle=subtitle)
            
            if address == active_addr:
                check_icon = Gtk.Image(icon_name="object-select-symbolic", margin_start=12, margin_end=6)
                row.add_prefix(check_icon)
            
            # Export btn
            btn_export = Gtk.Button(icon_name="view-reveal-symbolic", valign=Gtk.Align.CENTER)
            btn_export.add_css_class("flat")
            btn_export.connect("clicked", self.on_export_wallet_clicked, address)
            row.add_suffix(btn_export)

            # Delete btn
            btn_delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            btn_delete.add_css_class("flat")
            btn_delete.add_css_class("error")
            btn_delete.connect("clicked", self.on_delete_wallet_clicked, address)
            row.add_suffix(btn_delete)

            self.group_wallets.add(row)
            self._wallet_rows.append(row)

    @Gtk.Template.Callback()
    def on_pref_create_wallet_clicked(self, btn):
        self._prompt_password("Create Wallet", "Enter your master password to secure the new wallet.", self._do_create_wallet)
        
    def _do_create_wallet(self, password):

        try:
            keys = WalletKeys()
            AppWallet.get().add_key(keys.private_key_hex)
            self._save_wallet_state(password)
            self.refresh_wallets_list()
            self._sync_main_window()
            self._show_toast("New wallet created successfully!")
        except Exception as e:
            self._show_toast(f"Error: {e}")

    @Gtk.Template.Callback()
    def on_pref_import_wallet_clicked(self, btn):
        dialog = Adw.AlertDialog(
            heading="Import Wallet",
            body="Enter your Master Password and paste the 64-character hexadecimal private key."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("import", "Import")
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        pw_entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Master Password")
        pw_entry.add_css_class("card")
        pk_entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Hex Private Key")
        pk_entry.add_css_class("card")
        
        box.append(pw_entry)
        box.append(pk_entry)
        dialog.set_extra_child(box)
        
        dialog.connect("response", self._on_pref_import_response, pw_entry, pk_entry)
        dialog.present(self)

    def _on_pref_import_response(self, dialog, response, pw_entry, pk_entry):
        if response != "import":
            return
            
        password = pw_entry.get_text()
        priv_hex = pk_entry.get_text().strip()
        
        if not password or not priv_hex:
            self._show_toast("Both fields are required.")
            return
            

        try:
            with open(self.wallet_path, 'r') as f:
                encrypted = json.load(f)
            WalletAES.decrypt(encrypted, password)
        except Exception:
            self._show_toast("Incorrect master password.")
            return
            
        if len(priv_hex) != 64:
            self._show_toast("Private key must be exactly 64 characters.")
            return

        try:
            keys = WalletKeys(private_key_hex=priv_hex)
            AppWallet.get().add_key(keys.private_key_hex)
            self._save_wallet_state(password)
            
            self.refresh_wallets_list()
            self._sync_main_window()
            self._show_toast("Wallet imported successfully!")
        except Exception as e:
            self._show_toast(f"Import error: {e}")

    def on_delete_wallet_clicked(self, btn, address):

        if len(AppWallet.get().wallets) <= 1:
            self._show_toast("Cannot delete the last remaining wallet. Use 'Reset Wallet' under Security instead.")
            return
        self._prompt_password("Delete Wallet", f"Are you sure you want to remove wallet {address[:8]}...?", self._do_delete_wallet, address)

    def _do_delete_wallet(self, password, address):

        try:
            AppWallet.get().remove_key(address)
            self._save_wallet_state(password)
            self.refresh_wallets_list()
            self._sync_main_window()
            self._show_toast("Wallet removed safely.")
        except Exception as e:
            self._show_toast(f"Error: {e}")

    def on_export_wallet_clicked(self, btn, address):
        self._prompt_password("Export Private Key", f"Enter your master password to reveal the private key for {address[:8]}...?", self._do_export_wallet, address)

    def _do_export_wallet(self, password, address):

        wk = AppWallet.get().wallets.get(address)
        if wk:
            self._show_key_dialog(wk.private_key_hex)

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

            with open(self.wallet_path, 'r') as f:
                encrypted = json.load(f)
            
            # Verify old password and recover
            WalletAES.decrypt(encrypted, old_pw)
            
            # Re-encrypt the current app wallet listing with new password

            keys_str = json.dumps(AppWallet.get().get_all_hex_keys())
            new_encrypted = WalletAES.encrypt(keys_str, new_pw)
            
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
