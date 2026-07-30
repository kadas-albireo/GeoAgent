#!/usr/bin/env python3
"""Screen capture for benchmark runs, with a fallback chain.

Naming: ``runs/screenshots/[timestamp]_[agent]_[test_id]_[difficulty].png``

**Why Qt first, not pyautogui.** The eval runner executes *inside* KADAS, so Qt is already
loaded and ``QScreen.grabWindow(winId)`` is strictly better than an external grabber:

- it captures the KADAS window specifically, not whatever is on top;
- it works when the window is partially occluded or off-screen;
- it needs no X11/Wayland screen-capture permission. On Wayland, ``pyautogui``/``mss``
  typically return a black frame or fail outright, because the compositor forbids
  arbitrary screen reads. That failure is silent and would quietly ruin a whole sweep.
- it adds no dependency (``pyautogui``, ``mss`` and ``pillow`` are all absent from the
  py3.12 venv as of 2026-07-16).

The chain degrades: Qt window -> Qt full screen -> mss -> pyautogui -> None. Capture must
never abort a benchmark; a missing screenshot is logged as None and the run continues.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "runs" / "screenshots"


def _slug(text: str) -> str:
    """Return a filename-safe fragment."""
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text).strip()).strip("-") or "x"


def screenshot_path(
    agent_name: str,
    test_id: str,
    difficulty: str,
    *,
    directory: Path | None = None,
    when: datetime | None = None,
) -> Path:
    """Build the conventional screenshot path.

    >>> screenshot_path("claude", "E01", "easy").name.split("_")[1:]
    ['claude', 'E01', 'easy.png']
    """
    base = directory or Path(
        os.environ.get("LOCAL_AGENT_SCREENSHOT_DIR", SCREENSHOT_DIR)
    )
    stamp = (when or datetime.now()).strftime("%Y%m%dT%H%M%S")
    name = f"{stamp}_{_slug(agent_name)}_{_slug(test_id)}_{_slug(difficulty)}.png"
    return base / name


def is_headless() -> bool:
    """True when there is no display server to capture from."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return True
    if os.name == "nt" or sys_platform_is_darwin():
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def sys_platform_is_darwin() -> bool:
    """True on macOS."""
    import sys

    return sys.platform == "darwin"


def _grab_qt(target: Any, out: Path) -> bool:
    """Capture *target* (a QWidget) or the primary screen via Qt. True on success."""
    try:
        from qgis.PyQt.QtWidgets import QApplication
    except ImportError:
        try:
            from PyQt6.QtWidgets import QApplication  # type: ignore
        except ImportError:
            return False

    app = QApplication.instance()
    if app is None:
        return False

    try:
        if target is not None and hasattr(target, "grab"):
            # Widget-level grab: exact window, occlusion-proof.
            pixmap = target.grab()
        else:
            screen = app.primaryScreen()
            if screen is None:
                return False
            # winId 0 grabs the whole desktop (incl. any open modal dialogs).
            pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            return False
        return bool(pixmap.save(str(out), "PNG"))
    except Exception:
        return False


def _grab_mss(out: Path) -> bool:
    """Capture the primary monitor via mss. True on success."""
    try:
        import mss
        import mss.tools
    except ImportError:
        return False
    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            mss.tools.to_png(shot.rgb, shot.size, output=str(out))
        return out.exists()
    except Exception:
        return False


def _grab_pyautogui(out: Path) -> bool:
    """Capture via pyautogui. Last resort: black frames on Wayland."""
    try:
        import pyautogui
    except ImportError:
        return False
    try:
        pyautogui.screenshot().save(str(out))
        return out.exists()
    except Exception:
        return False


def capture(
    agent_name: str,
    test_id: str,
    difficulty: str,
    *,
    window: Any = None,
    directory: Path | None = None,
) -> Path | None:
    """Capture a screenshot for one benchmark step.

    Args:
        window: The KADAS main window (a QWidget). Strongly preferred -- grabbing it
            directly is the only reliable option under Wayland. When None, falls back to
            a full-desktop grab.

    Returns:
        The path written, or None if every backend failed (headless CI, no permission).
        Never raises: a failed capture must not abort a benchmark sweep.
    """
    out = screenshot_path(agent_name, test_id, difficulty, directory=directory)
    out.parent.mkdir(parents=True, exist_ok=True)

    if is_headless():
        return None

    for backend in (
        lambda: _grab_qt(window, out),
        lambda: _grab_mss(out),
        lambda: _grab_pyautogui(out),
    ):
        try:
            if backend():
                return out
        except Exception:
            continue
    return None


def find_kadas_window() -> Any:
    """Return the KADAS/QGIS main window, or None.

    Looks for the top-level widget that owns the application, so callers inside KADAS do
    not have to plumb ``iface.mainWindow()`` through by hand.
    """
    try:
        from qgis.PyQt.QtWidgets import QApplication
    except ImportError:
        return None
    app = QApplication.instance()
    if app is None:
        return None
    for widget in app.topLevelWidgets():
        if widget.isWindow() and widget.isVisible() and widget.width() > 400:
            return widget
    return None


if __name__ == "__main__":
    path = capture("manual-test", "T00", "easy")
    print(f"headless={is_headless()}  wrote={path}")
