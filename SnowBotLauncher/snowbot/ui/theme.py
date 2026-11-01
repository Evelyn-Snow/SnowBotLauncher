"""主题样式与图标。"""
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


QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #e8ecf6; }

QWidget#root, QMainWindow { background: #0a0e18; }
QDialog, QMessageBox { background: #0d1220; }
QMessageBox QLabel { color: #e8ecf6; }

/* ---------- 层级与容器 ---------- */
QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #121b30, stop:1 #0e1526);
    border: 1px solid #1d2a45;
    border-radius: 16px;
}
QFrame#banner {
    background: #241d0e;
    border: 1px solid #59421a;
    border-radius: 12px;
}
QLabel#warnText { color: #fcd34d; }
QGroupBox {
    border: 1px solid #1c2740;
    border-radius: 14px;
    margin-top: 20px;
    padding: 18px 14px 12px 14px;
    font-weight: 600;
    color: #aab8d4;
    background: #0d1424;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #aab8d4; }

/* ---------- 文本 ---------- */
QLabel { color: #e8ecf6; }
QLabel:disabled { color: #5c6a84; }
QLabel#title { font-size: 21px; font-weight: 800; color: #f8fafc; }
QLabel#subtitle { color: #8b97b0; font-size: 12px; }
QLabel#cardTitle { font-size: 16px; font-weight: 700; color: #f1f5f9; }
QLabel#muted { color: #94a3b8; font-size: 12px; }
QLabel#value { color: #e2e8f0; font-weight: 600; }
QLabel#pill {
    background: #131c30; color: #9aa7bf;
    border: 1px solid #263450; border-radius: 14px;
    padding: 5px 16px; font-weight: 600;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: #182238;
    border: 1px solid #2a3a55;
    padding: 7px 15px;
    border-radius: 9px;
    color: #dde4f0;
}
QPushButton:hover { background: #1f2c48; border-color: #3a4d6e; }
QPushButton:pressed { background: #141d31; }
QPushButton:disabled { color: #5c6a84; background: #121a2c; border-color: #1f2b44; }
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
    background: #1a2640; border-color: #243455; color: #55688c; font-weight: 600;
}
QPushButton#danger {
    background: #3d1b28;
    border: 1px solid #6b2237;
    color: #fda4af;
}
QPushButton#danger:hover { background: #4d2131; border-color: #8a2c47; }
QPushButton#danger:pressed { background: #331824; }
QPushButton#danger:disabled { background: #1c1622; border-color: #2b2333; color: #6b5b63; }
QPushButton#ghost { background: transparent; border: 1px solid #2a3a55; color: #cbd5e1; }
QPushButton#ghost:hover { background: #16203a; border-color: #3a4d6e; }
QPushButton#link {
    background: transparent; border: none;
    color: #7dd3fc; padding: 0; text-align: left; font-weight: 600;
}
QPushButton#link:hover { color: #bae6fd; text-decoration: underline; }
QToolButton {
    background: #162033; border: 1px solid #26354f; border-radius: 7px;
    padding: 3px 9px; color: #cbd5e1;
}
QToolButton:hover { background: #1e2c44; border-color: #38497a; }

/* ---------- 标签页 ---------- */
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent; color: #8b97b0;
    padding: 7px 16px; margin-right: 4px;
    border-radius: 9px; border: 1px solid transparent;
}
QTabBar::tab:hover { color: #cdd6e6; }
QTabBar::tab:selected {
    background: #1a2540; color: #ffffff;
    border: 1px solid #2b3c63; font-weight: 600;
}
QTabWidget QLabel { color: #e8ecf6; }
QTabWidget QLabel#muted { color: #94a3b8; }

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #0c1220;
    border: 1px solid #253252;
    border-radius: 9px;
    padding: 6px 11px;
    color: #e2e8f0;
    selection-background-color: #2b4a8f;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #4f7cff; background: #0e1626;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #5c6a84; background: #111928; border-color: #1f2b44;
}
QComboBox {
    background: #0c1220; border: 1px solid #253252;
    border-radius: 9px; padding: 6px 11px; color: #e2e8f0;
}
QComboBox:focus { border-color: #4f7cff; }
QComboBox:disabled { color: #5c6a84; background: #111928; border-color: #1f2b44; }
QComboBox QAbstractItemView {
    background: #101728; border: 1px solid #263450;
    border-radius: 8px; padding: 4px;
    selection-background-color: #1f3a70; selection-color: #ffffff;
    outline: none;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; }

QCheckBox { spacing: 8px; color: #cbd5e1; }
QCheckBox:disabled { color: #5c6a84; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1px solid #3a4d6e; border-radius: 5px;
    background: #0c1220;
}
QCheckBox::indicator:hover { border-color: #6a93ff; }
QCheckBox::indicator:checked { background: #4f7cff; border-color: #6a93ff; }
QCheckBox::indicator:disabled { background: #111928; border-color: #24304a; }

QListWidget {
    background: #0c1220; border: 1px solid #1c2740;
    border-radius: 12px; padding: 6px; outline: none;
}
QListWidget::item { padding: 10px 12px; border-radius: 9px; color: #cbd5e1; }
QListWidget::item:hover { background: #16203a; }
QListWidget::item:selected { background: #1f3a70; color: #ffffff; }

QPlainTextEdit {
    background: #080d18;
    border: 1px solid #1a2338;
    border-radius: 12px;
    color: #a3ccb8;
    selection-background-color: #2b4a8f;
}
QPlainTextEdit:disabled { color: #5c6a84; background: #0d1220; }

/* ---------- 进度 / 菜单 / 提示 ---------- */
QProgressBar {
    background: #0c1220; border: 1px solid #253252;
    border-radius: 8px; text-align: center; color: #cbd5e1; height: 20px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4c7dff, stop:1 #8b5cf6);
    border-radius: 7px;
}
QMenu { background: #101728; border: 1px solid #263450; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 24px; border-radius: 7px; }
QMenu::item:selected { background: #1f3a70; color: #ffffff; }
QToolTip {
    background: #131b2e; color: #e8ecf6;
    border: 1px solid #2a3a55; border-radius: 6px; padding: 5px 9px;
}

QSplitter::handle { background: #0d1424; }
QSplitter::handle:vertical { height: 8px; margin: 3px 0; border-radius: 4px; }
QSplitter::handle:horizontal { width: 8px; margin: 0 3px; border-radius: 4px; }
QSplitter::handle:hover { background: #273450; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #273450; min-height: 24px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #38497a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: #273450; min-width: 24px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: #38497a; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""
