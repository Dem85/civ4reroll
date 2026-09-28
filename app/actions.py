"""Модель действий и исполнитель последовательности (ActionRunner).

Типы действий (совместимы с multikey):
  - "key"   : полное нажатие клавиши (down + удержание + up)
  - "type"  : ввод текста (SendInput UNICODE, раскладка не важна)
  - "click" : клик кнопкой мыши в текущей позиции курсора ("button": left/right)
  - "move"  : перемещение курсора мыши в координаты ("x", "y";
              "relative": true — координаты относительно активного окна)
  - "pause" : пауза

У каждого действия есть поле "delay" — пауза (в секундах) ПОСЛЕ выполнения.
"""

import time
from dataclasses import dataclass
from typing import List, Optional

from app import winapi
from app.keys import parse_combo


@dataclass
class Action:
    type: str = "key"
    key: Optional[str] = None
    text: Optional[str] = None
    button: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    relative: bool = False
    delay: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        return cls(
            type=str(d.get("type", "key")),
            key=d.get("key"),
            text=d.get("text"),
            button=d.get("button"),
            x=d.get("x"),
            y=d.get("y"),
            relative=bool(d.get("relative", False)),
            delay=float(d.get("delay", 0.0)),
        )

    def validate(self) -> None:
        """Проверяет корректность действия (вызывается при загрузке конфига)."""
        if self.type == "key":
            parse_combo(self.key)
        elif self.type == "type":
            if not self.text:
                raise ValueError("Действие 'type' требует поле 'text'")
        elif self.type == "click":
            if self.button and self.button not in ("left", "right"):
                raise ValueError(
                    f"Неизвестная кнопка мыши: {self.button!r} "
                    f"(доступно: 'left' (ЛКМ), 'right' (ПКМ))"
                )
        elif self.type == "move":
            if self.x is None or self.y is None:
                raise ValueError("Действие 'move' требует поля 'x' и 'y' (координаты в пикселях)")
        elif self.type == "pause":
            pass
        else:
            raise ValueError(
                f"Неизвестный тип действия: {self.type!r} "
                f"(доступно: 'key', 'type', 'click', 'move', 'pause')"
            )

    def run(self, key_hold_sec: float) -> None:
        if self.type == "pause":
            time.sleep(max(0.0, self.delay))
            return
        if self.type == "key":
            main_vk, mod_vks = parse_combo(self.key)
            if mod_vks:
                winapi.send_combo(mod_vks, main_vk, max(0.0, key_hold_sec))
            else:
                winapi.send_key(main_vk, max(0.0, key_hold_sec))
        elif self.type == "click":
            winapi.send_mouse_click(self.button or "left", max(0.0, key_hold_sec))
        elif self.type == "move":
            winapi.send_mouse_move(float(self.x or 0), float(self.y or 0), self.relative)
        elif self.type == "type":
            winapi.send_text(self.text or "")
        if self.delay > 0:
            time.sleep(self.delay)


def find_target_window(window_title: Optional[str], window_process: Optional[str]):
    """Ищет окно игры: сначала по заголовку, затем по имени процесса.

    Возвращает HWND или None (окно/процесс не найден).
    """
    if window_title:
        hwnd = winapi.find_window(window_title)
        if hwnd:
            return hwnd
    if window_process:
        hwnd = winapi.find_window_by_process(window_process)
        if hwnd:
            return hwnd
    return None


class WindowNotReadyError(RuntimeError):
    """Окно игры не появилось или не стало активным в течение таймаута."""


class ActionRunner:
    """Выполняет последовательность действий сценария (синхронно).

    Перед КАЖДЫМ действием проверяет, что целевое окно игры существует и
    активно (foreground). Если окна нет — ждёт его появления; если окно не
    активно — пытается активировать и ждёт (в пределах wait_window_sec).
    """

    def __init__(self, actions: List[Action], key_hold_sec: float = 0.02,
                 target_window_title: Optional[str] = None,
                 target_window_process: Optional[str] = None,
                 skip_first_esc: bool = False,
                 wait_window_sec: float = 300.0,
                 check_interval_sec: float = 0.5,
                 on_wait=None) -> None:
        self.actions = actions
        self.key_hold_sec = key_hold_sec
        self.target_window_title = target_window_title
        self.target_window_process = target_window_process
        # True: пропустить ПЕРВОЕ действие "esc" (меню игры уже открыто).
        self.skip_first_esc = skip_first_esc
        self.wait_window_sec = max(1.0, wait_window_sec)
        self.check_interval_sec = max(0.1, check_interval_sec)
        # Колбэк для сообщений ожидания (например, logger.info).
        self.on_wait = on_wait

    def _notify(self, msg: str) -> None:
        if self.on_wait is not None:
            self.on_wait(msg)

    def _find_or_wait_window(self) -> Optional[int]:
        """Ищет окно игры; если не найдено — ждёт его появления."""
        deadline = time.time() + self.wait_window_sec
        last_log = 0.0
        while True:
            hwnd = find_target_window(self.target_window_title, self.target_window_process)
            if hwnd is not None:
                return hwnd
            if not (self.target_window_title or self.target_window_process):
                return None
            now = time.time()
            if now > deadline:
                raise WindowNotReadyError(
                    f"Окно игры не появилось за {self.wait_window_sec:.0f} с "
                    f"(заголовок: {self.target_window_title!r}, "
                    f"процесс: {self.target_window_process!r}). Запустите игру."
                )
            if now - last_log >= 5.0:
                last_log = now
                self._notify("Окно игры не найдено — жду его появления...")
            time.sleep(self.check_interval_sec)

    def _ensure_active(self, hwnd) -> Optional[int]:
        """Ждёт, пока окно игры окажется в фокусе (foreground).

        Ничего не активирует и не разворачивает: если окно свёрнуто или не в
        фокусе — просто ждём, пока пользователь сам переключится на него.
        HWND перепроверяется на каждой итерации: если окно было пересоздано
        (игра сменила HWND) — берём актуальный. Возвращает актуальный HWND.
        Логирование — не чаще одного раза в 5 секунд (чтобы не спамить лог).
        """
        if not hwnd:
            return None
        deadline = time.time() + self.wait_window_sec
        last_log = 0.0
        while True:
            # Окно могло быть пересоздано (HWND изменился) — перепроверяем.
            fresh = find_target_window(self.target_window_title, self.target_window_process)
            if fresh is None:
                fresh = self._find_or_wait_window()
            hwnd = fresh
            if winapi.foreground_window() == hwnd:
                return hwnd
            now = time.time()
            if now > deadline:
                raise WindowNotReadyError(
                    f"Окно игры не стало активным за {self.wait_window_sec:.0f} с "
                    f"(сейчас активно: {winapi.foreground_window_title()!r}). "
                    "Переключитесь в окно игры."
                )
            if now - last_log >= 5.0:
                last_log = now
                self._notify("Окно игры не в фокусе или свёрнуто — жду...")
            time.sleep(self.check_interval_sec)

    def run(self) -> Optional[int]:
        """Выполняет все действия и возвращает HWND окна игры (или None).

        Если задан target_window_title/target_window_process — сначала ждёт
        появления окна и переключения на него (фокус), иначе работает в
        текущем окне. Перед каждым действием фокус окна проверяется заново
        (HWND обновляется, если окно пересоздано).
        При skip_first_esc=True первое действие "key: esc" пропускается —
        оно открывает меню игры, которое уже открыто.
        """
        hwnd = self._find_or_wait_window()
        if hwnd:
            hwnd = self._ensure_active(hwnd)

        esc_skipped = not self.skip_first_esc
        for action in self.actions:
            if not esc_skipped and action.type == "key" \
                    and action.key and action.key.strip().lower() == "esc":
                esc_skipped = True
                continue
            if hwnd:
                hwnd = self._ensure_active(hwnd)
            action.run(self.key_hold_sec)
        return hwnd