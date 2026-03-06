# window.py
import os
import io
import json
import time
import threading

from gi.repository import Adw, Gtk, GLib, Gdk, GdkPixbuf, Gio

try:
    import qrcode
    HAVE_QRCODE = True
except ImportError:
    HAVE_QRCODE = False

from .crypto import WalletAES, WalletKeys, AppWallet, TransactionBuilder, decode_address
from .api import SoleAPIClient

@Gtk.Template(resource_path='/io/github/nicolocarcagni/Swallet/window.ui')
class SwalletWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'SwalletWindow'

    toast_overlay = Gtk.Template.Child()
    view_stack = Gtk.Template.Child()
    
    # Setup
    setup_password_entry = Gtk.Template.Child()
    btn_create_wallet = Gtk.Template.Child()
    btn_import_wallet = Gtk.Template.Child()
    
    # Lock
    unlock_password_entry = Gtk.Template.Child()
    btn_unlock_wallet = Gtk.Template.Child()
    
    # Dashboard
    nav_view = Gtk.Template.Child()
    receive_nav_page = Gtk.Template.Child()
    send_nav_page = Gtk.Template.Child()
    
    lbl_conn_status = Gtk.Template.Child()
    lbl_balance = Gtk.Template.Child()
    btn_copy_address = Gtk.Template.Child()
    btn_refresh = Gtk.Template.Child()
    btn_nav_receive = Gtk.Template.Child()
    btn_nav_send = Gtk.Template.Child()
    list_history = Gtk.Template.Child()
    
    # Receive
    qr_picture = Gtk.Template.Child()
    lbl_receive_address = Gtk.Template.Child()
    
    # Send
    entry_send_address = Gtk.Template.Child()
    entry_send_amount = Gtk.Template.Child()
    btn_confirm_send = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        self.api = SoleAPIClient()
        self.wallet_path = os.path.join(GLib.get_user_data_dir(), "swallet.json")
        self._poll_timer_id = None
        
        self.check_wallet_state()

    def show_toast(self, message: str):
        sanitized_msg = GLib.markup_escape_text(str(message))
        toast = Adw.Toast.new(sanitized_msg)
        self.toast_overlay.add_toast(toast)

    def check_wallet_state(self):
        self.reset_ui_state()
        if os.path.exists(self.wallet_path):
            self.view_stack.set_visible_child_name("lock_page")
            self.unlock_password_entry.grab_focus()
        else:
            self.view_stack.set_visible_child_name("setup_page")
            self.setup_password_entry.grab_focus()

    def reset_ui_state(self):
        """Completely clears sensitive inputs, balances, and transaction history."""
        # Intentionally clear string buffers
        self.setup_password_entry.set_text("")
        self.unlock_password_entry.set_text("")
        self.entry_send_address.set_text("")
        self.entry_send_amount.set_text("")
        
        # Reset labels
        self.lbl_balance.set_label("0.00 SOLE")
        self.lbl_conn_status.set_subtitle("Not connected")
        self.lbl_receive_address.set_label("No address")
        
        # Clear loops and child widgets
        self._stop_polling()
        while child := self.list_history.get_first_child():
            self.list_history.remove(child)

    def _save_wallet(self, priv_hex: str, password: str):
        encrypted = WalletAES.encrypt(priv_hex, password)
        with open(self.wallet_path, 'w') as f:
            json.dump(encrypted, f)

    @Gtk.Template.Callback()
    def on_create_wallet_clicked(self, btn):
        password = self.setup_password_entry.get_text()
        if not password:
            self.show_toast("Password cannot be empty!")
            return
            
        try:
            keys = WalletKeys()
            self._save_wallet(keys.private_key_hex, password)
            AppWallet.get().load_keys(keys.private_key_hex)
            self.show_dashboard()
        except Exception as e:
            self.show_toast(f"Error creating wallet: {e}")

    @Gtk.Template.Callback()
    def on_import_wallet_clicked(self, btn):
        password = self.setup_password_entry.get_text()
        if not password:
            self.show_toast("Please enter a Master Password to secure the imported wallet.")
            self.setup_password_entry.grab_focus()
            return
            
        dialog = Adw.AlertDialog(
            heading="Import Wallet",
            body="Paste your 64-character hexadecimal private key.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("import", "Import")
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        # Add a password entry as extra child to hide the private key
        pk_entry = Gtk.PasswordEntry(
            show_peek_icon=True,
            placeholder_text="Hex Private Key",
            hexpand=True,
        )
        pk_entry.add_css_class("card")
        dialog.set_extra_child(pk_entry)

        dialog.connect("response", self._on_import_dialog_response, pk_entry, password)
        dialog.present(self)

    def _on_import_dialog_response(self, dialog, response, pk_entry, password):
        if response != "import":
            return

        priv_hex = pk_entry.get_text().strip()
        
        if not priv_hex:
            self.show_toast("Private key cannot be empty.")
            return
            
        if len(priv_hex) != 64:
            self.show_toast(f"Invalid private key length ({len(priv_hex)}). Must be exactly 64 characters.")
            return
            
        try:
            # Validate hex
            int(priv_hex, 16)
        except ValueError:
            self.show_toast("Invalid private key format. Must be hexadecimal.")
            return

        try:
            # Reconstruct keys from hex to ensure validity
            keys = WalletKeys(private_key_hex=priv_hex)
            
            # Save and load
            self._save_wallet(keys.private_key_hex, password)
            AppWallet.get().load_keys(keys.private_key_hex)
            
            self.show_dashboard()
            self.show_toast("Wallet imported successfully!")
            
        except Exception as e:
            self.show_toast(f"Error importing wallet: {e}")

    @Gtk.Template.Callback()
    def on_unlock_wallet_clicked(self, btn):
        password = self.unlock_password_entry.get_text()
        if not password:
            self.show_toast("Please enter your password.")
            return
            
        def _unlock_task():
            try:
                with open(self.wallet_path, 'r') as f:
                    encrypted = json.load(f)
                priv_hex = WalletAES.decrypt(encrypted, password)
                GLib.idle_add(self._on_unlock_success, priv_hex)
            except Exception as e:
                GLib.idle_add(self._on_unlock_error, str(e))
                
        self.btn_unlock_wallet.set_sensitive(False)
        threading.Thread(target=_unlock_task, daemon=True).start()

    def _on_unlock_success(self, priv_hex):
        self.btn_unlock_wallet.set_sensitive(True)
        self.unlock_password_entry.set_text("")
        AppWallet.get().load_keys(priv_hex)
        self.show_dashboard()

    def _on_unlock_error(self, err_msg):
        self.btn_unlock_wallet.set_sensitive(True)
        self.show_toast(f"Unlock failed: {err_msg}")

    def show_dashboard(self):
        # Clear passwords from widgets since we are now unlocked
        self.setup_password_entry.set_text("")
        self.unlock_password_entry.set_text("")
        
        self.view_stack.set_visible_child_name("dashboard_page")
        address = AppWallet.get().wallet_keys.address
        short_addr = f"{address[:6]}...{address[-4:]}"
        self.lbl_conn_status.set_subtitle(short_addr)
        self.lbl_receive_address.set_label(address)
        
        self.refresh_dashboard()
        self._start_polling()

    # ── Auto-polling ─────────────────────────────────────────
    def _start_polling(self):
        """Start the 15-second background balance refresh loop."""
        self._stop_polling()
        self._poll_timer_id = GLib.timeout_add_seconds(15, self._poll_tick)

    def _stop_polling(self):
        """Cancel any running polling timer."""
        if self._poll_timer_id is not None:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = None

    def _poll_tick(self):
        """Called every 15 seconds. Returns True to keep the loop alive."""
        if AppWallet.get().wallet_keys is None:
            self._poll_timer_id = None
            return False
        if self.view_stack.get_visible_child_name() != "dashboard_page":
            self._poll_timer_id = None
            return False
        self.refresh_dashboard()
        return True

    def refresh_dashboard(self):
        address = AppWallet.get().wallet_keys.address
        self.api.get_balance_async(address, self._on_balance_fetched)
        self.api.get_transactions_async(address, self._on_history_fetched)

    def _on_balance_fetched(self, success, result):
        if success and isinstance(result, dict) and 'balance' in result:
            balance_sole = result.get('balance', 0) / 100_000_000 # Convert internal to SOLE units
            self.lbl_balance.set_label(f"{balance_sole:.8f} SOLE")
        else:
            self.lbl_balance.set_label("0.00 SOLE")
            self.show_toast("Failed to connect to node.")

    @Gtk.Template.Callback()
    def on_refresh_clicked(self, btn):
        self.show_toast("Refreshing balance...")
        self.refresh_dashboard()

    def _on_history_fetched(self, success, result):
        if success and isinstance(result, list):
            while child := self.list_history.get_first_child():
                self.list_history.remove(child)

            if not result:
                empty = Gtk.Label(label="No transactions found")
                empty.add_css_class("dim-label")
                self.list_history.append(empty)
                return

            address = AppWallet.get().wallet_keys.address

            for tx in result:
                is_sent = any(inp.get("sender_address") == address for inp in tx.get("inputs", []))
                
                amount = 0
                if is_sent:
                    # Sum outputs that do NOT go back to us (the actual sent value)
                    amount = sum(out.get('value_sole', 0.0) for out in tx.get('outputs', []) if out.get('receiver_address') != address)
                else:
                    # Sum outputs that DO go to us
                    amount = sum(out.get('value_sole', 0.0) for out in tx.get('outputs', []) if out.get('receiver_address') == address)

                row = Adw.ExpanderRow.new()
                
                # Setup Icon
                icon = Gtk.Image()
                if is_sent:
                    icon.set_from_icon_name("go-up-symbolic")
                    row.set_title("Sent SOLE")
                else:
                    icon.set_from_icon_name("go-down-symbolic")
                    row.set_title("Received SOLE")
                row.add_prefix(icon)

                # Format amount
                amt_str = f"- {amount:.8f} SOLE" if is_sent else f"+ {amount:.8f} SOLE"
                amt_label = Gtk.Label(label=amt_str)
                amt_label.add_css_class("error" if is_sent else "success")
                row.add_suffix(amt_label)

                # Format timestamp
                timestamp = tx.get("timestamp", 0)
                dt = GLib.DateTime.new_from_unix_local(timestamp)
                date_str = dt.format("%b %d, %H:%M") if dt else "Unknown Time"
                
                tx_id = tx.get('id', 'Unknown')
                short_id = f"{tx_id[:4]}...{tx_id[-4:]}" if len(tx_id) > 8 else tx_id
                
                row.set_subtitle(f"{date_str} • Tx: {short_id}")
                
                # ── Advanced Details inside Expander ──
                
                # Full TXID
                txid_row = Adw.ActionRow(title="Transaction Hash")
                txid_label = Gtk.Label(label=tx_id, selectable=True, wrap=True, max_width_chars=32, halign=Gtk.Align.END)
                txid_label.add_css_class("dim-label")
                txid_row.add_suffix(txid_label)
                
                copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
                copy_btn.add_css_class("flat")
                copy_btn.connect("clicked", self._on_copy_txid_clicked, tx_id)
                txid_row.add_suffix(copy_btn)
                row.add_row(txid_row)
                
                # Date & Time
                time_row = Adw.ActionRow(title="Date &amp; Time")
                full_date_str = dt.format("%Y-%m-%d %H:%M:%S") if dt else "Unknown Date"
                time_label = Gtk.Label(label=full_date_str)
                time_label.add_css_class("dim-label")
                time_row.add_suffix(time_label)
                row.add_row(time_row)
                
                # Status / Confirmations
                status_row = Adw.ActionRow(title="Status")
                # Assuming simple confirmed status or using string if available
                is_confirmed = tx.get("confirmed", True)
                status_text = "Confirmed" if is_confirmed else "Unconfirmed"
                status_label = Gtk.Label(label=status_text)
                status_label.add_css_class("dim-label")
                status_row.add_suffix(status_label)
                row.add_row(status_row)
                
                # Network Fee
                fee = tx.get("fee_sole", None)
                if fee is not None:
                    fee_row = Adw.ActionRow(title="Network Fee")
                    fee_label = Gtk.Label(label=f"{fee:.8f} SOLE")
                    fee_label.add_css_class("dim-label")
                    fee_row.add_suffix(fee_label)
                    row.add_row(fee_row)
                
                self.list_history.append(row)

    def _on_copy_txid_clicked(self, btn, tx_id):
        clipboard = self.get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_for_value(tx_id))
        self.show_toast("Transaction Hash copied to clipboard!")

    @Gtk.Template.Callback()
    def on_copy_address_clicked(self, btn):
        address = AppWallet.get().wallet_keys.address
        clipboard = self.get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_for_value(address))
        self.show_toast("Address copied to clipboard!")

    @Gtk.Template.Callback()
    def on_nav_receive_clicked(self, btn):
        if HAVE_QRCODE:
            address = AppWallet.get().wallet_keys.address
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(address)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            byte_io = io.BytesIO()
            img.save(byte_io, 'PNG')
            bytes_data = byte_io.getvalue()
            
            gbytes = GLib.Bytes.new(bytes_data)
            stream = Gio.MemoryInputStream.new_from_bytes(gbytes)
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.qr_picture.set_paintable(texture)
            except Exception as e:
                print("Failed to load QR pixbuf:", e)
        
        self.nav_view.push(self.receive_nav_page)

    @Gtk.Template.Callback()
    def on_nav_send_clicked(self, btn):
        self.entry_send_address.set_text("")
        self.entry_send_amount.set_text("")
        self.nav_view.push(self.send_nav_page)

    @Gtk.Template.Callback()
    def on_confirm_send_clicked(self, btn):
        target_addr = self.entry_send_address.get_text().strip()
        amount_text = self.entry_send_amount.get_text().strip()

        if not target_addr:
            self.show_toast("Please enter a destination address.")
            return
        
        try:
            amount_sole = float(amount_text)
            amount_satoshis = int(amount_sole * 100_000_000)
        except ValueError:
            self.show_toast("Invalid amount.")
            return

        if amount_satoshis <= 0:
            self.show_toast("Amount must be greater than zero.")
            return

        # Build a human-readable summary
        short_addr = f"{target_addr[:8]}...{target_addr[-6:]}"
        body = f"Send {amount_sole:.8f} SOLE to {short_addr}?"

        dialog = Adw.AlertDialog(
            heading="Confirm Transaction",
            body=body,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("send", "Confirm Send")
        dialog.set_response_appearance("send", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_send_dialog_response, target_addr, amount_satoshis)
        dialog.present(self)

    def _on_send_dialog_response(self, dialog, response, target_addr, amount_satoshis):
        """Handle the confirmation dialog response."""
        if response != "send":
            return

        address = AppWallet.get().wallet_keys.address
        self.btn_confirm_send.set_sensitive(False)
        self.api.get_utxos_async(address, lambda s, r: self._build_and_send_tx(s, r, target_addr, amount_satoshis))

    def _build_and_send_tx(self, success, utxos, target_addr, amount_satoshis):
        if not success:
            self.btn_confirm_send.set_sensitive(True)
            self.show_toast("Failed to fetch UTXOs.")
            return

        try:
            tx = TransactionBuilder()
            # All UTXOs belong to our wallet, so they share the same pubkeyhash
            wallet_pubkeyhash = decode_address(AppWallet.get().wallet_keys.address)
            total_in = 0
            for utxo in utxos:
                tx.add_input(utxo['txid'], utxo['vout'], wallet_pubkeyhash)
                total_in += utxo['amount']
                if total_in >= amount_satoshis:
                    break
                    
            if total_in < amount_satoshis:
                self.btn_confirm_send.set_sensitive(True)
                self.show_toast("Insufficient funds.")
                return
                
            tx.add_output(decode_address(target_addr), amount_satoshis)
            change = total_in - amount_satoshis
            if change > 0:
                tx.add_output(wallet_pubkeyhash, change)

            tx.timestamp = int(time.time())
            tx.sign(AppWallet.get().wallet_keys)
            hex_payload = tx.serialize()
            
            self.api.send_transaction_async(hex_payload, self._on_send_result)
        except Exception as e:
            self.btn_confirm_send.set_sensitive(True)
            self.show_toast(f"Transaction build error: {e}")

    def _on_send_result(self, success, result):
        self.btn_confirm_send.set_sensitive(True)
        if success and "error" not in result:
            self.show_toast("Transaction sent successfully!")
            self.nav_view.pop()
            self.refresh_dashboard()
        else:
            err = result.get('error', 'Unknown error') if isinstance(result, dict) else result
            self.show_toast(f"Send failed: {err}")
