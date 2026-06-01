"""
Popup window for Gary's laptop companion app.

Hybrid quarter-circle notification:
- Appears as a 200px outlined arc in the bottom-right corner
- Clicking expands it into a full rectangular card with the message
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QApplication, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen


# ─── Design tokens ───────────────────────────────────────────────
COLOR_BG = "#1a1a1a"
COLOR_BG_HOVER = "#2a2a2a"
COLOR_TEXT = "#e8e8e8"
COLOR_TEXT_DIM = "#888888"
COLOR_ACCENT = "#7c5cff"
COLOR_BORDER = "#2a2a2a"

INDICATOR_SIZE = 200
INDICATOR_LINE_WIDTH = 3

CARD_WIDTH = 400
CARD_HEIGHT = 320
EDGE_MARGIN = 0


# ─── The outlined quarter-circle indicator ──────────────────────
class GaryIndicator(QWidget):
    """Small outlined quarter-circle in the bottom-right of the screen."""

    def __init__(self, title: str, text: str, on_click):
        super().__init__()
        self.title = title
        self.text = text
        self.on_click = on_click
        self._build()
        self._position()
        self._animate_in()

    def _build(self) -> None:
        # Frameless + always on top, but NO Tool flag (it hides on macOS)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(INDICATOR_SIZE, INDICATOR_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw the arc.
        # Bounding rect for the full circle centered at the widget's bottom-right corner.
        full_circle_rect = QRectF(
            -INDICATOR_SIZE,
            -INDICATOR_SIZE,
            INDICATOR_SIZE * 2,
            INDICATOR_SIZE * 2,
        )

        pen = QPen(QColor(COLOR_ACCENT))
        pen.setWidth(INDICATOR_LINE_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Qt arcs: 1/16th of a degree, starting from 3 o'clock, going CCW.
        # 90° to 180° = upper-left quadrant.
        painter.drawArc(full_circle_rect, 90 * 16, 90 * 16)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()
            event.accept()

    def _position(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.center().x() - INDICATOR_SIZE // 2
        y = screen.center().y() - INDICATOR_SIZE // 2
        self.move(x, y)

    def _animate_in(self) -> None:
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()  # Force to front

        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(280)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def fade_out_and_close(self) -> None:
        self._anim_out = QPropertyAnimation(self, b"windowOpacity")
        self._anim_out.setDuration(180)
        self._anim_out.setStartValue(self.windowOpacity())
        self._anim_out.setEndValue(0.0)
        self._anim_out.finished.connect(self.close)
        self._anim_out.start()


# ─── The expanded card ──────────────────────────────────────────
class GaryCard(QWidget):
    """The full-content card shown when the indicator is clicked."""

    def __init__(self, title: str, text: str):
        super().__init__()
        self.text_content = text
        self._drag_pos = None
        self._build(title, text)
        self._position()
        self._animate_in()

    def _build(self, title: str, text: str) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(CARD_WIDTH, CARD_HEIGHT)

        self.card = QWidget(self)
        self.card.setGeometry(0, 0, CARD_WIDTH, CARD_HEIGHT)
        self.card.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_BG};
                border-radius: 14px;
                border: 1px solid {COLOR_BORDER};
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            color: {COLOR_TEXT};
            font-size: 14px;
            font-weight: 600;
            background: transparent;
            border: none;
        """)
        top.addWidget(title_label)
        top.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLOR_TEXT_DIM};
                font-size: 18px;
                border: none;
                border-radius: 12px;
            }}
            QPushButton:hover {{
                background: {COLOR_BG_HOVER};
                color: {COLOR_TEXT};
            }}
        """)
        close_btn.clicked.connect(self.fade_out_and_close)
        top.addWidget(close_btn)
        layout.addLayout(top)

        self.text_area = QTextEdit()
        self.text_area.setPlainText(text)
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {COLOR_TEXT};
                font-size: 13px;
                border: none;
                padding: 0px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BG_HOVER};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        layout.addWidget(self.text_area, stretch=1)

        bot = QHBoxLayout()
        bot.addStretch()
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setFixedHeight(28)
        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: white;
                font-size: 12px;
                font-weight: 500;
                border: none;
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                background-color: #8d6fff;
            }}
            QPushButton:pressed {{
                background-color: #6a4ce8;
            }}
        """)
        self.copy_btn.clicked.connect(self._copy_text)
        bot.addWidget(self.copy_btn)
        layout.addLayout(bot)

    def _position(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - CARD_WIDTH - 20
        y = screen.bottom() - CARD_HEIGHT - 20
        self.move(x, y)

    def _animate_in(self) -> None:
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        end_pos = self.pos()
        start_pos = QPoint(end_pos.x(), end_pos.y() + 30)
        self.move(start_pos)

        self._anim_pos = QPropertyAnimation(self, b"pos")
        self._anim_pos.setDuration(280)
        self._anim_pos.setStartValue(start_pos)
        self._anim_pos.setEndValue(end_pos)
        self._anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_pos.start()

        self._anim_op = QPropertyAnimation(self, b"windowOpacity")
        self._anim_op.setDuration(280)
        self._anim_op.setStartValue(0.0)
        self._anim_op.setEndValue(1.0)
        self._anim_op.start()

    def fade_out_and_close(self) -> None:
        self._anim_out = QPropertyAnimation(self, b"windowOpacity")
        self._anim_out.setDuration(180)
        self._anim_out.setStartValue(self.windowOpacity())
        self._anim_out.setEndValue(0.0)
        self._anim_out.finished.connect(self.close)
        self._anim_out.start()

    def _copy_text(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_content)
        self.copy_btn.setText("Copied!")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


# ─── The orchestrator ───────────────────────────────────────────
class GaryPopup:
    def __init__(self, title: str, text: str):
        self.title = title
        self.text = text
        self.indicator: GaryIndicator | None = None
        self.card: GaryCard | None = None

        self.indicator = GaryIndicator(title, text, on_click=self._on_indicator_click)

    def _on_indicator_click(self) -> None:
        if self.indicator:
            self.indicator.fade_out_and_close()
            self.indicator = None
        self.card = GaryCard(self.title, self.text)


def show_popup(title: str, text: str) -> GaryPopup:
    return GaryPopup(title, text)