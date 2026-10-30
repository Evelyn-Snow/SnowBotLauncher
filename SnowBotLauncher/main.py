"""SnowBotLauncher 入口。"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from snowbot.core.paths import APP_NAME, LOCK_PATH
from snowbot.ui.main_window import LauncherWindow
from snowbot.ui.theme import QSS, make_app_icon


def acquire_single_instance():
    try:
        import msvcrt

        fh = open(LOCK_PATH, "w")
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh
    except OSError:
        QMessageBox.information(
            None,
            APP_NAME,
            "控制台已经在运行。\n如果窗口被挂起到了系统托盘，请双击托盘图标恢复。",
        )
        return None
    except Exception:
        return True


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

    lock_handle = acquire_single_instance()
    if lock_handle is None:
        sys.exit(0)

    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
