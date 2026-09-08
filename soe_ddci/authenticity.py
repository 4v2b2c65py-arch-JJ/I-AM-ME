"""Secret-backed authenticity layer.

Canonicalization gives integrity/consistency verification: if a formation is
altered without regenerating its derived encoding, the alteration is detected.

It does NOT provide cryptographic authenticity against an attacker who can
recompute the hash. True authenticity requires a secret-backed mechanism.

This module closes that gap with HMAC-based signing over the canonical form:

    authentic_id = HMAC-SHA256(key, canonical_bytes(formation))

The authentic id is:

    - reproducible: same key + same canonical bytes -> same tag
    - secret-backed: an attacker without the key cannot forge a valid tag
    - distinct from the content-derived canonical id, which needs no secret
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional, Sequence

from .canonical import canonical_bytes, canonical_hash


class Authenticator:
    """HMAC-based signer and verifier for SOE-DDCI artifacts."""

    ALGORITHM = "sha256"

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("authenticator key must be non-empty")
        self.key = bytes(key)

    # ------------------------------------------------------------------
    def sign(self, obj: object) -> str:
        """Produce a secret-backed authentic tag for canonical bytes."""
        mac = hmac.new(
            self.key, canonical_bytes(obj), hashlib.sha256
        )
        return mac.hexdigest()

    def sign_canonical(self, canonical: str) -> str:
        """Sign an already-canonical identity string."""
        mac = hmac.new(self.key, canonical.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()

    def verify(self, obj: object, tag: str) -> bool:
        """Constant-time verification of a tag against the object's canonical form."""
        expected = self.sign(obj)
        return hmac.compare_digest(expected, tag)

    def verify_canonical(self, canonical: str, tag: str) -> bool:
        expected = self.sign_canonical(canonical)
        return hmac.compare_digest(expected, tag)

    # ------------------------------------------------------------------
    def authentic_id(self, obj: object) -> str:
        """Secret-backed identity: HMAC over canonical bytes."""
        return self.sign(obj)

    @staticmethod
    def derive_key(seed: bytes, *, salt: bytes = b"soe-ddci-auth-v1") -> bytes:
        """Derive a key from a seed using HKDF-like expansion.

        Deterministic: same seed -> same key. Domain-separated so a seed
        used for one purpose cannot be reused as a different-purpose key.
        """
        return hashlib.sha256(salt + b"|" + seed).digest()


def verify_formation_authentic(
    formation: object,
    tag: str,
    authenticator: Authenticator,
) -> bool:
    """Verify a formation's secret-backed authentic tag."""
    return authenticator.verify(formation, tag)


__all__ = [
    "Authenticator",
    "verify_formation_authentic",
]