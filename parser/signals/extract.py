"""Сигналы ролика для media_signal (техспека §5, Ф-10).

Из текста подписи — хэштеги, упоминания, артикулы WB. Отметки, collab и
партнёрство — только из структурных полей ответа, не из текста.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from parser.parse.models import IgMedia

# Хэштег: буквы любого алфавита (включая кириллицу), цифры, _
_HASHTAG = re.compile(r"(?<![\w&#])#(\w+)")
# Упоминание: 1–30 символов [a-z0-9._]
_MENTION = re.compile(r"(?<![\w@.])@([a-zA-Z0-9._]{1,30})(?![a-zA-Z0-9_])")
# Ключевое слово артикула, затем одно или несколько чисел из 6–12 цифр
_ARTICLE_KEYWORD = re.compile(
    r"(?:артикул[а-я]*|арт|art(?:icle)?|№)\s*[.:№#-]?\s*"
    r"((?:\d{6,12})(?:\s*(?:,|;|/|\bи\b|\band\b)\s*\d{6,12})*)(?!\d)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d{6,12}")
# Брендовый хэштег вида #WW318221: буквенный префикс и 6–12 цифр
_BRAND_HASHTAG_ARTICLE = re.compile(r"^[^\W\d_]+_?(\d{6,12})$")
# Отдельное число без ключевого слова — пониженная уверенность.
# Не часть телефона, суммы, даты или более длинного числа.
_BARE_NUMBER = re.compile(r"(?<![\d+\-.,:/#])\b(\d{6,12})\b(?![\d\-.,:/]\d)")

KEYWORD_CONFIDENCE = Decimal("1.000")
BRAND_HASHTAG_CONFIDENCE = Decimal("0.900")
BARE_NUMBER_CONFIDENCE = Decimal("0.400")
STRUCTURAL_CONFIDENCE = Decimal("1.000")


@dataclass(frozen=True, order=True)
class Signal:
    kind: str  # hashtag | mention | wb_article | usertag | coauthor | sponsor
    value: str
    confidence: Decimal


def extract_hashtags(caption: str) -> list[str]:
    return _unique(m.group(1).lower() for m in _HASHTAG.finditer(caption))


def extract_mentions(caption: str) -> list[str]:
    return _unique(m.group(1).lower().rstrip(".") for m in _MENTION.finditer(caption))


def extract_wb_articles(caption: str) -> dict[str, Decimal]:
    """Артикул → уверенность. Берётся максимальная уверенность из найденных правил."""
    found: dict[str, Decimal] = {}

    def put(article: str, conf: Decimal) -> None:
        if conf > found.get(article, Decimal(0)):
            found[article] = conf

    keyword_spans: list[tuple[int, int]] = []
    for m in _ARTICLE_KEYWORD.finditer(caption):
        keyword_spans.append(m.span(1))
        for num in _NUMBER.findall(m.group(1)):
            put(num, KEYWORD_CONFIDENCE)

    for tag in extract_hashtags(caption):
        hm = _BRAND_HASHTAG_ARTICLE.match(tag)
        if hm:
            put(hm.group(1), BRAND_HASHTAG_CONFIDENCE)

    for m in _BARE_NUMBER.finditer(caption):
        if any(a <= m.start() < b for a, b in keyword_spans):
            continue
        put(m.group(1), BARE_NUMBER_CONFIDENCE)
    return found


def extract_signals(media: IgMedia) -> list[Signal]:
    signals: set[Signal] = set()
    caption = media.caption or ""
    for tag in extract_hashtags(caption):
        signals.add(Signal("hashtag", tag, KEYWORD_CONFIDENCE))
    for mention in extract_mentions(caption):
        signals.add(Signal("mention", mention, KEYWORD_CONFIDENCE))
    for article, conf in extract_wb_articles(caption).items():
        signals.add(Signal("wb_article", article, conf))
    for kind, pks in (
        ("usertag", media.usertags),
        ("coauthor", media.coauthors),
        ("sponsor", media.sponsor_user_pks),
    ):
        for pk in pks or []:
            signals.add(Signal(kind, str(pk), STRUCTURAL_CONFIDENCE))
    return sorted(signals)


def _unique(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        if v:
            seen.setdefault(v, None)
    return list(seen)
