import base64
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

import jwt                                              # PyJWT
import requests as _http
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

# ─────────────────────────────────────────────
# Config (read from environment, same pattern as app.py)
# ─────────────────────────────────────────────
LTI_CLIENT_ID       = os.getenv("LTI_CLIENT_ID", "")
LTI_PLATFORM_ISSUER = os.getenv("LTI_PLATFORM_ISSUER", "")
LTI_AUTH_ENDPOINT   = os.getenv("LTI_AUTH_ENDPOINT", "")
LTI_JWKS_ENDPOINT   = os.getenv("LTI_JWKS_ENDPOINT", "")
_KEY_FILE           = Path(os.getenv("LTI_KEY_FILE", "./lti_private_key.pem"))
_KID                = "lti-key-1"

# In-memory nonce store  { nonce_str : expiry_unix_time }
# (same pattern as _SUBTOPIC_UPLOADS in app.py — dict in memory, cleaned periodically)
_LTI_NONCES: Dict[str, float] = {}
_NONCE_TTL = 600   # 10 minutes, same as OIDC round-trip window


# ─────────────────────────────────────────────
# RSA key management  (fix for bug #1)
# ─────────────────────────────────────────────

def _load_or_generate_private_key():
    """
    Load RSA private key from disk (so it survives server restarts and
    Moodle's JWKS cache stays valid), or generate + save a new one.
    This replaces generate_rsa_keys() from the original app.py.
    """
    if _KEY_FILE.exists():
        try:
            pem = _KEY_FILE.read_bytes()
            key = serialization.load_pem_private_key(
                pem, password=None, backend=default_backend()
            )
            print(f"✅ LTI private key loaded from {_KEY_FILE}")
            return key
        except Exception as e:
            print(f"⚠️ Could not load LTI key from {_KEY_FILE} ({e}), regenerating")

    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    try:
        _KEY_FILE.write_bytes(pem)
        print(f"✅ LTI private key generated and saved to {_KEY_FILE}")
    except OSError as e:
        print(f"⚠️ Could not persist LTI key ({e}); key lives in memory only this run")
    return key


# Module-level singletons — one key pair per process (stable across requests)
_PRIVATE_KEY = _load_or_generate_private_key()
_PUBLIC_KEY  = _PRIVATE_KEY.public_key()


def _int_to_b64url(n: int) -> str:
    """Convert a large integer to unpadded base64url (used in JWKS)."""
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).decode().rstrip("=")


def build_jwks() -> Dict[str, Any]:
    """
    Return the tool's public JWKS dict.
    Serve this at /.well-known/jwks.json  (replaces the old LTI_JWKS dict).
    The key is now stable across restarts because it is loaded from disk.
    """
    pub = _PUBLIC_KEY.public_numbers()
    return {
        "keys": [{
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "kid": _KID,
            "n":   _int_to_b64url(pub.n),
            "e":   _int_to_b64url(pub.e),
        }]
    }


# ─────────────────────────────────────────────
# Nonce helpers  (fix for bug #4)
# ─────────────────────────────────────────────

def generate_nonce() -> str:
    """Create a one-time nonce and store it for later validation."""
    nonce = secrets.token_urlsafe(32)
    _LTI_NONCES[nonce] = time.time() + _NONCE_TTL
    return nonce


def validate_and_consume_nonce(nonce: str) -> bool:
    """
    Returns True only if the nonce was issued by us AND has not expired.
    Removes it so it cannot be replayed.
    """
    expiry = _LTI_NONCES.pop(nonce, None)
    if expiry is None:
        return False        # unknown nonce
    if time.time() > expiry:
        return False        # expired
    return True


def purge_expired_nonces() -> None:
    """
    Call from app.py's cleanup_before_request() (the 1 % hook) so the dict
    never grows unbounded — same pattern as _cleanup_old_uploads().
    """
    now = time.time()
    expired = [k for k, v in _LTI_NONCES.items() if v < now]
    for k in expired:
        del _LTI_NONCES[k]
    if expired:
        print(f"🧹 Cleaned up {len(expired)} expired LTI nonces")


# ─────────────────────────────────────────────
# OIDC login helper  (fix for bug #2)
# ─────────────────────────────────────────────

def build_oidc_redirect_url(
    *,
    login_hint: str,
    lti_message_hint: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> tuple:
    """
    Build the URL that /lti/login must redirect the browser to.

    Moodle calls /lti/login with:
        iss, login_hint, lti_message_hint, client_id, target_link_uri

    We redirect to LTI_AUTH_ENDPOINT with the OIDC parameters.
    Returns (redirect_url, state, nonce).
    """
    if not LTI_AUTH_ENDPOINT:
        raise ValueError(
            "LTI_AUTH_ENDPOINT is not set in .env. "
            "Add it as: LTI_AUTH_ENDPOINT=https://your-moodle.example.com/mod/lti/auth.php"
        )

    state = secrets.token_urlsafe(32)
    nonce = generate_nonce()

    params = {
        "scope":            "openid",
        "response_type":    "id_token",
        "client_id":        client_id or LTI_CLIENT_ID,
        "redirect_uri":     redirect_uri,
        "login_hint":       login_hint,
        "lti_message_hint": lti_message_hint,
        "state":            state,
        "response_mode":    "form_post",
        "nonce":            nonce,
        "prompt":           "none",
    }

    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{LTI_AUTH_ENDPOINT}?{qs}", state, nonce


# ─────────────────────────────────────────────
# JWT id_token validation  (fix for bug #3)
# ─────────────────────────────────────────────

def _pad_b64(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def _fetch_platform_public_key(kid: Optional[str] = None):
    """
    Download Moodle's JWKS and return the matching RSA public key object.
    Raises RuntimeError if anything goes wrong.
    """
    if not LTI_JWKS_ENDPOINT:
        raise RuntimeError(
            "LTI_JWKS_ENDPOINT is not set in .env. "
            "Add it as: LTI_JWKS_ENDPOINT=https://your-moodle.example.com/mod/lti/certs.php"
        )
    try:
        resp = _http.get(LTI_JWKS_ENDPOINT, timeout=10)
        resp.raise_for_status()
        jwks = resp.json()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch Moodle JWKS: {e}")

    keys = jwks.get("keys", [])
    if not keys:
        raise RuntimeError("Moodle JWKS response contained no keys")

    for k in keys:
        if kid and k.get("kid") != kid:
            continue
        if k.get("kty") != "RSA":
            continue
        n = int.from_bytes(base64.urlsafe_b64decode(_pad_b64(k["n"])), "big")
        e = int.from_bytes(base64.urlsafe_b64decode(_pad_b64(k["e"])), "big")
        return RSAPublicNumbers(e, n).public_key(default_backend())

    raise RuntimeError(f"No suitable RSA key found in Moodle JWKS (kid={kid})")


def validate_lti_launch(id_token: str) -> Dict[str, Any]:
    """
    Validate the id_token JWT that Moodle POSTs during an LTI 1.3 launch.

    Checks:
      - JWT signature (via Moodle's JWKS)
      - iss  == LTI_PLATFORM_ISSUER
      - aud  contains LTI_CLIENT_ID
      - exp  not expired
      - nonce consumed (replay prevention)
      - LTI version claim == "1.3.0"

    Returns the decoded claims dict on success.
    Raises ValueError with a descriptive message on failure.
    """
    # Decode header without verifying (to get kid)
    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as e:
        raise ValueError(f"Cannot decode JWT header: {e}")

    kid = header.get("kid")

    try:
        public_key = _fetch_platform_public_key(kid)
    except RuntimeError as e:
        raise ValueError(str(e))

    try:
        claims = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=LTI_CLIENT_ID,
            issuer=LTI_PLATFORM_ISSUER,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("id_token has expired")
    except jwt.InvalidAudienceError:
        raise ValueError(
            f"id_token audience does not match LTI_CLIENT_ID ({LTI_CLIENT_ID})"
        )
    except jwt.InvalidIssuerError:
        raise ValueError(
            f"id_token issuer does not match LTI_PLATFORM_ISSUER ({LTI_PLATFORM_ISSUER})"
        )
    except jwt.PyJWTError as e:
        raise ValueError(f"JWT validation failed: {e}")

    # Nonce check
    nonce = claims.get("nonce")
    if not nonce or not validate_and_consume_nonce(nonce):
        raise ValueError("Invalid or already-used nonce in id_token")

    # LTI version
    lti_ver = claims.get("https://purl.imsglobal.org/spec/lti/claim/version")
    if lti_ver != "1.3.0":
        raise ValueError(f"Unexpected LTI version in token: {lti_ver}")

    return claims


# ─────────────────────────────────────────────
# Claim extractors  (same session keys app.py already uses)
# ─────────────────────────────────────────────

# Instructor role URNs from the IMS spec
_INSTRUCTOR_ROLES = {
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
    "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Faculty",
    "http://purl.imsglobal.org/vocab/lis/v2/system/person#SysAdmin",
    # short-form aliases Moodle sometimes sends
    "Instructor",
    "TeachingAssistant",
}


def extract_session_data(claims: Dict[str, Any]) -> Dict[str, str]:
    """
    Pull the values that app.py stores in session out of the validated JWT claims.
    Returns a dict with the same keys the rest of the app already reads:
        lti_user_id, lti_roles, lti_course_id, lti_context_title
    plus lti_email and lti_name for convenience.
    """
    roles_list = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/roles", []
    )
    ctx = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {})

    # Build a roles string that matches what the old LTI 1.1 code expected
    # so student_index / teacher_generate continue to work unchanged.
    roles_str = ",".join(roles_list)

    return {
        "lti_user_id":       claims.get("sub", "unknown"),
        "lti_roles":         roles_str,
        "lti_course_id":     ctx.get("id", ""),
        "lti_context_title": ctx.get("title", ""),
        "lti_email":         claims.get("email", ""),
        "lti_name":          claims.get("name", ""),
    }


def is_instructor(claims: Dict[str, Any]) -> bool:
    """
    Return True if the JWT claims indicate an instructor role.
    Mirrors the role check in the original lti_launch() function.
    """
    roles = set(claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/roles", []
    ))
    # Also accept short-form role names Moodle may include
    roles_lower = {r.lower() for r in roles}
    return bool(roles & _INSTRUCTOR_ROLES) or any(
        kw in roles_lower
        for kw in ("instructor", "teachingassistant", "teacher", "admin")
    )