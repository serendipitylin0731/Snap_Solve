"""Application entry point."""

import ctypes
import sys


def main() -> int:
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    from PySide6.QtWidgets import QApplication
    from .ui import MainWindow, icon

    app = QApplication(sys.argv)
    app.setApplicationName("Snap Solve")
    app.setOrganizationName("Snap Solve")
    app.setWindowIcon(icon())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

