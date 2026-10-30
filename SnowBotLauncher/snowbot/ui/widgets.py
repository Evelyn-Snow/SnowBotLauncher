"""通用界面组件。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

class Card(QFrame):
    def __init__(self, accent: str, letter: str, title: str, subtitle: str):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        icon = QLabel(letter)
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {accent}, stop:1 #8b5cf6);"
            "border-radius: 12px; color: white; font-size: 21px; font-weight: 700;"
        )
        head.addWidget(icon)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.sub_label = QLabel(subtitle)
        self.sub_label.setObjectName("muted")
        titles.addWidget(self.title_label)
        titles.addWidget(self.sub_label)
        head.addLayout(titles)
        head.addStretch(1)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color:#64748b; font-size: 14px;")
        self.status_text = QLabel("已停止")
        self.status_text.setObjectName("muted")
        head.addWidget(self.status_dot)
        head.addWidget(self.status_text)
        layout.addLayout(head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(9)
        layout.addLayout(self.grid)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        layout.addLayout(self.buttons)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add_row(self, row: int, name: str, widget: QWidget):
        label = QLabel(name)
        label.setObjectName("muted")
        self.grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(widget, row, 1)
        self.grid.setColumnStretch(1, 1)

    def set_status(self, kind: str, text: str):
        colors = {
            "on": "#22c55e",
            "starting": "#f59e0b",
            "off": "#64748b",
            "error": "#ef4444",
        }
        self.status_dot.setStyleSheet(
            f"color:{colors.get(kind, '#64748b')}; font-size: 14px;"
        )
        self.status_text.setText(text)
        self.status_text.setObjectName("value" if kind == "on" else "muted")
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)


def link_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("link")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn
