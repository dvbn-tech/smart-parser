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
# Брендовый хэштег вида #AB318221: буквенный префикс и 6–12 цифр (кроме WW — см. ниже)
_BRAND_HASHTAG_ARTICLE = re.compile(r"^(?!ww\d)[^\W\d_]+_?(\d{6,12})$")
# Подменный артикул WB «WW» + цифры (WW1070270, #WW318221): по нему считаются переходы и заказы
_WW_CODE = re.compile(r"(?<![A-Za-z0-9])#?(WW\d{5,9})(?!\d)", re.IGNORECASE)
# Промокод после «промо», «промокод», «promo»; между ними — до 25 не-латинских символов
# («промокод от меня #SVSTH2D7ED65»). В коде обязательна хотя бы одна латинская буква.
_PROMO = re.compile(
    r"(?:промо[\s-]?код[а-я]*|промо|promo[\s-]?code|promo)[^A-Za-z0-9#\n]{0,25}#?"
    r"(?=[A-Za-z0-9_]*[A-Za-z])([A-Za-z0-9_]{4,25})",
    re.IGNORECASE,
)
# Отдельное число без ключевого слова — пониженная уверенность.
# Не часть телефона, суммы, даты или более длинного числа.
_BARE_NUMBER = re.compile(r"(?<![\d+\-.,:/#])\b(\d{6,12})\b(?![\d\-.,:/]\d)")

KEYWORD_CONFIDENCE = Decimal("1.000")
BRAND_HASHTAG_CONFIDENCE = Decimal("0.900")
BARE_NUMBER_CONFIDENCE = Decimal("0.400")
STRUCTURAL_CONFIDENCE = Decimal("1.000")


@dataclass(frozen=True, order=True)
class Signal:
    kind: (
        str  # hashtag | mention | wb_article | ww_code | promo_code | usertag | coauthor | sponsor
    )
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


def extract_ww_codes(caption: str) -> list[str]:
    return _unique(m.group(1).upper() for m in _WW_CODE.finditer(caption))


def extract_promo_codes(caption: str) -> list[str]:
    codes = (m.group(1).upper() for m in _PROMO.finditer(caption))
    return _unique(c for c in codes if not c.startswith("WW") or not c[2:].isdigit())


def extract_signals(media: IgMedia) -> list[Signal]:
    signals: set[Signal] = set()
    caption = media.caption or ""
    for tag in extract_hashtags(caption):
        signals.add(Signal("hashtag", tag, KEYWORD_CONFIDENCE))
    for mention in extract_mentions(caption):
        signals.add(Signal("mention", mention, KEYWORD_CONFIDENCE))
    for article, conf in extract_wb_articles(caption).items():
        signals.add(Signal("wb_article", article, conf))
    for code in extract_ww_codes(caption):
        signals.add(Signal("ww_code", code, KEYWORD_CONFIDENCE))
    for promo in extract_promo_codes(caption):
        signals.add(Signal("promo_code", promo, KEYWORD_CONFIDENCE))
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
