from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Bunny Sort")
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    return app.exec()
