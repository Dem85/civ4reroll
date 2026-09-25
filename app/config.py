"""Конфигурация Civ4Reroll: модель данных, дефолты и загрузка из JSON.

Порядок поиска файла конфигурации:
  1. Аргумент командной строки --config <путь>
  2. Переменная окружения CIV4REROLL_CONFIG
  3. ./config.json (текущий каталог)
  4. <корень проекта>/config.json

Если файл не найден — создаётся config.json с конфигурацией по умолчанию.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from app.actions import Action

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELATIVE = "config.json"


# ---------------------------------------------------------------------------
# Список действий по умолчанию: сценарий из multikey/config.json
# (загрузка tmp.CivBeyondSwordSave, пропуск ходов, открытие летописи),
# НО без последнего "esc", который скрывает летопись — его нажимает сама
# программа после чтения скриншота.
# ---------------------------------------------------------------------------
DEFAULT_ACTIONS = [
    {"type": "move", "x": 50, "y": 50, "relative": True, "delay": 0.1},
    {"type": "key", "key": "esc", "delay": 0.1},
    {"type": "key", "key": "down", "delay": 0.1},
    {"type": "key", "key": "enter", "delay": 0.1},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "down", "delay": 0.1},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "down", "delay": 0.1},
    {"type": "key", "key": "down", "delay": 0.1},
    {"type": "key", "key": "enter", "delay": 0.1},
    {"type": "key", "key": "tab", "delay": 0.1},
    {"type": "key", "key": "tab", "delay": 0.1},
    {"type": "key", "key": "tab", "delay": 0.1},
    {"type": "key", "key": "tab", "delay": 0.1},
    {"type": "key", "key": "enter", "delay": 0.1},
    {"type": "move", "x": 600, "y": 233, "relative": True, "delay": 0.2},
    {"type": "click", "button": "left", "delay": 0.2},
    {"type": "key", "key": "enter", "delay": 1.0},
    {"type": "key", "key": "enter", "delay": 0.2},
    {"type": "key", "key": "enter", "delay": 0.2},
    {"type": "move", "x": 1110, "y": 130, "relative": True, "delay": 0.2},
    {"type": "click", "button": "left", "delay": 0.2},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "ctrl+tab", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 0.5},
    {"type": "key", "key": "enter", "delay": 2.0},
]

# Интересные события по умолчанию (находки ресурсов в шахтах).
DEFAULT_EVENT_ITEMS = [
    {"name": "Золото", "keywords": ["золото"]},
    {"name": "Серебро", "keywords": ["серебро"]},
    {"name": "Медь", "keywords": ["медь"]},
    {"name": "Железо", "keywords": ["железо"]},
    {"name": "Уголь", "keywords": ["уголь"]},
    {"name": "Драгоценные камни", "keywords": ["драгоценные камни"]},
]

DEFAULT_CONFIG_DICT = {
    "game": {
        "window_title": None,
        "key_hold_sec": 0.02,
        "dpi_aware": False,
        "comment": (
            "window_title: строка — заголовок окна игры (поиск по подстроке); "
            "null — работаем в текущем активном окне. dpi_aware: включайте, "
            "если скриншот/клики съезжают при масштабировании Windows ≠ 100%."
        ),
    },
    "profile": {
        "name": "civ4-reroll",
        "comment": (
            "Сценарий из multikey/config.json: загрузка tmp.CivBeyondSwordSave, "
            "пропуск ходов, открытие летописи. Последний esc (скрывающий "
            "летопись) НЕ входит в список — его нажимает сама программа после "
            "чтения скриншота."
        ),
        "actions": DEFAULT_ACTIONS,
    },
    "events": {
        "context_keywords": ["шахт", "обнаруж"],
        "fuzzy": True,
        "min_ratio": 0.8,
        "items": DEFAULT_EVENT_ITEMS,
        "comment": (
            "Событие считается найденным, если в одном предложении летописи "
            "есть ВСЕ context_keywords и ВСЕ keywords пункта. fuzzy=true — "
            "нечёткий поиск (устойчив к ошибкам OCR)."
        ),
    },
    "ocr": {
        "engine": "auto",
        "language": "ru-RU",
        "preprocess": True,
        "max_image_dim": 2400,
        "comment": (
            "engine: auto | windows (встроенный Windows OCR, PowerShell) | "
            "tesseract (pytesseract + Tesseract) | manual (показать скриншот и "
            "спросить пользователя)."
        ),
    },
    "screenshots": {
        "dir": "screenshots",
        "capture": "window",
        "keep_all_attempts": False,
        "save_success": True,
        "save_fail": False,
        "comment": (
            "capture: window (область активного окна, как в multikey) | "
            "fullscreen (весь экран)."
        ),
    },
    "log": {
        "dir": "logs",
        "file": "civ4_reroll.log",
        "level": "INFO",
        "comment": "level: DEBUG | INFO | WARNING | ERROR.",
    },
    "loop": {
        "max_attempts": 0,
        "warmup_sec": 5.0,
        "pause_between_attempts_sec": 3.0,
        "esc_after_read_sec": 0.3,
        "comment": (
            "max_attempts: 0 — бесконечно (остановка Ctrl+C или при находке). "
            "warmup_sec — пауза перед стартом, чтобы переключиться в игру."
        ),
    },
}


# ---------------------------------------------------------------------------
# Модель данных
# ---------------------------------------------------------------------------
@dataclass
class GameConfig:
    window_title: Optional[str] = None
    key_hold_sec: float = 0.02
    dpi_aware: bool = False


@dataclass
class Profile:
    name: str = "civ4-reroll"
    comment: str = ""
    actions: List[Action] = field(default_factory=list)


@dataclass
class EventItem:
    name: str
    keywords: List[str]


@dataclass
class EventsConfig:
    context_keywords: List[str] = field(default_factory=list)
    fuzzy: bool = True
    min_ratio: float = 0.8
    items: List[EventItem] = field(default_factory=list)


@dataclass
class OcrConfig:
    engine: str = "auto"          # auto | windows | tesseract | manual
    language: str = "ru-RU"
    preprocess: bool = True
    max_image_dim: int = 2400


@dataclass
class ScreenshotConfig:
    dir: str = "screenshots"
    capture: str = "window"       # window | fullscreen
    keep_all_attempts: bool = False
    save_success: bool = True
    save_fail: bool = False


@dataclass
class LogConfig:
    dir: str = "logs"
    file: str = "civ4_reroll.log"
    level: str = "INFO"


@dataclass
class LoopConfig:
    max_attempts: int = 0         # 0 = бесконечно
    warmup_sec: float = 5.0
    pause_between_attempts_sec: float = 3.0
    esc_after_read_sec: float = 0.3


@dataclass
class AppConfig:
    game: GameConfig
    profile: Profile
    events: EventsConfig
    ocr: OcrConfig
    screenshots: ScreenshotConfig
    log: LogConfig
    loop: LoopConfig


# ---------------------------------------------------------------------------
# Загрузка / сохранение
# ---------------------------------------------------------------------------
def _parse_profile(d: dict) -> Profile:
    actions = [Action.from_dict(a) for a in d.get("actions", [])]
    profile = Profile(
        name=str(d.get("name", "civ4-reroll")),
        comment=str(d.get("comment", "")),
        actions=actions,
    )
    for action in actions:
        action.validate()
    if not actions:
        raise ValueError("В профиле нет ни одного действия (profile.actions)")
    return profile


def _parse_events(d: dict) -> EventsConfig:
    items = []
    for raw in d.get("items", []):
        items.append(EventItem(
            name=str(raw.get("name", "?")),
            keywords=[str(k).strip().lower() for k in raw.get("keywords", [])],
        ))
    if not items:
        raise ValueError("Нет интересных событий (events.items)")
    return EventsConfig(
        context_keywords=[str(k).strip().lower() for k in d.get("context_keywords", [])],
        fuzzy=bool(d.get("fuzzy", True)),
        min_ratio=float(d.get("min_ratio", 0.85)),
        items=items,
    )


def parse_config_dict(d: dict) -> AppConfig:
    game = d.get("game", {})
    ocr = d.get("ocr", {})
    shots = d.get("screenshots", {})
    log = d.get("log", {})
    loop = d.get("loop", {})

    ocr_engine = str(ocr.get("engine", "auto")).lower()
    if ocr_engine not in ("auto", "windows", "tesseract", "manual"):
        raise ValueError(
            f"Неизвестный OCR-движок: {ocr_engine!r} "
            f"(доступно: auto, windows, tesseract, manual)"
        )

    cfg = AppConfig(
        game=GameConfig(
            window_title=game.get("window_title"),
            key_hold_sec=float(game.get("key_hold_sec", 0.02)),
            dpi_aware=bool(game.get("dpi_aware", False)),
        ),
        profile=_parse_profile(d.get("profile", {})),
        events=_parse_events(d.get("events", {})),
        ocr=OcrConfig(
            engine=ocr_engine,
            language=str(ocr.get("language", "ru-RU")),
            preprocess=bool(ocr.get("preprocess", True)),
            max_image_dim=int(ocr.get("max_image_dim", 2400)),
        ),
        screenshots=ScreenshotConfig(
            dir=str(shots.get("dir", "screenshots")),
            capture=str(shots.get("capture", "window")),
            keep_all_attempts=bool(shots.get("keep_all_attempts", False)),
            save_success=bool(shots.get("save_success", True)),
            save_fail=bool(shots.get("save_fail", False)),
        ),
        log=LogConfig(
            dir=str(log.get("dir", "logs")),
            file=str(log.get("file", "civ4_reroll.log")),
            level=str(log.get("level", "INFO")).upper(),
        ),
        loop=LoopConfig(
            max_attempts=int(loop.get("max_attempts", 0)),
            warmup_sec=float(loop.get("warmup_sec", 5.0)),
            pause_between_attempts_sec=float(loop.get("pause_between_attempts_sec", 3.0)),
            esc_after_read_sec=float(loop.get("esc_after_read_sec", 0.3)),
        ),
    )
    return cfg


def _resolve_path(explicit: Optional[str]) -> Path:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("CIV4REROLL_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates += [Path.cwd() / DEFAULT_RELATIVE, PROJECT_ROOT / DEFAULT_RELATIVE]

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue

    # Создаём конфиг по умолчанию в корне проекта.
    target = PROJECT_ROOT / DEFAULT_RELATIVE
    _write_default(target)
    return target


def _write_default(path: Path) -> None:
    path.write_text(
        json.dumps(DEFAULT_CONFIG_DICT, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_config(explicit: Optional[str] = None) -> Tuple[AppConfig, Path]:
    """Загружает конфигурацию. Возвращает (AppConfig, путь к файлу)."""
    path = _resolve_path(explicit)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_config_dict(raw), path


def dump_default() -> str:
    """Возвращает конфигурацию по умолчанию как JSON-строку (для отладки)."""
    return json.dumps(DEFAULT_CONFIG_DICT, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # pragma: no cover
    sys.stdout.write(dump_default())