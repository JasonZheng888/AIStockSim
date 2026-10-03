"""Window persistence tests without user configuration, workers or UI focus."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QObject, QPoint, QRect
from PySide6.QtWidgets import QApplication

import StockTradingSim as sim
from window_state import MainWindowState, bounded_geometry, capture_window_state, normalized_state


SCREEN = QRect(0, 0, 1920, 1080)


class FakeWindow(QObject):
    """Expose native state transitions without opening another desktop window."""
    def __init__(self):
        super().__init__()
        self.rect = QRect(100, 80, 1000, 700)
        self.normal_rect = QRect(self.rect)
        self.visible = False
        self.minimized = False
        self.mode = "normal"

    def geometry(self): return QRect(self.rect)
    def normalGeometry(self): return QRect(self.normal_rect)
    def frameGeometry(self): return QRect(self.rect)
    def isVisible(self): return self.visible
    def isMinimized(self): return self.minimized
    def isFullScreen(self): return self.mode == "fullscreen"
    def isMaximized(self): return self.mode == "maximized"
    def width(self): return self.rect.width()
    def height(self): return self.rect.height()
    def pos(self): return self.rect.topLeft()

    def setGeometry(self, x, y, width, height):
        self.rect = QRect(x, y, width, height)
        self.normal_rect = QRect(self.rect)

    def resize(self, width, height):
        self.rect.setWidth(width)
        self.rect.setHeight(height)
        self.normal_rect = QRect(self.rect)

    def move(self, point):
        self.rect.moveTopLeft(point)
        self.normal_rect = QRect(self.rect)

    def showNormal(self):
        self.visible, self.mode = True, "normal"
        self.rect = QRect(self.normal_rect)

    def showMaximized(self):
        self.visible, self.mode = True, "maximized"
        self.rect = QRect(SCREEN)

    def showFullScreen(self):
        self.visible, self.mode = True, "fullscreen"
        self.rect = QRect(SCREEN)


class MainWindowStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["main-window-state-tests"])

    def saved(self, mode="normal", x=100, y=80, width=1000, height=700):
        return {"version": 1, "mode": mode, "geometry": {"x": x, "y": y, "width": width, "height": height}}

    def test_normal_size_and_position_survive_round_trip(self):
        saved = self.saved(x=220, y=160, width=1150, height=810)
        window = FakeWindow()
        with patch("window_state.available_screen_rects", return_value=[SCREEN]), patch("window_state.QTimer.singleShot"):
            controller = MainWindowState(window, saved)
            controller.show_restored()
            controller._finish_restore()
            self.assertEqual(controller.snapshot(), saved)

    def test_maximized_and_fullscreen_restore_mode_and_normal_rectangle(self):
        for mode in ("maximized", "fullscreen"):
            with self.subTest(mode=mode), patch("window_state.available_screen_rects", return_value=[SCREEN]), \
                 patch("window_state.QTimer.singleShot"):
                saved = self.saved(mode=mode, width=1060, height=760)
                window = FakeWindow()
                controller = MainWindowState(window, saved)
                controller.show_restored()
                controller._finish_restore()
                self.assertEqual(window.mode, mode)
                self.assertEqual(controller.snapshot(), saved)
                self.assertEqual(window.geometry(), SCREEN)
                self.assertEqual(window.normalGeometry(), QRect(100, 80, 1060, 760))

    def test_tray_hidden_window_does_not_overwrite_last_visible_geometry(self):
        window = FakeWindow()
        with patch("window_state.available_screen_rects", return_value=[SCREEN]):
            controller = MainWindowState(window, self.saved())
            window.visible = True
            window.setGeometry(150, 120, 1200, 800)
            controller.eventFilter(window, QEvent(QEvent.Resize))
            expected = controller.snapshot()
            window.visible = False
            window.rect = QRect(0, 0, 1, 1)
            controller.eventFilter(window, QEvent(QEvent.Resize))
            self.assertEqual(controller.snapshot(), expected)

    def test_minimizing_keeps_last_maximized_launch_mode(self):
        previous = self.saved(mode="maximized")
        window = FakeWindow()
        window.visible, window.minimized = True, True
        self.assertEqual(capture_window_state(window, previous), previous)

    def test_removed_monitor_recenters_and_clamps_to_primary_work_area(self):
        rect = bounded_geometry(QRect(2600, -200, 2500, 1400), [SCREEN])
        self.assertTrue(SCREEN.adjusted(12, 12, -12, -12).contains(rect))
        self.assertEqual(rect.size(), SCREEN.adjusted(12, 12, -12, -12).size())

    def test_negative_coordinate_second_monitor_is_retained(self):
        secondary = QRect(-1600, 0, 1600, 1000)
        saved_rect = QRect(-1450, 80, 1000, 700)
        self.assertEqual(bounded_geometry(saved_rect, [SCREEN, secondary]), saved_rect)

    def test_malformed_saved_values_fall_back_to_reachable_normal_geometry(self):
        state = normalized_state({"mode": "minimized", "geometry": {"x": "bad", "height": -1}}, QRect(50, 60, 900, 650), [SCREEN])
        self.assertEqual(state["mode"], "normal")
        self.assertEqual(state["geometry"], {"x": 50, "y": 60, "width": 900, "height": 650})

    def test_window_state_is_saved_to_the_store_without_touching_other_settings(self):
        saved = self.saved(mode="fullscreen")
        store = SimpleNamespace(data={"cash": 12345}, save=Mock())
        owner = SimpleNamespace(store=store, _main_window_state=SimpleNamespace(snapshot=lambda: saved))
        sim.MainWindow.save_main_window_state(owner)
        self.assertEqual(store.data, {"cash": 12345, "main_window": saved})
        store.save.assert_called_once_with()

    def test_close_button_uses_guarded_quit_path(self):
        event = Mock()
        owner = SimpleNamespace(quit_app=Mock())
        sim.MainWindow.closeEvent(owner, event)
        event.ignore.assert_called_once_with()
        owner.quit_app.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
