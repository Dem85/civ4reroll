"""Чтение текста со скриншота летописи.

Движки (config.json -> ocr.engine):
  - "windows"   — встроенный OCR Windows 10/11 (Windows.Media.Ocr) через
                  скрипт scripts/ocr_windows.ps1. Не требует установки
                  сторонних программ, работает через PowerShell 5.1+.
  - "tesseract" — pytesseract + Tesseract OCR (нужна установка Tesseract
                  с русским языком: --lang rus).
  - "manual"    — не распознаёт текст, а сохраняет скриншот и просит
                  пользователя ответить, были ли интересные события.
  - "auto"      — сначала windows, при неудаче tesseract.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app import screen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCR_SCRIPT = PROJECT_ROOT / "scripts" / "ocr_windows.ps1"

# ru-RU (Windows OCR) -> код языка Tesseract.
_TESSERACT_LANGS = {"ru-RU": "rus", "ru": "rus", "en-US": "eng", "en": "eng"}


class OcrError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Подготовка изображения
# ---------------------------------------------------------------------------
def _preprocess(img: "Image.Image", max_dim: int) -> "Image.Image":
    """Улучшает картинку для OCR: градации серого, контраст, масштаб.

    Увеличиваем мелкий шрифт летописи (до 2x), при этом не превышаем
    max_dim — ограничение Windows OCR (OcrEngine.MaxImageDimension ~2600).
    """
    gray = ImageOps.autocontrast(img.convert("L"))
    w, h = gray.size
    if w <= 0 or h <= 0:
        return gray

    target = max(w, h)
    if target * 2 <= max_dim:
        scale = 2.0
    elif target > max_dim:
        scale = max_dim / target
    else:
        scale = 1.0

    if scale != 1.0:
        gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return gray


def prepare_for_ocr(image_path: str, cfg) -> str:
    """Возвращает путь к изображению, готовому для OCR.

    Если ocr.preprocess=true — сохраняет обработанную копию рядом с исходным
    файлом (имя "<исходное>_ocr.png"), иначе возвращает исходный путь.
    """
    if not cfg.ocr.preprocess:
        return image_path
    src = Path(image_path)
    out = src.with_name(src.stem + "_ocr.png")
    with Image.open(src) as img:
        processed = _preprocess(img, cfg.ocr.max_image_dim)
        processed.save(out, format="PNG")
    return str(out)


# ---------------------------------------------------------------------------
# Движки
# ---------------------------------------------------------------------------
def ocr_windows(image_path: str, language: str = "ru-RU") -> str:
    """OCR через встроенный Windows.Media.Ocr (скрипт PowerShell)."""
    if not OCR_SCRIPT.is_file():
        raise OcrError(f"Не найден скрипт {OCR_SCRIPT}")

    # WinRT StorageFile требует абсолютный путь.
    absolute = os.path.abspath(image_path)
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(OCR_SCRIPT),
        "-ImagePath", absolute,
        "-Language", language,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True)
    except OSError as exc:
        raise OcrError(f"Не удалось запустить PowerShell: {exc}") from exc

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise OcrError(err or f"PowerShell-скрипт завершился с кодом {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace").strip()


def ocr_tesseract(image_path: str, language: str = "ru-RU") -> str:
    """OCR через pytesseract + Tesseract."""
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrError(
            "pytesseract не установлен. Либо установите его "
            "(pip install pytesseract) вместе с Tesseract OCR и русским языком, "
            "либо используйте движок 'windows'."
        ) from exc
    tess_lang = _TESSERACT_LANGS.get(language, "rus")
    try:
        return pytesseract.image_to_string(image_path, lang=tess_lang).strip()
    except Exception as exc:
        raise OcrError(f"Tesseract не смог обработать изображение: {exc}") from exc


# ---------------------------------------------------------------------------
# Выбор движка
# ---------------------------------------------------------------------------
def resolve_engine(cfg) -> str:
    """Определяет фактический движок OCR (для auto)."""
    engine = cfg.ocr.engine
    if engine != "auto":
        return engine
    # windows доступен всегда на Windows 10/11; проверяем наличие скрипта.
    if OCR_SCRIPT.is_file():
        return "windows"
    return "tesseract"


def recognize(image_path: str, cfg) -> Tuple[str, str]:
    """Распознаёт текст со скриншота. Возвращает (текст, движок).

    Для движка "manual" возвращает ("", "manual") — вызывающий код должен
    сам показать скриншот пользователю и спросить результат.
    """
    prepared = prepare_for_ocr(image_path, cfg)
    engine = cfg.ocr.engine

    candidates = []
    if engine == "auto":
        candidates = ["windows", "tesseract"]
    else:
        candidates = [engine]

    last_err: Optional[Exception] = None
    for eng in candidates:
        try:
            if eng == "windows":
                return ocr_windows(prepared, cfg.ocr.language), eng
            if eng == "tesseract":
                return ocr_tesseract(prepared, cfg.ocr.language), eng
            if eng == "manual":
                return "", "manual"
        except OcrError as exc:
            last_err = exc
            continue

    raise OcrError(f"OCR не удался: {last_err}")


# ---------------------------------------------------------------------------
# Самопроверка (selftest): пробуем распознать тестовую картинку
# ---------------------------------------------------------------------------
def probe_engine(cfg) -> str:
    """Прогоняет OCR на тестовой картинке и возвращает распознанный текст."""
    from pathlib import Path

    tmp_dir = Path(cfg.screenshots.dir) / "selftest"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    img_path = tmp_dir / "probe.png"

    img = Image.new("L", (640, 96), 255)
    draw = ImageDraw.Draw(img)
    font = None
    for font_path in ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/times.ttf"):
        if Path(font_path).is_file():
            font = ImageFont.truetype(font_path, 28)
            break
    draw.text((16, 24), "тест 123 золото шахта", fill=0, font=font)
    img.save(img_path, format="PNG")

    text, eng = recognize(str(img_path), cfg)
    return f"{eng}: {text!r}"