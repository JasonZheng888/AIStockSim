"""Remember the main window's normal rectangle and visible display mode."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer
from PySide6.QtGui import QGuiApplication


def available_screen_rects() -> list[QRect]:
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    ordered = ([primary] if primary else []) + [screen for screen in screens if screen != primary]
    return [screen.availableGeometry() for screen in ordered]


def bounded_geometry(rect: QRect, screens: list[QRect]) -> QRect:
    """Keep the full normal rectangle visible, including after monitor removal."""
    if not screens:
        return QRect(rect)
    areas = [rect.intersected(screen).width() * rect.intersected(screen).height()
             if rect.intersects(screen) else 0 for screen in screens]
    best = max(range(len(screens)), key=lambda index: areas[index])
    bounds = screens[best].adjusted(12, 12, -12, -12)
    width = min(max(1, rect.width()), max(1, bounds.width()))
    height = min(max(1, rect.height()), max(1, bounds.height()))
    if areas[best] == 0:
        x = bounds.x() + (bounds.width() - width) // 2
        y = bounds.y() + (bounds.height() - height) // 2
    else:
        x = min(max(rect.x(), bounds.left()), bounds.right() - width + 1)
        y = min(max(rect.y(), bounds.top()), bounds.bottom() - height + 1)
    return QRect(x, y, width, height)


def normalized_state(saved, fallback: QRect, screens: list[QRect]) -> dict:
    mode = "normal"
    rect = QRect(fallback)
    if isinstance(saved, dict):
        raw = saved.get("geometry")
        if isinstance(raw, dict):
            try:
                x, y, width, height = (int(raw[key]) for key in ("x", "y", "width", "height"))
                if width > 0 and height > 0 and all(abs(value) < 10_000_000 for value in (x, y, width, height)):
                    rect = QRect(x, y, width, height)
            except (KeyError, ValueError, TypeError, OverflowError):
                pass
        if saved.get("mode") in ("normal", "maximized", "fullscreen"):
            mode = saved["mode"]
    rect = bounded_geometry(rect, screens)
    return {"version": 1, "mode": mode,
            "geometry": {"x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height()}}


def capture_window_state(window, previous: dict) -> dict:
    # Tray hiding and minimising are temporary visibility changes, not a new
    # preferred launch size. The event filter already cached the visible state.
    if not window.isVisible() or window.isMinimized():
        return deepcopy(previous)
    mode = "fullscreen" if window.isFullScreen() else "maximized" if window.isMaximized() else "normal"
    rect = window.normalGeometry() if mode != "normal" else window.geometry()
    if not rect.isValid():
        return deepcopy(previous)
    return {"version": 1, "mode": mode,
            "geometry": {"x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height()}}


class MainWindowState(QObject):
    def __init__(self, window, saved=None):
        super().__init__(window)
        self.window = window
        self.state = normalized_state(saved, window.geometry(), available_screen_rects())
        self.restoring = False
        window.installEventFilter(self)

    def snapshot(self) -> dict:
        if not self.restoring:
            self.state = capture_window_state(self.window, self.state)
        return deepcopy(self.state)

    def eventFilter(self, watched, event):
        if not self.restoring and event.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange, QEvent.Show):
            self.state = capture_window_state(self.window, self.state)
        return super().eventFilter(watched, event)

    def show_restored(self) -> None:
        self.restoring = True
        self.state = normalized_state(self.state, self.window.geometry(), available_screen_rects())
        geometry = self.state["geometry"]
        self.window.setGeometry(geometry["x"], geometry["y"], geometry["width"], geometry["height"])
        mode = self.state["mode"]
        if mode == "fullscreen":
            self.window.showFullScreen()
        elif mode == "maximized":
            self.window.showMaximized()
        else:
            self.window.showNormal()
        QTimer.singleShot(0, self._finish_restore)

    def _finish_restore(self) -> None:
        # Native frame margins are available only after show. Correct the outer
        # frame as well so that the title bar remains reachable at high DPI.
        if self.state["mode"] == "normal" and self.window.isVisible():
            frame = self.window.frameGeometry()
            target = bounded_geometry(frame, available_screen_rects())
            extra_width = max(0, frame.width() - self.window.width())
            extra_height = max(0, frame.height() - self.window.height())
            self.window.resize(max(1, target.width() - extra_width), max(1, target.height() - extra_height))
            frame = self.window.frameGeometry()
            target = bounded_geometry(frame, available_screen_rects())
            self.window.move(self.window.pos() + QPoint(target.x() - frame.x(), target.y() - frame.y()))
        self.restoring = False
        self.state = capture_window_state(self.window, self.state)
