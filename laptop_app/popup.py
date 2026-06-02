"""
Popup window for Gary's laptop companion app.

Hybrid quarter-circle notification:
- Appears as a 200px outlined arc in the bottom-right corner
- Clicking expands it into a full rectangular card with the message

Uses setMask() for shape clipping instead of translucent backgrounds,
which avoids macOS rendering issues with frameless + transparent windows.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QApplication
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QRectF, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QRegion, QPainterPath


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
CARD_RADIUS = 14


# ─── The outlined quarter-circle indicator ──────────────────────
class GaryIndicator(QWidget):
    """Outlined quarter-circle in the bottom-right of the screen."""

    def __init__(self, title: str, text: str, on_click):
        super().__init__()
        self.title = title
        self.text = text
        self.on_click = on_click
        self._build()
        self._position()
        self._apply_mask()
        self._animate_in()

    def _build(self) -> None:
        # Frameless only — no translucency
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(INDICATOR_SIZE, INDICATOR_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _apply_mask(self) -> None:
        """
        Mask the window so only the area near the arc is visible.
        Without this, we'd see a 200x200 dark square.
        """
        # Build a region that's just a thin ring matching the arc shape.
        # We use two ellipses: outer (radius=200) minus inner (radius=200-strokewidth*4)
        # then we mask to only show the upper-left quadrant.
        center_x, center_y = INDICATOR_SIZE, INDICATOR_SIZE  # bottom-right corner of widget
        outer_r = INDICATOR_SIZE
        inner_r = INDICATOR_SIZE - (INDICATOR_LINE_WIDTH * 6)  # ring thickness

        # Create a path for the ring portion in the upper-left quadrant
        path = QPainterPath()
        # Outer arc quadrant
        path.moveTo(center_x - outer_r, center_y)
        path.arcTo(
            center_x - outer_r, center_y - outer_r,
            outer_r * 2, outer_r * 2,
            180, -90,
        )
        # Line to inner arc start
        path.lineTo(center_x, center_y - inner_r)
        # Inner arc quadrant (reverse direction)
        path.arcTo(
            center_x - inner_r, center_y - inner_r,
            inner_r * 2, inner_r * 2,
            90, 90,
        )
        path.closeSubpath()

        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fill the visible (masked) region with the accent color
        painter.fillRect(self.rect(), QColor(COLOR_ACCENT))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()
            event.accept()

    def _position(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - INDICATOR_SIZE
        y = screen.bottom() - INDICATOR_SIZE
        self.move(x, y)

    def _animate_in(self) -> None:
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

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
        self._apply_rounded_mask()
        self._animate_in()

    def _build(self, title: str, text: str) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(CARD_WIDTH, CARD_HEIGHT)

        # Set the whole widget's background — no child widget needed since
        # we're not using translucency
        self.setStyleSheet(f"""
            QWidget#root {{
                background-color: {COLOR_BG};
            }}
        """)
        self.setObjectName("root")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Top: title + close
        top = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            color: {COLOR_TEXT};
            font-size: 14px;
            font-weight: 600;
            background: transparent;
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

        # Body
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

        # Bottom: copy button
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

    def _apply_rounded_mask(self) -> None:
        """Clip the window to rounded corners using setMask."""
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT),
            CARD_RADIUS, CARD_RADIUS,
        )
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

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


# ─── Orchestrator ───────────────────────────────────────────────
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