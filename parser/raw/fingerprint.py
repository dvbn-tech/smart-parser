"""Отпечаток структуры ответа: хэш множества путей ключей (техспека §7).

Массивы схлопываются в `[]`, значения не учитываются: два ответа одной формы
с разными данными дают один отпечаток. Новый отпечаток — запись в журнал,
исчезновение обязательного пути — алерт.
"""

import hashlib
from typing import Any


def key_paths(obj: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths |= key_paths(value, path)
    elif isinstance(obj, list):
        for item in obj:
            paths |= key_paths(item, f"{prefix}[]")
    return paths


def fingerprint(obj: Any) -> str:
    joined = "\n".join(sorted(key_paths(obj)))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def missing_paths(obj: Any, required: set[str]) -> set[str]:
    return required - key_paths(obj)
