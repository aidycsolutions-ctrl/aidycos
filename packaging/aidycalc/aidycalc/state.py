"""Persisted angle, memory and history for Calculadora."""

from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path


def state_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "aidycos" / "calculadora.json"


def load_state() -> dict[str, object]:
    payload = {"angle": "deg", "memory": "0", "history": []}
    path = state_path()
    if not path.is_file():
        return payload
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return payload
    if not isinstance(raw, dict):
        return payload
    angle = raw.get("angle")
    payload["angle"] = angle if angle in {"deg", "rad"} else "deg"
    memory = raw.get("memory", "0")
    try:
        Decimal(str(memory).replace(",", "."))
    except (InvalidOperation, ValueError):
        memory = "0"
    payload["memory"] = str(memory)
    history = raw.get("history")
    cleaned: list[dict[str, str]] = []
    if isinstance(history, list):
        for item in history[-40:]:
            if not isinstance(item, dict):
                continue
            expr = item.get("expr")
            result = item.get("result")
            if isinstance(expr, str) and isinstance(result, str) and expr and result:
                cleaned.append({"expr": expr[:1000], "result": result[:200]})
    payload["history"] = cleaned
    return payload


def save_state(*, angle: str, memory: Decimal, history: list[dict[str, str]]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "angle": angle if angle in {"deg", "rad"} else "deg",
        "memory": format(memory, "f"),
        "history": history[-40:],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
