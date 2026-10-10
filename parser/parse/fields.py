"""Строгое извлечение полей из сырого JSON.

`req_*` — обязательное поле: нет или не тот тип → InvalidResponse.
`opt_*` — необязательное: нет или null → None. Неверный тип у присутствующего
поля — тоже InvalidResponse: это признак изменения формата, а не отсутствия данных.
"""

import unicodedata
from typing import Any

from parser.parse.errors import InvalidResponse

_MISSING = object()


def _get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def has(obj: Any, path: str) -> bool:
    return _get(obj, path) not in (_MISSING, None)


def req_dict(obj: Any, path: str) -> dict[str, Any]:
    v = _get(obj, path)
    if not isinstance(v, dict):
        raise InvalidResponse(path, "required object missing")
    return v


def opt_dict(obj: Any, path: str) -> dict[str, Any] | None:
    v = _get(obj, path)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, dict):
        raise InvalidResponse(path, f"expected object, got {type(v).__name__}")
    return v


def req_list(obj: Any, path: str) -> list[Any]:
    v = _get(obj, path)
    if not isinstance(v, list):
        raise InvalidResponse(path, "required list missing")
    return v


def opt_list(obj: Any, path: str) -> list[Any] | None:
    v = _get(obj, path)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, list):
        raise InvalidResponse(path, f"expected list, got {type(v).__name__}")
    return v


def _as_int(v: Any, path: str) -> int:
    # bool — подкласс int, но в метриках он означает ошибку формата
    if isinstance(v, bool):
        raise InvalidResponse(path, "expected int, got bool")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)  # pk иногда приходит строкой
    raise InvalidResponse(path, f"expected int, got {type(v).__name__}")


def req_int(obj: Any, path: str) -> int:
    v = _get(obj, path)
    if v is _MISSING or v is None:
        raise InvalidResponse(path, "required int missing")
    return _as_int(v, path)


def opt_int(obj: Any, path: str) -> int | None:
    v = _get(obj, path)
    if v is _MISSING or v is None:
        return None
    return _as_int(v, path)


def req_bool(obj: Any, path: str) -> bool:
    v = _get(obj, path)
    if not isinstance(v, bool):
        raise InvalidResponse(path, "required bool missing")
    return v


def opt_bool(obj: Any, path: str) -> bool | None:
    v = _get(obj, path)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, bool):
        raise InvalidResponse(path, f"expected bool, got {type(v).__name__}")
    return v


def req_str(obj: Any, path: str) -> str:
    v = opt_str(obj, path)
    if v is None:
        raise InvalidResponse(path, "required string missing")
    return v


def opt_str(obj: Any, path: str) -> str | None:
    """Строка в NFC; пустая строка → None (нет данных, а не пустое значение)."""
    v = _get(obj, path)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, str):
        raise InvalidResponse(path, f"expected string, got {type(v).__name__}")
    v = unicodedata.normalize("NFC", v)
    return v if v.strip() else None


def opt_id_str(obj: Any, path: str) -> str | None:
    """Идентификатор, который приходит то числом, то строкой."""
    v = _get(obj, path)
    if v is _MISSING or v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | str):
        raise InvalidResponse(path, f"expected id, got {type(v).__name__}")
    return str(v) if str(v).strip() else None
