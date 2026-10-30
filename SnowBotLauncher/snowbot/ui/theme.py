"""主题样式与图标。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QLinearGradient, QPainter, QPixmap


def make_app_icon() -> QIcon:
    pm = QPixmap(128, 128)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 128, 128)
    grad.setColorAt(0, QColor("#3b82f6"))
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
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #e5e7eb; }
QWidget#root, QMainWindow { background: #0b1020; }
QFrame#card { background: #121a2d; border: 1px solid #22304a; border-radius: 14px; }
QFrame#banner { background: #2a2110; border: 1px solid #6b5214; border-radius: 10px; }
QLabel#warnText { color: #fbbf24; }
QLabel#title { font-size: 22px; font-weight: 700; color: #f8fafc; }
QLabel#subtitle { color: #8b97b0; font-size: 12px; }
QLabel#cardTitle { font-size: 17px; font-weight: 600; color: #f1f5f9; }
QLabel#muted { color: #94a3b8; font-size: 12px; }
QLabel#pill { background:#151d31; color:#94a3b8; border:1px solid #24304a; border-radius:13px; padding:5px 14px; font-weight:600; }
QLabel#value { color: #e2e8f0; }
QTabWidget QLabel { color: #e5e7eb; }
QTabWidget QLabel#muted { color: #94a3b8; }
QPushButton { background: #1b2539; border: 1px solid #2a3a55; padding: 7px 14px; border-radius: 8px; }
QPushButton:hover { background: #243149; border-color: #3a4d6e; }
QPushButton:pressed { background: #162033; }
QPushButton#primary { background: #2563eb; border: 1px solid #2563eb; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #3b82f6; border-color: #3b82f6; }
QPushButton#primary:disabled { background: #16233d; border-color: #24304a; color: #5b6b85; }
QPushButton#danger { background: #3a1c27; border: 1px solid #6b2237; color: #fca5a5; }
QPushButton#danger:hover { background: #4a2233; }
QPushButton#danger:disabled { background: #1a1a24; border-color: #2b2b38; color: #6b5b63; }
QPushButton#ghost { background: transparent; border: 1px solid #2a3a55; color: #cbd5e1; }
QPushButton#ghost:hover { background: #182238; }
QPushButton#link { background: transparent; border: none; color: #7dd3fc; padding: 0; text-align: left; }
QPushButton#link:hover { color: #bae6fd; text-decoration: underline; }
QPushButton:disabled { color: #64748b; background: #141c2e; border-color: #1f2b44; }
QToolButton { background: #162033; border: 1px solid #26354f; border-radius: 6px; padding: 2px 8px; color: #cbd5e1; }
QToolButton:hover { background: #1e2c44; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #94a3b8; padding: 8px 18px; margin-right: 6px; border-radius: 8px; }
QTabBar::tab:selected { background: #1b2740; color: #e2e8f0; }
QTabBar::tab:hover { color: #e2e8f0; }
QPlainTextEdit { background: #070b16; border: 1px solid #1c2740; border-radius: 10px; color: #a7f3d0; }
QLineEdit, QSpinBox, QDoubleSpinBox { background: #0e1526; border: 1px solid #24304a; border-radius: 8px; padding: 6px 10px; color: #e2e8f0; }
QLineEdit:focus, QSpinBox:focus { border-color: #3b82f6; }
QCheckBox { spacing: 8px; color: #cbd5e1; }
QGroupBox { border: 1px solid #1f2b44; border-radius: 12px; margin-top: 18px; padding: 16px 14px 12px 14px; font-weight: 600; color: #cbd5e1; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #cbd5e1; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QMenu { background: #121a2d; border: 1px solid #22304a; padding: 6px; }
QMenu::item { padding: 7px 24px; border-radius: 6px; }
QMenu::item:selected { background: #1e3a8a; }
QListWidget { background: #0e1526; border: 1px solid #1c2740; border-radius: 10px; padding: 6px; }
QListWidget::item { padding: 10px 12px; border-radius: 8px; color: #cbd5e1; }
QListWidget::item:hover { background: #162033; }
QListWidget::item:selected { background: #1e3a8a; color: #ffffff; }
QComboBox { background: #0e1526; border: 1px solid #24304a; border-radius: 8px; padding: 6px 10px; color: #e2e8f0; }
QComboBox QAbstractItemView { background: #121a2d; border: 1px solid #24304a; selection-background-color: #1e3a8a; }
QProgressBar { background: #0e1526; border: 1px solid #24304a; border-radius: 7px; text-align: center; color: #cbd5e1; height: 20px; }
QProgressBar::chunk { background: #2563eb; border-radius: 6px; }
QLabel { color: #e5e7eb; }
QLabel:disabled { color: #64748b; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #3a4d6e;
    border-radius: 4px;
    background: #0e1526;
}
QCheckBox::indicator:hover { border-color: #5b8cff; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #3b82f6; }
QCheckBox::indicator:disabled { background: #141c2e; border-color: #24304a; }
QScrollBar:vertical { background: #0b1020; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2a3a55; min-height: 24px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #3a4d6e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: #0b1020; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #2a3a55; min-width: 24px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #3a4d6e; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled { color: #64748b; background: #141c2e; }
QToolTip { background: #131a2e; color: #e5e7eb; border: 1px solid #24304a; padding: 4px 8px; }
QDialog, QMessageBox { background: #0b1020; }
QMessageBox QLabel { color: #e5e7eb; }
"""
