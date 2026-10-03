r"""Theme regressions, isolated from application data and market requests.

Run with: .venv\Scripts\python.exe -m unittest discover -s tests -v
Only plain Qt widgets and the in-memory quote model are constructed here.
"""

import os
import unittest

# Windows' native plugin can verify the window-decoration color preference.
# Widgets stay hidden; only this process' theme is changed. Other environments
# can still run the palette assertions with the offscreen plugin.
if os.name != "nt" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
)

from app_theme import configure_light_theme, make_light_palette
from StockWidget import DOWN_COLOR, UP_COLOR, SimpleTableModel


def luminance(color):
    """Relative luminance in the sRGB space, as used for contrast ratios."""
    channels = [color.redF(), color.greenF(), color.blueF()]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
              for v in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(foreground, background):
    bright, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def host_palette(dark):
    """A deliberately hostile incoming palette, including disabled/selection roles."""
    palette = QPalette()
    background = QColor("#161616" if dark else "#fafafa")
    foreground = QColor("#eeeeee" if dark else "#202020")
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role in (QPalette.Window, QPalette.Base, QPalette.AlternateBase,
                     QPalette.Button, QPalette.ToolTipBase):
            palette.setColor(group, role, background)
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                     QPalette.PlaceholderText, QPalette.ToolTipText):
            palette.setColor(group, role, foreground)
        palette.setColor(group, QPalette.Highlight, QColor("#ffeeaa"))
        palette.setColor(group, QPalette.HighlightedText, QColor("#ffffff"))
    return palette


class LightThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["theme-regression-tests"])

    def setUp(self):
        configure_light_theme(self.app)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        configure_light_theme(self.app)

    def assertReadable(self, palette, group, foreground, background, minimum=4.5):
        ratio = contrast(palette.color(group, foreground), palette.color(group, background))
        self.assertGreaterEqual(
            ratio, minimum,
            f"{group.name}: {foreground.name}/{background.name} contrast is {ratio:.2f}",
        )

    def assertLightPalette(self, palette):
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            for background in (QPalette.Window, QPalette.Base, QPalette.Button,
                               QPalette.AlternateBase, QPalette.ToolTipBase):
                self.assertGreater(luminance(palette.color(group, background)), 0.7)
            minimum = 3.0 if group == QPalette.Disabled else 4.5
            for foreground, background in (
                (QPalette.WindowText, QPalette.Window),
                (QPalette.Text, QPalette.Base),
                (QPalette.Text, QPalette.AlternateBase),
                (QPalette.ButtonText, QPalette.Button),
                (QPalette.ToolTipText, QPalette.ToolTipBase),
                (QPalette.HighlightedText, QPalette.Highlight),
            ):
                self.assertReadable(palette, group, foreground, background, minimum)
            self.assertReadable(palette, group, QPalette.PlaceholderText, QPalette.Base, 3.0)

    def assertLightColorScheme(self):
        # These headless plugins cannot report a native color scheme at all.
        if self.app.platformName() in ("offscreen", "minimal"):
            self.assertIn(self.app.styleHints().colorScheme(),
                          (Qt.ColorScheme.Unknown, Qt.ColorScheme.Light))
        else:
            self.assertEqual(self.app.styleHints().colorScheme(), Qt.ColorScheme.Light)

    def test_palette_is_complete_and_readable_in_all_states(self):
        self.assertLightPalette(make_light_palette())

    def test_light_and_dark_host_settings_are_both_normalized(self):
        for scheme, dark in ((Qt.ColorScheme.Light, False), (Qt.ColorScheme.Dark, True)):
            with self.subTest(host_scheme=scheme.name):
                self.app.styleHints().setColorScheme(scheme)
                incoming = host_palette(dark)
                self.app.setPalette(incoming)
                self.app.processEvents()
                self.assertLess(
                    contrast(incoming.color(QPalette.HighlightedText),
                             incoming.color(QPalette.Highlight)), 2.0,
                )
                configure_light_theme(self.app)
                self.app.processEvents()
                self.assertEqual(self.app.style().objectName().lower(), "fusion")
                self.assertLightColorScheme()
                self.assertLightPalette(self.app.palette())

    def test_existing_and_new_controls_inherit_readable_palette(self):
        self.app.setPalette(host_palette(True))
        existing = QDialog()
        self.widgets.append(existing)
        configure_light_theme(self.app)
        controls = (
            (existing, QPalette.WindowText, QPalette.Window),
            (QDialog(), QPalette.WindowText, QPalette.Window),
            (QMenu(), QPalette.WindowText, QPalette.Window),
            (QLineEdit(), QPalette.Text, QPalette.Base),
            (QComboBox(), QPalette.ButtonText, QPalette.Button),
            (QSpinBox(), QPalette.Text, QPalette.Base),
            (QPushButton("提交"), QPalette.ButtonText, QPalette.Button),
            (QTableWidget(1, 1), QPalette.Text, QPalette.Base),
        )
        self.widgets.extend(widget for widget, _, _ in controls if widget is not existing)
        for widget, foreground, background in controls:
            with self.subTest(widget=type(widget).__name__):
                widget.ensurePolished()
                self.assertReadable(widget.palette(), QPalette.Active, foreground, background)
                widget.setEnabled(False)
                self.assertReadable(widget.palette(), QPalette.Disabled, foreground, background, 3.0)
        edit = next(widget for widget, _, _ in controls if isinstance(widget, QLineEdit))
        edit.setPlaceholderText("输入股票代码")
        self.assertReadable(edit.palette(), QPalette.Active, QPalette.PlaceholderText,
                            QPalette.Base, 3.0)

    def test_theme_survives_event_processing_and_repeated_configuration(self):
        before = QPalette(self.app.palette())
        for event_type in (QEvent.ThemeChange, QEvent.ApplicationActivate):
            QApplication.sendEvent(self.app, QEvent(event_type))
        self.app.processEvents()
        self.assertLightPalette(self.app.palette())
        self.assertEqual(self.app.palette(), before)
        configure_light_theme(self.app)
        self.app.processEvents()
        self.assertEqual(self.app.palette(), before)
        self.assertLightColorScheme()


class QuoteModelThemeTests(unittest.TestCase):
    def test_unchanged_quotes_use_the_selected_widget_foreground(self):
        headers = ["现价", "涨跌值", "涨跌幅", "委比", "均价", "买一", "卖一", "名称"]
        for foreground in (QColor("#f3f3f3"), QColor("#252525")):
            with self.subTest(foreground=foreground.name()):
                model = SimpleTableModel()
                model.set_color_scheme(True, foreground)
                model.set_rows_headers([["0"] * len(headers)], headers,
                                       [{"delta": 0, "commi": 0, "avg": 0, "b1": 0, "s1": 0}])
                for column in range(len(headers)):
                    self.assertEqual(model.data(model.index(0, column), Qt.ForegroundRole),
                                     foreground, headers[column])

    def test_up_down_colors_and_custom_color_mode_are_preserved(self):
        model = SimpleTableModel()
        foreground = QColor("#f3f3f3")
        model.set_rows_headers([["100"], ["99"], ["100"]], ["现价"],
                               [{"delta": 1}, {"delta": -1}, {}])
        model.set_color_scheme(True, foreground)
        for row, expected in enumerate((UP_COLOR, DOWN_COLOR, foreground)):
            self.assertEqual(model.data(model.index(row, 0), Qt.ForegroundRole), expected)
        model.set_color_scheme(False, foreground)
        for row in range(model.rowCount()):
            self.assertEqual(model.data(model.index(row, 0), Qt.ForegroundRole), foreground)


if __name__ == "__main__":
    unittest.main()
