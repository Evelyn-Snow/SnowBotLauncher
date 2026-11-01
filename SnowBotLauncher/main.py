"""SnowBotLauncher 入口。"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from snowbot.core.paths import APP_NAME
from snowbot.core.single_instance import acquire_single_instance
from snowbot.ui.main_window import LauncherWindow
from snowbot.ui.theme import QSS, make_app_icon


def main():
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_app_icon())
    app.setStyleSheet(QSS)
    app.setQuitOnLastWindowClosed(False)

    if not acquire_single_instance():
        QMessageBox.information(
            None,
            APP_NAME,
            "控制台已经在运行。\n如果窗口被挂起到了系统托盘，请双击托盘图标恢复。",
        )
        sys.exit(0)

    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
