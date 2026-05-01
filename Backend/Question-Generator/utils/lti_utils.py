import base64
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

import jwt
import requests as _http
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

LTI_CLIENT_ID       = os.getenv("LTI_CLIENT_ID", "")
LTI_PLATFORM_ISSUER = os.getenv("LTI_PLATFORM_ISSUER", "")
LTI_AUTH_ENDPOINT   = os.getenv("LTI_AUTH_ENDPOINT", "")
LTI_JWKS_ENDPOINT   = os.getenv("LTI_JWKS_ENDPOINT", "")
_KEY_FILE           = Path(os.getenv("LTI_KEY_FILE", "./lti_private_key.pem"))
_KID                = "lti-key-1"

# Nonce store (replace with Redis in production)
_LTI_NONCES: Dict[str, float] = {}
_NONCE_TTL = 600  # 10 min


# ─────────────────────────────────────────────
# RSA Key Management
# ─────────────────────────────────────────────

def _load_or_generate_private_key():
    if _KEY_FILE.exists():
        try:
            pem = _KEY_FILE.read_bytes()
            return serialization.load_pem_private_key(
                pem, password=None, backend=default_backend()
            )
        except Exception:
            pass

    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )

    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    try:
        _KEY_FILE.write_bytes(pem)
    except Exception:
        pass

    return key


_PRIVATE_KEY = _load_or_generate_private_key()
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


# ─────────────────────────────────────────────
# JWKS
# ─────────────────────────────────────────────

def _int_to_b64url(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).decode().rstrip("=")


def build_jwks() -> Dict[str, Any]:
    pub = _PUBLIC_KEY.public_numbers()

    return {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": _KID,
                "n": _int_to_b64url(pub.n),
                "e": _int_to_b64url(pub.e),
            }
        ]
    }


# This variable is what lti_routes.py imports
LTI_JWKS = build_jwks()


# ─────────────────────────────────────────────
# Nonce Handling
# ─────────────────────────────────────────────

def generate_nonce() -> str:
    nonce = secrets.token_urlsafe(32)
    _LTI_NONCES[nonce] = time.time() + _NONCE_TTL
    return nonce


def validate_and_consume_nonce(nonce: str) -> bool:
    expiry = _LTI_NONCES.pop(nonce, None)
    if not expiry:
        return False
    return time.time() <= expiry


def purge_expired_nonces():
    now = time.time()
    expired = [k for k, v in _LTI_NONCES.items() if v < now]
    for k in expired:
        del _LTI_NONCES[k]


# ─────────────────────────────────────────────
# OIDC Redirect
# ─────────────────────────────────────────────

def build_oidc_redirect_url(
    *,
    login_hint: str,
    lti_message_hint: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
):
    if not LTI_AUTH_ENDPOINT:
        raise ValueError("Missing LTI_AUTH_ENDPOINT")

    state = secrets.token_urlsafe(32)
    nonce = generate_nonce()

    params = {
        "scope": "openid",
        "response_type": "id_token",
        "client_id": client_id or LTI_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "login_hint": login_hint,
        "lti_message_hint": lti_message_hint,
        "state": state,
        "response_mode": "form_post",
        "nonce": nonce,
        "prompt": "none",
    }

    from urllib.parse import urlencode
    qs = urlencode(params)

    return f"{LTI_AUTH_ENDPOINT}?{qs}", state, nonce


# ─────────────────────────────────────────────
# JWT Validation
# ─────────────────────────────────────────────

def _pad_b64(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def _fetch_platform_public_key(kid: Optional[str] = None):
    if not LTI_JWKS_ENDPOINT:
        raise RuntimeError("Missing LTI_JWKS_ENDPOINT")

    resp = _http.get(LTI_JWKS_ENDPOINT, timeout=10)
    resp.raise_for_status()
    jwks = resp.json()

    for k in jwks.get("keys", []):
        if kid and k.get("kid") != kid:
            continue
        if k.get("kty") != "RSA":
            continue

        n = int.from_bytes(base64.urlsafe_b64decode(_pad_b64(k["n"])), "big")
        e = int.from_bytes(base64.urlsafe_b64decode(_pad_b64(k["e"])), "big")

        return RSAPublicNumbers(e, n).public_key(default_backend())

    raise RuntimeError("No valid JWKS key found")


def validate_lti_launch(id_token: str) -> Dict[str, Any]:
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")

    public_key = _fetch_platform_public_key(kid)

    claims = jwt.decode(
        id_token,
        public_key,
        algorithms=["RS256"],
        audience=[LTI_CLIENT_ID],
        issuer=LTI_PLATFORM_ISSUER,
        options={"verify_exp": True},
    )

    # Nonce check
    nonce = claims.get("nonce")
    if not nonce or not validate_and_consume_nonce(nonce):
        raise ValueError("Invalid nonce")

    # LTI version check
    if claims.get("https://purl.imsglobal.org/spec/lti/claim/version") != "1.3.0":
        raise ValueError("Invalid LTI version")

    return claims


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def extract_session_data(claims: Dict[str, Any]) -> Dict[str, str]:
    ctx = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {})

    return {
        "lti_user_id": claims.get("sub", ""),
        "lti_roles": ",".join(claims.get("roles", [])),
        "lti_course_id": ctx.get("id", ""),
        "lti_context_title": ctx.get("title", ""),
        "lti_email": claims.get("email", ""),
        "lti_name": claims.get("name", ""),
    }


def is_instructor(claims: Dict[str, Any]) -> bool:
    roles = claims.get("https://purl.imsglobal.org/spec/lti/claim/roles", [])
    roles_lower = {r.lower() for r in roles}

    return any(
        r in roles_lower
        for r in ["instructor", "teacher", "admin", "faculty"]
    )