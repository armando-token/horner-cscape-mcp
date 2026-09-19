import ctypes
import ctypes.wintypes
import json
from pathlib import Path
import time
from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = Path("artifacts/.cscape_live_gate.json")
with open(gate_path) as f:
    gate = json.load(f)
main_hwnd = int(gate["hwnd"], 16)
pid = gate["pid"]

print(f"Target Cscape PID={pid}, HWND=0x{main_hwnd:08X}")

# 1. Bring Cscape to foreground
user32.ShowWindow(main_hwnd, 9)
user32.SetForegroundWindow(main_hwnd)
user32.BringWindowToTop(main_hwnd)
time.sleep(0.5)

# 2. Dispatch Error Check (ID_PROGRAM_ERRORCHECK = 32826)
ID_PROGRAM_ERRORCHECK = 32826
print(f"Dispatching WM_COMMAND ID_PROGRAM_ERRORCHECK ({ID_PROGRAM_ERRORCHECK})...")
user32.PostMessageW(main_hwnd, 0x0111, ID_PROGRAM_ERRORCHECK, 0)

# 3. Monitor for compilation modal dialogs
time.sleep(1.5)

modals_detected = []
modal_action = "none"

def check_modals():
    found = []
    def cb(h, _):
        if user32.IsWindowVisible(h):
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, c, 256)
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, t, 512)
            if c.value == "#32770":
                # Check controls
                ctrl_texts = []
                def ccb(ch, _):
                    ct = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(ch, ct, 512)
                    cid = user32.GetDlgCtrlID(ch)
                    if ct.value.strip():
                        ctrl_texts.append(f"[ID {cid}] {ct.value.strip()}")
                    return 1
                WNDENUMCHILD = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
                user32.EnumChildWindows(h, WNDENUMCHILD(ccb), 0)
                found.append((h, t.value, ctrl_texts))
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUM(cb), 0)
    return found

for check_i in range(5):
    modals = check_modals()
    for mh, mt, mtexts in modals:
        combined = f"{mt} {' '.join(mtexts)}".lower()
        print(f"Intercepted modal 0x{mh:X}: title='{mt}', controls={mtexts}")
        modals_detected.append({"hwnd": f"0x{mh:X}", "title": mt, "controls": mtexts})
        if "non-fatal" in combined or "continue" in combined:
            print("NON-FATAL DIALOG DETECTED. STRICT BAN ON YES: Dismissing with IDNO (7)...")
            user32.PostMessageW(mh, 0x0111, 7, 0)
            modal_action = "Dismissed with IDNO (7) per fail-closed policy (Do not click Yes)"
        elif "no error" in combined or "clean" in combined or "0 error" in combined or "cscape" in mt.lower():
            # Check if there is an OK button (ID 1)
            has_ok = any("[ID 1]" in t or "ok" in t.lower() for t in mtexts)
            if has_ok:
                print("Clean compilation modal: Dismissing with OK (ID 1)...")
                user32.PostMessageW(mh, 0x0111, 1, 0)
                modal_action = "Dismissed with OK (1) - clean compile result"
            else:
                user32.PostMessageW(mh, 0x0111, 2, 0) # Cancel
                modal_action = "Dismissed foreign modal with Cancel"
    time.sleep(0.5)

# 4. Scrape Output Window ListBox
# Find Output Window (ID 45011) and ListBox (ID 372)
lb_hwnd = None
def find_lb(h, _):
    global lb_hwnd
    cid = user32.GetDlgCtrlID(h)
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if cid == 372 or "listbox" in c.value.lower():
        lb_hwnd = h
        return 0
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(find_lb), 0)

output_lines = []
if lb_hwnd:
    LB_GETCOUNT = 0x018B
    LB_GETTEXTLEN = 0x018A
    LB_GETTEXT = 0x0189
    cnt = user32.SendMessageW(lb_hwnd, LB_GETCOUNT, 0, 0)
    print(f"Output ListBox HWND=0x{lb_hwnd:X}, count={cnt}")
    for i in range(cnt):
        tlen = user32.SendMessageW(lb_hwnd, LB_GETTEXTLEN, i, 0)
        buf = ctypes.create_unicode_buffer(tlen + 1)
        user32.SendMessageW(lb_hwnd, LB_GETTEXT, i, ctypes.cast(buf, ctypes.c_void_p))
        output_lines.append(buf.value.strip())
        print(f"  [Line {i+1:02d}] {buf.value.strip()}")
else:
    print("Output ListBox control 372 not directly located in child tree.")

# 5. Capture screenshot
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
        print(f"Saved screenshot: {out_path} ({w}x{h})")
        return True
    finally:
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(target_hwnd, hdc_window)

shot_path = Path("artifacts/recovery/W04_screen1_fixed_compile.png")
capture_screenshot(main_hwnd, shot_path)

# 6. Record compile evidence data to JSON
compile_evidence = {
    "mission_id": "W04_FIX_EMPTY_SCREEN1_AND_ONE_G1",
    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "pid": pid,
    "hwnd": f"0x{main_hwnd:08X}",
    "project_file": str(gate.get("project_file")),
    "command_id": ID_PROGRAM_ERRORCHECK,
    "command_name": "ID_PROGRAM_ERRORCHECK",
    "modals_detected": modals_detected,
    "modal_action": modal_action,
    "scraped_output_lines": output_lines,
    "has_screen1_empty_warning": any("Screen set as first screen is empty" in l for l in output_lines),
    "clean_compile": any("No error detected" in l for l in output_lines) and not any("Warn" in l or "Error" in l for l in output_lines),
}

with open("artifacts/recovery/W04_compile_evidence.json", "w", encoding="utf-8") as f:
    json.dump(compile_evidence, f, indent=2)

print("Saved compile evidence to artifacts/recovery/W04_compile_evidence.json")
