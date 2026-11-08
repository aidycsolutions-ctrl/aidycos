"""Team HMAC helpers — only peers that share team_secret are trusted."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def sign_payload(secret: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_payload(secret: str, body: dict[str, Any], signature: str) -> bool:
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, (signature or "").strip())
