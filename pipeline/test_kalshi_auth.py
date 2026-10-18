#!/usr/bin/env python3
"""Offline tests for kalshi_auth.py: no network. Generates a throwaway RSA key to sign
with and verifies the signature with the matching public key -- the same math Kalshi's
server would do, just run locally instead of trusting it blindly."""
import base64, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import kalshi_auth as K

# ---- no key configured: headers() is a no-op, never raises
for k in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY"):
    os.environ.pop(k, None)
assert K.available() is False
assert K.headers("GET", "/trade-api/v2/markets") == {}

# ---- a real (throwaway) keypair: signed headers verify against the public key
priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
os.environ["KALSHI_KEY_ID"] = "test-key-id"
os.environ["KALSHI_PRIVATE_KEY"] = pem
assert K.available() is True

h = K.headers("GET", "/trade-api/v2/markets")
assert h["KALSHI-ACCESS-KEY"] == "test-key-id"
assert h["KALSHI-ACCESS-TIMESTAMP"].isdigit()
msg = (h["KALSHI-ACCESS-TIMESTAMP"] + "GET" + "/trade-api/v2/markets").encode()
sig = base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"])
pub = priv.public_key()
pub.verify(sig, msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size), hashes.SHA256())  # raises if invalid
print("OK valid signature verifies")

# ---- a different path/method/timestamp must NOT verify against this signature (catches a sloppy implementation that ignores its inputs)
try:
    pub.verify(sig, (h["KALSHI-ACCESS-TIMESTAMP"] + "GET" + "/trade-api/v2/portfolio").encode(),
               padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size), hashes.SHA256())
    raise AssertionError("signature verified against the WRONG path -- it isn't binding to its inputs")
except Exception as e:
    assert "verified against the WRONG path" not in str(e)
print("OK signature is bound to method+path+timestamp")

# ---- a garbage private key never raises -- falls back to unauthenticated
os.environ["KALSHI_PRIVATE_KEY"] = "not a real pem"
assert K.headers("GET", "/trade-api/v2/markets") == {}
print("OK malformed key fails closed, never crashes")

print("KALSHI_AUTH TESTS PASS")
