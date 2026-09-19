# Horner Cscape 10.2 UI Automation Tree Specification

**Application**: Horner Cscape (10.2.751.4 Service Pack 3)  
**Executable**: `C:\Program Files (x86)\Cscape 10.2\Cscape.exe`  
**Architecture**: x86 (32-bit)  
**Underlying Engine**: Copa-Data Straton K5 IEC 61131-3  
**Generated**: 2026-09-03 20:24:25 by Subagent 4: UI Automation Tree Specialist  

---

## Executive Summary

This specification documents the complete UI Automation (UIA) and Win32 control hierarchy of **Horner Cscape 10.2**, captured via `pywinauto` (UIA backend) and `uiautomation` on Windows 11. It provides exact Automation IDs, Win32 Control IDs (`GetDlgCtrlID`), Class Names, Control Types, Bounding Rectangles, and deterministic automation recipes for:
1. **'About Cscape' Splash Dialog** (`#32770`) - Startup splash with version information and dismissal controls.
2. **'Select Editor Type' Dialog** (`#32770`) - Mode selection modal featuring Radio ID 1461 for IEC 61131 Language Editors.
3. **Main Cscape Application Window** (`Afx:...`) - Complete MFC Ribbon Bar, Quick Access Toolbar, Project Navigator, Project Toolbox, Straton Data Dictionary, MDI Workspace, and Status Bar.

---

## 1. 'About Cscape' Splash Dialog

- **Window Title**: `About Cscape`
- **Class Name**: `#32770` (Standard Windows Dialog Box)
- **UIA Control Type**: `Window` / `Dialog`
- **Dimensions**: `531 x 426 px` (Typical rect: `[L:374, T:143, R:905, B:569]`)
- **Behavior**: Displayed during startup before main workspace initialization. Must be dismissed to allow project creation or editing.

### Control Inventory

| Win32 ID | Automation ID | Control Type | Class Name | Text / Label | Action / Purpose |
|:---:|:---:|:---:|:---:|:---|:---|
| `1677` | `1677` | `Text` | `Static` | `Version 10.2 Service Pack 3` | Product version and service pack display |
| `1` | `1` | `Button` | `Button` | `OK` | Dismisses splash screen and advances to editor selection (default button) |
| `1680` | `1680` | `Button` | `Button` | `File Versions` | Opens detailed DLL component versions dialog |
| `-1` | `*(none)*` | `Image` | `Static` | *(empty)* | Horner Cscape splash image and copyright branding |
| `2510` | `2510` | `Button` | `Button` | *(empty)* | Hidden dialog helper button |

### Automation Recipe (Python)
```python
# Dismiss 'About Cscape' via pywinauto UIA
app = Application(backend='uia').connect(title='About Cscape', class_name='#32770')
about_dlg = app.window(title='About Cscape', class_name='#32770')
about_dlg.child_window(auto_id='1', control_type='Button').click()

# Direct Win32 BM_CLICK fallback
ok_btn = win32gui.GetDlgItem(about_hwnd, 1)
win32gui.SendMessage(ok_btn, win32con.BM_CLICK, 0, 0)
```

---

## 2. 'Select Editor Type' Dialog

- **Window Title**: `Select Editor Type`
- **Class Name**: `#32770` (Standard Windows Dialog Box)
- **UIA Control Type**: `Window` / `Dialog`
- **Dimensions**: `457 x 172 px` (Typical rect: `[L:278, T:196, R:735, B:368]`)
- **Behavior**: Modal dialog displayed after splash dismissal if no project file was passed on CLI. Prompts the user to select the programming model.

### Control Inventory

| Win32 ID | Automation ID | Control Type | Class Name | Text / Label | Action / Purpose |
|:---:|:---:|:---:|:---:|:---|:---|
| `-1` | `*(none)*` | `Text` | `Static` | `Select the type of Editor to be used for developing the program:` | Header prompt label instructing user to choose editor mode |
| `1460` | `1460` | `RadioButton` | `Button` | `Advanced Ladder with Register Based Addressing Editor` | Radio button for legacy Horner register-based ladder editor (%R, %AI, %AQ) |
| `1461` | `1461` | `RadioButton` | `Button` | `IEC 61131 Language Editors` | Radio button for Copa-Data Straton K5 IEC 61131-3 engine (ST, SFC, FBD, LD, IL) |
| `3757` | `3757` | `RadioButton` | `Button` | `Advanced Ladder with Variable Based Addressing Editor` | Radio button for variable-based tag addressing ladder editor |
| `1` | `1` | `Button` | `Button` | `OK` | Confirms editor selection and opens project workspace (default button) |
| `2` | `2` | `Button` | `Button` | `Cancel` | Cancels editor selection |

### Automation Recipe (Python)
```python
# Select IEC 61131 Language Editors and click OK
app = Application(backend='uia').connect(title='Select Editor Type', class_name='#32770')
sel_dlg = app.window(title='Select Editor Type', class_name='#32770')
sel_dlg.child_window(auto_id='1461', control_type='RadioButton').select()
sel_dlg.child_window(auto_id='1', control_type='Button').click()

# Direct Win32 BM_CLICK fallback
radio_iec = win32gui.GetDlgItem(sel_hwnd, 1461)
win32gui.SendMessage(radio_iec, win32con.BM_CLICK, 0, 0)
ok_btn = win32gui.GetDlgItem(sel_hwnd, 1)
win32gui.SendMessage(ok_btn, win32con.BM_CLICK, 0, 0)
```

---

## 3. Main Cscape Application Window

- **Window Title**: `Cscape` or `Cscape - [untitled1]`
- **Class Name**: `Afx:00BC0000:8:00010003:00000000:...` (MFC Frame Window)
- **UIA Control Type**: `Window`
- **Architecture**: Modern Ribbon UI built on MFC BCGControlBar / CMFCRibbonBar architecture hosting Copa-Data Straton K5 components.

### Major Layout Components

| Component | Win32 ID | Class Name | Description |
|:---|:---:|:---|:---|
| **Cscape** | `59398` | `Afx:RibbonBar:bc0000:8:10003:10` | MFC Ribbon Bar housing Application Menu, Quick Access Toolbar, and Tabs |
| **Project Navigator** | `45012` | `Afx:ControlBar:bc0000:8:10003:10` | Dockable tree containing hardware configuration, network, and program sections |
| **Project Toolbox** | `37567` | `Afx:ControlBar:bc0000:8:10003:10` | Dockable toolbox palette with function blocks, operators, and I/O elements |
| **Program Variables** | `38053` | `Afx:ControlBar:bc0000:8:10003:10` | Straton variable data dictionary grid and tree editor |
| **IEC Defines/SpyList/BitFields/Enums/Structs** | `38030` | `Afx:ControlBar:bc0000:8:10003:10` | IEC type definitions, data structures, and live spy list watch window |
| **IEC Debugger Windows** | `38343` | `Afx:ControlBar:bc0000:8:10003:10` | Straton execution debugger watch, call stack, and breakpoint viewer |
| **Output Window** | `45011` | `Afx:ControlBar:bc0000:8:10003:10` | Build output, compiler error messages, and link logs |
| **Bookmark Window** | `38579` | `Afx:ControlBar:bc0000:8:10003:10` | Code navigation bookmarks list |
| **Search** | `320` | `Afx:ControlBar:bc0000:8:10003:10` | Find and replace results window |
| **Workspace** | `59648` | `MDIClient` | Multiple Document Interface workspace hosting Straton IEC and ladder views |
| **Ready** | `59393` | `Afx:StatusBar:bc0000:8:10003:10` | Application status bar with target connection status, mode, and cursor coordinates |

### Ribbon Bar Structure

The Ribbon Bar (`ID: 59398`, Class `Afx:RibbonBar:...`) contains 3 primary sections:
1. **Application Menu Button**: Top-left corner application menu (File / Open / Save / Export).
2. **Quick Access Toolbar**: 28 direct one-click command buttons for rapid hardware, compile, and debug control.
3. **Ribbon Tabs**: 8 thematic tabs with categorized command panels.

#### Quick Access Toolbar Buttons
- `Save`, `Hardware Config`, `Connection Wizard`, `Connect`, `Set Target ID`, `Run`, `Do I/O`, `Stop`
- `Upload`, `Download`, `Action`, `Debug Mode`, `Error Check`, `Find`, `Start Simulation`
- `Continue`, `Complete Cycle`, `Step In`, `Step Over`, `Step Out`, `Set Breakpoint`, `Set Tracepoint`, `Remove All`
- `Enumerated Types`, `Bitfields`, `Structures`, `Cscape Log In`, `Cscape Log Out`, `Customize Quick Access Toolbar`

#### Ribbon Tabs & Categories
1. **Home Tab**:
   - **View Panel**: `Project Navigator`, `Project Toolbox`, `Output Window`, `Program Variables`, `Defines Window`
   - **Controller Panel**: `Set Target ID`, `Set Local ID`, `Connection Wizard`, `Hardware Config`, `Connect`, `Disconnect`, `Download`, `Upload`, `Verify`, `Run`, `Do I/O`, `Stop`
   - **Online Change Panel**: `Download Online Change`, `Action`
   - **Program Panel**: `Error Check`, `Error List`, `Element Usage`, `Messaging`, `Setpoints`, `Download Options`, `Protocols`, `Import L5K`, `Audio`
   - **Data Panel**: `Datalogging`, `Reports`, `Recipe Database`, `File Counters`
2. **Edit Tab**: Cut, Copy, Paste, Find, Replace, Undo, Redo.
3. **Logic Editing Tab**: Structured Text language constructs, function block insertion, rung operations.
4. **User Interface Tab**: Screen editor, graphics elements, alarms, trend graphs.
5. **Debug Tab**: Simulation runtime, single stepping, live variable monitoring, spy list.
6. **Tools Tab**: Toolchain options, compiler settings, Straton K5 diagnostics.
7. **My Account Tab**: User authentication and cloud service synchronization.
8. **Help Tab**: Documentation, About box, Horner contact support.

---

## 4. Straton K5 Engine Dockable Windows

When Cscape operates in IEC 61131 mode (`Radio 1461`), the following Straton K5 tool windows are instantiated:
- **Program Variables Window** (`ID: 38053`): Class `CProjectDatabaseWnd` (ID 355) hosting `W5EditTL` (ID 1603, `CW5EditTLWnd_Dico`). Contains a tree view (`SysTreeView32`, ID 1001) for navigating global variables, retain variables, and I/O tags.
- **Project Navigator** (`ID: 45012`): Class `SysTreeView32` (ID 300). Organizes the project hierarchy: Controller, I/O Configuration, Network Configuration, Logic Programs (Structured Text programs, Function Blocks), and Data Types.
- **Project Toolbox** (`ID: 37567`): Class `CProjectToolboxWnd` (ID 310). Provides a drag-and-drop or clickable catalog of IEC 61131-3 standard functions (timers `TON`/`TOF`, counters `CTU`/`CTD`, math, string operations) and Horner-specific hardware blocks.
- **Output Window** (`ID: 45011`): Class `ListBox` (ID 372). Captures compiler messages from `K5Cmp.dll` and linking status from `K5CmpPost.dll`.

---

## 5. UI Automation Tree Excerpt (JSON Structure)

Below is an excerpt showing the top-level structure in `cscape_uia_tree.json`:
```json
{
  "metadata": {
    "application": "Horner Cscape",
    "version": "10.2.751.4 Service Pack 3",
    "executable_path": "C:\\Program Files (x86)\\Cscape 10.2\\Cscape.exe",
    "architecture": "x86 (32-bit)",
    "pid": 3868,
    "timestamp": "2026-09-03 20:24:25",
    "toolchain": "Horner Cscape 10.2 + Copa-Data Straton K5",
    "author": "Subagent 4: UI Automation Tree Specialist",
    "description": "Complete UI Automation hierarchy and control inventory for Horner Cscape 10.2"
  },
  "windows": {
    "about_cscape_dialog": {
      "name": "About Cscape",
      "class_name": "#32770",
      "control_type": "Window",
      "children_count": 5
    },
    "select_editor_type_dialog": {
      "name": "Select Editor Type",
      "class_name": "#32770",
      "control_type": "Window",
      "children_count": 7
    },
    "main_cscape_window": {
      "name": "Cscape - [untitled1]",
      "class_name": "Afx:00BC0000:8:00010003:00000000:004B052D",
      "control_type": "Window",
      "children_count": 8
    }
  }
}
```

---

## 6. Safety & Non-Interference Guidelines

> [!CAUTION]
> **Hardware Safety Directives**: The Quick Access Toolbar and Home Ribbon contain `Download`, `Connect`, and `Run` buttons. Automated test scripts MUST NOT trigger these buttons against physical hardware. The MCP server operates exclusively in offline simulation or headless toolchain compilation mode.

1. **Headless Execution**: CLI and compiler operations should invoke `K5Cmp.dll` or headless CLI execution with `CREATE_NO_WINDOW` and `SW_HIDE`.
2. **Dialog Dismissal**: When GUI automation is required, automated drivers must proactively check for `#32770` dialogs (About Cscape, Select Editor Type) and dismiss them programmatically using the Control IDs cataloged herein.
