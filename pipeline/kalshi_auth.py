"""Optional authenticated Kalshi requests.

Every Kalshi call in this pipeline already works unauthenticated against Kalshi's
free, public market-data endpoints -- this module adds nothing new to fetch, it
only signs the same requests so Kalshi can tell they come from a registered key
and give them a higher rate limit than anonymous traffic. Without KALSHI_KEY_ID
and KALSHI_PRIVATE_KEY set, headers() returns {} and every call falls back to
plain, unauthenticated requests exactly as before.

Auth scheme (Kalshi API-key auth): sign `timestamp + method + path` (path only,
no host or query string) with the account's RSA private key using RSASSA-PSS
(SHA-256, MGF1-SHA256, salt length = digest size), base64-encode the signature,
and send it alongside the key id and timestamp as headers. The private key never
leaves this process -- it signs locally and only the signature is sent.

Needs the `cryptography` package (not stdlib); if it's missing, auth is silently
skipped and unauthenticated calls still work.
"""
import os, time, base64


def available():
    return bool(os.environ.get("KALSHI_KEY_ID")) and bool(os.environ.get("KALSHI_PRIVATE_KEY"))


def headers(method, path):
    """path: URL path only, e.g. '/trade-api/v2/markets' -- no host, no query string.
    Returns {} (never raises) if the key isn't configured or the signer can't load."""
    key_id = os.environ.get("KALSHI_KEY_ID")
    pem = os.environ.get("KALSHI_PRIVATE_KEY")
    if not key_id or not pem:
        return {}
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        ts = str(int(time.time() * 1000))
        msg = (ts + method.upper() + path).encode("utf-8")
        private_key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        sig = private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
            hashes.SHA256(),
        )
        return {"KALSHI-ACCESS-KEY": key_id, "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("ascii")}
    except Exception:  # noqa  a bad/missing key or missing `cryptography` must not break the (still-free) unauthenticated path
        return {}
