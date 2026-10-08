from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from .drop_policy import evaluate_csv_drop


class CsvDropZone(QFrame):
    file_selected = Signal(object)
    rejected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        self.setMinimumHeight(190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt = QLabel("CSVをここにドロップ")
        self.prompt.setObjectName("sectionTitle")
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("または")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.choose_button = QPushButton("ファイルを選択")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.prompt)
        layout.addWidget(hint)
        layout.addWidget(self.choose_button, alignment=Qt.AlignmentFlag.AlignCenter)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            self.prompt.setText("ここにドロップしてください")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._reset_drag_state()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = tuple(
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        )
        decision = evaluate_csv_drop(paths)
        self._reset_drag_state()
        if decision.accepted_path is not None:
            self.file_selected.emit(decision.accepted_path)
            event.acceptProposedAction()
        else:
            self.rejected.emit(decision.message)
            event.ignore()

    def _reset_drag_state(self) -> None:
        self.prompt.setText("CSVをここにドロップ")
        self._set_drag_active(False)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
