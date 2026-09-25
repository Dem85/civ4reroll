"""Захват скриншотов окна игры (Pillow + Win32).

Скриншот снимается в той же системе координат, что и действия "move"
с relative=true в проекте multikey — то есть по прямоугольнику активного
окна (включая заголовок), возвращаемому GetWindowRect.
"""

from typing import Optional

from app import winapi

try:
    from PIL import Image, ImageGrab
except ImportError:  # pragma: no cover
    Image = None
    ImageGrab = None


def window_bbox() -> Optional[tuple]:
    """BBox активного окна: (left, top, right, bottom) или None."""
    left, top, right, bottom = winapi.foreground_window_rect()
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def capture(mode: str = "window") -> "Image.Image":
    """Снимает скриншот.

    mode="window"    — область активного окна (как скриншот окна в multikey);
    mode="fullscreen"— весь основной экран.
    """
    if ImageGrab is None:
        raise RuntimeError("Pillow не установлена. Выполните: pip install -r requirements.txt")

    bbox = None if mode == "fullscreen" else window_bbox()
    if mode != "fullscreen" and bbox is None:
        # Окно не найдено — падаем на весь экран.
        bbox = None
    return ImageGrab.grab(bbox=bbox)


def save(image: "Image.Image", path: str) -> None:
    """Сохраняет изображение в PNG (создаёт каталоги при необходимости)."""
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")