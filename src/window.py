# window.py
import os
import io
import json
import time
import threading
import logging

from gi.repository import Adw, Gtk, GLib, Gdk, GdkPixbuf, Gio

try:
    import qrcode
    HAVE_QRCODE = True
except ImportError:
    HAVE_QRCODE = False

from .crypto import WalletAES, WalletKeys, AppWallet, TransactionBuilder, decode_address
from .api import SoleAPIClient
from .ui_helpers import build_detail_row, build_copyable_row, copy_to_clipboard

@Gtk.Template(resource_path='/io/github/nicolocarcagni/Swallet/window.ui')
class SwalletWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'SwalletWindow'

    toast_overlay = Gtk.Template.Child()
    view_stack = Gtk.Template.Child()
    

    setup_password_entry = Gtk.Template.Child()
    btn_create_wallet = Gtk.Template.Child()
    btn_import_wallet = Gtk.Template.Child()
    

    unlock_password_entry = Gtk.Template.Child()
    btn_unlock_wallet = Gtk.Template.Child()
    

    nav_view = Gtk.Template.Child()
    receive_nav_page = Gtk.Template.Child()
    send_nav_page = Gtk.Template.Child()
    
    lbl_conn_status = Gtk.Template.Child()
    lbl_balance = Gtk.Template.Child()
    btn_copy_address = Gtk.Template.Child()
    btn_refresh = Gtk.Template.Child()
    btn_nav_receive = Gtk.Template.Child()
    btn_nav_send = Gtk.Template.Child()
    scroll_history = Gtk.Template.Child()
    list_history = Gtk.Template.Child()

    btn_wallet_switcher = Gtk.Template.Child()
    popover_wallets = Gtk.Template.Child()
    list_wallets = Gtk.Template.Child()
    

    qr_picture = Gtk.Template.Child()
    lbl_receive_address = Gtk.Template.Child()
    

    entry_send_address = Gtk.Template.Child()
    entry_send_amount = Gtk.Template.Child()
    row_send_fee = Gtk.Template.Child()
    scale_send_fee = Gtk.Template.Child()
    row_send_memo = Gtk.Template.Child()
    entry_send_memo = Gtk.Template.Child()
    btn_confirm_send = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        self.api = SoleAPIClient()
        self.wallet_path: str = os.path.join(GLib.get_user_data_dir(), "swallet.json")
        self._poll_timer_id: int | None = None
        self._history_rows: list[Gtk.Widget] = []
        self._switcher_rows: list[Gtk.ListBoxRow] = []
        self._tx_history_full: list[dict] = []
        self._tx_rendered_count: int = 0
        self._CHUNK_SIZE = 20
        self._is_rendering = False
        
        self.entry_send_address.connect("notify::text", self._on_send_input_changed)
        self.entry_send_amount.connect("notify::text", self._on_send_input_changed)
        self.entry_send_memo.connect("notify::text", self._on_send_input_changed)
        self.scale_send_fee.connect("value-changed", self._on_fee_scale_changed)

        # Connect to ScrolledWindow directly for infinite scrolling
        self.scroll_history.connect("edge-reached", self._on_scroll_edge_reached)

        GLib.idle_add(self.check_wallet_state)

    def show_toast(self, message: str):
        sanitized_msg = GLib.markup_escape_text(str(message))
        toast = Adw.Toast.new(sanitized_msg)
        self.toast_overlay.add_toast(toast)

    def check_wallet_state(self) -> None:
        self.reset_ui_state()
        if os.path.exists(self.wallet_path):
            self.view_stack.set_visible_child_name("lock_page")
            self.unlock_password_entry.grab_focus()
        else:
            self.view_stack.set_visible_child_name("setup_page")
            self.setup_password_entry.grab_focus()

    def reset_ui_state(self) -> None:
        """Completely clears sensitive inputs, balances, and transaction history."""

        if self.setup_password_entry is not None:
            self.setup_password_entry.set_text("")
        if self.unlock_password_entry is not None:
            self.unlock_password_entry.set_text("")
        if self.entry_send_address is not None:
            self.entry_send_address.set_text("")
        if self.entry_send_amount is not None:
            self.entry_send_amount.set_text("")
        if self.scale_send_fee is not None:
            self.scale_send_fee.set_value(0.005)
        if self.entry_send_memo is not None:
            self.entry_send_memo.set_text("")
            self.entry_send_memo.remove_css_class("error")
        if self.row_send_memo is not None:
            self.row_send_memo.set_subtitle("0 / 80 bytes. Publicly visible on the blockchain.")
        if self.btn_confirm_send is not None:
            self.btn_confirm_send.set_sensitive(False)

        if self.lbl_balance is not None:
            self.lbl_balance.set_label("0.00 SOLE")
        if self.lbl_conn_status is not None:
            self.lbl_conn_status.set_subtitle("Not connected")
        if self.lbl_receive_address is not None:
            self.lbl_receive_address.set_label("No address")
        

        self._stop_polling()
        
        for r in self._history_rows:
            try:
                self.list_history.remove(r)
            except Exception:
                pass
        self._history_rows = []
        
        while child := self.list_history.get_first_child():
            try:
                self.list_history.remove(child)
            except Exception:
                break

    def _save_wallet(self, password: str):
        keys_str = json.dumps(AppWallet.get().get_all_hex_keys())
        encrypted = WalletAES.encrypt(keys_str, password)
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
            AppWallet.get().add_key(keys.private_key_hex)
            self._save_wallet(password)
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
            AppWallet.get().add_key(keys.private_key_hex)
            self._save_wallet(password)
            
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
        
        try:
            keys_data = json.loads(priv_hex)
        except json.JSONDecodeError:
            keys_data = priv_hex  # Legacy single string format
            
        AppWallet.get().load_keys(keys_data)
        self.show_dashboard()

    def _on_unlock_error(self, err_msg):
        self.btn_unlock_wallet.set_sensitive(True)
        self.show_toast(f"Unlock failed: {err_msg}")

    def show_dashboard(self):
        # Clear passwords from widgets since we are now unlocked
        self.setup_password_entry.set_text("")
        self.unlock_password_entry.set_text("")
        
        self.view_stack.set_visible_child_name("dashboard_page")
        
        wallet = AppWallet.get().wallet_keys
        if wallet:
            address = wallet.address
            short_addr = f"{address[:6]}...{address[-4:]}"
            self.lbl_conn_status.set_subtitle(short_addr)
            self.lbl_receive_address.set_label(address)
        
        self.refresh_wallet_switcher()
        self.refresh_dashboard()
        self._start_polling()

    def refresh_wallet_switcher(self) -> None:
        wallet_dict = AppWallet.get().wallets
        active_addr = AppWallet.get().current_address
        
        # Track existing addresses in the UI
        existing_addrs = [r.get_name() for r in self._switcher_rows if r.get_name()]
        

        for r in list(self._switcher_rows):
            addr = r.get_name()
            if addr and addr not in wallet_dict:
                try:
                    self.list_wallets.remove(r)
                except Exception:
                    pass
                self._switcher_rows.remove(r)

        for address in wallet_dict.keys():
            short_addr = f"{address[:8]}...{address[-6:]}"
            
            if address not in existing_addrs:
                row = Gtk.ListBoxRow()
                row.set_name(address)
                label = Gtk.Label(label=short_addr, halign=Gtk.Align.START, margin_start=12, margin_end=12, margin_top=12, margin_bottom=12)
                row.set_child(label)
                self.list_wallets.append(row)
                self._switcher_rows.append(row)
                
        for r in self._switcher_rows:
            address = r.get_name()
            if address:
                short_addr = f"{address[:8]}...{address[-6:]}"
                label = r.get_child()
                if address == active_addr:
                    label.add_css_class("accent")
                    label.set_markup(f"<b>{short_addr}</b>")
                else:
                    label.remove_css_class("accent")
                    label.set_label(short_addr)

    @Gtk.Template.Callback()
    def on_wallet_switched(self, listbox, row):
        new_addr = row.get_name()
        if not new_addr:
            return
            
        logging.debug(f"Switcher selected new address: {new_addr}")
        if new_addr != AppWallet.get().current_address:
            AppWallet.get().current_address = new_addr
            self.reset_ui_state()
            self.show_dashboard()
            
        self.popover_wallets.popdown()

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

    def refresh_dashboard(self) -> None:
        wallet = AppWallet.get().wallet_keys
        if not wallet:
            return
        address = wallet.address
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

    def _on_history_fetched(self, success: bool, result) -> None:
        self._is_rendering = False
        
        for r in self._history_rows:
            try:
                self.list_history.remove(r)
            except Exception:
                pass
        self._history_rows = []
        
        while child := self.list_history.get_first_child():
            try:
                self.list_history.remove(child)
            except Exception:
                break

        if success and isinstance(result, list):
            self._tx_history_full = result
            self._tx_rendered_count = 0
            
            if not self._tx_history_full:
                empty = Gtk.Label(label="No transactions found")
                empty.add_css_class("dim-label")
                self.list_history.append(empty)
                self._history_rows.append(empty)
                return

            # Start rendering the first chunk
            self._render_next_chunk()

    def _on_scroll_edge_reached(self, scrolled_window, position):
        if position == Gtk.PositionType.BOTTOM and not self._is_rendering:
            self._render_next_chunk()

    def _render_next_chunk(self):
        if self._is_rendering or self._tx_rendered_count >= len(self._tx_history_full):
            return
            
        self._is_rendering = True
        
        def render_generator():
            address = AppWallet.get().wallet_keys.address
            end_index = min(self._tx_rendered_count + self._CHUNK_SIZE, len(self._tx_history_full))
            
            for index in range(self._tx_rendered_count, end_index):
                tx = self._tx_history_full[index]
                inputs_list = tx.get("inputs", [])
                outputs_list = tx.get("outputs", [])
                is_sent = any(inp.get("sender_address") == address for inp in inputs_list)
                
                amount = 0
                target_address = ""
                
                if is_sent:
                    # Sum outputs that do NOT go back to us (the actual sent value)
                    out_vals = [out for out in outputs_list if out.get('receiver_address') != address]
                    amount = sum(out.get('value_sole', 0.0) for out in out_vals)
                    if out_vals:
                        target_address = out_vals[0].get('receiver_address', 'Unknown')
                else:
                    # Sum outputs that DO go to us
                    amount = sum(out.get('value_sole', 0.0) for out in outputs_list if out.get('receiver_address') == address)
                    # Determine sender for incoming tx
                    if tx.get("is_coinbase", False) or not inputs_list or not inputs_list[0].get("sender_address"):
                        target_address = "Network Reward (Coinbase)"
                    else:
                        target_address = inputs_list[0].get("sender_address", "Unknown")

                row = Adw.ExpanderRow.new()
                
                # Setup Icon
                icon = Gtk.Image()
                if is_sent:
                    icon.set_from_icon_name("go-up-symbolic")
                    icon.add_css_class("warning")
                    row.set_title("Sent SOLE")
                else:
                    icon.set_from_icon_name("go-down-symbolic")
                    icon.add_css_class("success")
                    row.set_title("Received SOLE")
                row.add_prefix(icon)

                # Format amount
                amt_str = f"- {amount:.8f} SOLE" if is_sent else f"+ {amount:.8f} SOLE"
                amt_label = Gtk.Label(label=amt_str)
                amt_label.add_css_class("numeric")
                amt_label.add_css_class("error" if is_sent else "success")
                row.add_suffix(amt_label)

                # Format timestamp and context
                timestamp = tx.get("timestamp", 0)
                dt = GLib.DateTime.new_from_unix_local(timestamp)
                date_str = dt.format("%b %d, %H:%M") if dt else "Unknown Time"
                
                tx_id = tx.get('id', 'Unknown')
                
                # Robust Memo Extraction
                memo_str = tx.get("memo") or tx.get("Memo") or ""
                if not memo_str:
                    for out in outputs_list:
                        try:
                            val = float(out.get('value_sole', out.get('value', 1.0)))
                        except (ValueError, TypeError):
                            val = 1.0
                        
                        if val == 0.0:
                            memo_candidate = out.get("receiver_address", "") or out.get("address", "")
                            if memo_candidate.startswith("Memo: "):
                                memo_candidate = memo_candidate[10:]
                            memo_str = memo_candidate
                            break
                memo_str = str(memo_str).strip()
                
                if memo_str:
                    display_memo = memo_str if len(memo_str) <= 40 else memo_str[:37] + "..."
                    subtitle_text = f"{date_str}  •  💬 {display_memo}"
                else:
                    subtitle_text = date_str
                    
                row.set_subtitle(subtitle_text)
                
                # ── Advanced Details inside Expander ──
                
                # Target Address (From/To)
                addr_title = "Recipient (To)" if is_sent else "Sender (From)"
                addr_row = build_copyable_row(
                    addr_title, target_address,
                    self._on_copy_clicked, css_classes=["monospace"]
                )
                row.add_row(addr_row)
                
                # Full TXID
                txid_row = build_copyable_row(
                    "Transaction Hash", tx_id,
                    self._on_copy_clicked, css_classes=["monospace"]
                )
                row.add_row(txid_row)

                # Date & Time
                full_date_str = dt.format("%Y-%m-%d %H:%M:%S") if dt else "Unknown Date"
                row.add_row(build_detail_row("Date &amp; Time", full_date_str))
                
                # Status / Confirmations
                is_confirmed = tx.get("confirmed", True)
                status_text = "Confirmed" if is_confirmed else "Unconfirmed"
                row.add_row(build_detail_row("Status", status_text))
                
                # Network Fee
                fee = tx.get("fee_sole", None)
                if fee is not None:
                    row.add_row(build_detail_row("Network Fee", f"{fee:.8f} SOLE"))
                
                self.list_history.append(row)
                self._history_rows.append(row)
                
                # Yield control back to GTK main loop after rendering each row
                yield True

            self._tx_rendered_count = end_index
            self._is_rendering = False
            yield False  # Stop idle callback

        gen = render_generator()
        
        def consume_generator():
            try:
                return next(gen)
            except StopIteration:
                return False

        GLib.idle_add(consume_generator)

    def _on_copy_clicked(self, btn, text: str) -> None:
        copy_to_clipboard(self, text, "Copied to clipboard!")

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
                logging.error(f"Failed to load QR pixbuf: {e}")
        
        self.nav_view.push(self.receive_nav_page)

    def _on_fee_scale_changed(self, scale):
        val = scale.get_value()
        if val <= 0.002:
            self.row_send_fee.set_subtitle("Low Priority (Slow)")
        elif val >= 0.01:
            self.row_send_fee.set_subtitle("High Priority (Fast)")
        else:
            self.row_send_fee.set_subtitle("Standard")

    def _on_send_input_changed(self, entry, pspec):
        target_addr = self.entry_send_address.get_text().strip()
        amount_text = self.entry_send_amount.get_text().strip()
        memo_text = self.entry_send_memo.get_text()

        # Update memo counter
        memo_bytes = len(memo_text.encode('utf-8'))
        self.row_send_memo.set_subtitle(f"{memo_bytes} / 80 bytes. Publicly visible on the blockchain.")
        is_memo_valid = True
        if memo_bytes > 80:
            self.entry_send_memo.add_css_class("error")
            is_memo_valid = False
        else:
            self.entry_send_memo.remove_css_class("error")

        is_valid = bool(target_addr and amount_text)
        try:
            val = float(amount_text)
            if val <= 0:
                is_valid = False
        except ValueError:
            is_valid = False

        self.btn_confirm_send.set_sensitive(is_valid and is_memo_valid)

    @Gtk.Template.Callback()
    def on_nav_send_clicked(self, btn):
        self.entry_send_address.set_text("")
        self.entry_send_amount.set_text("")
        self.scale_send_fee.set_value(0.005)
        self.entry_send_memo.set_text("")
        self.nav_view.push(self.send_nav_page)

    @Gtk.Template.Callback()
    def on_confirm_send_clicked(self, btn):
        target_addr = self.entry_send_address.get_text().strip()
        amount_text = self.entry_send_amount.get_text().strip()
        fee_sole = self.scale_send_fee.get_value()
        memo_text = self.entry_send_memo.get_text().strip()

        if not target_addr:
            self.show_toast("Please enter a destination address.")
            return
        
        try:
            amount_sole = float(amount_text)
            amount_satoshis = int(amount_sole * 100_000_000)
            if fee_sole < 0:
                raise ValueError("Negative fee")
            fee_satoshis = int(fee_sole * 100_000_000)
        except ValueError:
            self.show_toast("Invalid amount or fee.")
            return

        if amount_satoshis <= 0:
            self.show_toast("Amount must be greater than zero.")
            return
            
        if len(memo_text.encode('utf-8')) > 80:
            self.entry_send_memo.add_css_class("error")
            self.show_toast("Memo exceeds 80 bytes.")
            return
        else:
            self.entry_send_memo.remove_css_class("error")

        # Build a human-readable summary
        short_addr = f"{target_addr[:8]}...{target_addr[-6:]}"
        body = f"Send {amount_sole:.8f} SOLE (Fee: {fee_sole:.8f}) to {short_addr}?"
        if memo_text:
            body += f"\n\nMemo: {memo_text}"

        dialog = Adw.AlertDialog(
            heading="Confirm Transaction",
            body=body,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("send", "Confirm Send")
        dialog.set_response_appearance("send", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_send_dialog_response, target_addr, amount_satoshis, fee_satoshis, memo_text)
        dialog.present(self)

    def _on_send_dialog_response(self, dialog, response, target_addr, amount_satoshis, fee_satoshis, memo_text):
        """Handle the confirmation dialog response."""
        if response != "send":
            return

        address = AppWallet.get().wallet_keys.address
        self.btn_confirm_send.set_sensitive(False)
        self._build_and_send_tx(address, target_addr, amount_satoshis, fee_satoshis, memo_text)

    def _build_and_send_tx(self, address, target_addr, amount_satoshis, fee_satoshis, memo_text):
        self.show_toast("Signing transaction…")

        # Capture wallet state needed by the worker thread
        wallet_keys = AppWallet.get().wallet_keys
        wallet_pubkeyhash = decode_address(wallet_keys.address)

        def _sign_worker():
            """Runs UTXO fetching + selection + ECDSA signing off the main thread."""
            try:
                # 1. Strict Just-In-Time UTXO Fetch
                utxos = self.api.get_utxos(address)
                if not isinstance(utxos, list):
                    raise ValueError(f"Invalid UTXO response format. Expected list, got {type(utxos)}")

                tx = TransactionBuilder()
                total_in = 0

                target_amount_with_fee = amount_satoshis + fee_satoshis
                for utxo in utxos:
                    tx.add_input(utxo['txid'], utxo['vout'], wallet_pubkeyhash)
                    total_in += utxo['amount']
                    if total_in >= target_amount_with_fee:
                        break

                if total_in < target_amount_with_fee:
                    GLib.idle_add(self._on_sign_error, "Insufficient funds (including fee).")
                    return

                tx.add_output(decode_address(target_addr), amount_satoshis)

                if memo_text:
                    memo_bytes = memo_text.encode('utf-8')
                    tx.add_output(memo_bytes, 0)

                change = total_in - target_amount_with_fee
                if change > 0:
                    tx.add_output(wallet_pubkeyhash, change)

                tx.timestamp = int(time.time())
                tx.sign(wallet_keys)
                hex_payload = tx.serialize()

                GLib.idle_add(self._on_sign_complete, hex_payload)
            except Exception as e:
                GLib.idle_add(self._on_sign_error, str(e))

        threading.Thread(target=_sign_worker, daemon=True).start()

    def _on_sign_complete(self, hex_payload: str) -> None:
        """Called on the main thread after successful signing."""
        self.api.send_transaction_async(hex_payload, self._on_send_result)

    def _on_sign_error(self, error_msg: str) -> None:
        """Called on the main thread if signing fails."""
        self.btn_confirm_send.set_sensitive(True)
        self.show_toast(f"Transaction build error: {error_msg}")

    def _on_send_result(self, success, result):
        self.btn_confirm_send.set_sensitive(True)
        if success and "error" not in result:
            self.show_toast("Transaction broadcasted successfully!")
            self.nav_view.pop()
            self.refresh_dashboard()
        else:
            err = result.get('error', 'Unknown error') if isinstance(result, dict) else result
            self.show_toast(f"Send failed: {err}")
