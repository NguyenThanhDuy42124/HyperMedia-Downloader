"""
providers.crypto_utils
~~~~~~~~~~~~~~~~~~~~~~
Lightweight cryptography helper using PyCryptodome (already included in environment
and PyInstaller spec), avoiding heavy third-party cryptography binaries.
Provides:
- DramaBox RSA-SHA256 signature
- ByteDance Spade AES-128-CBC URL decryption
"""

import base64
import hashlib
import re
from typing import Optional

try:
    from Cryptodome.PublicKey import RSA
    from Cryptodome.Signature import pkcs1_15
    from Cryptodome.Hash import SHA256
    from Cryptodome.Cipher import AES
    HAVE_CRYPTO = True
except ImportError:
    try:
        from Crypto.PublicKey import RSA
        from Crypto.Signature import pkcs1_15
        from Crypto.Hash import SHA256
        from Crypto.Cipher import AES
        HAVE_CRYPTO = True
    except ImportError:
        HAVE_CRYPTO = False

_DB_PEM_BODY = (
    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC9Q4Y5QX5j08HrnbY3irfKdkEllAU2OORnAjlXDyCzcm2Z6ZRrGvtTZUAM"
    "elfU5PWS6XGEm3d4kJEKbXi4Crl8o2E/E3YJPk1lQD1d0JTdrvZleETN1ViHZFSQwS3L94Woh0E3TPebaEYq88eExvKu1tDdjSoFjBbgMezy"
    "Snas5Nc2xF28XhPuC8m15u+dectsrJl+ALGcTDX3Lv3FURuwV/dN7WMEkgcseIKVMdJxzUB0PeSqCNftfxmdBV/U4yXFRxPhnSFSXCrkj6uJ"
    "jickiYq1pQ1aZfrQe1eLD3MB2hKq7crhMcA3kpggQlnmy1wRR4BAttmSU4fPb/yF8D3hAgMBAAECggEBAJdru6p5RLZ3h/GLF2rud8bqv4pi"
    "F51e/RWQyPFnMAGBrkByiYT7bFI3cnvJMhYpLHRigqjWfUofV3thRDDym54lVLtTRZ91khRMxgwVwdRuk8Fw7JNFenOwCJxbgdlq6iuAMuQc"
    "lwll7qWUrm8DgMvzH93xf8o6X171cp4Sh0og1Ra7E9GZ37dzBlX2aJBK8VBfctZntuDPx52e71nafqfbjXxZuEtpu92oJd6A9mWbd0BZTk72"
    "ZHUmDcKcqjfcEH19SWOphMJFYkxU5FRoIEr3/zisyTO4Mt33ZmwELOrY9PdlyAAyed7ZoH+hlTr7c025QROvb2LmqgRiUT56tMECgYEA+jH5"
    "m6iMRK6XjiBhSUnlr3DzRybwlQrtIj5sZprWe2my5uYHG3jbViYIO7GtQvMTnDrBCxNhuM6dPrL0cRnbsp/iBMXe3pyjT/aWveBkn4R+UpBs"
    "nbtDn28r1MZpCDtr5UNc0TPj4KFJvjnV/e8oGoyYEroECqcw1LqNOGDiLhkCgYEAwaemNePYrXW+MVX/hatfLQ96tpxwf7yuHdENZ2q5AFw7"
    "3GJWYvC8VY+TcoKPAmeoCUMltI3TrS6K5Q/GoLd5K2BsoJrSxQNQFd3ehWAtdOuPDvQ5rn/2fsvgvc3rOvJh7uNnwEZCI/45WQg+UFWref4P"
    "Pc+ArNtp9Xj2y7LndwkCgYARojIQeXmhYZjG6JtSugWZLuHGkwUDzChYcIPdW25ndluokG/RzNvQn4+W/XfTryQjr7RpXm1VxCIrCBvYWNU2"
    "KrSYV4XUtL+B5ERNj6In6AOrOAifuVITy5cQQQeoD+AT4YKKMBkQfO2gnZzqb8+ox130e+3K/mufoqJPZeyrCQKBgC2fobjwhQvYwYY+DIUh"
    "arri+rYrBRYTDtJYnh/PNOaw1CmHwXJt5PEDcml3+NlIMn58I1X2U/hpDrAIl3MlxpZBkVYFI8LmlOeR7ereTddN59ZOE4jY/OnCfqA480Jf"
    "+FKfoMHby5lPO5OOLaAfjtae1FhrmpUe3EfIx9wVuhKBAoGBAPFzHKQZbGhkqmyPW2ctTEIWLdUHyO37fm8dj1WjN4wjRAI4ohNiKQJRh3QE"
    "11E1PzBTl9lZVWT8QtEsSjnrA/tpGr378fcUT7WGBgTmBRaAnv1P1n/Tp0TSvh5XpIhhMuxcitIgrhYMIG3GbP9JNAarxO/qPW6Gi0xWaF7i"
    "l7Or"
)

SPADE_CONSTANTS = bytes([
    0x4D, 0xD4, 0xC2, 0xE6, 0xB8, 0x31, 0x62, 0x09, 0x0E, 0x52, 0xB3, 0xC7, 0xA6,
    0x73, 0x3B, 0xA4, 0x1C, 0xB2, 0x46, 0x2B, 0x82, 0x9A, 0xB5, 0x8A, 0x19, 0x6B,
    0x39, 0xDB, 0x57, 0x17, 0x75, 0x24, 0xF4, 0x9B, 0xAF, 0x7F, 0x08, 0xE8, 0xD6,
    0x8D, 0x26, 0xA7, 0x2E, 0x37, 0xC1, 0xA9, 0x5A, 0x2F, 0x1F, 0x05, 0xA5, 0x18,
    0x92, 0xAE, 0xF2, 0x94, 0x97, 0x32, 0xB6, 0x2A, 0x38, 0xAA, 0xDD, 0x58,
])

_rsa_key_cache = None


def sign_dramabox(payload: str) -> str:
    """Signs payload with DramaBox RSA Private Key using SHA256 PKCS1v15 padding."""
    global _rsa_key_cache
    if not HAVE_CRYPTO:
        return ""
    try:
        if _rsa_key_cache is None:
            raw_pem = base64.b64decode(_DB_PEM_BODY)
            _rsa_key_cache = RSA.import_key(raw_pem)
        h = SHA256.new(payload.encode("utf-8"))
        sig = pkcs1_15.new(_rsa_key_cache).sign(h)
        return base64.b64encode(sig).decode("utf-8")
    except Exception:
        return ""


def _decode_base64(s: str) -> bytes:
    s = s.strip()
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    return base64.b64decode(s)


def _bits_ones(n: int) -> int:
    cnt = 0
    while n > 0:
        cnt += n & 1
        n >>= 1
    return cnt & 0xFF


def derive_content_key(spade_a: str) -> str:
    """Derives 32-character hex AES key from ByteDance spade_a payload."""
    raw = bytearray(_decode_base64(spade_a))
    if len(raw) < 3:
        raise ValueError("spade_a is too short")

    calc_len = len(raw) - (raw[0] ^ raw[1] ^ raw[2]) + 0x2F
    if calc_len <= 0 or calc_len > len(raw) * 2:
        raise ValueError(f"spade_a computed length {calc_len} is invalid")

    if 1 + calc_len > len(raw):
        calc_len = len(raw) - 1
    if calc_len < 0x21:
        raise ValueError("spade_a payload is too short")

    payload = bytearray(raw[1 : 1 + calc_len])
    b55 = 0x55
    bf6 = 0xF6

    for i in range(len(payload)):
        if i & 1:
            prev = b55
            b55 = payload[i]
        else:
            prev = bf6
            bf6 = payload[i]

        payload[i] = (-0x15 - _bits_ones(i) + (prev ^ payload[i])) & 0xFF

    key = payload[1:0x21].decode("latin1")
    if not re.match(r"^[0-9a-fA-F]{32}$", key):
        raise ValueError("invalid content key in spade_a")

    return key.lower()


def decrypt_spade_url(encrypted_url: str, key_hex: str) -> Optional[str]:
    """Decrypts ByteDance spade encrypted video URL using AES-128-CBC."""
    if not HAVE_CRYPTO:
        return None
    try:
        raw = _decode_base64(encrypted_url)
        if len(raw) < 5 or raw[0] != 0xA8 or raw[2] != 0x01 or raw[3] != 0x00:
            return None

        body = raw[4:]
        body_len = (len(body) // 16) * 16
        body = body[:body_len]
        if not body:
            return None

        h1 = hashlib.sha512(key_hex.encode("utf-8")).digest()
        h2 = hashlib.sha512(h1 + SPADE_CONSTANTS).digest()

        aes_key = h2[:16]
        aes_iv = h2[16:32]

        cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
        decrypted = cipher.decrypt(body)

        pad_len = decrypted[-1]
        if 1 <= pad_len <= 16 and pad_len <= len(decrypted):
            decrypted = decrypted[:-pad_len]

        res = decrypted.decode("utf-8", errors="ignore").rstrip("\x00")
        return res if res.startswith("http") else None
    except Exception:
        return None
