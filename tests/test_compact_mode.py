"""Protect the transparent watch window while the trading architecture changes."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow

import StockTradingSim as sim


class WatchHarness(QMainWindow):
    ensure_compact_window = sim.MainWindow.ensure_compact_window
    enter_compact_mode = sim.MainWindow.enter_compact_mode
    exit_compact_mode = sim.MainWindow.exit_compact_mode
    sync_compact_watchlist = sim.MainWindow.sync_compact_watchlist
    _compact_checked_codes = sim.MainWindow._compact_checked_codes
    show_main_after_compact_hidden = sim.MainWindow.show_main_after_compact_hidden

    def __init__(self):
        super().__init__()
        self.store = SimpleNamespace(watchlist=['sh603986', 'hk01810'], refresh_seconds=3)
        self.compact_window = None
        self._compact_mode_active = False
        self._closing = False
        self._suppress_compact_restore = False
        self.update_tray_actions = Mock()
        self.toggle_active_panel_visibility = Mock()
        self.open_main_settings = Mock()
        self.save_compact_config = Mock()
        self.quit_app = Mock()
        self.compact_display_limit = lambda: 0


class CompactModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['watch-mode-tests'])

    def setUp(self):
        self.patches = [
            patch.object(sim.LegacyStockWidget.FloatLabel, '_register_hotkey'),
            patch.object(sim.LegacyStockWidget.FloatLabel, '_refresh_from_function'),
            patch.object(sim, 'load_compact_config', return_value={
                'font_size': 12, 'fg': '#eaeaea', 'opacity_pct': 75,
                'price_visible': True, 'change_pct_visible': True,
                'kline_visible': True, 'hotkey': 'Ctrl+Alt+F',
            }),
        ]
        for item in self.patches:
            item.start()
        self.host = WatchHarness()

    def tearDown(self):
        self.host._closing = True
        if self.host.compact_window is not None:
            self.host.compact_window.timer.stop()
            self.host.compact_window._keep_top_timer.stop()
            self.host.compact_window.hide()
            self.host.compact_window.deleteLater()
        self.host.hide()
        self.host.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()

    def test_enter_and_return_keep_the_same_watch_window_and_settings(self):
        self.host.show()
        self.host.enter_compact_mode()
        watch = self.host.compact_window
        self.assertTrue(watch.isVisible())
        self.assertFalse(self.host.isVisible())
        self.assertTrue(watch.timer.isActive())
        self.assertTrue(watch.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(watch.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(watch.testAttribute(Qt.WA_TranslucentBackground))
        cfg = watch.current_config()
        self.assertEqual(cfg['codes'], self.host.store.watchlist)
        self.assertEqual(cfg['font_size'], 12)
        self.assertEqual(cfg['fg'], '#eaeaea')
        self.assertTrue(cfg['kline_visible'])
        self.host.exit_compact_mode()
        self.assertTrue(self.host.isVisible())
        self.assertFalse(watch.isVisible())
        self.assertFalse(watch.timer.isActive())
        self.host.enter_compact_mode()
        self.assertIs(self.host.compact_window, watch)
        self.assertTrue(watch.timer.isActive())
        self.assertEqual(watch.current_config()['fg'], cfg['fg'])

    def test_watchlist_updates_and_hotkey_return_to_owner(self):
        self.host.enter_compact_mode()
        watch = self.host.compact_window
        self.host.store.watchlist = ['sh688820', 'sh603986', 'hk01810']
        self.host.sync_compact_watchlist(show_all=True)
        self.assertEqual(watch.codes, self.host.store.watchlist)
        self.assertEqual(watch.checked_codes, self.host.store.watchlist)
        watch.hotkey_triggered.emit()
        self.host.toggle_active_panel_visibility.assert_called_once()
        watch.hide()
        self.assertTrue(self.host.isVisible())
        self.assertFalse(self.host._compact_mode_active)


if __name__ == '__main__':
    unittest.main()
