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

# Toolbar HWND
tb_hwnd = 0x343067C

TB_BUTTONCOUNT = 0x0418
TB_GETBUTTON = 0x0417

hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 1024, 0x1000, 0x04)

btn_count = user32.SendMessageW(tb_hwnd, TB_BUTTONCOUNT, 0, 0)
print(f"Toolbar button count: {btn_count}")

# In 32-bit: TBBUTTON is 20 bytes: iBitmap(4), idCommand(4), fsState(1), fsStyle(1), bReserved(2), dwData(4), iString(4)
for i in range(btn_count):
    res = user32.SendMessageW(tb_hwnd, TB_GETBUTTON, i, remote_buf)
    data = ctypes.create_string_buffer(20)
    kernel32.ReadProcessMemory(hproc, remote_buf, data, 20, None)
    iBitmap, idCommand, fsState, fsStyle, bRes, dwData, iString = struct.unpack("<iiBBhII", data.raw)
    print(f"  Button {i}: idCommand={idCommand}, state=0x{fsState:X}, style=0x{fsStyle:X}, str_idx={iString}")

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)

# Also check child windows of HornerAPGTabbedGraphicsEditor
editor_hwnd = 0xA508C2
def enum_direct(p):
    res = []
    def cb(h, _):
        if user32.GetParent(h) == p:
            res.append(h)
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(p, WNDENUM(cb), 0)
    return res

print("=== Editor Direct Children ===")
for ch in enum_direct(editor_hwnd):
    tc = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ch, tc, 256)
    tt = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(ch, tt, 512)
    vis = bool(user32.IsWindowVisible(ch))
    cid = user32.GetDlgCtrlID(ch)
    print(f"  Child: 0x{ch:X} Class='{tc.value}' Title='{tt.value}' ID={cid} Vis={vis}")
