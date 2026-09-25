"""Таблица виртуальных клавиш Windows (Virtual-Key Codes) и их разбор из текста.

Скопировано из проекта multikey (app/keys.py) без изменений.

Клавиши задаются строками в конфигурации, например: "esc", "down", "enter",
"tab", "]" (OEM-6, в русской раскладке та же физическая клавиша даёт «ъ»),
"a".."z", "0".."9", "f1".."f24" или шестнадцатеричным кодом вида "0xDD".

В действиях "key" можно задавать комбинации через "+": модификаторы (ctrl,
alt, shift, win) перечисляются перед основной клавишей, например "ctrl+tab".
"""

VK = {
    # --- Управление ---
    "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09,
    "enter": 0x0D, "return": 0x0D,
    "space": 0x20, "spacebar": 0x20,
    "backspace": 0x08, "bksp": 0x08,
    "del": 0x2E, "delete": 0x2E,
    "ins": 0x2D, "insert": 0x2D,
    "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pageup": 0x21, "pgdn": 0x22, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "pause": 0x13, "printscreen": 0x2C, "prtsc": 0x2C,
    "menu": 0x5D, "apps": 0x5D,
    "lwin": 0x5B, "rwin": 0x5C, "win": 0x5B,
    # --- Модификаторы (используются в "modifiers" хоткея) ---
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    # --- Буквы и цифры ---
    **{chr(c): c for c in range(ord("a"), ord("z") + 1)},
    **{str(d): ord("0") + d for d in range(10)},
    # --- F1..F24 ---
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    # --- NumPad ---
    **{f"numpad{i}": 0x60 + i for i in range(10)},
    "numpad*": 0x6A, "numpad+": 0x6B, "numpad-": 0x6D,
    "numpad.": 0x6E, "numpad/": 0x6F,
    # --- OEM-клавиши ---
    "]": 0xDD, "oem6": 0xDD, "oemclosebrackets": 0xDD, "ъ": 0xDD,
    "[": 0xDB, "oem4": 0xDB, "oemopenbrackets": 0xDB,
    "-": 0xBD, "oemminus": 0xBD,
    "=": 0xBB, "oemplus": 0xBB,
    ",": 0xBC, "oemcomma": 0xBC,
    "oemperiod": 0xBE,           # английская точка «.» (VK 0xBE)
    "/": 0xBF, "oemquestion": 0xBF,
    ";": 0xBA, "oemsemicolon": 0xBA,
    "'": 0xDE, "oemquotes": 0xDE,
    "`": 0xC0, "oemtilde": 0xC0,
    "\\": 0xDC, "oem5": 0xDC,
}


def parse_key(name) -> int:
    """Преобразует текстовое имя клавиши в Virtual-Key Code (int)."""
    key = str(name).strip().lower()
    if key in VK:
        return VK[key]
    if key.startswith("0x"):
        return int(key, 16)
    raise ValueError(
        f"Неизвестная клавиша: {name!r}. "
        f"Доступные варианты ищите в app/keys.py (или укажите hex-код, например '0xDD')."
    )


# Модификаторы, допустимые в комбинациях действия "key" (вида "ctrl+tab").
MODIFIER_KEYS = {
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
}


def parse_combo(name) -> tuple:
    """Разбирает комбинацию вида "ctrl+tab" / "ctrl+shift+f5".

    Возвращает кортеж (vk_основной_клавиши, [vk_модификаторов]).
    Модификаторы должны идти первыми; они нажимаются до основной клавиши
    и отпускаются после неё. Одиночная клавиша без "+" даёт пустой список
    модификаторов — это эквивалент parse_key().
    """
    parts = [p.strip().lower() for p in str(name).split("+") if p.strip()]
    if not parts:
        raise ValueError("Пустое имя клавиши в действии 'key'")
    mods = []
    while parts and parts[0] in MODIFIER_KEYS:
        mods.append(MODIFIER_KEYS[parts.pop(0)])
    if not parts:
        raise ValueError(
            f"Комбинация состоит только из модификаторов: {name!r}. "
            f"Укажите основную клавишу, например 'ctrl+tab'."
        )
    if len(parts) > 1:
        raise ValueError(
            f"Неизвестная комбинация: {name!r}. "
            f"Формат: [модификатор(+модификатор...)]+клавиша, например 'ctrl+shift+tab'."
        )
    return parse_key(parts[0]), mods