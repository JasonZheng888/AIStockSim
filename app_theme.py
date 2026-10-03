"""A consistent light desktop theme, independent of the Windows color scheme.

Keep backgrounds out of application-wide style sheets: the compact quote window
owns its translucent background and user-selected foreground colors.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def make_light_palette() -> QPalette:
    """Set every visible palette role explicitly, including inactive windows."""
    palette = QPalette()
    colors = {
        QPalette.Window: "#f7f8fa",
        QPalette.WindowText: "#17202a",
        QPalette.Base: "#ffffff",
        QPalette.AlternateBase: "#f1f5f9",
        QPalette.Text: "#17202a",
        QPalette.Button: "#ffffff",
        QPalette.ButtonText: "#17202a",
        QPalette.BrightText: "#ffffff",
        QPalette.Light: "#ffffff",
        QPalette.Midlight: "#e5e7eb",
        QPalette.Mid: "#c2cad4",
        QPalette.Dark: "#8994a3",
        QPalette.Shadow: "#637083",
        QPalette.Highlight: "#2563eb",
        QPalette.HighlightedText: "#ffffff",
        QPalette.Link: "#1d4ed8",
        QPalette.LinkVisited: "#6d28d9",
        QPalette.ToolTipBase: "#fffbe8",
        QPalette.ToolTipText: "#17202a",
        QPalette.PlaceholderText: "#697386",
    }
    if hasattr(QPalette, "Accent"):
        colors[QPalette.Accent] = "#2563eb"
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role, color in colors.items():
            palette.setColor(group, role, QColor(color))

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.PlaceholderText):
        palette.setColor(QPalette.Disabled, role, QColor("#697386"))
    for role in (QPalette.Base, QPalette.Button):
        palette.setColor(QPalette.Disabled, role, QColor("#f1f5f9"))
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#dbe4f0"))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor("#526176"))
    return palette


def configure_light_theme(app: QApplication) -> None:
    """Call before constructing windows, in either application entry point.

    Qt 6.8+ also applies this preference to native window decoration/dialogs.
    Fusion and explicit palette roles keep older Qt versions readable as well.
    Explicit roles survive operating-system theme and accent changes.
    """
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)
    app.setStyle("Fusion")
    app.setPalette(make_light_palette())
