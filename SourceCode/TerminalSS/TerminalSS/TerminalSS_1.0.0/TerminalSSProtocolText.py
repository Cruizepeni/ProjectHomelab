from __future__ import annotations

from typing import Iterable


def normalized_key(value: str) -> str:
    return "".join(char for char in str(value).casefold() if char.isalnum())


def parse_headers_and_sections(text: str, sections: Iterable[str]) -> tuple[dict[str, str], dict[str, list[list[str]]]]:
    names = {normalized_key(name): str(name) for name in sections}
    headers: dict[str, str] = {}
    result: dict[str, list[list[str]]] = {name: [] for name in names.values()}
    current_name: str | None = None
    current_lines: list[str] = []
    for raw in str(text).splitlines():
        stripped = raw.strip()
        if stripped.endswith(":"):
            section = names.get(normalized_key(stripped[:-1]))
            if section is not None:
                if current_name is not None:
                    result[current_name].append(current_lines)
                current_name = section
                current_lines = []
                continue
        if current_name is not None:
            current_lines.append(raw.rstrip())
            continue
        if ":" in raw:
            key, value = raw.split(":", 1)
            key = key.strip()
            if key:
                headers[key] = value.strip() or "Unknown"
    if current_name is not None:
        result[current_name].append(current_lines)
    for groups in result.values():
        for group in groups:
            while group and not group[0].strip():
                group.pop(0)
            while group and not group[-1].strip():
                group.pop()
    return headers, result


def header_value(headers: dict[str, str], key: str, default: str = "Unknown") -> str:
    target = normalized_key(key)
    for name, value in headers.items():
        if normalized_key(name) == target:
            text = str(value).strip()
            return text if text else default
    return default


def parse_bracket_sections(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    for raw in str(text).splitlines():
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
            current = stripped[1:-1].strip()
            result.setdefault(current, [])
            continue
        if current is not None and stripped:
            result[current].append(raw.rstrip())
    return result
