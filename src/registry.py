"""
Windows Registry Shell Context Menu Manager.
Installs and removes 'Merge into PDF' context menu entries in Explorer for current user.
Does NOT require Administrator privileges!
"""

import sys
import os
import winreg
from typing import Optional

VERB_NAME = "PDFMerger"
DISPLAY_NAME_FILES = "Объединить в PDF..."
DISPLAY_NAME_FOLDER = "Объединить файлы в папке в PDF..."


def get_default_command(exe_or_script_path: Optional[str] = None) -> tuple[str, str, str]:
    """
    Returns (command_format_files, icon_path, command_format_folder)
    Detects whether we are running as a frozen executable (PyInstaller)
    or as a Python script.
    """
    if exe_or_script_path is None:
        if getattr(sys, 'frozen', False):
            # Running as compiled binary
            exe_path = os.path.abspath(sys.executable)
            icon_path = exe_path
            cmd_files = f'"{exe_path}" "%1"'
            cmd_folder = f'"{exe_path}" "%V"'
            return cmd_files, icon_path, cmd_folder
        else:
            # Running as Python script
            # Locate pythonw.exe to avoid flashing console
            py_dir = os.path.dirname(sys.executable)
            pythonw = os.path.join(py_dir, "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
                
            script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(project_dir, "assets", "app_icon.ico")
            
            cmd_files = f'"{pythonw}" "{script_path}" "%1"'
            cmd_folder = f'"{pythonw}" "{script_path}" "%V"'
            return cmd_files, icon_path, cmd_folder
    else:
        # Custom path provided
        abs_p = os.path.abspath(exe_or_script_path)
        if abs_p.lower().endswith('.exe'):
            cmd_files = f'"{abs_p}" "%1"'
            cmd_folder = f'"{abs_p}" "%V"'
            icon_path = abs_p
        else:
            py_dir = os.path.dirname(sys.executable)
            pythonw = os.path.join(py_dir, "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(project_dir, "assets", "app_icon.ico")
            cmd_files = f'"{pythonw}" "{abs_p}" "%1"'
            cmd_folder = f'"{pythonw}" "{abs_p}" "%V"'
        return cmd_files, icon_path, cmd_folder


def install_context_menu(target_path: Optional[str] = None) -> bool:
    """
    Installs context menu entries under HKCU\\Software\\Classes:
    - for all files (*)
    - for folders (Directory)
    - for folder background (Directory\\Background)
    """
    cmd_files, icon_path, cmd_folder = get_default_command(target_path)
    
    entries = [
        (f"Software\\Classes\\*\\shell\\{VERB_NAME}", DISPLAY_NAME_FILES, cmd_files, True),
        (f"Software\\Classes\\Directory\\shell\\{VERB_NAME}", DISPLAY_NAME_FOLDER, cmd_folder, False),
        (f"Software\\Classes\\Directory\\Background\\shell\\{VERB_NAME}", DISPLAY_NAME_FOLDER, cmd_folder, False),
    ]
    
    for subkey_path, title, cmd, is_multi in entries:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, title)
                if os.path.exists(icon_path):
                    winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
                if is_multi:
                    # 'Player' instructs Windows Explorer to pass multi-selected files together
                    winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
                    
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{subkey_path}\\command") as cmd_key:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
        except Exception as e:
            print(f"Error registering {subkey_path}: {e}")
            return False
            
    return True


def uninstall_context_menu() -> bool:
    """Removes all PDFMerger context menu entries from HKCU."""
    keys_to_delete = [
        f"Software\\Classes\\*\\shell\\{VERB_NAME}\\command",
        f"Software\\Classes\\*\\shell\\{VERB_NAME}",
        f"Software\\Classes\\Directory\\shell\\{VERB_NAME}\\command",
        f"Software\\Classes\\Directory\\shell\\{VERB_NAME}",
        f"Software\\Classes\\Directory\\Background\\shell\\{VERB_NAME}\\command",
        f"Software\\Classes\\Directory\\Background\\shell\\{VERB_NAME}",
    ]
    
    for k in keys_to_delete:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
        except FileNotFoundError:
            pass
        except Exception:
            pass
            
    return True


def is_context_menu_installed() -> bool:
    """Checks if the context menu verb is currently registered in HKCU."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"Software\\Classes\\*\\shell\\{VERB_NAME}"):
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
