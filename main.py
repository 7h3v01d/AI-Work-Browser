"""
main.py — entry point for AI Work Browser.

Initialises QApplication, loads settings, applies base stylesheet,
shows BrowserWindow.
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from settings import Settings
from browser_window import BrowserWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("AI Work Browser")
    app.setOrganizationName("AIWorkBrowser")
    app.setStyleSheet(_BASE_STYLESHEET)

    settings = Settings()
    window   = BrowserWindow(settings)
    window.show()

    sys.exit(app.exec())


_BASE_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 13px;
}
QToolBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #3a3a3a;
    spacing: 4px;
    padding: 3px 6px;
}
QLineEdit {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    color: #e0e0e0;
    padding: 3px 8px;
    selection-background-color: #264f78;
}
QLineEdit:focus { border: 1px solid #007acc; }
QPushButton {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    color: #d4d4d4;
    padding: 3px 10px;
}
QPushButton:hover   { background-color: #4a4a4a; border-color: #777; }
QPushButton:pressed { background-color: #2a2a2a; }
QToolButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #d4d4d4;
    padding: 3px 6px;
}
QToolButton:hover   { background-color: #3c3c3c; }
QToolButton:pressed { background-color: #2a2a2a; }
QStatusBar {
    background-color: #007acc;
    color: #ffffff;
    font-size: 11px;
}
QMenu {
    background-color: #2d2d2d;
    border: 1px solid #3a3a3a;
    color: #d4d4d4;
}
QMenu::item:selected { background-color: #094771; }
QComboBox {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    color: #d4d4d4;
    padding: 2px 6px;
}
QComboBox::drop-down { border: none; }
QTextEdit {
    background-color: #1e1e1e;
    border: 1px solid #3a3a3a;
    color: #c0c0c0;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}
QSplitter::handle     { background-color: #3a3a3a; }
QLabel                { color: #d4d4d4; }
QCheckBox             { color: #d4d4d4; spacing: 6px; }
QCheckBox::indicator  {
    width: 14px; height: 14px;
    border: 1px solid #555;
    border-radius: 3px;
    background-color: #3c3c3c;
}
QCheckBox::indicator:checked {
    background-color: #007acc;
    border-color: #007acc;
}
QScrollBar:vertical          { background-color:#2d2d2d; width:10px; border:none; }
QScrollBar::handle:vertical  {
    background-color:#5a5a5a; border-radius:5px; min-height:20px;
}
QScrollBar::handle:vertical:hover { background-color:#7a7a7a; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height:0; }
"""


if __name__ == "__main__":
    main()
