"""Глобальный хоткей на основе низкоуровневого хука клавиатуры (pynput).

Адаптировано из проекта multikey (app/hotkey.py).

Срабатывание определяется по Virtual-Key коду, поэтому физическая клавиша
работает одинаково в любой раскладке: «]» и «ъ» — это одна и та же клавиша.
"""

import ctypes
import traceback

from pynput import keyboard

from app.keys import parse_key
from app.winapi import key_pressed

# Виртуальные коды клавиш-модификаторов для проверки состояния.
MOD_KEYS = {
    "ctrl": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,  # проверяем обе Win-клавиши ниже
}

WIN_VKS = (0x5B, 0x5C)  # VK_LWIN, VK_RWIN


class HotkeyListener:
    """Слушает глобальные нажатия и вызывает callback при совпадении хоткея.

    Требуемые модификаторы задаются в конфиге ("modifiers": ["ctrl", ...]).
    Если список пуст — срабатывает только при отжатых ctrl/alt/shift/win.
    """

    def __init__(self, hotkey_cfg, callback) -> None:
        self._callback = callback
        self._listener = None
        self._pressed = False
        self.reconfigure(hotkey_cfg)

    def reconfigure(self, hotkey_cfg) -> None:
        self._vk = parse_key(hotkey_cfg.key)
        self._required = {str(m).strip().lower() for m in (hotkey_cfg.modifiers or [])}
        unknown = self._required - set(MOD_KEYS)
        if unknown:
            raise ValueError(
                f"Неизвестные модификаторы хоткея: {sorted(unknown)} "
                f"(доступно: {', '.join(MOD_KEYS)})"
            )

    # --- проверка состояния модификаторов ---
    def _modifier_pressed(self, name: str) -> bool:
        if name == "win":
            return any(key_pressed(vk) for vk in WIN_VKS)
        return key_pressed(MOD_KEYS[name])

    def _match(self) -> bool:
        for name in MOD_KEYS:
            is_pressed = self._modifier_pressed(name)
            needed = name in self._required
            if is_pressed != needed:
                return False
        return True

    # --- обработка событий хука ---
    def _on_press(self, key):
        vk = getattr(key, "vk", None)
        if vk != self._vk or self._pressed:
            return
        if not self._match():
            return
        self._pressed = True
        try:
            self._callback()
        except Exception:
            traceback.print_exc()

    def _on_release(self, key):
        vk = getattr(key, "vk", None)
        if vk == self._vk:
            self._pressed = False

    # --- жизненный цикл ---
    def start(self) -> None:
        if self._listener is None:
            self._listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
            self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None