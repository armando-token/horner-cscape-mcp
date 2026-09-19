import ctypes
import ctypes.wintypes
import json
from pathlib import Path
from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = Path("artifacts/.cscape_live_gate.json")
with open(gate_path) as f:
    gate = json.load(f)
hwnd = int(gate["hwnd"], 16)

def capture_screenshot(target_hwnd, out_path):
    r = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(target_hwnd, ctypes.byref(r)):
        return False
    w = max(100, r.right - r.left)
    h = max(100, r.bottom - r.top)

    hdc_window = user32.GetWindowDC(target_hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbm = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    res = user32.PrintWindow(target_hwnd, hdc_mem, 2)
    if not res:
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_window, 0, 0, 0x00CC0020)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.wintypes.DWORD),
            ("biWidth", ctypes.wintypes.LONG),
            ("biHeight", ctypes.wintypes.LONG),
            ("biPlanes", ctypes.wintypes.WORD),
            ("biBitCount", ctypes.wintypes.WORD),
            ("biCompression", ctypes.wintypes.DWORD),
            ("biSizeImage", ctypes.wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.wintypes.LONG),
            ("biYPelsPerMeter", ctypes.wintypes.LONG),
            ("biClrUsed", ctypes.wintypes.DWORD),
            ("biClrImportant", ctypes.wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

    try:
        im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        im.save(str(out_path))
        print(f"Saved screenshot to {out_path} ({w}x{h})")
        return True
    finally:
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(target_hwnd, hdc_window)

capture_screenshot(hwnd, Path("artifacts/recovery/screen1_cscape.png"))
