"""Windows-friendly Qt interface and interactive screen selection."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from . import __version__
from .config import get_api_key, save_api_key, setting
from .deepseek import DeepSeekError, solve, transcribe


STYLE = """
QWidget { color: #202b3e; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #f5f7fb; }
QFrame#card { background: #ffffff; border: 1px solid #e4e9f1; border-radius: 16px; }
QFrame#header { background: #ffffff; border-bottom: 1px solid #e4e9f1; }
QLabel#eyebrow { color: #73829b; font-size: 11px; font-weight: 600; }
QLabel#title { color: #15233b; font-size: 23px; font-weight: 700; }
QLabel#section { color: #1d2d46; font-size: 15px; font-weight: 700; }
QLabel#muted { color: #7d8aa0; }
QLabel#pill { color: #276e67; background: #e3f5ef; border-radius: 9px; padding: 5px 10px; font-size: 11px; }
QPushButton { border: 1px solid #dce3ee; border-radius: 9px; background: #fff; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #f1f5fb; border-color: #b9c7db; }
QPushButton:disabled { color: #9ca9bb; background: #f1f3f7; }
QPushButton#primary { background: #246aee; color: white; border-color: #246aee; padding: 10px 20px; }
QPushButton#primary:hover { background: #175bd8; }
QPushButton#primary:disabled { background: #a7c2f8; border-color: #a7c2f8; color: #fff; }
QPushButton#quiet { border: 0; color: #4a6080; padding: 8px 10px; }
QCheckBox { spacing: 9px; font-weight: 600; }
QCheckBox::indicator { width: 17px; height: 17px; }
QPlainTextEdit, QLineEdit { border: 1px solid #e0e7f1; border-radius: 10px; background: #fbfcff; padding: 12px; selection-background-color: #bcd3ff; }
QPlainTextEdit:focus, QLineEdit:focus { border-color: #6a9bfa; }
QLabel#preview { border: 1px dashed #cbd6e7; border-radius: 12px; background: #f8fafd; color: #8d9bb0; }
"""


def icon() -> QIcon:
    image = QPixmap(64, 64)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#246aee"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 15, 15)
    painter.setPen(QPen(QColor("white"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for a, b in [((17, 27), (17, 18)), ((17, 18), (27, 18)),
                 ((47, 27), (47, 18)), ((47, 18), (37, 18)),
                 ((17, 37), (17, 46)), ((17, 46), (27, 46)),
                 ((47, 37), (47, 46)), ((47, 46), (37, 46))]:
        painter.drawLine(*a, *b)
    painter.drawLine(26, 33, 38, 33)
    painter.end()
    return QIcon(image)


class CaptureOverlay(QWidget):
    selected = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.screen = screen
        self.snapshot = screen.grabWindow(0)
        self.origin: QPoint | None = None
        self.current: QPoint | None = None
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def selection_rect(self) -> QRect:
        if self.origin is None or self.current is None:
            return QRect()
        return QRect(self.origin, self.current).normalized().adjusted(0, 0, 1, 1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.fillRect(self.rect(), QColor(10, 23, 43, 135))
        rect = self.selection_rect().intersected(self.rect())
        if not rect.isEmpty():
            ratio = self.snapshot.devicePixelRatio()
            source = QRect(round(rect.x() * ratio), round(rect.y() * ratio),
                           round(rect.width() * ratio), round(rect.height() * ratio))
            painter.drawPixmap(rect, self.snapshot, source)
            painter.setPen(QPen(QColor("#8cdbcf"), 2))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            label = f"{rect.width()} × {rect.height()}"
            painter.setPen(QColor("white"))
            painter.drawText(rect.left() + 8, max(25, rect.top() - 10), label)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei UI", 12, QFont.Weight.DemiBold))
        painter.drawText(self.rect().adjusted(0, 22, 0, 0), Qt.AlignmentFlag.AlignHCenter, "拖动选择题目区域  ·  Esc 取消")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.current = self.origin
            self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.current = event.position().toPoint()
        rect = self.selection_rect().intersected(self.rect())
        if rect.width() < 12 or rect.height() < 12:
            self.origin = self.current = None
            self.update()
            return
        ratio = self.snapshot.devicePixelRatio()
        cropped = self.snapshot.copy(QRect(round(rect.x() * ratio), round(rect.y() * ratio),
                                           round(rect.width() * ratio), round(rect.height() * ratio)))
        cropped.setDevicePixelRatio(ratio)
        self.selected.emit(cropped)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


class ApiKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DeepSeek API 设置")
        self.setFixedWidth(440)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 25, 26, 24)
        layout.setSpacing(14)
        title = QLabel("连接 DeepSeek")
        title.setObjectName("section")
        layout.addWidget(title)
        note = QLabel("输入 API Key 后保存在 Windows 凭据管理器。也可以在 .env 中配置。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("sk-...")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setText(get_api_key())
        layout.addWidget(self.key_input)
        reveal = QCheckBox("显示 API Key")
        reveal.toggled.connect(lambda checked: self.key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        layout.addWidget(reveal)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

    def save(self):
        try:
            save_api_key(self.key_input.text())
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.accept()


class RecognitionThread(QThread):
    stage = Signal(str)
    recognized = Signal(str)
    solved = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, image: bytes, solve_enabled: bool):
        super().__init__()
        self.api_key = api_key
        self.image = image
        self.solve_enabled = solve_enabled

    def run(self):
        try:
            self.stage.emit("正在识别并转写题目…")
            markdown = transcribe(self.api_key, self.image)
            self.recognized.emit(markdown)
            if self.solve_enabled:
                self.stage.emit("正在生成题解…")
                self.solved.emit(solve(self.api_key, markdown, self.image))
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"处理失败：{exc}")


class MarkdownCard(QFrame):
    def __init__(self, title: str, placeholder: str):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(19, 18, 19, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("section")
        top.addWidget(label)
        top.addStretch()
        self.copy_button = QPushButton("复制 Markdown")
        self.copy_button.setObjectName("quiet")
        self.copy_button.clicked.connect(self.copy)
        top.addWidget(self.copy_button)
        layout.addLayout(top)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(placeholder)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setFont(QFont("Cascadia Code", 10))
        layout.addWidget(self.editor)

    def copy(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.copy_button.setText("已复制")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1800, lambda: self.copy_button.setText("复制 Markdown"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Snap Solve  ·  v{__version__}")
        self.setWindowIcon(icon())
        self.setMinimumSize(890, 650)
        self.resize(1180, 760)
        self.setStyleSheet(STYLE)
        self.overlays: list[CaptureOverlay] = []
        self.worker: RecognitionThread | None = None
        self.image_bytes: bytes | None = None
        self.preview_pixmap: QPixmap | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        head = QHBoxLayout(header)
        head.setContentsMargins(30, 18, 30, 18)
        logo = QLabel("◩")
        logo.setStyleSheet("color: #246aee; font-size: 29px; font-weight: bold;")
        head.addWidget(logo)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        small = QLabel("SCREEN TO MARKDOWN")
        small.setObjectName("eyebrow")
        name = QLabel("Snap Solve")
        name.setObjectName("title")
        brand.addWidget(small)
        brand.addWidget(name)
        head.addLayout(brand)
        head.addStretch()
        model = QLabel(f"DeepSeek · {setting('DEEPSEEK_MODEL', 'deepseek-flash')}")
        model.setObjectName("pill")
        head.addWidget(model)
        settings = QPushButton("API 设置")
        settings.setObjectName("quiet")
        settings.clicked.connect(self.open_settings)
        head.addWidget(settings)
        outer.addWidget(header)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(30, 25, 30, 22)
        body.setSpacing(20)
        action_row = QHBoxLayout()
        action_row.setSpacing(12)
        self.capture_button = QPushButton("＋  选择屏幕区域")
        self.capture_button.setObjectName("primary")
        self.capture_button.clicked.connect(self.start_capture)
        action_row.addWidget(self.capture_button)
        self.solve_toggle = QCheckBox("同时解题")
        self.solve_toggle.setChecked(True)
        action_row.addWidget(self.solve_toggle)
        action_row.addStretch()
        hint = QLabel("拖动框选题目，自动转写为 Markdown")
        hint.setObjectName("muted")
        action_row.addWidget(hint)
        body.addLayout(action_row)

        columns = QHBoxLayout()
        columns.setSpacing(18)
        left = QFrame()
        left.setObjectName("card")
        left.setMinimumWidth(265)
        left.setMaximumWidth(340)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(19, 18, 19, 18)
        left_layout.setSpacing(14)
        left_title = QLabel("截图预览")
        left_title.setObjectName("section")
        left_layout.addWidget(left_title)
        self.preview = QLabel("尚未选择截图\n\n点击上方按钮开始")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_layout.addWidget(self.preview)
        privacy = QLabel("仅将所选区域发送到 DeepSeek API")
        privacy.setObjectName("muted")
        privacy.setWordWrap(True)
        left_layout.addWidget(privacy)
        columns.addWidget(left, 3)

        right = QVBoxLayout()
        right.setSpacing(18)
        self.question_card = MarkdownCard("题目 · Markdown 源码", "截图中的题目会显示在这里，可编辑、选择和复制。")
        self.solution_card = MarkdownCard("题解 · Markdown 源码", "勾选「同时解题」后，题解会显示在这里。")
        right.addWidget(self.question_card, 1)
        right.addWidget(self.solution_card, 1)
        columns.addLayout(right, 7)
        body.addLayout(columns, 1)
        self.status = QLabel("准备就绪  ·  Ctrl+Shift+A 快速截图")
        self.status.setObjectName("muted")
        body.addWidget(self.status)
        outer.addWidget(content, 1)
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        shortcut.activated.connect(self.start_capture)

    def open_settings(self):
        ApiKeyDialog(self).exec()

    def start_capture(self):
        if self.worker and self.worker.isRunning():
            return
        if not get_api_key():
            if ApiKeyDialog(self).exec() != QDialog.DialogCode.Accepted:
                return
        self.hide()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, self.show_overlays)

    def show_overlays(self):
        self.overlays = []
        for screen in QApplication.screens():
            overlay = CaptureOverlay(screen)
            overlay.selected.connect(self.capture_selected)
            overlay.cancelled.connect(self.cancel_capture)
            self.overlays.append(overlay)
        for overlay in self.overlays:
            overlay.show()
            overlay.raise_()
        if self.overlays:
            self.overlays[0].activateWindow()

    def dismiss_overlays(self):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []
        self.show()
        self.activateWindow()

    def cancel_capture(self):
        self.dismiss_overlays()
        self.status.setText("已取消截图")

    def capture_selected(self, pixmap: QPixmap):
        self.dismiss_overlays()
        if pixmap.isNull():
            self.status.setText("截图失败，请重试")
            return
        output = QByteArray()
        buffer = QBuffer(output)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        buffer.close()
        self.image_bytes = bytes(output)
        self.preview_pixmap = pixmap
        self.update_preview()
        self.question_card.editor.clear()
        self.solution_card.editor.clear()
        self.capture_button.setEnabled(False)
        self.worker = RecognitionThread(get_api_key(), self.image_bytes, self.solve_toggle.isChecked())
        self.worker.stage.connect(self.status.setText)
        self.worker.recognized.connect(self.question_card.editor.setPlainText)
        self.worker.solved.connect(self.solution_card.editor.setPlainText)
        self.worker.failed.connect(self.on_error)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_error(self, message: str):
        self.status.setText(message)
        QMessageBox.warning(self, "处理失败", message)

    def on_finished(self):
        self.capture_button.setEnabled(True)
        if self.status.text().startswith("正在"):
            self.status.setText("处理完成  ·  可编辑或复制 Markdown 源码")
        if self.worker:
            self.worker.deleteLater()
            self.worker = None

    def update_preview(self):
        if self.preview_pixmap:
            self.preview.setPixmap(self.preview_pixmap.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "正在处理", "请等待本次识别或解题完成后再关闭。")
            event.ignore()
        else:
            super().closeEvent(event)

