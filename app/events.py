"""Поиск интересных событий в тексте летописи (по скриншоту).

Интересные события по умолчанию (находки ресурсов в шахтах):
  - Золото:              «В шахте около города [Город] обнаружено золото!»
  - Серебро:             «...обнаружено серебро!»
  - Медь:                «...обнаружена медь!»
  - Железо:              «...обнаружено железо!»
  - Уголь:               «...обнаружен уголь!»
  - Драгоценные камни:   «...обнаружены драгоценные камни!»

Событие считается найденным, если в одном предложении есть все
context_keywords (по умолчанию «шахт», «обнаруж») и все keywords пункта.
Нечёткий поиск (difflib) устойчив к ошибкам распознавания текста OCR.
"""

import difflib
import re
from dataclasses import dataclass
from typing import List

# Шаблон для извлечения названия города из строки летописи.
CITY_RE = re.compile(r"шахт\w*\s+около\s+города\s+(.+?)\s+обнаруж")

# Символы, которыми можно разделить «предложения» в тексте OCR.
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;\n\r]+")


@dataclass
class EventMatch:
    """Одно найденное интересное событие."""
    name: str                 # название ресурса/события (из конфига)
    sentence: str             # нормализованное предложение летописи
    city: str = ""            # название города (если удалось распознать)
    keywords: List[str] = None


def normalize_text(text: str) -> str:
    """Нормализует текст: нижний регистр, ё→е, знаки препинания → пробелы."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(raw_text: str) -> List[str]:
    """Разбивает распознанный текст на нормализованные «предложения»."""
    sentences = []
    for part in _SENTENCE_SPLIT_RE.split(raw_text):
        norm = normalize_text(part)
        if norm:
            sentences.append(norm)
    return sentences


def _token_hit(kw: str, token: str, min_ratio: float) -> bool:
    """Проверяет, что токен «похож» на ключевое слово (устойчиво к OCR).

    Критерии (для слов сопоставимой длины):
      - точное совпадение;
      - SequenceMatcher.ratio >= min_ratio (одна опечатка в слове из 6 букв);
      - совпадение первых трёх букв (короткие слова, напр. «медь» vs «медъ»).
    """
    if token == kw:
        return True
    if abs(len(token) - len(kw)) > 2:
        return False
    if difflib.SequenceMatcher(None, kw, token).ratio() >= min_ratio:
        return True
    return len(kw) >= 3 and token.startswith(kw[:3])


def _keyword_hit(keyword: str, sentence: str, fuzzy: bool, min_ratio: float) -> bool:
    """Проверяет вхождение ключевой фразы (одного или нескольких слов).

    Сначала точное вхождение подстроки; при fuzzy=true дополнительно
    проверяем каждое слово ключа на похожесть со словами предложения —
    это покрывает типичные ошибки OCR.
    """
    if keyword in sentence:
        return True
    if not fuzzy:
        return False

    key_words = keyword.split()
    tokens = sentence.split()
    for kw in key_words:
        if not any(_token_hit(kw, tok, min_ratio) for tok in tokens):
            return False
    return True


def extract_city(sentence: str) -> str:
    """Пытается извлечь название города из предложения летописи."""
    m = CITY_RE.search(sentence)
    return m.group(1).strip() if m else ""


def find_interesting_events(text: str, cfg) -> List[EventMatch]:
    """Ищет в тексте летописи события из конфигурации (cfg.events).

    Возвращает список EventMatch (может быть пустым).
    """
    if not text or not text.strip():
        return []

    matches: List[EventMatch] = []
    ctx = cfg.events.context_keywords
    fuzzy = cfg.events.fuzzy
    ratio = cfg.events.min_ratio

    for sentence in split_sentences(text):
        if ctx and not all(_keyword_hit(k, sentence, fuzzy, ratio) for k in ctx):
            continue
        for item in cfg.events.items:
            if all(_keyword_hit(k, sentence, fuzzy, ratio) for k in item.keywords):
                matches.append(EventMatch(
                    name=item.name,
                    sentence=sentence,
                    city=extract_city(sentence),
                    keywords=list(item.keywords),
                ))
    return matches


def format_summary(matches: List[EventMatch]) -> str:
    """Краткое описание найденных событий для лога."""
    if not matches:
        return "нет"
    seen = {}
    for m in matches:
        seen.setdefault(m.name, []).append(m.city or "(город не распознан)")
    parts = []
    for name, cities in seen.items():
        parts.append(f"{name} ({', '.join(cities)})")
    return "; ".join(parts)