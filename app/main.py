"""Civ4Reroll — точка входа.

Автоматический «реролл» последнего сохранения Civilization IV:
  1. выполняет сценарий загрузки (config.json -> profile.actions):
     загрузка сохранения, пропуск ходов, открытие летописи;
  2. делает скриншот летописи (перед тем esc, который её скрывает);
  3. читает летопись OCR-ом и ищет интересные события
     (золото/серебро/медь/железо/уголь/драгоценные камни в шахтах);
  4. если события есть — закрывает летопись и останавливается;
     если нет — закрывает летопись и повторяет сценарий заново.

Режимы:
  python -m app.main                   ожидание хоткея: запуск/остановка цикла
  python -m app.main --start           запустить цикл сразу при старте
  python -m app.main --once            одна попытка и выход
  python -m app.main --selftest        проверка конфигурации, OCR, поиска событий
  python -m app.main --check-image F   распознать готовый скриншот и найти события
  python -m app.main --hotkey KEY      переопределить клавишу хоткея (например 'f9')
  python -m app.main --config PATH     другой файл конфигурации
"""

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

# Позволяет запускать и `python app/main.py`, и `python -m app.main`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import events as events_mod   # noqa: E402
from app import ocr as ocr_mod         # noqa: E402
from app import screen, winapi         # noqa: E402
from app.actions import (              # noqa: E402
    ActionRunner,
    WindowNotReadyError,
    find_target_window,
)
from app.config import load_config     # noqa: E402
from app.hotkey import HotkeyListener  # noqa: E402
from app.keys import parse_key         # noqa: E402

LOG_NAME = "civ4reroll"


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
def setup_logging(cfg) -> Path:
    """Настраивает логирование: файл (UTF-8) + консоль."""
    log_dir = Path(cfg.log.dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / cfg.log.file

    level = getattr(logging, cfg.log.level, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(fmt))
    root.addHandler(ch)

    logging.getLogger(LOG_NAME).info("Файл лога: %s", log_path.resolve())
    return log_path


# ---------------------------------------------------------------------------
# Одна попытка
# ---------------------------------------------------------------------------
def _log_markers_found(text: str, cfg) -> bool:
    """Есть ли хотя бы один маркер летописи в распознанном тексте."""
    for marker in cfg.ocr.log_markers:
        if events_mod.text_has_keyword(text, marker, fuzzy=True, min_ratio=0.68):
            return True
    return False


def _menu_is_open(screenshot_path: str, cfg, logger) -> bool:
    """Проверяет по скриншоту, открыто ли игровое меню (правый верхний угол).

    Меню паузы Civ4 — колонка кнопок справа сверху («Выйти в главное меню»,
    «Сохранить игру», «Настройки», «Отмена» и т.п.). Если в OCR-тексте области
    cfg.menu.crop найден хотя бы один cfg.menu.markers — меню открыто.
    """
    if not cfg.menu.enabled or not cfg.menu.markers:
        return False
    try:
        text, eng = ocr_mod.recognize(screenshot_path, cfg, crop=cfg.menu.crop)
    except ocr_mod.OcrError as exc:
        logger.warning("OCR проверки меню не удался (%s) — считаем меню закрытым.", exc)
        return False
    for marker in cfg.menu.markers:
        if events_mod.text_has_keyword(text, marker, fuzzy=cfg.menu.fuzzy,
                                       min_ratio=cfg.menu.min_ratio):
            logger.info(
                "Меню игры открыто: найден маркер %r (движок %s). Текст области: %r",
                marker, eng, text[:120],
            )
            return True
    logger.debug("Меню не обнаружено. Текст области: %r", text[:120])
    return False


def _wait_game_window(cfg, logger, on_game_down=None):
    """Ждёт, пока появится и станет активным окно игры.

    Возвращает HWND окна или None (если target не задан — работаем
    в текущем активном окне). Если окно не появилось / не активировалось
    в течение loop.window_wait_sec — бросает WindowNotReadyError.

    on_game_down — колбэк перезапуска игры (опция relaunch): вызывается,
    когда окно не найдено; если он вернул True (игра перезапущена) —
    таймаут ожидания продлевается.
    """
    if not (cfg.game.window_title or cfg.game.window_process):
        return None

    wait_sec = max(1.0, cfg.loop.window_wait_sec)
    interval = max(0.1, cfg.loop.window_check_interval_sec)
    deadline = time.time() + wait_sec
    last_log = 0.0

    def _relaunch_on_demand() -> bool:
        if on_game_down is None:
            return False
        try:
            return bool(on_game_down())
        except Exception:
            return False

    # Фаза 1: окно должно появиться.
    while True:
        hwnd = find_target_window(cfg.game.window_title, cfg.game.window_process)
        if hwnd:
            break
        if time.time() > deadline:
            raise WindowNotReadyError(
                f"Окно игры не появилось за {wait_sec:.0f} с "
                f"(заголовок: {cfg.game.window_title!r}, "
                f"процесс: {cfg.game.window_process!r}). Запустите игру."
            )
        # Опция relaunch: игра «умерла» — перезапускаем её и ждём дальше.
        if _relaunch_on_demand():
            deadline = time.time() + wait_sec
            last_log = 0.0
        now = time.time()
        if now - last_log >= 5.0:
            last_log = now
            logger.info("Окно игры не найдено — жду его появления...")
        time.sleep(interval)

    # Фаза 2: окно должно оказаться в фокусе (foreground). Разворачивать и
    # активировать окно не пытаемся — просто ждём, пока пользователь сам
    # переключится на него. HWND перепроверяется: игра может пересоздать окно.
    while True:
        fresh = find_target_window(cfg.game.window_title, cfg.game.window_process)
        if fresh is not None:
            hwnd = fresh
        elif _relaunch_on_demand():
            deadline = time.time() + wait_sec
            last_log = 0.0
            continue
        if winapi.foreground_window() == hwnd:
            return hwnd
        if time.time() > deadline:
            raise WindowNotReadyError(
                f"Окно игры не стало активным за {wait_sec:.0f} с "
                f"(сейчас активно: {winapi.foreground_window_title()!r}). "
                "Переключитесь в окно игры."
            )
        now = time.time()
        if now - last_log >= 5.0:
            last_log = now
            logger.info("Окно игры не в фокусе или свёрнуто — жду...")
        time.sleep(interval)


def _game_is_running(cfg) -> bool:
    """Игра считается запущенной, если жив её процесс или найдено окно."""
    if cfg.game.window_process:
        try:
            if winapi.is_process_running(cfg.game.window_process):
                return True
        except Exception:
            pass
    if cfg.game.window_title:
        try:
            if winapi.find_window(cfg.game.window_title):
                return True
        except Exception:
            pass
    return False


def _relaunch_game(cfg, logger) -> bool:
    """Запускает игру через ярлык .url, ждёт и активирует её окно.

    Возвращает True, если игра запущена (окно найдено). Фокус дальше
    обеспечивает ActionRunner перед каждым действием.
    """
    if not (cfg.game.window_title or cfg.game.window_process):
        logger.warning(
            "relaunch требует game.window_title/window_process — автозапуск пропущен."
        )
        return False
    shortcut = (cfg.relaunch.shortcut or "").strip()
    if not shortcut or not Path(shortcut).is_file():
        logger.error(
            "Ярлык игры не найден: %r — автозапуск невозможен. "
            "Проверьте relaunch.shortcut в конфигурации.", shortcut,
        )
        return False
    logger.info("Игра не запущена — запускаю через ярлык: %s", shortcut)
    try:
        winapi.launch_shortcut(shortcut)
    except Exception as exc:
        logger.error("Не удалось запустить игру через ярлык: %s", exc)
        return False

    time.sleep(max(0.0, cfg.relaunch.wait_sec))
    logger.info("Жду появления окна игры (%s)...",
                cfg.game.window_title or cfg.game.window_process)

    hwnd = None
    wait_sec = max(1.0, cfg.loop.window_wait_sec)
    interval = max(0.1, cfg.loop.window_check_interval_sec)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        hwnd = find_target_window(cfg.game.window_title, cfg.game.window_process)
        if hwnd:
            break
        time.sleep(interval)
    if not hwnd:
        logger.warning("Окно игры не появилось за %.0f с.", wait_sec)
        return False

    if winapi.activate_window(hwnd):
        logger.info("Окно игры активировано (HWND=%d).", hwnd)
    else:
        logger.warning("Не удалось активировать окно игры — жду переключения.")
    return True


class _RelaunchGuard:
    """Контроль автозапуска игры (опция relaunch).

    - relaunch(): перезапускает игру, если она не запущена. Троттлинг
      RELAUNCH_COOLDOWN_SEC — чтобы не спамить повторными запусками, пока
      Steam/игра грузятся; при успехе помечает «игру недавно перезапустили».
    - consume_relaunch(): однократно возвращает True, если игра была недавно
      перезапущена (в т.ч. посреди предыдущей попытки) — тогда следующая
      попытка выполняется по relaunch-сценарию вместо обычного.
    """

    RELAUNCH_COOLDOWN_SEC = 30.0   # мин. интервал между попытками запуска
    RELAUNCH_FRESH_SEC = 60.0      # период, в который действует «после перезапуска»

    def __init__(self, cfg, logger) -> None:
        self.cfg = cfg
        self.logger = logger
        self._last_attempt = 0.0
        self._relaunched_at = 0.0

    def game_down(self) -> bool:
        """True, если игра не запущена (нет процесса и окна)."""
        if not (self.cfg.game.window_title or self.cfg.game.window_process):
            return False
        return not _game_is_running(self.cfg)

    def relaunch(self) -> bool:
        """Запускает игру, если она не запущена. Возвращает True при успехе."""
        if not self.cfg.relaunch.enabled:
            return False
        if not (self.cfg.game.window_title or self.cfg.game.window_process):
            return False
        now = time.time()
        if now - self._last_attempt < self.RELAUNCH_COOLDOWN_SEC:
            return False
        self._last_attempt = now
        if not self.game_down():
            return False
        ok = _relaunch_game(self.cfg, self.logger)
        if ok:
            self._relaunched_at = now
        return ok

    def consume_relaunch(self) -> bool:
        """Однократно сообщает, что игра была недавно перезапущена."""
        fresh = bool(self._relaunched_at
                     and time.time() - self._relaunched_at < self.RELAUNCH_FRESH_SEC)
        self._relaunched_at = 0.0
        return fresh


def perform_attempt(cfg, logger, use_relaunch_actions: bool = False,
                    on_game_down=None) -> dict:
    """Выполняет одну попытку: сценарий -> скриншот -> OCR -> поиск событий.

    use_relaunch_actions=True — вместо profile.actions выполняется
    relaunch.actions (сценарий первой попытки после автозапуска игры).
    В этом случае проверка меню не выполняется (в relaunch-сценарии свои
    esc в начале), а первый esc сценария никогда не пропускается.

    Возвращает словарь с полями:
      status: 'ok' | 'no_log' | 'focus_lost' | 'ocr_error'
      found, matches, engine, text, screenshot, game_focused, hwnd
    """
    shots_dir = Path(cfg.screenshots.dir)
    shots_dir.mkdir(parents=True, exist_ok=True)

    # Ждём появления и активации окна игры — скриншот проверки меню должен
    # сниматься именно с окна игры (окончательно окно ждёт runner.run()).
    hwnd = _wait_game_window(cfg, logger, on_game_down=on_game_down)

    # После автозапуска используем relaunch-сценарий вместо обычного.
    use_relaunch = use_relaunch_actions and bool(cfg.relaunch.actions)
    actions = cfg.relaunch.actions if use_relaunch else cfg.profile.actions

    # Проверка: открыто ли уже игровое меню (тогда первый esc сценария не нужен).
    # Для relaunch-сценария не нужна: игра только что стартовала, и свои esc
    # в начале сценария всегда выполняются полностью.
    menu_open = False
    if cfg.menu.enabled and not use_relaunch:
        try:
            pre_img = screen.capture(cfg.screenshots.capture)
            pre_path = shots_dir / "menu_check.png"
            screen.save(pre_img, str(pre_path))
            menu_open = _menu_is_open(str(pre_path), cfg, logger)
        except Exception as exc:
            logger.warning(
                "Не удалось проверить состояние меню (%s) — считаем меню закрытым.", exc
            )
        if menu_open:
            logger.info("Меню игры уже открыто — первый esc сценария будет пропущен.")

    runner = ActionRunner(
        actions=actions,
        key_hold_sec=cfg.game.key_hold_sec,
        target_window_title=cfg.game.window_title,
        target_window_process=cfg.game.window_process,
        skip_first_esc=(False if use_relaunch else menu_open),
        wait_window_sec=cfg.loop.window_wait_sec,
        check_interval_sec=cfg.loop.window_check_interval_sec,
        on_wait=logger.info,
        on_game_down=on_game_down,
    )

    logger.info("Запуск сценария: загрузка сохранения, пропуск ходов, открытие летописи...")
    hwnd = runner.run()

    # Даём летописи полностью отрисоваться (loop.log_wait_sec).
    time.sleep(cfg.loop.log_wait_sec)

    # Проверка фокуса: скриншот и esc должны идти только в окно игры.
    game_focused = True
    if hwnd:
        if winapi.foreground_window() != hwnd:
            game_focused = False
            logger.warning(
                "Фокус ушёл с окна игры (активно: %r) — попытка не засчитана.",
                winapi.foreground_window_title(),
            )
            return {"status": "focus_lost", "found": False, "matches": [],
                    "engine": "?", "text": "", "screenshot": "",
                    "game_focused": False, "hwnd": hwnd}

    img = screen.capture(cfg.screenshots.capture)
    shot_path = shots_dir / "latest.png"
    screen.save(img, str(shot_path))
    logger.info("Скриншот летописи: %s", shot_path.resolve())

    # Движок manual — спрашиваем пользователя (OCR не используется).
    if cfg.ocr.engine == "manual":
        logger.info("Режим manual: посмотрите скриншот выше.")
        try:
            answer = input("Были ли интересные события "
                           "(золото/серебро/медь/железо/уголь/драгоценные камни в шахтах)? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer in ("y", "yes", "д", "да"):
            try:
                name = input("Какое событие произошло? [Золото] ").strip() or "Золото"
            except EOFError:
                name = "Золото"
            match = events_mod.EventMatch(name=name, sentence="(подтверждено пользователем)", city="")
            return {"status": "ok", "found": True, "matches": [match], "engine": "manual",
                    "text": "", "screenshot": str(shot_path),
                    "game_focused": game_focused, "hwnd": hwnd}
        return {"status": "ok", "found": False, "matches": [], "engine": "manual",
                "text": "", "screenshot": str(shot_path),
                "game_focused": game_focused, "hwnd": hwnd}

    # OCR: ансамбль вариантов предобработки (основной + ocr.variants).
    try:
        ocr_results = ocr_mod.recognize_variants(str(shot_path), cfg)
    except ocr_mod.OcrError as exc:
        logger.error("OCR не удался: %s", exc)
        return {"status": "ocr_error", "found": False, "matches": [], "engine": "?",
                "text": "", "screenshot": str(shot_path),
                "game_focused": game_focused, "hwnd": hwnd}
    if not ocr_results:
        logger.error("OCR не вернул ни одного текста.")
        return {"status": "ocr_error", "found": False, "matches": [], "engine": "?",
                "text": "", "screenshot": str(shot_path),
                "game_focused": game_focused, "hwnd": hwnd}

    texts = [t for t, _ in ocr_results]
    engines = [e for _, e in ocr_results]
    main_text = max(texts, key=len)
    logger.info(
        "Распознано символов: %d (движок: %s, вариантов: %d)",
        len(main_text), engines[0], len(texts),
    )
    for i, t in enumerate(texts):
        logger.info("  OCR вариант %d (%s): %d символов", i + 1, engines[i], len(t))
    logger.info("Текст летописи:\n%s", main_text)
    if len(main_text) < 10:
        logger.warning(
            "Текста почти нет (%d символов) — возможно, летопись не открылась "
            "или скриншот снят не с того окна.", len(main_text)
        )

    # Проверка: открыта ли летопись (маркеры в любом из вариантов).
    if not any(_log_markers_found(t, cfg) for t in texts):
        try:
            text2, eng2 = ocr_mod.recognize(
                str(shot_path), cfg, crop=cfg.ocr.verify_crop
            )
        except ocr_mod.OcrError as exc:
            logger.warning("Дополнительный OCR (verify_crop) не удался: %s", exc)
            return {"status": "no_log", "found": False, "matches": [],
                    "engine": engines[0], "text": main_text,
                    "screenshot": str(shot_path),
                    "game_focused": game_focused, "hwnd": hwnd}
        if _log_markers_found(text2, cfg):
            logger.info(
                "Маркер летописи найден на расширенной области (%d символов) — "
                "летопись открыта.", len(text2)
            )
            texts.append(text2)
            engines.append(eng2)
        else:
            logger.warning(
                "Маркеры %r не найдены в распознанном тексте — летопись не видна.",
                cfg.ocr.log_markers,
            )
            return {"status": "no_log", "found": False, "matches": [],
                    "engine": engines[0], "text": main_text,
                    "screenshot": str(shot_path),
                    "game_focused": game_focused, "hwnd": hwnd}

    # Поиск событий по всем вариантам OCR, объединение без дублей.
    matches = []
    seen = set()
    for t in texts:
        for m in events_mod.find_interesting_events(t, cfg):
            key = (m.name, m.city)
            if key not in seen:
                seen.add(key)
                matches.append(m)
    return {"status": "ok", "found": bool(matches), "matches": matches,
            "engine": engines[0], "text": main_text,
            "screenshot": str(shot_path),
            "game_focused": game_focused, "hwnd": hwnd}


def press_esc_close_log(cfg, logger=None, on_game_down=None) -> None:
    """Нажимает esc — скрывает летопись (последний esc из multikey-сценария).

    Перед esc ждёт, пока окно игры активно; если окно недоступно в течение
    таймаута — esc не отправляется (в лог пишется предупреждение).
    on_game_down — колбэк перезапуска игры (опция relaunch): если игра
    выключилась, она будет перезапущена, а esc отправлен уже в новое окно.
    """
    if logger is None:
        logger = logging.getLogger(LOG_NAME)
    time.sleep(cfg.loop.esc_after_read_sec)
    try:
        _wait_game_window(cfg, logger, on_game_down=on_game_down)
    except WindowNotReadyError as exc:
        logger.warning("esc не отправлен: %s", exc)
        return
    winapi.send_key(parse_key("esc"), cfg.game.key_hold_sec)
    time.sleep(0.2)


def save_attempt_screenshot(cfg, shot_path: str, suffix: str, attempt: int) -> None:
    """Копирует скриншот попытки в отдельный файл (если включено в конфиге)."""
    src = Path(shot_path)
    if not src.is_file():
        return
    dst = src.parent / f"{suffix}_{attempt:03d}{src.suffix}"
    dst.write_bytes(src.read_bytes())
    logging.getLogger(LOG_NAME).info("Скриншот сохранён: %s", dst.resolve())


# ---------------------------------------------------------------------------
# Цикл реролла
# ---------------------------------------------------------------------------
def run_loop(cfg, logger, once: bool = False, stop_event=None) -> int:
    """Главный цикл: повторяет сценарий, пока не найдёт интересные события.

    stop_event — threading.Event: при установке цикл останавливается после
    текущей попытки (используется хоткеем).
    """
    winapi.set_dpi_aware(cfg.game.dpi_aware)

    if cfg.game.window_title:
        logger.info("Целевое окно: %r", cfg.game.window_title)
    else:
        logger.info(
            "Работаем в текущем активном окне. Сейчас активно: %r",
            winapi.foreground_window_title(),
        )

    if cfg.game.window_title or cfg.game.window_process:
        logger.info(
            "Окно игры будет ожидаться перед каждым действием "
            "(таймаут %.0f с, проверка каждые %.1f с).",
            cfg.loop.window_wait_sec, cfg.loop.window_check_interval_sec,
        )

    max_attempts = 1 if once else cfg.loop.max_attempts
    if not once and cfg.loop.warmup_sec > 0:
        if stop_event is not None and stop_event.is_set():
            logger.info("Остановка запрошена до старта.")
            return 0
        logger.info(
            "Старт через %.0f с. Переключитесь в окно игры!",
            cfg.loop.warmup_sec,
        )
        if not _countdown(cfg.loop.warmup_sec, logger, stop_event):
            logger.info("Отсчёт прерван: запрошена остановка.")
            return 0

    guard = _RelaunchGuard(cfg, logger)
    log_miss_streak = 0
    attempt = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Остановлено по хоткею после попытки %d.", attempt)
            return 0
        attempt += 1
        limit_label = "∞" if max_attempts == 0 else str(max_attempts)
        logger.info("=== Попытка %d/%s ===", attempt, limit_label)

        # Опция relaunch: если игра не запущена или выключилась — запустить её
        # через ярлык, подождать и активировать окно. Если игра была недавно
        # перезапущена (в т.ч. посреди предыдущей попытки) — текущая попытка
        # выполняется по relaunch-сценарию вместо обычного.
        if cfg.relaunch.enabled and guard.game_down():
            guard.relaunch()
        relaunched = guard.consume_relaunch()

        try:
            res = perform_attempt(cfg, logger, use_relaunch_actions=relaunched,
                                  on_game_down=guard.relaunch)
        except WindowNotReadyError as exc:
            # Окно игры недоступно — ждём дальше, не засчитывая попытку.
            logger.warning("%s Жду следующей попытки...", exc)
            time.sleep(cfg.loop.pause_between_attempts_sec)
            continue
        except RuntimeError as exc:
            logger.error("Ошибка выполнения сценария: %s", exc)
            logger.error(
                "Проверьте, что игра запущена и окно находится по "
                "game.window_title из config.json."
            )
            return 2
        except Exception:
            logger.exception("Непредвиденная ошибка при выполнении попытки")
            return 1

        status = res.get("status", "ok")

        # Неудачные попытки: летопись не видна / фокус потерян / OCR ошибся.
        # Аварийная остановка — только после log_check_retries подряд.
        if status in ("no_log", "ocr_error", "focus_lost"):
            reason = {
                "focus_lost": "фокус не на окне игры",
                "ocr_error": "OCR не сработал",
                "no_log": "маркеры летописи не найдены",
            }[status]
            log_miss_streak += 1
            retries = max(0, cfg.loop.log_check_retries)
            if retries and log_miss_streak > retries:
                logger.critical(
                    "АВАРИЙНАЯ ОСТАНОВКА: %s (%d попыток подряд).",
                    reason, log_miss_streak,
                )
                if res.get("game_focused"):
                    press_esc_close_log(cfg, on_game_down=guard.relaunch)
                return 3
            logger.warning(
                "%s — попытка не засчитана (%d/%d), повторяю сценарий.",
                reason, log_miss_streak, retries if retries else 1,
            )
            if cfg.screenshots.save_fail and res.get("screenshot"):
                save_attempt_screenshot(cfg, res["screenshot"], "no_log", attempt)
            if res.get("game_focused"):
                press_esc_close_log(cfg, on_game_down=guard.relaunch)
            time.sleep(cfg.loop.pause_between_attempts_sec)
            continue

        # Успешное чтение летописи — сбрасываем счётчик пропусков.
        log_miss_streak = 0

        if res["found"]:
            summary = events_mod.format_summary(res["matches"])
            logger.info("НАЙДЕНЫ интересные события: %s", summary)
            for m in res["matches"]:
                logger.info("  - %s (город: %s): %s", m.name, m.city or "?", m.sentence)
            if cfg.screenshots.save_success:
                save_attempt_screenshot(cfg, res["screenshot"], "success", attempt)
            logger.info("Закрываю летопись (esc) и останавливаюсь.")
            press_esc_close_log(cfg, on_game_down=guard.relaunch)
            logger.info("Готово: интересные события найдены на попытке %d.", attempt)
            return 0

        logger.info("Интересных событий не найдено (движок OCR: %s).", res["engine"])
        if cfg.screenshots.save_fail:
            save_attempt_screenshot(cfg, res["screenshot"], "no_events", attempt)

        logger.info("Закрываю летопись (esc) и повторяю сценарий заново.")
        press_esc_close_log(cfg, on_game_down=guard.relaunch)

        if 0 < max_attempts <= attempt:
            break
        if stop_event is not None and stop_event.is_set():
            logger.info("Остановлено по хоткею после попытки %d.", attempt)
            return 0
        time.sleep(cfg.loop.pause_between_attempts_sec)

    logger.warning("Достигнут лимит попыток (%d), интересных событий не найдено.", attempt)
    return 1


def _countdown(seconds: float, logger, stop_event=None) -> bool:
    """Обратный отсчёт. Возвращает True, если отсчёт завершён полностью."""
    for left in range(int(seconds), 0, -1):
        if stop_event is not None and stop_event.is_set():
            return False
        logger.info("%d...", left)
        time.sleep(1.0)
    return True


# ---------------------------------------------------------------------------
# Управление циклом глобальным хоткеем
# ---------------------------------------------------------------------------
class RerollHotkeyApp:
    """Запуск/остановка цикла реролла глобальным хоткеем (переключатель)."""

    def __init__(self, cfg, logger) -> None:
        self.cfg = cfg
        self.logger = logger
        self._stop = threading.Event()
        self._thread = None
        self._exit_event = threading.Event()
        self._exit_code = 0
        self.hotkey = HotkeyListener(cfg.hotkey, self.toggle)

    def hotkey_label(self) -> str:
        h = self.cfg.hotkey
        mods = "".join(f"{m.upper()}+" for m in h.modifiers)
        return f"{mods}{h.key}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def toggle(self) -> None:
        """Обработчик хоткея: если цикл идёт — остановить, иначе — запустить."""
        if self.running:
            self.logger.info("Хоткей: запрошена остановка цикла (после текущей попытки)...")
            self._stop.set()
        else:
            self.logger.info("Хоткей: запуск цикла реролла.")
            self._stop.clear()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def start_now(self) -> None:
        """Запуск цикла без нажатия хоткея (флаг --start)."""
        if self.running:
            self.logger.warning("Цикл уже запущен.")
            return
        self.logger.info("Старт цикла реролла.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        try:
            rc = run_loop(self.cfg, self.logger, stop_event=self._stop)
        except Exception:
            self.logger.exception("Цикл завершился с ошибкой")
            self._finish(1)
            return

        # Остановлено пользователем хоткеем — остаёмся ждать следующий запуск.
        if self._stop.is_set():
            self.logger.info(
                "Цикл остановлен. Нажмите хоткей '%s' для нового запуска.",
                self.hotkey_label(),
            )
            return

        # Цикл завершился сам (находка / лимит / ошибка) — завершаем процесс.
        if rc == 0:
            self.logger.info("Интересные события найдены — завершение работы.")
        elif rc == 1:
            self.logger.warning("Лимит попыток исчерпан — завершение работы.")
        elif rc == 2:
            self.logger.error("Окно/процесс игры не найден — завершение работы.")
        else:
            self.logger.error("Аварийная остановка — завершение работы.")
        self._finish(rc)

    def _finish(self, rc: int) -> None:
        """Завершает приложение с кодом rc."""
        self._exit_code = rc
        self._exit_event.set()

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def exit_event(self) -> threading.Event:
        return self._exit_event

    def start(self) -> None:
        self.hotkey.start()

    def stop(self) -> None:
        self._stop.set()
        self.hotkey.stop()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Режимы: selftest / check-image
# ---------------------------------------------------------------------------
def selftest(cfg, cfg_path, logger) -> int:
    print(f"Файл конфигурации        : {cfg_path}")
    print(f"Действий в сценарии      : {len(cfg.profile.actions)}")
    print(f"Целевое окно             : {cfg.game.window_title or 'текущее (активное)'}"
          f"{'' if not cfg.game.window_process else ' / процесс ' + cfg.game.window_process}")
    print(f"OCR-движок               : {cfg.ocr.engine} -> {ocr_mod.resolve_engine(cfg)}")
    print(f"Область OCR (crop)       : {cfg.ocr.crop or 'весь экран'}")
    print(f"Область проверки         : {cfg.ocr.verify_crop or 'весь экран'}")
    print(f"Маркеры летописи         : {cfg.ocr.log_markers or 'выключено'}")
    print(f"Ансамбль OCR             : {cfg.ocr.variants or 'выключен'}")
    print(f"Пауза после летописи     : {cfg.loop.log_wait_sec:.1f} с")
    print(f"Повторов до аварии       : {cfg.loop.log_check_retries}")
    print(f"Ожидание окна            : {cfg.loop.window_wait_sec:.0f} с "
          f"(проверка каждые {cfg.loop.window_check_interval_sec:.1f} с)")
    print(f"Проверка меню            : {'включена' if cfg.menu.enabled else 'выключена'}"
          f"{f' (crop={cfg.menu.crop}, маркеров: {len(cfg.menu.markers)})' if cfg.menu.enabled else ''}")
    print(f"Автозапуск (relaunch)    : {'включён' if cfg.relaunch.enabled else 'выключен'}"
          f"{f' ({cfg.relaunch.shortcut})' if cfg.relaunch.enabled else ''}")
    print(f"Интересных событий       : {len(cfg.events.items)} "
          f"({', '.join(i.name for i in cfg.events.items)})")

    print("\nПроверка OCR на тестовой картинке...")
    try:
        text = ocr_mod.probe_engine(cfg)
        print(f"  OK: {text}")
    except ocr_mod.OcrError as exc:
        print(f"  ОШИБКА: {exc}")
        print("  Совет: укажите ocr.engine=tesseract или manual в config.json.")

    print("\nПроверка поиска событий на образце текста...")
    sample = "В шахте около города Москва обнаружено золото! Торговля принесла 50 золота."
    matches = events_mod.find_interesting_events(sample, cfg)
    summary = events_mod.format_summary(matches)
    print(f"  Образец: {sample}")
    print(f"  Найдено: {summary or 'ничего'} "
          f"{'(корректно)' if matches and matches[0].name == 'Золото' else '(проверьте events в config.json)'}")

    print("\nSelf-test завершён.")
    return 0


def check_image(cfg, image_path: str, logger) -> int:
    """Распознаёт готовый скриншот (без игры) и ищет события."""
    if not Path(image_path).is_file():
        logger.error("Файл не найден: %s", image_path)
        return 2
    logger.info("Анализ изображения: %s", image_path)
    text, eng = ocr_mod.recognize(image_path, cfg)
    logger.info("Движок OCR: %s", eng)
    logger.info("Распознанный текст:\n%s", text)
    matches = events_mod.find_interesting_events(text, cfg)
    if matches:
        logger.info("Найдены интересные события: %s", events_mod.format_summary(matches))
        for m in matches:
            logger.info("  - %s (город: %s): %s", m.name, m.city or "?", m.sentence)
        return 0
    logger.info("Интересных событий не найдено.")
    return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="Civ4Reroll",
        description="Автоматический реролл последнего сохранения Civ4: загрузка, "
                    "пропуск ходов, чтение летописи через скриншот и поиск интересных "
                    "событий; при отсутствии событий сценарий повторяется.",
    )
    parser.add_argument("--config", metavar="PATH", help="путь к JSON-конфигурации")
    parser.add_argument("--once", action="store_true",
                        help="выполнить только одну попытку и выйти")
    parser.add_argument("--start", action="store_true",
                        help="запустить цикл сразу при старте (без ожидания хоткея)")
    parser.add_argument("--max-attempts", type=int, metavar="N",
                        help="лимит попыток цикла (переопределяет loop.max_attempts)")
    parser.add_argument("--hotkey", metavar="KEY",
                        help="переопределить клавишу хоткея (например 'f9' или '0xDD')")
    parser.add_argument("--selftest", action="store_true",
                        help="проверить конфигурацию, OCR и поиск событий, без игры")
    parser.add_argument("--check-image", metavar="FILE",
                        help="распознать готовый скриншот летописи и найти события")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        cfg, cfg_path = load_config(args.config)
    except Exception as exc:
        print(f"[Civ4Reroll] Ошибка чтения конфигурации: {exc}")
        return 1

    if args.hotkey:
        cfg.hotkey.key = args.hotkey
    if args.max_attempts is not None:
        cfg.loop.max_attempts = args.max_attempts

    log_path = setup_logging(cfg)
    logger = logging.getLogger(LOG_NAME)
    logger.info("Civ4Reroll запущен. Конфигурация: %s", cfg_path)

    if args.selftest:
        return selftest(cfg, cfg_path, logger)
    if args.check_image:
        return check_image(cfg, args.check_image, logger)

    if args.once:
        try:
            return run_loop(cfg, logger, once=True)
        except KeyboardInterrupt:
            logger.info("Прервано пользователем (Ctrl+C).")
            return 0

    app = RerollHotkeyApp(cfg, logger)
    app.start()
    if args.start:
        app.start_now()
    logger.info(
        "Ожидание глобального хоткея '%s' — запуск/остановка цикла. Ctrl+C — выход.",
        app.hotkey_label(),
    )
    try:
        # Ждём естественного завершения цикла (находка/лимит/ошибка);
        # Ctrl+C — выход из приложения.
        app.exit_event.wait()
        return app.exit_code
    except KeyboardInterrupt:
        logger.info("Выход (Ctrl+C).")
        return 0
    finally:
        app.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)