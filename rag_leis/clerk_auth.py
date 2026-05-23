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
    """Verified Clerk session claims.

    Always carries `email` + `is_operator`. The Phase 10c fields below
    (user_id, image_url, full_name, first_name, last_name) come from the
    Clerk session token — they're optional and default empty for any
    construction site that doesn't supply them (admin code paths,
    pre-10c tests). The /v1/ask Clerk path needs user_id to upsert the
    users row + scope conversations; the profile fields are nice-to-have
    so the users table mirrors what Clerk knows.
    """

    email: str
    is_operator: bool
    # Phase 10c — Clerk session profile fields. Default empty so admin
    # code paths + older tests that construct ClerkClaims(email=..., is_operator=...)
    # keep working unchanged.
    user_id: str = ""
    image_url: str = ""
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""


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


def _decode_token(token: str) -> dict:
    """Verify signature + decode payload. Raises ClerkAuthError on failure.

    Shared by `verify_token` (admin path) and `verify_session_token`
    (any-authed-user path) — they differ only in whether they apply
    the admin allowlist.
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
        return jwt.decode(token, **decode_kwargs)
    except jwt.ExpiredSignatureError as e:
        raise ClerkAuthError("token expired") from e
    except jwt.InvalidAudienceError as e:
        raise ClerkAuthError("invalid audience") from e
    except jwt.InvalidSignatureError as e:
        raise ClerkAuthError("invalid signature") from e
    except jwt.PyJWTError as e:
        raise ClerkAuthError(f"jwt decode failed: {type(e).__name__}") from e


def _extract_email(payload: dict) -> str:
    """Pull the email claim out of a decoded JWT payload.

    Clerk emits email under `email` for personal connections OR as
    `primary_email_address`. Be defensive about both. Returns the
    lowercased, stripped email; raises if missing.
    """
    email = payload.get("email") or payload.get("primary_email_address") or ""
    email = str(email).strip().lower()
    if not email:
        raise ClerkAuthError("token missing email claim")
    return email


def _extract_profile(payload: dict) -> dict[str, str]:
    """Phase 10c — pull profile fields (user_id, image_url, names) from a
    decoded Clerk JWT payload. Missing fields return empty strings; the
    only required field across the system is `email` (handled separately).

    `sub` is the standard JWT subject claim; Clerk uses it for the
    user_id (`user_xxx`). The profile fields match what `sessionClaims`
    exposes to the Astro layouts (see ui/src/layouts/Layout.astro).
    """
    return {
        "user_id": str(payload.get("sub") or "").strip(),
        "image_url": str(payload.get("image_url") or "").strip(),
        "full_name": str(payload.get("full_name") or "").strip(),
        "first_name": str(payload.get("first_name") or "").strip(),
        "last_name": str(payload.get("last_name") or "").strip(),
    }


def _is_operator(email: str) -> bool:
    """True if the email matches `RAG_OPERATOR_EMAIL`."""
    operator_email = _read_operator_email()
    return bool(operator_email) and email == operator_email


def verify_token(token: str) -> ClerkClaims:
    """Verify a Clerk-issued JWT AND check the admin allowlist.

    Use for `/v1/admin/*` endpoints. Raises ClerkAuthError on
    signature failure, expired token, audience mismatch, missing
    email claim, or email not in allowlist.
    """
    payload = _decode_token(token)
    email = _extract_email(payload)
    profile = _extract_profile(payload)

    allowlist = _read_allowlist()
    if email not in allowlist:
        raise ClerkAuthError(f"email {email!r} not in admin allowlist")

    return ClerkClaims(email=email, is_operator=_is_operator(email), **profile)


def verify_session_token(token: str) -> ClerkClaims:
    """Verify a Clerk-issued JWT WITHOUT the admin-allowlist check.

    Use for endpoints that require AUTH but accept any registered
    user — e.g. the public `/v1/ask` endpoint after Phase 14.6's
    Clerk integration on aferida.com.br. Same signature + audience
    + email-claim checks as `verify_token`; just doesn't gate on
    `RAG_ADMIN_ALLOWLIST`. Phase 10c: also extracts profile fields
    (user_id, image_url, name) needed for the users-table upsert.
    """
    payload = _decode_token(token)
    email = _extract_email(payload)
    profile = _extract_profile(payload)
    return ClerkClaims(email=email, is_operator=_is_operator(email), **profile)


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


def clerk_session_dependency(request: Request) -> ClerkClaims:
    """FastAPI Depends() target for non-admin endpoints (e.g. `/v1/ask`).

    Same Bearer-token parsing as `clerk_auth_dependency` but uses
    `verify_session_token` (no allowlist), so any registered Clerk
    user passes. Raises 401 on missing/bad token.
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
        return verify_session_token(token)
    except ClerkAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


def require_operator(claims: ClerkClaims) -> ClerkClaims:
    """Helper to gate operator-only endpoints. Use inside the handler."""
    if not claims.is_operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="operator-only endpoint",
        )
    return claims
