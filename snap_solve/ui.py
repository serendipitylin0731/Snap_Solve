"""Windows-friendly Qt interface and interactive screen selection."""

from __future__ import annotations

import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from .capture import exclude_window_from_capture, foreground_window, restore_foreground
from .config import get_api_key, save_api_key, setting
from .deepseek import SOLVE_EFFORTS, DeepSeekError, StreamCancelled, solve_stream, transcribe_stream
from .hotkey import (DEFAULT_SHORTCUT, HOTKEY_ID, WM_HOTKEY, load_shortcut,
                     register_hotkey, save_shortcut, unregister_hotkey, windows_hotkey)
from .monitor import POLL_MILLISECONDS, STABLE_SECONDS, has_meaningful_change, image_signature
from .theme import DARK, LIGHT, load_theme_mode, match_native_caption, save_theme_mode, style_sheet, uses_dark_colors


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


class RegionFrame(QWidget):
    """A resizeable outline with a mouse-transparent interior."""

    interaction_started = Signal()
    interaction_finished = Signal(QRect, bool)
    MARGIN = 8
    HIT = 12
    MIN_SIZE = 12

    def __init__(self, screen, region: QRect):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.screen_ref = screen
        self.region = QRect(region)
        self.drag_part = None
        self.drag_origin = QPoint()
        self.drag_region = QRect()
        self.capture_excluded = False
        self.update_geometry()

    def update_geometry(self):
        geometry = self.screen_ref.geometry()
        margin = self.MARGIN
        self.setGeometry(geometry.x() + self.region.x() - margin,
                         geometry.y() + self.region.y() - margin,
                         self.region.width() + margin * 2, self.region.height() + margin * 2)
        inner = QRect(margin + 4, margin + 4, self.region.width() - 8, self.region.height() - 8)
        self.setMask(QRegion(self.rect()).subtracted(QRegion(inner)))
        self.update()

    def hit_part(self, point: QPoint) -> str:
        left, right = point.x() < self.HIT, point.x() >= self.width() - self.HIT
        top, bottom = point.y() < self.HIT, point.y() >= self.height() - self.HIT
        if top and left: return "top_left"
        if top and right: return "top_right"
        if bottom and left: return "bottom_left"
        if bottom and right: return "bottom_right"
        if top and abs(point.x() - self.width() // 2) <= 25: return "move"
        if top: return "top"
        if bottom: return "bottom"
        if left: return "left"
        if right: return "right"
        return "move"

    def set_part_cursor(self, part: str):
        cursors = {"top_left": Qt.CursorShape.SizeFDiagCursor, "bottom_right": Qt.CursorShape.SizeFDiagCursor,
                   "top_right": Qt.CursorShape.SizeBDiagCursor, "bottom_left": Qt.CursorShape.SizeBDiagCursor,
                   "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
                   "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
                   "move": Qt.CursorShape.SizeAllCursor}
        self.setCursor(cursors[part])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_part = self.hit_part(event.position().toPoint())
            self.drag_origin = event.globalPosition().toPoint()
            self.drag_region = QRect(self.region)
            self.set_part_cursor(self.drag_part)
            self.interaction_started.emit()

    def mouseMoveEvent(self, event):
        if self.drag_part is None:
            self.set_part_cursor(self.hit_part(event.position().toPoint()))
            return
        delta = event.globalPosition().toPoint() - self.drag_origin
        rect = QRect(self.drag_region)
        bounds = self.screen_ref.geometry()
        max_x, max_y = bounds.width() - 1, bounds.height() - 1
        if self.drag_part == "move":
            x = max(0, min(rect.x() + delta.x(), max_x - rect.width() + 1))
            y = max(0, min(rect.y() + delta.y(), max_y - rect.height() + 1))
            rect.moveTo(x, y)
        else:
            if "left" in self.drag_part:
                rect.setLeft(max(0, min(rect.left() + delta.x(), rect.right() - self.MIN_SIZE + 1)))
            if "right" in self.drag_part:
                rect.setRight(min(max_x, max(rect.right() + delta.x(), rect.left() + self.MIN_SIZE - 1)))
            if "top" in self.drag_part:
                rect.setTop(max(0, min(rect.top() + delta.y(), rect.bottom() - self.MIN_SIZE + 1)))
            if "bottom" in self.drag_part:
                rect.setBottom(min(max_y, max(rect.bottom() + delta.y(), rect.top() + self.MIN_SIZE - 1)))
        self.region = rect
        self.update_geometry()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_part is not None:
            self.drag_part = None
            self.interaction_finished.emit(QRect(self.region), self.region != self.drag_region)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#246aee"), 2))
        rect = QRect(self.MARGIN, self.MARGIN, self.region.width(), self.region.height())
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.setBrush(QColor("white"))
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight(),
                      QPoint(rect.center().x(), rect.top()), QPoint(rect.center().x(), rect.bottom()),
                      QPoint(rect.left(), rect.center().y()), QPoint(rect.right(), rect.center().y())):
            painter.drawEllipse(point, 4, 4)
        painter.setPen(QPen(QColor("#246aee"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(rect.center().x() - 15, rect.top() - 5, rect.center().x() + 15, rect.top() - 5)

    def showEvent(self, event):
        super().showEvent(event)
        self.capture_excluded = exclude_window_from_capture(int(self.winId()))


class ThemeComboBox(QComboBox):
    def __init__(self, dark: bool):
        super().__init__()
        self.arrow_color = QColor((DARK if dark else LIGHT)["muted"])

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.arrow_color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 22, self.height() // 2
        painter.drawLine(x - 5, y - 2, x, y + 3)
        painter.drawLine(x, y + 3, x + 5, y - 2)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedWidth(470)
        self.setStyleSheet(style_sheet(parent.dark_mode))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 25, 26, 24)
        layout.setSpacing(14)
        title = QLabel("DeepSeek API Key")
        title.setObjectName("section")
        layout.addWidget(title)
        note = QLabel("在应用中填写的 Key 保存在 Windows 凭据管理器；也可以使用 .env。")
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

        shortcut_label = QLabel("截图快捷键")
        shortcut_label.setObjectName("section")
        layout.addWidget(shortcut_label)
        shortcut_row = QHBoxLayout()
        self.shortcut_input = QKeySequenceEdit(parent.hotkey_sequence)
        self.shortcut_input.setMaximumSequenceLength(1)
        self.shortcut_input.setClearButtonEnabled(True)
        shortcut_row.addWidget(self.shortcut_input, 1)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(lambda: self.shortcut_input.setKeySequence(QKeySequence(DEFAULT_SHORTCUT)))
        shortcut_row.addWidget(reset)
        layout.addLayout(shortcut_row)
        shortcut_note = QLabel("全局生效；支持 Ctrl、Alt、Shift + 字母、数字或 F1–F11。")
        shortcut_note.setObjectName("muted")
        layout.addWidget(shortcut_note)

        theme_label = QLabel("外观")
        theme_label.setObjectName("section")
        layout.addWidget(theme_label)
        self.theme_input = ThemeComboBox(parent.dark_mode)
        self.theme_input.addItem("跟随系统", "system")
        self.theme_input.addItem("浅色", "light")
        self.theme_input.addItem("深色", "dark")
        self.theme_input.setCurrentIndex(self.theme_input.findData(parent.theme_mode))
        layout.addWidget(self.theme_input)

        self.bring_to_front_input = QCheckBox("选区完成后将主窗口显示在最前")
        self.bring_to_front_input.setChecked(parent.bring_to_front_after_capture)
        layout.addWidget(self.bring_to_front_input)

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
            sequence = self.shortcut_input.keySequence()
            windows_hotkey(sequence)
            if self.key_input.text().strip():
                save_api_key(self.key_input.text())
            self.parent().bind_shortcut(sequence, persist=True, strict=True)
            self.parent().set_theme_mode(self.theme_input.currentData())
            self.parent().set_bring_to_front(self.bring_to_front_input.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        match_native_caption(self, self.parent().dark_mode)


class RecognitionThread(QThread):
    stage = Signal(str)
    recognized = Signal(str)
    solved = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, image: bytes, transcribe_enabled: bool,
                 solve_enabled: bool, solve_effort: str):
        super().__init__()
        self.api_key = api_key
        self.image = image
        self.transcribe_enabled = transcribe_enabled
        self.solve_enabled = solve_enabled
        self.solve_effort = solve_effort
        self.cancel_requested = False

    def run(self):
        try:
            markdown = None
            if self.transcribe_enabled:
                self.stage.emit("正在流式转写题目…")
                last_question_emit = 0.0

                def question_update(text: str):
                    nonlocal last_question_emit
                    now = time.monotonic()
                    if not self.cancel_requested and now - last_question_emit >= 0.08:
                        self.recognized.emit(text)
                        last_question_emit = now

                markdown = transcribe_stream(self.api_key, self.image,
                                             question_update,
                                             cancelled=lambda: self.cancel_requested)
                if self.cancel_requested:
                    return
                self.recognized.emit(markdown)
            if self.solve_enabled:
                self.stage.emit("题目已转写 · 正在仔细解题…" if self.transcribe_enabled else
                                "正在根据截图仔细解题…")
                last_solution_emit = 0.0

                def solution_update(text: str):
                    nonlocal last_solution_emit
                    now = time.monotonic()
                    if not self.cancel_requested and now - last_solution_emit >= 0.08:
                        self.solved.emit(text)
                        last_solution_emit = now

                solution = solve_stream(self.api_key, markdown, self.image,
                                        solution_update,
                                        cancelled=lambda: self.cancel_requested,
                                        effort=self.solve_effort)
                if not self.cancel_requested:
                    self.solved.emit(solution)
        except StreamCancelled:
            pass
        except DeepSeekError as exc:
            if not self.cancel_requested:
                self.failed.emit(str(exc))
        except Exception as exc:
            if not self.cancel_requested:
                self.failed.emit(f"处理失败：{exc}")


class MarkdownCard(QFrame):
    def __init__(self, title: str, placeholder: str, accent: str):
        super().__init__()
        self.setObjectName(f"{accent}Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(19, 18, 19, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName(f"{accent}Section")
        top.addWidget(label)
        top.addStretch()
        self.copy_button = QPushButton("复制 Markdown")
        self.copy_button.setObjectName("quiet")
        self.copy_button.clicked.connect(self.copy)
        self.copy_reset_timer = QTimer(self)
        self.copy_reset_timer.setSingleShot(True)
        self.copy_reset_timer.timeout.connect(lambda: self.copy_button.setText("复制 Markdown"))
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
        self.copy_reset_timer.start(1800)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Snap Solve")
        self.setWindowIcon(icon())
        self.setMinimumSize(890, 650)
        self.resize(1180, 760)
        self.theme_mode = load_theme_mode()
        self.dark_mode = uses_dark_colors(self.theme_mode)
        self.setStyleSheet(style_sheet(self.dark_mode))
        QApplication.styleHints().colorSchemeChanged.connect(self.on_system_color_scheme_changed)
        self.overlays: list[CaptureOverlay] = []
        self.worker: RecognitionThread | None = None
        self.pending_single_pixmap: QPixmap | None = None
        self.single_shot_active = False
        self.capture_excluded = False
        self.capture_in_progress = False
        self.previous_foreground = None
        self.hotkey_sequence = load_shortcut()
        self.hotkey_registered = False
        self.hotkey_initialized = False
        self.shortcut_editing = False
        self.bring_to_front_after_capture = QSettings("Snap Solve", "Snap Solve").value(
            "bring_to_front_after_capture", False, type=bool)
        self.region_screen = None
        self.region_rect: QRect | None = None
        self.region_frame: RegionFrame | None = None
        self.last_signature: bytes | None = None
        self.processed_signature: bytes | None = None
        self.last_changed_at = 0.0
        self.candidate_pixmap: QPixmap | None = None
        self.generation = 0
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(POLL_MILLISECONDS)
        self.monitor_timer.timeout.connect(self.poll_region)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        head = QHBoxLayout(header)
        head.setContentsMargins(30, 23, 30, 10)
        head.setSpacing(12)
        logo = QLabel()
        logo.setObjectName("brandIcon")
        logo.setFixedSize(42, 42)
        logo.setPixmap(icon().pixmap(42, 42))
        head.addWidget(logo)
        name = QLabel("Snap Solve")
        name.setObjectName("title")
        head.addWidget(name)
        head.addStretch()
        settings = QPushButton("设置")
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
        self.monitor_toggle = QCheckBox("持续监测")
        self.monitor_toggle.setChecked(True)
        self.monitor_toggle.toggled.connect(self.on_monitor_toggled)
        action_row.addWidget(self.monitor_toggle)
        self.transcribe_toggle = QCheckBox("转写题目")
        self.transcribe_toggle.setChecked(True)
        self.transcribe_toggle.toggled.connect(self.on_transcribe_toggled)
        action_row.addWidget(self.transcribe_toggle)
        self.solve_toggle = QCheckBox("解题")
        self.solve_toggle.toggled.connect(self.on_solve_toggled)
        action_row.addWidget(self.solve_toggle)
        action_row.addStretch()
        hint = QLabel("拖动边框调整选区  ·  顶部短横可移动")
        hint.setObjectName("muted")
        action_row.addWidget(hint)
        body.addLayout(action_row)

        self.effort_panel = QWidget()
        effort_row = QHBoxLayout(self.effort_panel)
        effort_row.setContentsMargins(0, 0, 0, 0)
        effort_row.setSpacing(12)
        effort_row.addWidget(QLabel("思考强度"))
        effort_row.addWidget(QLabel("低"))
        self.effort_slider = QSlider(Qt.Orientation.Horizontal)
        self.effort_slider.setRange(0, len(SOLVE_EFFORTS) - 1)
        self.effort_slider.setSingleStep(1)
        self.effort_slider.setPageStep(1)
        self.effort_slider.setFixedWidth(200)
        saved_effort = QSettings("Snap Solve", "Snap Solve").value(
            "solve_effort", setting("DEEPSEEK_SOLVE_EFFORT", "high"))
        if saved_effort not in SOLVE_EFFORTS:
            saved_effort = "high"
        self.effort_slider.setValue(SOLVE_EFFORTS.index(saved_effort))
        self.effort_slider.valueChanged.connect(self.on_solve_effort_changed)
        effort_row.addWidget(self.effort_slider)
        effort_row.addWidget(QLabel("最高"))
        self.effort_label = QLabel(f"当前：{('低', '高', '最高')[self.effort_slider.value()]}")
        self.effort_label.setObjectName("solutionSection")
        effort_row.addWidget(self.effort_label)
        effort_note = QLabel("强度越高，耗时和费用可能增加")
        effort_note.setObjectName("muted")
        effort_row.addWidget(effort_note)
        effort_row.addStretch()
        self.effort_panel.hide()
        body.addWidget(self.effort_panel)

        results = QHBoxLayout()
        results.setSpacing(18)
        self.question_card = MarkdownCard("题目 · Markdown 源码", "截图中的题目会显示在这里，可编辑、选择和复制。", "question")
        self.solution_card = MarkdownCard("题解 · Markdown 源码", "截图中的题解会显示在这里，可编辑、选择和复制。", "solution")
        results.addWidget(self.question_card, 1)
        results.addWidget(self.solution_card, 1)
        self.solution_card.hide()
        body.addLayout(results, 1)
        self.status = QLabel(f"准备就绪  ·  {self.hotkey_sequence.toString()} 选择区域")
        self.status.setObjectName("muted")
        body.addWidget(self.status)
        outer.addWidget(content, 1)
        self.local_shortcut = QShortcut(self.hotkey_sequence, self)
        self.local_shortcut.activated.connect(self.start_capture)

    def set_theme_mode(self, mode: str) -> None:
        save_theme_mode(mode)
        self.theme_mode = mode
        self.apply_theme()

    def set_bring_to_front(self, enabled: bool) -> None:
        self.bring_to_front_after_capture = enabled
        QSettings("Snap Solve", "Snap Solve").setValue("bring_to_front_after_capture", enabled)

    def on_system_color_scheme_changed(self, _scheme) -> None:
        if self.theme_mode == "system":
            self.apply_theme()

    def apply_theme(self) -> None:
        self.dark_mode = uses_dark_colors(self.theme_mode)
        self.setStyleSheet(style_sheet(self.dark_mode))
        match_native_caption(self, self.dark_mode)

    def open_settings(self):
        self.shortcut_editing = True
        if self.hotkey_registered:
            unregister_hotkey(int(self.winId()))
            self.hotkey_registered = False
        self.local_shortcut.setEnabled(False)
        try:
            result = SettingsDialog(self).exec()
        finally:
            self.shortcut_editing = False
            if not self.hotkey_registered:
                self.bind_shortcut(self.hotkey_sequence)
            self.local_shortcut.setEnabled(not self.hotkey_registered)
        return result

    def bind_shortcut(self, sequence: QKeySequence, *, persist: bool = False,
                      strict: bool = False) -> None:
        windows_hotkey(sequence)
        previous = self.hotkey_sequence
        if self.hotkey_registered:
            unregister_hotkey(int(self.winId()))
            self.hotkey_registered = False
        registered = register_hotkey(int(self.winId()), sequence)
        if strict and sys.platform == "win32" and not registered:
            self.hotkey_registered = register_hotkey(int(self.winId()), previous)
            self.local_shortcut.setKey(previous)
            self.local_shortcut.setEnabled(not self.hotkey_registered and not self.shortcut_editing)
            raise ValueError("快捷键已被其他程序占用，请换一组")
        self.hotkey_sequence = sequence
        self.hotkey_registered = registered
        self.local_shortcut.setKey(sequence)
        self.local_shortcut.setEnabled(not registered and not self.shortcut_editing)
        if persist:
            save_shortcut(sequence)
        prefix = "全局快捷键" if registered else "窗口快捷键（全局组合被占用）"
        self.status.setText(f"{prefix}：{sequence.toString()}  ·  选择屏幕区域")

    def start_capture(self):
        if self.capture_in_progress or QApplication.activeModalWidget() is not None:
            return
        if not get_api_key():
            if self.open_settings() != QDialog.DialogCode.Accepted or not get_api_key():
                return
        self.capture_in_progress = True
        self.monitor_timer.stop()
        if self.region_frame:
            self.region_frame.hide()
        self.hide()
        QTimer.singleShot(250, self.show_overlays)

    def show_overlays(self):
        self.previous_foreground = foreground_window()
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

    def dismiss_overlays(self, *, bring_to_front: bool = False):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []
        self.capture_in_progress = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not bring_to_front)
        self.show()
        if bring_to_front:
            self.raise_()
            self.activateWindow()
        else:
            self.lower()
            previous = self.previous_foreground
            if previous and previous != int(self.winId()):
                QTimer.singleShot(0, lambda: restore_foreground(previous))
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

    def cancel_capture(self):
        self.dismiss_overlays()
        if self.region_rect and self.monitor_toggle.isChecked():
            self.monitor_timer.start()
            if self.region_frame:
                self.region_frame.show()
            self.status.setText("已取消重新选区，继续监测原区域")
        else:
            if self.region_frame:
                self.region_frame.show()
            self.status.setText("已取消选择区域")

    def capture_selected(self, pixmap: QPixmap):
        overlay = self.sender()
        screen = overlay.screen if isinstance(overlay, CaptureOverlay) else None
        region = overlay.selection_rect() if isinstance(overlay, CaptureOverlay) else QRect()
        self.dismiss_overlays(bring_to_front=self.bring_to_front_after_capture)
        if pixmap.isNull() or screen is None or region.isEmpty():
            self.status.setText("截图失败，请重试")
            return
        if self.region_frame:
            self.region_frame.close()
            self.region_frame.deleteLater()
            self.region_frame = None
        self.candidate_pixmap = pixmap
        self.generation += 1
        if self.worker:
            self.worker.cancel_requested = True
        self.question_card.editor.clear()
        self.solution_card.editor.clear()
        self.region_screen = screen
        self.region_rect = region
        self.region_frame = RegionFrame(screen, region)
        self.region_frame.interaction_started.connect(self.on_region_interaction_started)
        self.region_frame.interaction_finished.connect(self.on_region_interaction_finished)
        if not self.capture_excluded:
            self.move_away_from_region()
        self.region_frame.show()
        if self.monitor_toggle.isChecked():
            self.single_shot_active = False
            self.pending_single_pixmap = None
            self.last_signature = image_signature(pixmap)
            self.processed_signature = None
            self.last_changed_at = time.monotonic()
            self.monitor_timer.start()
            self.status.setText("监测中 · 拖动边框可调整选区")
        else:
            self.last_signature = None
            self.processed_signature = None
            self.single_shot_active = True
            self.pending_single_pixmap = pixmap
            self.start_pending_single_shot()

    def on_region_interaction_started(self):
        self.monitor_timer.stop()
        self.status.setText("正在调整选区…")

    def on_region_interaction_finished(self, region: QRect, changed: bool):
        self.region_rect = region
        if not changed:
            if self.monitor_toggle.isChecked():
                self.monitor_timer.start()
                self.status.setText("监测中 · 拖动边框可调整选区")
            else:
                self.status.setText("单次模式 · 拖动边框可调整选区")
            return
        self.generation += 1
        self.pending_single_pixmap = None
        self.processed_signature = None
        if self.worker:
            self.worker.cancel_requested = True
        if not self.capture_excluded:
            self.move_away_from_region()
        pixmap = self.capture_region()
        if pixmap.isNull():
            self.status.setText("无法读取区域，请重新选择屏幕")
            return
        self.candidate_pixmap = pixmap
        if self.monitor_toggle.isChecked():
            self.single_shot_active = False
            self.last_signature = image_signature(pixmap)
            self.processed_signature = None
            self.last_changed_at = time.monotonic()
            self.monitor_timer.start()
            self.status.setText("选区已调整 · 等待画面稳定…")
        else:
            self.single_shot_active = True
            self.pending_single_pixmap = pixmap
            self.start_pending_single_shot()

    def start_pending_single_shot(self):
        if self.pending_single_pixmap is None or self.worker is not None:
            if self.pending_single_pixmap is not None:
                self.status.setText("正在结束上一次请求，随后识别新截图…")
            return
        pixmap = self.pending_single_pixmap
        self.pending_single_pixmap = None
        self.status.setText("单次截图已选取 · 正在转写…")
        self.start_recognition(pixmap)

    def move_away_from_region(self):
        """Keep the app itself out of the monitored pixels when space permits."""
        if self.region_screen is None or self.region_rect is None:
            return
        screen_geometry = self.region_screen.geometry()
        target = self.region_rect.translated(screen_geometry.topLeft())
        window = self.frameGeometry()
        if not window.intersects(target):
            return
        candidates = []
        for screen in QApplication.screens():
            available = screen.availableGeometry()
            width, height = window.width(), window.height()
            positions = [
                QPoint(available.left(), available.top()),
                QPoint(available.right() - width + 1, available.top()),
                QPoint(available.left(), available.bottom() - height + 1),
                QPoint(available.right() - width + 1, available.bottom() - height + 1),
                QPoint(target.right() + 16, target.top()),
                QPoint(target.left() - width - 16, target.top()),
                QPoint(target.left(), target.bottom() + 16),
                QPoint(target.left(), target.top() - height - 16),
            ]
            for point in positions:
                x = max(available.left(), min(point.x(), available.right() - width + 1))
                y = max(available.top(), min(point.y(), available.bottom() - height + 1))
                candidate = QRect(x, y, width, height)
                overlap = candidate.intersected(target)
                overlap_area = overlap.width() * overlap.height()
                distance = abs(x - window.x()) + abs(y - window.y())
                candidates.append((overlap_area, distance, x, y))
        if candidates:
            _, _, x, y = min(candidates)
            self.move(x, y)

    def on_monitor_toggled(self, enabled: bool):
        self.generation += 1
        if self.worker:
            self.worker.cancel_requested = True
        self.single_shot_active = False
        self.pending_single_pixmap = None
        if not enabled:
            self.monitor_timer.stop()
            self.status.setText("单次模式 · 选取或调整选区后识别一次")
            return
        if not self.region_rect:
            self.status.setText("监测已开启 · 请先选择屏幕区域")
            return
        self.processed_signature = None
        self.last_changed_at = time.monotonic()
        if self.region_frame:
            self.region_frame.show()
        self.monitor_timer.start()
        self.status.setText("监测中 · 等待画面稳定…")

    def on_transcribe_toggled(self, enabled: bool):
        self.question_card.editor.clear()
        if not enabled and not self.solve_toggle.isChecked():
            blocked = self.solve_toggle.blockSignals(True)
            self.solve_toggle.setChecked(True)
            self.solve_toggle.blockSignals(blocked)
            self.solution_card.editor.clear()
        self.update_mode()

    def on_solve_toggled(self, enabled: bool):
        self.solution_card.editor.clear()
        if not enabled and not self.transcribe_toggle.isChecked():
            blocked = self.transcribe_toggle.blockSignals(True)
            self.transcribe_toggle.setChecked(True)
            self.transcribe_toggle.blockSignals(blocked)
            self.question_card.editor.clear()
        self.update_mode()

    def on_solve_effort_changed(self, value: int):
        self.effort_label.setText(f"当前：{('低', '高', '最高')[value]}")
        QSettings("Snap Solve", "Snap Solve").setValue("solve_effort", SOLVE_EFFORTS[value])
        if self.solve_toggle.isChecked() and self.monitor_toggle.isChecked() and self.region_rect:
            self.update_mode()
        elif self.solve_toggle.isChecked() and not self.monitor_toggle.isChecked() and self.worker is None:
            self.status.setText("思考强度已更新 · 下次解题时生效")

    def update_mode(self):
        self.question_card.setVisible(self.transcribe_toggle.isChecked())
        self.solution_card.setVisible(self.solve_toggle.isChecked())
        self.effort_panel.setVisible(self.solve_toggle.isChecked())
        self.generation += 1
        if self.worker:
            self.worker.cancel_requested = True
        self.pending_single_pixmap = None
        self.processed_signature = None
        self.last_changed_at = time.monotonic()
        if self.region_rect and self.monitor_toggle.isChecked():
            self.status.setText("模式已更新 · 等待画面稳定…")
        elif not self.monitor_toggle.isChecked():
            self.status.setText("模式已更新 · 下次选取或调整选区时生效")

    def capture_region(self) -> QPixmap:
        if self.region_screen is None or self.region_rect is None:
            return QPixmap()
        if self.region_screen not in QApplication.screens():
            return QPixmap()
        rect = self.region_rect
        frame = self.region_frame
        hidden = frame is not None and frame.isVisible() and not frame.capture_excluded
        if hidden:
            frame.hide()
            QApplication.processEvents()
        try:
            return self.region_screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        finally:
            if hidden:
                frame.show()

    def poll_region(self):
        if not self.monitor_toggle.isChecked() or self.region_rect is None:
            return
        if (not self.capture_excluded and self.region_screen is not None and self.isVisible() and
                self.frameGeometry().intersects(
                    self.region_rect.translated(self.region_screen.geometry().topLeft()))):
            self.status.setText("应用窗口挡住了监测区域，请将窗口移到选区外")
            return
        pixmap = self.capture_region()
        if pixmap.isNull():
            self.monitor_timer.stop()
            self.status.setText("无法读取区域，请重新选择屏幕")
            return
        signature = image_signature(pixmap)
        if has_meaningful_change(self.last_signature, signature):
            self.last_signature = signature
            self.last_changed_at = time.monotonic()
            self.candidate_pixmap = pixmap
            self.generation += 1
            if self.worker:
                self.worker.cancel_requested = True
            self.status.setText("检测到画面变化 · 等待稳定…")
            return
        if (time.monotonic() - self.last_changed_at >= STABLE_SECONDS and
                self.processed_signature != self.last_signature and
                self.worker is None):
            if not get_api_key():
                self.monitor_toggle.setChecked(False)
                self.status.setText("请先在「设置」填写 DeepSeek Key")
                return
            self.processed_signature = self.last_signature
            self.start_recognition(self.candidate_pixmap if self.candidate_pixmap is not None else pixmap)

    def start_recognition(self, pixmap: QPixmap):
        max_side = max(pixmap.width(), pixmap.height())
        if max_side > 1800:
            pixmap = pixmap.scaled(1800, 1800, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        output = QByteArray()
        buffer = QBuffer(output)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        buffer.close()
        generation = self.generation
        worker = RecognitionThread(get_api_key(), bytes(output), self.transcribe_toggle.isChecked(),
                                   self.solve_toggle.isChecked(), SOLVE_EFFORTS[self.effort_slider.value()])
        self.worker = worker
        worker.stage.connect(lambda message: self.show_stage(generation, message))
        worker.recognized.connect(lambda text: self.show_question(generation, text))
        worker.solved.connect(lambda text: self.show_solution(generation, text))
        worker.failed.connect(lambda message: self.on_error(generation, message))
        worker.finished.connect(lambda: self.on_finished(generation, worker))
        worker.start()

    def is_current(self, generation: int) -> bool:
        return generation == self.generation

    def show_stage(self, generation: int, message: str):
        if self.is_current(generation):
            self.status.setText(message)

    def show_question(self, generation: int, text: str):
        if self.is_current(generation) and self.transcribe_toggle.isChecked():
            self.question_card.editor.setPlainText(text)

    def show_solution(self, generation: int, text: str):
        if self.is_current(generation) and self.solve_toggle.isChecked():
            self.solution_card.editor.setPlainText(text)

    def on_error(self, generation: int, message: str):
        if self.is_current(generation):
            retry = "重新选区后可重试" if self.single_shot_active else "画面变化或重启监测后可重试"
            self.status.setText(message + " · " + retry)

    def on_finished(self, generation: int, worker: RecognitionThread):
        if self.is_current(generation) and self.status.text().startswith(("正在", "题目已转写")):
            result = "解题" if self.solve_toggle.isChecked() else "转写"
            self.status.setText(f"单次{result}完成 · 可再次选区" if self.single_shot_active else
                                f"监测中 · {result}完成，等待画面变化")
        if self.worker is worker:
            worker.deleteLater()
            self.worker = None
        if self.pending_single_pixmap is not None:
            QTimer.singleShot(0, self.start_pending_single_shot)
            return
        if self.single_shot_active:
            self.single_shot_active = False
        if self.monitor_timer.isActive():
            QTimer.singleShot(0, self.poll_region)

    def showEvent(self, event):
        super().showEvent(event)
        match_native_caption(self, self.dark_mode)
        self.capture_excluded = exclude_window_from_capture(int(self.winId()))
        if not self.hotkey_initialized:
            self.hotkey_initialized = True
            self.bind_shortcut(self.hotkey_sequence)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            try:
                native = wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                native = None
            if native is not None and native.message == WM_HOTKEY and native.wParam == HOTKEY_ID:
                if not self.shortcut_editing:
                    QTimer.singleShot(0, self.start_capture)
                return True, 0
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "正在处理", "请等待本次识别或解题完成后再关闭。")
            event.ignore()
        else:
            self.monitor_timer.stop()
            if self.region_frame:
                self.region_frame.close()
            if self.hotkey_registered:
                unregister_hotkey(int(self.winId()))
                self.hotkey_registered = False
            super().closeEvent(event)

