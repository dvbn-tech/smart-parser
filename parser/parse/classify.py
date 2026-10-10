"""Классификация ответа до разбора: блокировка, не найден или обычный ответ.

Стену логина, проверку на бота и капчу не обходим: такой ответ — сигнал
снизить темп и отложить задачу (техспека §6, принцип 7).
"""

from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    OK = "ok"
    RATE_LIMITED = "rate_limited"  # 429
    LOGIN_WALL = "login_wall"  # стена логина, checkpoint, капча
    NOT_FOUND = "not_found"
    SERVER_ERROR = "server_error"  # 5xx — повтор с другим IP
    AUTH_ERROR = "auth_error"  # токен Graph API недействителен или нет прав — нужен человек


_LOGIN_MARKERS = (
    "login_required",
    "checkpoint_required",
    "challenge_required",
    "require_login",
    "please wait a few minutes",
    "/accounts/login",
)


def classify(status: int, location: str | None, body: Any) -> Outcome:
    if status == 429:
        return Outcome.RATE_LIMITED
    if location and "/accounts/login" in location:
        return Outcome.LOGIN_WALL
    if status in (401, 403):
        return Outcome.LOGIN_WALL
    if status == 404:
        return Outcome.NOT_FOUND
    if status >= 500:
        return Outcome.SERVER_ERROR
    if isinstance(body, dict):
        message = str(body.get("message", "")).lower()
        if body.get("require_login") is True or any(m in message for m in _LOGIN_MARKERS):
            return Outcome.LOGIN_WALL
        if body.get("spam") is True:
            return Outcome.LOGIN_WALL
    elif isinstance(body, str):
        low = body[:5000].lower()
        if any(m in low for m in _LOGIN_MARKERS):
            return Outcome.LOGIN_WALL
    return Outcome.OK
