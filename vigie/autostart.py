"""Lancement automatique à l'ouverture de session (Windows et macOS)."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

LABEL = "fr.vigie.freebox"


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimise"]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "main.py"), "--minimise"]


def supported() -> bool:
    return sys.platform.startswith("win") or sys.platform == "darwin"


def is_enabled() -> bool:
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "VigieFreebox")
                return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()
    return False


def set_enabled(on: bool):
    if sys.platform.startswith("win"):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                cmd = " ".join(f'"{c}"' if " " in c else c for c in _command())
                winreg.SetValueEx(k, "VigieFreebox", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, "VigieFreebox")
                except OSError:
                    pass
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "wb") as f:
                plistlib.dump({"Label": LABEL, "ProgramArguments": _command(), "RunAtLoad": True}, f)
        elif p.exists():
            os.remove(p)
