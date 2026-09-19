import ctypes
import json
import struct

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = "artifacts/.cscape_live_gate.json"
with open(gate_path) as f:
    gate = json.load(f)
pid = gate["pid"]
main_hwnd = int(gate["hwnd"], 16)

hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)

toolbars = []
def cb(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "toolbarwindow32" in c.value.lower():
        vis = bool(user32.IsWindowVisible(h))
        cid = user32.GetDlgCtrlID(h)
        toolbars.append((h, cid, vis))
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(cb), 0)

TB_BUTTONCOUNT = 0x0418
TB_GETBUTTON = 0x0417
TB_GETBUTTONTEXTW = 0x044B

for tbhwnd, cid, vis in toolbars:
    count = user32.SendMessageW(tbhwnd, TB_BUTTONCOUNT, 0, 0)
    print(f"\nToolbar HWND 0x{tbhwnd:X}, ID={cid}, Vis={vis}, ButtonCount={count}")
    for i in range(count):
        user32.SendMessageW(tbhwnd, TB_GETBUTTON, i, remote_buf)
        data = ctypes.create_string_buffer(20)
        kernel32.ReadProcessMemory(hproc, remote_buf, data, 20, None)
        iBitmap, idCommand, fsState, fsStyle, bRes, dwData, iString = struct.unpack("<iiBBhII", data.raw)
        
        # Try getting button text
        tlen = user32.SendMessageW(tbhwnd, TB_GETBUTTONTEXTW, idCommand, 0)
        btn_text = ""
        if tlen > 0:
            text_buf = ctypes.create_unicode_buffer(tlen + 1)
            user32.SendMessageW(tbhwnd, TB_GETBUTTONTEXTW, idCommand, ctypes.cast(text_buf, ctypes.c_void_p))
            btn_text = text_buf.value
        print(f"  [{i}] ID={idCommand} state=0x{fsState:X} style=0x{fsStyle:X} text='{btn_text}'")

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)
