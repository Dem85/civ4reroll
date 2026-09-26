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


class ActionRunner:
    """Выполняет последовательность действий сценария (синхронно)."""

    def __init__(self, actions: List[Action], key_hold_sec: float = 0.02,
                 target_window_title: Optional[str] = None,
                 target_window_process: Optional[str] = None) -> None:
        self.actions = actions
        self.key_hold_sec = key_hold_sec
        self.target_window_title = target_window_title
        self.target_window_process = target_window_process

    def _find_target_window(self):
        """Ищет окно игры: сначала по заголовку, затем по имени процесса."""
        if self.target_window_title:
            hwnd = winapi.find_window(self.target_window_title)
            if hwnd:
                return hwnd
        if self.target_window_process:
            hwnd = winapi.find_window_by_process(self.target_window_process)
            if hwnd:
                return hwnd
        return None

    def run(self) -> Optional[int]:
        """Выполняет все действия и возвращает HWND окна игры (или None).

        Если задан target_window_title/target_window_process — сначала
        активирует окно игры, иначе работает в текущем (активном) окне.
        """
        hwnd = self._find_target_window()
        if hwnd:
            winapi.activate_window(hwnd)
        elif self.target_window_title or self.target_window_process:
            raise RuntimeError(
                f"Окно игры не найдено (заголовок: {self.target_window_title!r}, "
                f"процесс: {self.target_window_process!r}). Запустите игру."
            )

        for action in self.actions:
            action.run(self.key_hold_sec)
        return hwnd