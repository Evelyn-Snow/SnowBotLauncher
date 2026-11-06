"""通用界面组件。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from snowbot.ui.theme import MUTED_COLOR, STATUS_COLORS, _darken


class Card(QFrame):
    def __init__(self, accent: str, letter: str, title: str, subtitle: str):
        super().__init__()
        self.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(15, 23, 42, 26))
        self.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.icon_label = QLabel(letter)
        self.icon_label.setFixedSize(44, 44)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon_label)
        self.set_icon(letter, accent)

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
        self.status_dot.setStyleSheet(f"color:{MUTED_COLOR}; font-size: 14px;")
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

    def set_icon(self, letter: str, accent: str):
        """更新卡片图标字母与主色（协议端切换时用）。"""
        self.icon_label.setText(letter)
        self.icon_label.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f" stop:0 {accent}, stop:1 {_darken(accent)});"
            "border-radius: 12px; color: white; font-size: 21px; font-weight: 700;"
        )

    def add_row(self, row: int, name: str, widget: QWidget):
        label = QLabel(name)
        label.setObjectName("muted")
        self.grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(widget, row, 1)
        self.grid.setColumnStretch(1, 1)

    def set_status(self, kind: str, text: str):
        self.status_dot.setStyleSheet(
            f"color:{STATUS_COLORS.get(kind, MUTED_COLOR)}; font-size: 14px;"
        )
        self.status_text.setText(text)
        self.status_text.setObjectName("value" if kind == "on" else "muted")
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)


def link_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("link")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(text)
    btn.setMinimumWidth(80)
    btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return btn


def scroll_page(widget: QWidget, min_height: int | None = None) -> QScrollArea:
    """把页面放进可滚动容器，避免窗口变矮时控件被挤压。

    Args:
        widget: 页面内容。
        min_height: 内容最小高度；留空时按当前 sizeHint 自动计算。
    """
    widget.ensurePolished()
    if min_height is None:
        min_height = max(320, widget.sizeHint().height() + 12)
    widget.setMinimumHeight(min_height)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    return scroll
