r"""Settings-window placement regressions without application data or workers.

Run with: .venv\Scripts\python.exe -m unittest discover -s tests -v
Only the small dialogs constructed here are shown, without requesting focus.
"""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

if os.name != "nt" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget, QVBoxLayout, QWidget

from app_theme import configure_light_theme
from StockTradingSim import MainSettingsDialog, MainWindow


class FakeScreen:
    def __init__(self, available):
        self.available = QRect(available)

    def availableGeometry(self):
        return QRect(self.available)


class MinimalSettingsDialog(MainSettingsDialog):
    """Exercise production placement/show methods without legacy constructors."""

    def __init__(self):
        QDialog.__init__(self)
        self.setWindowTitle("AIStockSim placement regression test")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(QWidget(), "Small")
        self.tabs.addTab(QWidget(), "Large")
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tab_sizes = {0: QSize(260, 180), 1: QSize(620, 560)}
        self.tabs.currentChanged.connect(self._apply_tab_size)
        self._apply_tab_size(0)


class SettingsPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["placement-regression-tests"])
        configure_light_theme(cls.app)

    def setUp(self):
        self.dialog = MinimalSettingsDialog()
        self.dialog.show()
        self.settle()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def settle(self):
        # Native frame measurements and the singleShot(0) correction must both
        # have run before inspecting the outer frame, rather than its client area.
        self.app.processEvents()
        QTest.qWait(20)
        self.app.processEvents()

    def realBounds(self):
        return self.dialog._placement_screen().availableGeometry()

    def moveFrameTo(self, point):
        displacement = point - self.dialog.frameGeometry().topLeft()
        self.dialog.move(self.dialog.pos() + displacement)
        self.settle()

    def assertFrameContained(self, bounds):
        frame = self.dialog.frameGeometry()
        self.assertTrue(bounds.contains(frame),
                        f"Outer frame {frame.getRect()} escapes {bounds.getRect()}")
        self.assertGreater(self.dialog.width(), 0)
        self.assertGreater(self.dialog.height(), 0)

    def assertCentered(self, bounds):
        difference = self.dialog.frameGeometry().center() - bounds.center()
        self.assertLessEqual(abs(difference.x()), 2)
        self.assertLessEqual(abs(difference.y()), 2)

    def test_switching_to_larger_tab_at_bottom_right_keeps_entire_frame_visible(self):
        bounds = self.realBounds()
        small_frame = self.dialog.frameGeometry()
        self.moveFrameTo(QPoint(bounds.right() - small_frame.width() - 16,
                               bounds.bottom() - small_frame.height() - 16))
        before = self.dialog.frameGeometry()
        self.assertFrameContained(bounds)
        self.dialog.tabs.setCurrentIndex(1)
        self.settle()
        self.assertGreater(self.dialog.width(), small_frame.width())
        self.assertFrameContained(bounds)
        self.assertLess(self.dialog.frameGeometry().left(), before.left())
        self.assertLess(self.dialog.frameGeometry().top(), before.top())

    def test_title_bar_above_work_area_is_recovered(self):
        bounds = self.realBounds()
        frame = self.dialog.frameGeometry()
        self.moveFrameTo(QPoint(frame.left(), bounds.top() - 30))
        self.assertLess(self.dialog.frameGeometry().top(), bounds.top())
        self.dialog.ensure_on_screen()
        self.settle()
        self.assertFrameContained(bounds)

    def test_fully_offscreen_window_is_recentered(self):
        bounds = self.realBounds()
        self.moveFrameTo(QPoint(bounds.right() + 200, bounds.bottom() + 200))
        self.assertFalse(self.dialog.frameGeometry().intersects(bounds))
        self.dialog.ensure_on_screen()
        self.settle()
        self.assertFrameContained(bounds)
        self.assertCentered(bounds)

    def test_visible_window_keeps_user_position(self):
        bounds = self.realBounds()
        self.moveFrameTo(bounds.topLeft() + QPoint(70, 75))
        before = QRect(self.dialog.frameGeometry())
        self.dialog.ensure_on_screen()
        self.settle()
        self.assertEqual(self.dialog.frameGeometry(), before)

    def test_negative_coordinate_monitor_is_supported(self):
        bounds = QRect(-960, -180, 820, 680)
        with patch.object(self.dialog, "_placement_screen", return_value=FakeScreen(bounds)):
            self.moveFrameTo(bounds.topLeft() + QPoint(45, 45))
            self.dialog.tabs.setCurrentIndex(1)
            self.settle()
            self.assertFrameContained(bounds)
            self.assertLess(self.dialog.frameGeometry().right(), 0)
            # A fully lost dialog should recover on that monitor, not primary.
            self.moveFrameTo(QPoint(bounds.right() + 200, bounds.bottom() + 200))
            self.dialog.ensure_on_screen()
            self.settle()
            self.assertFrameContained(bounds)
            self.assertCentered(bounds)

    def test_small_logical_work_area_reduces_client_size_to_fit_frame(self):
        actual = self.realBounds()
        bounds = QRect(actual.topLeft() + QPoint(30, 30), QSize(400, 310))
        with patch.object(self.dialog, "_placement_screen", return_value=FakeScreen(bounds)):
            self.dialog.tabs.setCurrentIndex(1)
            self.settle()
            self.assertFrameContained(bounds)
            self.assertLess(self.dialog.width(), self.dialog.tab_sizes[1].width())
            self.assertLess(self.dialog.height(), self.dialog.tab_sizes[1].height())

    def test_open_existing_settings_recovers_window_without_recreating_it(self):
        bounds = self.realBounds()
        self.moveFrameTo(QPoint(bounds.right() + 200, bounds.bottom() + 200))
        owner = SimpleNamespace(_settings_dialog=self.dialog, compact_window=None,
                                ensure_compact_window=Mock())
        with patch("StockTradingSim.MainSettingsDialog") as constructor, \
                patch.object(self.dialog, "ensure_on_screen",
                             wraps=self.dialog.ensure_on_screen) as ensure, \
                patch.object(self.dialog, "raise_") as raise_dialog, \
                patch.object(self.dialog, "activateWindow") as activate:
            MainWindow.open_main_settings(owner)
            self.settle()
            constructor.assert_not_called()
            ensure.assert_called_once_with()
            owner.ensure_compact_window.assert_called_once_with()
            raise_dialog.assert_called_once_with()
            activate.assert_called_once_with()
        self.assertFrameContained(bounds)
        self.assertCentered(bounds)


if __name__ == "__main__":
    unittest.main()
