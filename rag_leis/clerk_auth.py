"""Phase 11.0 — Clerk JWT verification + admin allowlist.

Verifies signed JWTs against Clerk's published PEM public key
(networkless mode — no JWKS fetch at request time). Checks the
`email` claim against an env-configured allowlist. Marks the
operator with `is_operator=True` so operator-only endpoints can
gate.

Env vars (set as Fly secrets on the backend):
  CLERK_JWT_KEY        — Clerk's RS256 PEM public key. Get from
                         the Clerk dashboard → API Keys → "JWT
                         Public Key". Multi-line; embed as-is in
                         `flyctl secrets set CLERK_JWT_KEY=...`.
  CLERK_AUDIENCE       — Expected `aud` claim. Often the Clerk
                         instance ID or app URL. If unset, the
                         audience claim is not checked (less safe;
                         use only for development).
  RAG_ADMIN_ALLOWLIST  — Comma-separated emails allowed to access
                         `/v1/admin/*`. Whitespace stripped.
  RAG_OPERATOR_EMAIL   — Single email; that user gets
                         `is_operator=True`, which gates the
                         operator-only endpoints (new eval row,
                         proposals queue).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class ClerkClaims:
    """Verified Clerk session claims, narrowed to what admin endpoints need."""

    email: str
    is_operator: bool


class ClerkAuthError(Exception):
    """Raised when JWT verification or allowlist check fails."""


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


def _read_public_key() -> str:
    """Pull the Clerk PEM public key from env. Required."""
    key = os.environ.get("CLERK_JWT_KEY")
    if not key:
        raise ClerkAuthError(
            "CLERK_JWT_KEY not set; admin endpoints cannot verify JWTs"
        )
    # Clerk's dashboard sometimes provides the key with literal "\n"
    # escapes when copied; normalize so PEM parsers don't choke.
    return key.replace("\\n", "\n")


def _read_allowlist() -> set[str]:
    raw = os.environ.get("RAG_ADMIN_ALLOWLIST", "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def _read_operator_email() -> str | None:
    raw = os.environ.get("RAG_OPERATOR_EMAIL", "").strip().lower()
    return raw or None


def verify_token(token: str) -> ClerkClaims:
    """Verify a Clerk-issued JWT and return narrowed claims.

    Raises ClerkAuthError on signature failure, expired token,
    audience mismatch, missing email claim, or not-in-allowlist.
    """
    pubkey = _read_public_key()
    audience = os.environ.get("CLERK_AUDIENCE")

    decode_kwargs: dict = {
        "key": pubkey,
        "algorithms": ["RS256"],
    }
    if audience:
        decode_kwargs["audience"] = audience

    try:
        payload = jwt.decode(token, **decode_kwargs)
    except jwt.ExpiredSignatureError as e:
        raise ClerkAuthError("token expired") from e
    except jwt.InvalidAudienceError as e:
        raise ClerkAuthError("invalid audience") from e
    except jwt.InvalidSignatureError as e:
        raise ClerkAuthError("invalid signature") from e
    except jwt.PyJWTError as e:
        raise ClerkAuthError(f"jwt decode failed: {type(e).__name__}") from e

    # Clerk emits email under `email` for personal connections OR
    # as a primary_email_address. Be defensive about both.
    email = payload.get("email") or payload.get("primary_email_address") or ""
    email = str(email).strip().lower()
    if not email:
        raise ClerkAuthError("token missing email claim")

    allowlist = _read_allowlist()
    if email not in allowlist:
        raise ClerkAuthError(f"email {email!r} not in admin allowlist")

    operator_email = _read_operator_email()
    is_operator = bool(operator_email) and email == operator_email

    return ClerkClaims(email=email, is_operator=is_operator)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def clerk_auth_dependency(request: Request) -> ClerkClaims:
    """FastAPI Depends() target for `/v1/admin/*` endpoints.

    Expects `Authorization: Bearer <jwt>`. Returns ClerkClaims on
    success. Raises 401 (missing/bad token) or 403 (not in allowlist).
    """
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="empty bearer token",
        )

    try:
        return verify_token(token)
    except ClerkAuthError as e:
        # Distinguish "bad token" (401) from "not in allowlist" (403).
        msg = str(e)
        if "not in admin allowlist" in msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorized for admin endpoints",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg,
        ) from e


def require_operator(claims: ClerkClaims) -> ClerkClaims:
    """Helper to gate operator-only endpoints. Use inside the handler."""
    if not claims.is_operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="operator-only endpoint",
        )
    return claims
