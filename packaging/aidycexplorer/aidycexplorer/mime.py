"""Register AidyCExplorer as the handler that opens folders."""

from __future__ import annotations

from pathlib import Path

HANDLER = "inode/directory=aidycexplorer.desktop"
SECTION = "[Default Applications]"


def set_directory_handler(path: Path) -> bool:
    """Point inode/directory at AidyCExplorer. Return True when the file changes."""
    path = Path(path)
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    updated = render_handler(original)
    if updated == original:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return True


def clear_directory_handler(path: Path) -> bool:
    """Drop only the AidyCExplorer folder handler. Remove the file if it ends empty."""
    path = Path(path)
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated = render_cleared(original)
    if updated == original:
        return False
    if updated.strip() == "":
        path.unlink()
        return True
    path.write_text(updated, encoding="utf-8")
    return True


def render_handler(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    seen_section = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not replaced:
                out.append(HANDLER)
                replaced = True
            in_section = stripped == SECTION
            seen_section = seen_section or in_section
            out.append(line)
            continue
        if in_section and stripped.startswith("inode/directory="):
            if not replaced:
                out.append(HANDLER)
                replaced = True
            continue
        out.append(line)
    if not seen_section:
        if out and out[-1] != "":
            out.append("")
        out.extend([SECTION, HANDLER])
    elif not replaced:
        out.append(HANDLER)
    return "\n".join(out).rstrip() + "\n"


def render_cleared(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip() != HANDLER]
    cleaned: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == SECTION:
            follower = index + 1
            while follower < len(lines) and lines[follower].strip() == "":
                follower += 1
            next_is_section = follower >= len(lines) or (
                lines[follower].strip().startswith("[") and lines[follower].strip().endswith("]")
            )
            if next_is_section:
                index = follower
                continue
        cleaned.append(lines[index])
        index += 1
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    if not cleaned:
        return ""
    return "\n".join(cleaned).rstrip() + "\n"
