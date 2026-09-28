"""Низкоуровневый ввод и работа с окнами через Win32 API (user32.dll).

Взято за основу из проекта multikey (app/winapi.py) и дополнено функциями
получения заголовка активного окна и настройки DPI-awareness.

Клавиши и текст отправляются через SendInput с флагом KEYEVENTF_UNICODE —
раскладка клавиатуры при этом не влияет на вводимый текст.
"""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Уточняем сигнатуры Win32-функций (важно для корректных типов на x64).
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

ULONG_PTR = ctypes.c_size_t  # эквивалент ULONG_PTR


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


# Union должен содержать ВСЕ три структуры: размер struct INPUT в Win32 API
# определяется самым большим членом (MOUSEINPUT -> 40 байт на x64).
class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


def _input_keyboard(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk & 0xFFFF
    inp.ki.wScan = scan & 0xFFFF
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = 0
    return inp


def _input_mouse(flags: int, data: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = 0
    inp.mi.dy = 0
    inp.mi.mouseData = data & 0xFFFFFFFF
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = 0
    return inp


def _send(inp: INPUT) -> bool:
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        err = ctypes.get_last_error()
        print(f"[Civ4Reroll] Внимание: SendInput не принял событие (error={err})")
        return False
    return True


def set_dpi_aware(enabled: bool = True) -> None:
    """Включает/выключает DPI-awareness процесса (по умолчанию выключен —
    полная совместимость с координатами проекта multikey).
    """
    if not enabled:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def send_key(vk: int, hold_sec: float = 0.02) -> None:
    """Полное нажатие клавиши: key down -> пауза (удержание) -> key up."""
    _send(_input_keyboard(vk=vk))
    if hold_sec > 0:
        time.sleep(hold_sec)
    _send(_input_keyboard(vk=vk, flags=KEYEVENTF_KEYUP))


def send_combo(modifier_vks, vk: int, hold_sec: float = 0.02) -> None:
    """Полное нажатие комбинации с модификаторами, например Ctrl+Tab.

    modifier_vks — список Virtual-Key кодов модификаторов (ctrl/alt/shift/win).
    Последовательность: модификаторы вниз -> основная клавиша вниз -> пауза
    (удержание) -> основная клавиша вверх -> модификаторы вверх (в обратном
    порядке).
    """
    for mod in modifier_vks:
        _send(_input_keyboard(vk=mod))
    _send(_input_keyboard(vk=vk))
    if hold_sec > 0:
        time.sleep(hold_sec)
    _send(_input_keyboard(vk=vk, flags=KEYEVENTF_KEYUP))
    for mod in reversed(modifier_vks):
        _send(_input_keyboard(vk=mod, flags=KEYEVENTF_KEYUP))


def send_mouse_click(button: str = "left", hold_sec: float = 0.02) -> None:
    """Полный клик кнопкой мыши в текущей позиции курсора.

    button: "left" (ЛКМ) или "right" (ПКМ). down -> пауза (удержание) -> up.
    """
    if button == "right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    _send(_input_mouse(down))
    if hold_sec > 0:
        time.sleep(hold_sec)
    _send(_input_mouse(up))


def _screen_size() -> tuple:
    """Размер основного экрана в пикселях: (ширина, высота)."""
    return (
        user32.GetSystemMetrics(0),  # SM_CXSCREEN
        user32.GetSystemMetrics(1),  # SM_CYSCREEN
    )


def foreground_window() -> int:
    """HWND активного (переднего) окна."""
    return user32.GetForegroundWindow()


def foreground_window_title() -> str:
    """Заголовок активного окна (для логов — куда уйдут нажатия)."""
    hwnd = foreground_window()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def foreground_window_rect() -> tuple:
    """Прямоугольник активного (переднего) окна: (left, top, right, bottom)."""
    hwnd = user32.GetForegroundWindow()
    rect = wintypes.RECT()
    if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 0, 0


def send_mouse_move(x: float, y: float, relative_to_window: bool = False) -> None:
    """Перемещает курсор мыши в координаты (x, y) в пикселях.

    relative_to_window=False — абсолютные координаты экрана (от левого
    верхнего угла основного монитора).
    relative_to_window=True — координаты относительно левого верхнего угла
    активного (переднего) окна (как на скриншоте окна, включая заголовок).

    SendInput с MOUSEEVENTF_ABSOLUTE принимает нормализованные координаты
    0..65535, поэтому пиксели конвертируются с учётом размера экрана.
    """
    if relative_to_window:
        left, top, _, _ = foreground_window_rect()
        x += left
        y += top
    sw, sh = _screen_size()
    dx = int(max(0.0, min(x, sw - 1)) * 65535 / max(1, sw - 1))
    dy = int(max(0.0, min(y, sh - 1)) * 65535 / max(1, sh - 1))
    inp = _input_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    inp.mi.dx = dx
    inp.mi.dy = dy
    _send(inp)


def send_text(text: str) -> None:
    """Ввод текста через SendInput с KEYEVENTF_UNICODE (раскладка не важна)."""
    for ch in text:
        code = ord(ch)
        if code == 0x0D:      # "\r" -> Enter
            send_key(0x0D)
            continue
        if code == 0x09:      # "\t" -> Tab
            send_key(0x09)
            continue
        _send(_input_keyboard(scan=code, flags=KEYEVENTF_UNICODE))
        _send(_input_keyboard(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))


def find_window(title_part: str):
    """Ищет окно, заголовок которого содержит title_part (без учёта регистра)."""
    title_part_l = title_part.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_part_l in buf.value.lower():
                found.append(hwnd)
                return False  # остановить перебор
        return True

    found = []
    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else None


def find_window_by_process(process_name: str):
    """Ищет видимое главное окно процесса по имени исполняемого файла.

    Например, "Civ4BeyondSword.exe". Сначала собираются PID процессов с
    нужным именем (Toolhelp32), затем EnumWindows ищет видимое окно с
    заголовком, принадлежащее одному из этих PID.
    """
    process_name = process_name.strip().lower()
    if not process_name:
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    TH32CS_SNAPPROCESS = 0x00000002
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.c_void_p(-1).value or snapshot in (0, -1):
        return None

    pids = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() == process_name:
                    pids.add(entry.th32ProcessID)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    if not pids:
        return None

    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd) \
                and user32.GetWindowTextLengthW(hwnd) > 0:
            found.append(hwnd)
            return False  # остановить перебор
        return True

    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else None


def key_pressed(vk: int) -> bool:
    """Состояние клавиши (зажата ли она прямо сейчас)."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)