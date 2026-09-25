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
from app.actions import ActionRunner   # noqa: E402
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
def perform_attempt(cfg, logger) -> dict:
    """Выполняет одну попытку: сценарий -> скриншот -> OCR -> поиск событий.

    Возвращает словарь с полями: found, matches, engine, text, screenshot.
    """
    shots_dir = Path(cfg.screenshots.dir)
    shots_dir.mkdir(parents=True, exist_ok=True)

    runner = ActionRunner(
        actions=cfg.profile.actions,
        key_hold_sec=cfg.game.key_hold_sec,
        target_window_title=cfg.game.window_title,
    )

    logger.info("Запуск сценария: загрузка сохранения, пропуск ходов, открытие летописи...")
    runner.run()

    # Даём летописи полностью отрисоваться.
    time.sleep(0.6)

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
            return {"found": True, "matches": [match], "engine": "manual",
                    "text": "", "screenshot": str(shot_path)}
        return {"found": False, "matches": [], "engine": "manual",
                "text": "", "screenshot": str(shot_path)}

    # OCR + анализ.
    try:
        text, eng = ocr_mod.recognize(str(shot_path), cfg)
    except ocr_mod.OcrError as exc:
        logger.warning("OCR не удался: %s", exc)
        return {"found": False, "matches": [], "engine": "?",
                "text": "", "screenshot": str(shot_path)}

    logger.info("Распознано символов: %d (движок: %s)", len(text), eng)
    if len(text) < 10:
        logger.warning(
            "Текста почти нет (%d символов) — возможно, летопись не открылась "
            "или скриншот снят не с того окна.", len(text)
        )
    logger.debug("Текст летописи:\n%s", text[:4000])

    matches = events_mod.find_interesting_events(text, cfg)
    return {"found": bool(matches), "matches": matches, "engine": eng,
            "text": text, "screenshot": str(shot_path)}


def press_esc_close_log(cfg) -> None:
    """Нажимает esc — скрывает летопись (последний esc из multikey-сценария)."""
    time.sleep(cfg.loop.esc_after_read_sec)
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

    attempt = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Остановлено по хоткею после попытки %d.", attempt)
            return 0
        attempt += 1
        limit_label = "∞" if max_attempts == 0 else str(max_attempts)
        logger.info("=== Попытка %d/%s ===", attempt, limit_label)

        try:
            res = perform_attempt(cfg, logger)
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

        if res["found"]:
            summary = events_mod.format_summary(res["matches"])
            logger.info("НАЙДЕНЫ интересные события: %s", summary)
            for m in res["matches"]:
                logger.info("  - %s (город: %s): %s", m.name, m.city or "?", m.sentence)
            if cfg.screenshots.save_success:
                save_attempt_screenshot(cfg, res["screenshot"], "success", attempt)
            logger.info("Закрываю летопись (esc) и останавливаюсь.")
            press_esc_close_log(cfg)
            logger.info("Готово: интересные события найдены на попытке %d.", attempt)
            return 0

        logger.info("Интересных событий не найдено (движок OCR: %s).", res["engine"])
        if cfg.screenshots.save_fail:
            save_attempt_screenshot(cfg, res["screenshot"], "no_events", attempt)

        logger.info("Закрываю летопись (esc) и повторяю сценарий заново.")
        press_esc_close_log(cfg)

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
            if rc == 0:
                self.logger.info("Цикл завершён: интересные события найдены.")
            elif rc == 2:
                self.logger.error("Цикл остановлен: окно игры не найдено.")
        except Exception:
            self.logger.exception("Цикл завершился с ошибкой")
        finally:
            self.logger.info(
                "Цикл остановлен. Нажмите хоткей '%s' для нового запуска.",
                self.hotkey_label(),
            )

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
    print(f"Целевое окно             : {cfg.game.window_title or 'текущее (активное)'}")
    print(f"OCR-движок               : {cfg.ocr.engine} -> {ocr_mod.resolve_engine(cfg)}")
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
        while True:
            time.sleep(1.0)
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