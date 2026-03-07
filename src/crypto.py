import os
import struct
import hashlib
from base58 import b58encode_check, b58decode_check
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature


class WalletAES:
    """Handles PBKDF2 Master Password derivation and AES-256-GCM encryption/decryption."""
    @staticmethod
    def derive_key(password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        return kdf.derive(password.encode('utf-8'))

    @staticmethod
    def encrypt(data_str: str, password: str) -> dict:
        salt = os.urandom(16)
        key = WalletAES.derive_key(password, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, data_str.encode('utf-8'), None)
        return {
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "ciphertext": ct.hex()
        }

    @staticmethod
    def decrypt(encrypted_dict: dict, password: str) -> str:
        salt = bytes.fromhex(encrypted_dict["salt"])
        nonce = bytes.fromhex(encrypted_dict["nonce"])
        ct = bytes.fromhex(encrypted_dict["ciphertext"])
        key = WalletAES.derive_key(password, salt)
        aesgcm = AESGCM(key)
        try:
            pt = aesgcm.decrypt(nonce, ct, None)
            return pt.decode('utf-8')
        except Exception as e:
            raise ValueError("Invalid password or corrupted data.") from e


class WalletKeys:
    """Handles P-256 Keypair generation, address derivation, and signing."""
    def __init__(self, private_key_hex: str = None):
        if private_key_hex:
            priv_int = int(private_key_hex, 16)
            self._private_key = ec.derive_private_key(priv_int, ec.SECP256R1())
        else:
            self._private_key = ec.generate_private_key(ec.SECP256R1())
            
    @property
    def private_key_hex(self) -> str:
        priv_num = self._private_key.private_numbers().private_value
        return f"{priv_num:064x}"

    @property
    def public_key_uncompressed(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        
    @property
    def address(self) -> str:
        pubkey = self.public_key_uncompressed
        
        # SHA256 of Public Key
        sha256_hash = hashlib.sha256(pubkey).digest()
        
        # RIPEMD160 of the SHA256 Hash
        ripemd160_hash = hashlib.new('ripemd160', sha256_hash).digest()
        
        # Base58Check with 0x00 version byte
        payload = b'\x00' + ripemd160_hash
        return b58encode_check(payload).decode('utf-8')

    def sign_data(self, data: bytes) -> bytes:
        """Sign data (typically SHA-256 hash of tx) using ECDSA P-256."""
        return self._private_key.sign(
            data,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())) if len(data) == 32 else ec.ECDSA(hashes.SHA256())
        )


def decode_address(address: str) -> bytes:
    """Decode a Base58Check address to its raw 20-byte PubKeyHash."""
    decoded = b58decode_check(address)
    return decoded[1:]  # Strip the 0x00 version byte


class TransactionBuilder:
    """Builds and serializes a UTXO transaction.

    Binary format mirrors the Go node exactly:
    every integer (lengths, values, indices) is an 8-byte
    signed Big Endian int64  →  struct format '>q'.
    """

    def __init__(self):
        self.inputs = []
        self.outputs = []
        self.timestamp = 0  # Unix epoch; set before broadcasting

    # ── helpers ───────────────────────────────────────────────
    @staticmethod
    def _pack_int64(n: int) -> bytes:
        """Pack a single value as Big Endian signed int64."""
        return struct.pack('>q', n)

    @staticmethod
    def _pack_bytes(data: bytes) -> bytes:
        """Length-prefix + raw bytes  (length as int64 BE)."""
        return struct.pack('>q', len(data)) + data

    # ── building ──────────────────────────────────────────────
    def add_input(self, txid: str, vout: int, prev_pubkeyhash: bytes):
        """Add an input.  `prev_pubkeyhash` is the 20-byte RIPEMD160 hash
        of the output being spent (needed for the trimmed-copy signing loop)."""
        self.inputs.append({
            'txid': bytes.fromhex(txid),  # raw bytes, no reversal
            'vout': vout,
            'signature': b'',
            'pubkey': b'',
            'prev_pubkeyhash': prev_pubkeyhash,
        })

    def add_output(self, pubkeyhash: bytes, value: int):
        """Add an output.  `pubkeyhash` is the raw 20-byte RIPEMD160 hash
        (decoded from the recipient's Base58Check address)."""
        self.outputs.append({
            'pubkeyhash': pubkeyhash,
            'value': value,
        })

    # ── serialize_for_hash (matches Go SerializeForHash) ─────
    def _serialize_for_hash(self, inputs_snapshot: list) -> bytes:
        """Serialize for hashing — NO length prefixes anywhere.

        This mirrors Go's SerializeForHash() exactly:
        raw byte concatenation of fields, with integers as >q.
        `inputs_snapshot` contains the trimmed-copy state for each input.
        """
        buf = bytearray()

        # --- Inputs (no array length prefix) ---
        for vin in inputs_snapshot:
            buf += vin['txid']                               # raw bytes
            buf += self._pack_int64(vin['vout'])             # int64 >q
            buf += vin['pubkey']                             # raw bytes (trimmed)
            buf += vin['signature']                          # raw bytes (empty)

        # --- Outputs (no array length prefix) ---
        for vout in self.outputs:
            buf += self._pack_int64(vout['value'])           # int64 >q
            buf += vout['pubkeyhash']                        # raw bytes

        # --- Timestamp ---
        buf += self._pack_int64(self.timestamp)

        return bytes(buf)

    # ── wire-format serialization (matches Go Serialize) ─────
    def _serialize_core(self, include_sig: bool) -> bytes:
        """Full binary serialization for broadcasting.

        Uses int64 length prefixes before every byte slice,
        matching Go's Transaction.Serialize().
        """
        buf = bytearray()

        # --- Inputs ---
        buf += self._pack_int64(len(self.inputs))
        for vin in self.inputs:
            buf += self._pack_bytes(vin['txid'])             # int64(len) + raw
            buf += self._pack_int64(vin['vout'])              # int64
            if include_sig:
                buf += self._pack_bytes(vin['signature'])     # int64(len) + raw
                buf += self._pack_bytes(vin['pubkey'])        # int64(len) + raw
            else:
                buf += self._pack_int64(0)                    # sig  len = 0
                buf += self._pack_int64(0)                    # pub  len = 0

        # --- Outputs ---
        buf += self._pack_int64(len(self.outputs))
        for vout in self.outputs:
            buf += self._pack_int64(vout['value'])            # int64
            buf += self._pack_bytes(vout['pubkeyhash'])       # int64(len) + raw

        # --- Timestamp ---
        buf += self._pack_int64(self.timestamp)

        return bytes(buf)

    # ── signing (trimmed copy, per-input) ─────────────────────
    def sign(self, wallet: WalletKeys):
        """Sign each input using Go's trimmed-copy logic.

        For input[i]:
          • ALL signatures are empty (b'').
          • ALL pubkeys EXCEPT input[i] are empty (b'').
          • input[i].pubkey is set to prev_pubkeyhash (the RIPEMD160
            hash of the output being spent).
          • The SHA-256 of _serialize_for_hash() on this state is the digest.

        The Go node expects a raw 64-byte signature (32B R + 32B S).
        """
        for i, vin in enumerate(self.inputs):
            # Build the trimmed-copy snapshot for this input
            trimmed_inputs = []
            for j, inp in enumerate(self.inputs):
                trimmed_inputs.append({
                    'txid': inp['txid'],
                    'vout': inp['vout'],
                    'signature': b'',                         # always empty
                    'pubkey': inp['prev_pubkeyhash'] if j == i else b'',
                })

            # Hash the trimmed state
            tx_hash = hashlib.sha256(
                self._serialize_for_hash(trimmed_inputs)
            ).digest()

            # ECDSA sign → DER → raw R||S (64 bytes)
            der_sig = wallet._private_key.sign(
                tx_hash, ec.ECDSA(Prehashed(hashes.SHA256()))
            )
            r, s = decode_dss_signature(der_sig)
            raw_sig = r.to_bytes(32, byteorder='big') + s.to_bytes(32, byteorder='big')

            vin['signature'] = raw_sig
            vin['pubkey'] = wallet.public_key_uncompressed

    def serialize(self) -> str:
        """Returns the fully signed transaction as a hex string."""
        return self._serialize_core(include_sig=True).hex()

class AppWallet:
    """Singleton-like structure to hold the active decrypted wallets in RAM."""
    _instance = None
    
    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.wallets = {}  # dict[address, WalletKeys]
        self.current_address = None

    @property
    def wallet_keys(self) -> WalletKeys:
        """Returns the currently active WalletKeys instance, or None."""
        if self.current_address and self.current_address in self.wallets:
            return self.wallets[self.current_address]
        return None

    def load_keys(self, private_keys):
        """Load one or multiple private keys. Handles list or single string (legacy)."""
        self.wallets.clear()
        self.current_address = None
        
        if not private_keys:
            return
            
        # Normalize to list for backward compatibility
        if isinstance(private_keys, str):
            private_keys = [private_keys]
            
        for hex_key in private_keys:
            if isinstance(hex_key, str):
                wk = WalletKeys(hex_key)
                self.wallets[wk.address] = wk
                
        # Set the first loaded wallet as the active one by default
        if self.wallets:
            self.current_address = list(self.wallets.keys())[0]

    def add_key(self, private_key_hex: str):
        wk = WalletKeys(private_key_hex)
        self.wallets[wk.address] = wk
        self.current_address = wk.address

    def remove_key(self, address: str):
        if address in self.wallets:
            del self.wallets[address]
        if self.current_address == address:
            self.current_address = list(self.wallets.keys())[0] if self.wallets else None

    def get_all_hex_keys(self) -> list:
        return [wk.private_key_hex for wk in self.wallets.values()]
        
    def clear(self):
        self.wallets.clear()
        self.current_address = None
