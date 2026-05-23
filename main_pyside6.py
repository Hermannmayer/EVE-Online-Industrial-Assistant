"""
EVE 商人助手 — PySide6 入口点
运行: python main_pyside6.py
"""
import sys
from PySide6.QtWidgets import QApplication
from ui_pyside6.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EVE 商人助手")
    app.setOrganizationName("EVEAssistant")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
