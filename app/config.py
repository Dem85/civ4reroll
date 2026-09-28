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

# Маркеры открытого игрового меню (пункты меню паузы Civ4 в правом верхнем углу).
DEFAULT_MENU_MARKERS = [
    "выйти",
    "отмена",
    "сохранить игру",
    "настройки",
    "главное меню",
    "завершить игру",
    "сведения об игре",
    "ваши данные",
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
    "hotkey": {
        "key": "]",
        "modifiers": [],
        "comment": (
            "Глобальный хоткей запуска/остановки цикла. ']' — та же "
            "физическая клавиша даёт 'ъ' в русской раскладке (срабатывание "
            "по Virtual-Key коду). Модификаторы: ctrl, alt, shift, win."
        ),
    },
    "game": {
        "window_title": "Civ IV: Beyond The Sword",
        "window_process": "Civ4BeyondSword.exe",
        "key_hold_sec": 0.02,
        "dpi_aware": False,
        "comment": (
            "Окно игры ищется по window_title (подстрока), затем — по процессу "
            "window_process (имя exe). null — работать в текущем активном окне. "
            "dpi_aware: включайте, если скриншот/клики съезжают при "
            "масштабировании Windows ≠ 100%."
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
        "max_image_dim": 3000,
        "crop": [0.0, 0.15, 1.0, 0.45],
        "verify_crop": [0.0, 0.0, 1.0, 0.6],
        "log_markers": ["летопис", "журнал"],
        "variants": ["adaptive"],
        "comment": (
            "engine: auto | windows | tesseract | manual. crop: область чтения "
            "летописи, verify_crop: более широкая область для проверки, что "
            "летопись открыта. log_markers: если НИ ОДНОГО маркера нет в "
            "распознанном тексте (основной кроп + verify_crop) — попытка не "
            "засчитывается, авария только после loop.log_check_retries подряд. "
            "variants: ансамбль OCR — дополнительные варианты предобработки "
            "(сейчас: adaptive), события ищутся во всех вариантах и "
            "объединяются."
        ),
    },
    "screenshots": {
        "dir": "screenshots",
        "capture": "window",
        "keep_all_attempts": False,
        "save_success": True,
        "save_fail": True,
        "comment": (
            "capture: window (область активного окна, как в multikey) | "
            "fullscreen (весь экран). save_fail: сохранять скриншоты неудачных "
            "попыток (для диагностики)."
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
        "warmup_sec": 0.0,
        "pause_between_attempts_sec": 3.0,
        "esc_after_read_sec": 0.3,
        "log_check_retries": 2,
        "window_wait_sec": 300.0,
        "window_check_interval_sec": 0.5,
        "log_wait_sec": 1.2,
        "comment": (
            "max_attempts: 0 — бесконечно (остановка Ctrl+C или при находке). "
            "log_check_retries: сколько попыток ПОДРЯД можно не обнаружить "
            "летопись, прежде чем сработает аварийная остановка. warmup_sec: "
            "по умолчанию 0 — отсчёт не нужен, программа сама ждёт окно игры "
            "перед каждым действием. window_wait_sec: сколько ждать появления "
            "окна и переключения на него; window_check_interval_sec: частота "
            "проверок. log_wait_sec: пауза после открытия летописи, чтобы она "
            "полностью отрисовалась (улучшает OCR)."
        ),
    },
    "menu": {
        "enabled": True,
        "crop": [0.5, 0.0, 1.0, 0.6],
        "markers": [
            "выйти",
            "отмена",
            "сохранить игру",
            "настройки",
            "главное меню",
            "завершить игру",
            "сведения об игре",
            "ваши данные"
        ],
        "fuzzy": True,
        "min_ratio": 0.65,
        "comment": (
            "Проверка перед каждым сценарием: со скриншота правого верхнего "
            "угла (menu.crop) OCR ищет пункты игрового меню (menu.markers). "
            "Если меню уже открыто — первый esc сценария пропускается "
            "(иначе он закрыл бы меню). enabled=false отключает проверку."
        ),
    },
}


# ---------------------------------------------------------------------------
# Модель данных
# ---------------------------------------------------------------------------
@dataclass
class HotkeyConfig:
    key: str = "]"
    modifiers: List[str] = field(default_factory=list)


@dataclass
class GameConfig:
    window_title: Optional[str] = "Civ IV: Beyond The Sword"
    window_process: Optional[str] = "Civ4BeyondSword.exe"
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
    max_image_dim: int = 3000
    crop: Optional[List[float]] = None              # область чтения летописи
    verify_crop: Optional[List[float]] = None       # область проверки «летопись открыта»
    log_markers: List[str] = field(default_factory=lambda: ["летопис", "журнал"])
    variants: List[str] = field(default_factory=list)  # ансамбль: доп. варианты предобработки


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
    warmup_sec: float = 0.0       # отсчёт перед стартом (0 — не нужен, окно ждём сами)
    pause_between_attempts_sec: float = 3.0
    esc_after_read_sec: float = 0.3
    log_check_retries: int = 2    # попыток подряд без летописи до аварии
    window_wait_sec: float = 300.0        # таймаут ожидания появления/активации окна
    window_check_interval_sec: float = 0.5  # частота проверки окна, сек
    log_wait_sec: float = 1.2     # пауза после открытия летописи (для полной отрисовки)


@dataclass
class MenuConfig:
    """Проверка «открыто ли игровое меню» перед выполнением сценария.

    Если меню уже открыто — первый esc сценария пропускается (иначе он
    закрыл бы меню). Меню ищется OCR-ом по правому верхнему углу скриншота
    (crop) среди маркеров markers.
    """
    enabled: bool = True
    crop: Optional[List[float]] = field(default_factory=lambda: [0.5, 0.0, 1.0, 0.6])
    markers: List[str] = field(default_factory=lambda: list(DEFAULT_MENU_MARKERS))
    fuzzy: bool = True
    min_ratio: float = 0.65


@dataclass
class AppConfig:
    hotkey: HotkeyConfig
    game: GameConfig
    profile: Profile
    events: EventsConfig
    ocr: OcrConfig
    screenshots: ScreenshotConfig
    log: LogConfig
    loop: LoopConfig
    menu: MenuConfig


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


def _parse_crop(raw) -> Optional[List[float]]:
    """Разбирает ocr.crop: список [x1, y1, x2, y2] в долях 0..1."""
    if not raw:
        return None
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        raise ValueError(f"ocr.crop должен быть списком из 4 чисел, получено: {raw!r}")
    if len(vals) != 4:
        raise ValueError(f"ocr.crop должен содержать 4 числа (x1,y1,x2,y2), получено: {raw!r}")
    if not all(0.0 <= v <= 1.0 for v in vals):
        raise ValueError(f"ocr.crop должен быть в долях 0..1, получено: {raw!r}")
    return vals


def parse_config_dict(d: dict) -> AppConfig:
    hotkey = d.get("hotkey", {})
    game = d.get("game", {})
    ocr = d.get("ocr", {})
    shots = d.get("screenshots", {})
    log = d.get("log", {})
    loop = d.get("loop", {})
    menu = d.get("menu", {})

    ocr_engine = str(ocr.get("engine", "auto")).lower()
    if ocr_engine not in ("auto", "windows", "tesseract", "manual"):
        raise ValueError(
            f"Неизвестный OCR-движок: {ocr_engine!r} "
            f"(доступно: auto, windows, tesseract, manual)"
        )

    # Валидация клавиши и модификаторов хоткея (raise при ошибке).
    from app.keys import parse_key  # noqa: F401  (валидируем ключ)
    parse_key(str(hotkey.get("key", "]")))

    # Маркеры летописи: список, либо одиночное слово (legacy log_title_keyword).
    markers_raw = ocr.get("log_markers")
    if markers_raw is None and ocr.get("log_title_keyword") is not None:
        markers_raw = [ocr.get("log_title_keyword")]
    markers = []
    for m in (markers_raw or ["летопис", "журнал"]):
        if isinstance(m, str) and m.strip():
            markers.append(m.strip().lower())

    cfg = AppConfig(
        hotkey=HotkeyConfig(
            key=str(hotkey.get("key", "]")),
            modifiers=[str(m) for m in hotkey.get("modifiers", [])],
        ),
        game=GameConfig(
            window_title=game.get("window_title"),
            window_process=game.get("window_process"),
            key_hold_sec=float(game.get("key_hold_sec", 0.02)),
            dpi_aware=bool(game.get("dpi_aware", False)),
        ),
        profile=_parse_profile(d.get("profile", {})),
        events=_parse_events(d.get("events", {})),
        ocr=OcrConfig(
            engine=ocr_engine,
            language=str(ocr.get("language", "ru-RU")),
            preprocess=bool(ocr.get("preprocess", True)),
            max_image_dim=int(ocr.get("max_image_dim", 3000)),
            crop=_parse_crop(ocr.get("crop")),
            verify_crop=_parse_crop(ocr.get("verify_crop")) or [0.0, 0.0, 1.0, 0.6],
            log_markers=markers,
            variants=[str(v).strip().lower() for v in ocr.get("variants", [])
                      if isinstance(v, str) and v.strip()],
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
            warmup_sec=float(loop.get("warmup_sec", 0.0)),
            pause_between_attempts_sec=float(loop.get("pause_between_attempts_sec", 3.0)),
            esc_after_read_sec=float(loop.get("esc_after_read_sec", 0.3)),
            log_check_retries=int(loop.get("log_check_retries", 2)),
            window_wait_sec=float(loop.get("window_wait_sec", 300.0)),
            window_check_interval_sec=float(loop.get("window_check_interval_sec", 0.5)),
            log_wait_sec=float(loop.get("log_wait_sec", 1.2)),
        ),
        menu=MenuConfig(
            enabled=bool(menu.get("enabled", True)),
            crop=_parse_crop(menu.get("crop")) or [0.5, 0.0, 1.0, 0.6],
            markers=[m.strip().lower() for m in menu.get("markers", [])
                     if isinstance(m, str) and m.strip()] or list(DEFAULT_MENU_MARKERS),
            fuzzy=bool(menu.get("fuzzy", True)),
            min_ratio=float(menu.get("min_ratio", 0.65)),
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