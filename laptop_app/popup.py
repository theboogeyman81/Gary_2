"""
Popup window for Gary's laptop companion app.

Uses PyQt6 to show a native window with title and text.
The popup is non-blocking — multiple can appear at once if needed.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit, QHBoxLayout
)
from PyQt6.QtCore import Qt


class GaryPopup(QWidget):
    """
    A simple popup window showing text from Gary.
    
    Has:
    - A title (header text)
    - A scrollable text area for the content
    - A 'Copy' button
    - A 'Close' button
    """

    def __init__(self, title: str, text: str):
        super().__init__()
        self.text_content = text
        self._build_ui(title, text)

    def _build_ui(self, title: str, text: str) -> None:
        # Window properties
        self.setWindowTitle(f"Gary — {title}")
        self.resize(500, 400)
        # Stay on top so user sees it immediately
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # Layout
        layout = QVBoxLayout()

        # Title label
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title_label)

        # Scrollable text area
        text_area = QTextEdit()
        text_area.setPlainText(text)
        text_area.setReadOnly(True)
        layout.addWidget(text_area)

        # Buttons row
        button_row = QHBoxLayout()

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_text)
        button_row.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)
        self.setLayout(layout)

    def _copy_text(self) -> None:
        """Copy the popup's text to system clipboard."""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_content)
        # Brief visual confirmation
        self.findChild(QPushButton).setText("Copied!")


def show_popup(title: str, text: str) -> GaryPopup:
    """
    Create and show a popup. Returns the popup widget.
    
    Keep a reference to the returned widget — otherwise Python's garbage
    collector may close it immediately.
    """
    popup = GaryPopup(title, text)
    popup.show()
    return popup