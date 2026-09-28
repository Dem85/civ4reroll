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

import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from app import screen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCR_SCRIPT = PROJECT_ROOT / "scripts" / "ocr_windows.ps1"

# ru-RU (Windows OCR) -> код языка Tesseract.
_TESSERACT_LANGS = {"ru-RU": "rus", "ru": "rus", "en-US": "eng", "en": "eng"}

# Частые артефакты Windows OCR: сербские/македонские буквы, которые движок
# подставляет вместо похожих русских. В русском тексте эти символы не
# встречаются, поэтому замена безопасна.
OCR_CHAR_FIXES = {
    "љ": "ь", "Љ": "Ь",
    "њ": "н", "Њ": "Н",
    "џ": "ж", "Џ": "Ж",
    "ћ": "ч", "Ћ": "Ч",
    "ђ": "д", "Ђ": "Д",
    "ј": "й", "Ј": "Й",
    "і": "и", "І": "И",
    "ї": "и", "Ї": "И",
    "є": "е", "Є": "Е",
    "ѕ": "з", "Ѕ": "З",
}
_OCR_FIX_TABLE = str.maketrans(OCR_CHAR_FIXES)


def _cleanup_text(raw: str) -> str:
    """Заменяет частые артефакты распознавания (без изменения остального)."""
    if not raw:
        return raw
    return raw.translate(_OCR_FIX_TABLE)


class OcrError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Подготовка изображения
# ---------------------------------------------------------------------------
def _apply_crop(img: "Image.Image", crop_rect) -> "Image.Image":
    """Обрезает изображение до области, где появляется летопись.

    crop_rect — список [x1, y1, x2, y2] в ДОЛЯХ (0..1) от ширины/высоты
    исходного скриншота. Например, летопись Civ4 в верхней части окна:
    [0.0, 0.15, 1.0, 0.45].
    """
    if not crop_rect:
        return img
    try:
        x1, y1, x2, y2 = (float(v) for v in crop_rect)
    except (TypeError, ValueError):
        raise OcrError(
            f"Некорректный ocr.crop: {crop_rect!r} "
            f"(нужно [x1, y1, x2, y2] в долях 0..1)"
        )
    w, h = img.size
    box = (
        max(0, int(w * x1)),
        max(0, int(h * y1)),
        min(w, int(w * x2)),
        min(h, int(h * y2)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise OcrError(f"Область кропа пустая: {crop_rect!r}")
    return img.crop(box)


def _adaptive_binarize(img: "Image.Image") -> "Image.Image":
    """Локальный порог: вычитаем размытый фон (BoxBlur), оставляем ч/б."""
    gray = img.convert("L")
    bg = gray.filter(ImageFilter.BoxBlur(15))
    diff = ImageChops.subtract(gray, bg)
    return diff.point(lambda p: 255 if p > 8 else 0)


def _preprocess(img: "Image.Image", max_dim: int, variant: str = "standard") -> "Image.Image":
    """Улучшает картинку для OCR: контраст/бинаризация + масштаб.

    variant:
      - "standard" — градации серого + автоконтраст (по умолчанию);
      - "adaptive" — локальный порог (ч/б, хорошо для мелкого текста).
    Мелкий шрифт летописи увеличивается до 2x, не превышая max_dim —
    ограничение Windows OCR (OcrEngine.MaxImageDimension).
    """
    if variant == "adaptive":
        gray = _adaptive_binarize(img)
    else:
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


def prepare_for_ocr(image_path: str, cfg, crop=None, variant: str = "standard") -> str:
    """Возвращает путь к изображению, готовому для OCR.

    Применяется кроп (crop или cfg.ocr.crop — область летописи), затем
    предобработка (cfg.ocr.preprocess; variant — способ обработки).
    Результат сохраняется рядом с исходным файлом. Для варианта, отличного
    от "standard", имя содержит суффикс варианта, чтобы файлы не
    перезаписывали друг друга. Если ничего не настроено — возвращается
    исходный путь.
    """
    crop = crop if crop is not None else cfg.ocr.crop
    if not cfg.ocr.preprocess and not crop:
        return image_path
    src = Path(image_path)
    suffix = "" if variant == "standard" else f"_{variant}"
    out = src.with_name(src.stem + suffix + "_ocr.png")
    with Image.open(src) as img:
        img = _apply_crop(img, crop)
        processed = _preprocess(img, cfg.ocr.max_image_dim, variant=variant)
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


def _run_engines(prepared: str, cfg) -> Tuple[str, str]:
    """Прогоняет подготовленное изображение через настроенные движки OCR."""
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
                return _cleanup_text(ocr_windows(prepared, cfg.ocr.language)), eng
            if eng == "tesseract":
                return _cleanup_text(ocr_tesseract(prepared, cfg.ocr.language)), eng
            if eng == "manual":
                return "", "manual"
        except OcrError as exc:
            last_err = exc
            continue

    raise OcrError(f"OCR не удался: {last_err}")


def recognize(image_path: str, cfg, crop=None, variant: str = "standard") -> Tuple[str, str]:
    """Распознаёт текст со скриншота. Возвращает (текст, движок).

    crop — опциональный прямоугольник [x1,y1,x2,y2] (переопределяет cfg.ocr.crop);
    variant — способ предобработки ("standard" | "adaptive").
    Текст очищается от частых OCR-артефактов (_cleanup_text).
    Для движка "manual" возвращает ("", "manual") — вызывающий код должен
    сам показать скриншот пользователю и спросить результат.
    """
    prepared = prepare_for_ocr(image_path, cfg, crop=crop, variant=variant)
    return _run_engines(prepared, cfg)


def recognize_variants(image_path: str, cfg, crop=None) -> List[Tuple[str, str]]:
    """Ансамбль OCR: основной вариант + варианты из cfg.ocr.variants.

    Возвращает список (текст, движок) — первый элемент основной вариант.
    Пустые результаты (движок manual) отбрасываются. Если какой-то вариант
    упал — он пропускается, остальные остаются.
    """
    results: List[Tuple[str, str]] = []
    variants = list(getattr(cfg.ocr, "variants", []) or [])
    logger = logging.getLogger("civ4reroll")

    try:
        results.append(recognize(image_path, cfg, crop=crop))
    except OcrError as exc:
        logger.warning("OCR (основной вариант) не удался: %s", exc)

    for variant in variants:
        try:
            results.append(recognize(image_path, cfg, crop=crop, variant=variant))
        except OcrError as exc:
            logger.warning("OCR вариант %r не удался: %s", variant, exc)

    return [(t, e) for t, e in results if t]


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

    # Для проверки движка кроп не применяем (тестовая картинка маленькая).
    import copy
    probe_cfg = copy.copy(cfg)
    probe_cfg.ocr = copy.copy(cfg.ocr)
    probe_cfg.ocr.crop = None

    text, eng = recognize(str(img_path), probe_cfg)
    return f"{eng}: {text!r}"