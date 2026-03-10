import json
import urllib.request
import urllib.error
import threading
from gi.repository import GLib

class SoleAPIClient:
    def __init__(self, base_url="https://sole.nicolocarcagni.dev"):
        self.base_url = base_url

    def set_node(self, node_url: str):
        node_url = node_url.strip()
        if not node_url.startswith("http://") and not node_url.startswith("https://"):
            node_url = "https://" + node_url
        self.base_url = node_url.rstrip('/')

    def _request(self, method: str, endpoint: str, payload: dict = None) -> dict:
        url = urllib.parse.urljoin(self.base_url + '/', endpoint.lstrip('/'))
        
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        
        if payload:
            headers['Content-Type'] = 'application/json'
            
        req = urllib.request.Request(url, method=method, headers=headers)
        if payload:
                req.data = json.dumps(payload).encode('utf-8')
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read().decode('utf-8')
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 502:
                return {"error": "Node rejected the transaction (502 Bad Gateway). Check node logs."}
            try:
                err_body = e.read().decode('utf-8')
                return json.loads(err_body) # Try to parse JSON from error
            except:
                return {"error": f"HTTP {e.code}: Server Error"}
        except urllib.error.URLError as e:
            return {"error": f"Network Error: {str(e)}"}

    # --- Synchronous endpoints ---
    def get_tip(self):
        return self._request('GET', '/blocks/tip')

    def get_block(self, block_hash: str):
        return self._request('GET', f'/blocks/{block_hash}')

    def get_balance(self, address: str):
        return self._request('GET', f'/balance/{address}')

    def get_utxos(self, address: str):
        return self._request('GET', f'/utxos/{address}')

    def get_transaction(self, tx_id: str):
        return self._request('GET', f'/transaction/{tx_id}')

    def get_transactions(self, address: str):
        return self._request('GET', f'/transactions/{address}')

    def get_peers(self):
        return self._request('GET', '/network/peers')

    def get_validators(self):
        return self._request('GET', '/consensus/validators')

    def send_transaction(self, hex_payload: str):
        payload = {"hex": hex_payload}
        return self._request('POST', '/tx/send', payload=payload)

    # --- Asynchronous Helpers ---
    def _run_async(self, func, callback, *args, **kwargs):
        """Runs the function in a background thread and posts the result to the GTK main loop."""
        def worker():
            try:
                result = func(*args, **kwargs)
                GLib.idle_add(callback, True, result)
            except Exception as e:
                GLib.idle_add(callback, False, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def get_balance_async(self, address: str, callback):
        self._run_async(self.get_balance, callback, address)

    def get_transactions_async(self, address: str, callback):
        self._run_async(self.get_transactions, callback, address)

    def get_utxos_async(self, address: str, callback):
        self._run_async(self.get_utxos, callback, address)

    def send_transaction_async(self, hex_payload: str, callback):
        self._run_async(self.send_transaction, callback, hex_payload)

