"""主题样式与图标。

浅色主题：白色卡片 + 冷灰背景 + 蓝色主色。
动态颜色（状态点、提示文字、状态胶囊）集中在这里，页面代码引用常量，
避免散落各处的深色硬编码。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QLinearGradient, QPainter, QPixmap


def make_app_icon() -> QIcon:
    pm = QPixmap(128, 128)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 128, 128)
    grad.setColorAt(0, QColor("#4f7cff"))
    grad.setColorAt(1, QColor("#8b5cf6"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(8, 8, 112, 112, 30, 30)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 58, QFont.Weight.Bold))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    return QIcon(pm)


def _darken(hex_color: str, factor: float = 0.82) -> str:
    """把颜色按比例压暗（factor<1 变深），用于渐变的第二停点。"""
    color = QColor(hex_color)
    color.setRed(int(color.red() * factor))
    color.setGreen(int(color.green() * factor))
    color.setBlue(int(color.blue() * factor))
    return color.name()


# ---------- 动态颜色（页面代码引用） ----------
OK_COLOR = "#059669"        # 成功 / 在线
WARN_COLOR = "#b45309"      # 警告 / 等待
MUTED_COLOR = "#94a3b8"     # 中性 / 停止
ERROR_COLOR = "#dc2626"     # 错误

STATUS_COLORS = {
    "on": "#16a34a",
    "starting": "#d97706",
    "off": MUTED_COLOR,
    "error": ERROR_COLOR,
}

# 顶部状态胶囊：(背景, 文字, 边框)
PILL_OK = ("#ecfdf5", "#047857", "#a7f3d0")
PILL_WARN = ("#fffbeb", "#b45309", "#fde68a")
PILL_IDLE = ("#eef2f8", "#64748b", "#dbe3ee")


def pill_style(colors: tuple[str, str, str]) -> str:
    bg, fg, border = colors
    return (
        f"background:{bg}; color:{fg}; border:1px solid {border};"
        "border-radius:14px; padding:5px 16px; font-weight:600;"
    )


QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #1e293b; }

QWidget#root, QMainWindow { background: #f3f5f9; }
QDialog, QMessageBox { background: #ffffff; }
QMessageBox QLabel { color: #1e293b; }

/* ---------- 层级与容器 ---------- */
QFrame#card {
    background: #ffffff;
    border: 1px solid #e4e9f2;
    border-radius: 16px;
}
QFrame#banner {
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 12px;
}
QLabel#warnText { color: #b45309; }
QGroupBox {
    border: 1px solid #e4e9f2;
    border-radius: 14px;
    margin-top: 20px;
    padding: 18px 14px 12px 14px;
    font-weight: 600;
    color: #475569;
    background: #ffffff;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #64748b; }

/* ---------- 文本 ---------- */
QLabel { color: #1e293b; }
QLabel:disabled { color: #a8b3c5; }
QLabel#title { font-size: 21px; font-weight: 800; color: #0f172a; }
QLabel#subtitle { color: #64748b; font-size: 12px; }
QLabel#cardTitle { font-size: 16px; font-weight: 700; color: #0f172a; }
QLabel#muted { color: #64748b; font-size: 12px; }
QLabel#value { color: #0f172a; font-weight: 600; }
QLabel#pill {
    background: #eef2f8; color: #64748b;
    border: 1px solid #dbe3ee; border-radius: 14px;
    padding: 5px 16px; font-weight: 600;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #d9e0ec;
    padding: 7px 15px;
    border-radius: 9px;
    color: #334155;
}
QPushButton:hover { background: #f1f5fb; border-color: #b9c6dd; }
QPushButton:pressed { background: #e6ecf6; }
QPushButton:disabled { color: #a8b3c5; background: #f6f8fb; border-color: #e7ecf4; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4c7dff, stop:1 #3a68ee);
    border: 1px solid #3a68ee;
    color: white; font-weight: 600;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #5d89ff, stop:1 #4a76f5);
    border-color: #5d89ff;
}
QPushButton#primary:pressed { background: #3559d6; }
QPushButton#primary:disabled {
    background: #e4ebf7; border-color: #dbe4f2; color: #9db0d4; font-weight: 600;
}
QPushButton#danger {
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #dc2626;
}
QPushButton#danger:hover { background: #fee2e2; border-color: #fca5a5; }
QPushButton#danger:pressed { background: #fee4e2; }
QPushButton#danger:disabled { background: #f6f8fb; border-color: #e7ecf4; color: #c3a9ad; }
QPushButton#ghost { background: transparent; border: 1px solid #d9e0ec; color: #475569; }
QPushButton#ghost:hover { background: #f1f5fb; border-color: #b9c6dd; }
QPushButton#link {
    background: transparent; border: none;
    color: #2563eb; padding: 0; text-align: left; font-weight: 600;
}
QPushButton#link:hover { color: #1d4ed8; text-decoration: underline; }
QToolButton {
    background: #f1f5fb; border: 1px solid #d9e0ec; border-radius: 7px;
    padding: 3px 9px; color: #475569;
}
QToolButton:hover { background: #e6ecf6; border-color: #b9c6dd; }

/* ---------- 标签页 ---------- */
QTabWidget::pane { border: none; margin-top: 4px; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent; color: #64748b;
    padding: 7px 18px; margin-right: 4px;
    border-radius: 9px; border: 1px solid transparent;
}
QTabBar::tab:hover { color: #1e293b; background: #eaeff7; }
QTabBar::tab:selected {
    background: #e8f0ff; color: #2563eb;
    border: 1px solid #cfe0ff; font-weight: 600;
}
QTabWidget QLabel { color: #1e293b; }
QTabWidget QLabel#muted { color: #64748b; }

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #d9e0ec;
    border-radius: 9px;
    padding: 6px 11px;
    color: #0f172a;
    selection-background-color: #bfdbfe;
    selection-color: #0f172a;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #4f7cff; background: #ffffff;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #a8b3c5; background: #f6f8fb; border-color: #e7ecf4;
}
QComboBox {
    background: #ffffff; border: 1px solid #d9e0ec;
    border-radius: 9px; padding: 6px 11px; color: #0f172a;
}
QComboBox:focus { border-color: #4f7cff; }
QComboBox:disabled { color: #a8b3c5; background: #f6f8fb; border-color: #e7ecf4; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #dbe3ee;
    border-radius: 8px; padding: 4px;
    selection-background-color: #e3edff; selection-color: #1d4ed8;
    outline: none;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; }

QCheckBox { spacing: 8px; color: #334155; }
QCheckBox:disabled { color: #a8b3c5; }

QListWidget {
    background: #ffffff; border: 1px solid #e4e9f2;
    border-radius: 12px; padding: 6px; outline: none;
}
QListWidget::item { padding: 10px 12px; border-radius: 9px; color: #334155; }
QListWidget::item:hover { background: #f1f5fb; }
QListWidget::item:selected { background: #e3edff; color: #1d4ed8; }

QPlainTextEdit {
    background: #fbfcfe;
    border: 1px solid #e4e9f2;
    border-radius: 12px;
    padding: 10px 12px;
    color: #334155;
    selection-background-color: #bfdbfe;
}
QPlainTextEdit:disabled { color: #a8b3c5; background: #f6f8fb; }

/* ---------- 进度 / 菜单 / 提示 ---------- */
QProgressBar {
    background: #eef2f8; border: 1px solid #dbe3ee;
    border-radius: 8px; text-align: center; color: #475569; height: 20px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4c7dff, stop:1 #8b5cf6);
    border-radius: 7px;
}
QMenu { background: #ffffff; border: 1px solid #dbe3ee; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 24px; border-radius: 7px; color: #334155; }
QMenu::item:selected { background: #e3edff; color: #1d4ed8; }
QToolTip {
    background: #ffffff; color: #1e293b;
    border: 1px solid #d9e0ec; border-radius: 6px; padding: 5px 9px;
}

QSplitter::handle { background: #f3f5f9; }
QSplitter::handle:vertical { height: 8px; margin: 3px 0; border-radius: 4px; }
QSplitter::handle:horizontal { width: 8px; margin: 0 3px; border-radius: 4px; }
QSplitter::handle:hover { background: #dbe3ee; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e1; min-height: 24px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cbd5e1; min-width: 24px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: #94a3b8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""
