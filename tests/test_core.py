import io
import json
import os
import sys
import time
import ctypes
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QKeySequence, QPixmap
from PySide6.QtTest import QTest

from snap_solve import deepseek
from snap_solve.hotkey import HOTKEY_ID, WM_HOTKEY, MOD_ALT, MOD_CONTROL, windows_hotkey
from snap_solve.monitor import image_signature
from snap_solve.ui import MainWindow


class DeepSeekTests(unittest.TestCase):
    def test_image_request_and_markdown_response(self):
        captured = []

        def fake_urlopen(request, timeout):
            captured.append(request)
            self.assertEqual(timeout, 90)
            chunk = json.dumps({"choices": [{"delta": {"content": "# 题目\n\n$x^2$"}}]})
            return FakeResponseStream(f"data: {chunk}\n\ndata: [DONE]\n\n".encode())

        with patch.object(deepseek, "urlopen", fake_urlopen):
            result = deepseek.transcribe_stream("test-key", b"\x89PNG\r\n", lambda text: None)
        self.assertEqual(result, "# 题目\n\n$x^2$")
        body = json.loads(captured[0].data)
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertTrue(body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(captured[0].get_header("Authorization"), "Bearer test-key")

    def test_api_error_is_readable(self):
        payload = io.BytesIO(b'{"error":{"message":"Invalid API key"}}')
        failure = HTTPError("https://api.deepseek.com/chat/completions", 401, "Unauthorized", {}, payload)
        with patch.object(deepseek, "urlopen", side_effect=failure):
            with self.assertRaisesRegex(deepseek.DeepSeekError, "401.*Invalid API key"):
                deepseek.transcribe_stream("bad-key", b"image", lambda text: None)

    def test_streaming_ocr_is_fast_and_solution_thinks(self):
        seen = []
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data))
            content = "# 题目" if len(requests) == 1 else "## 解答"
            chunks = [{"choices": [{"delta": {"content": content}}]}]
            lines = "".join("data: " + json.dumps(item) + "\n\n" for item in chunks)
            return FakeResponseStream((lines + "data: [DONE]\n\n").encode())

        with patch.object(deepseek, "urlopen", fake_urlopen):
            question = deepseek.transcribe_stream("test-key", b"image", seen.append)
            solution = deepseek.solve_stream("test-key", question, b"image", seen.append)
        self.assertEqual((question, solution), ("# 题目", "## 解答"))
        self.assertEqual(seen, ["# 题目", "## 解答"])
        self.assertTrue(requests[0]["stream"])
        self.assertEqual(requests[0]["thinking"], {"type": "disabled"})
        self.assertEqual(requests[1]["thinking"], {"type": "enabled"})
        self.assertEqual(requests[1]["reasoning_effort"], "high")
        self.assertIn("# 题目", requests[1]["messages"][0]["content"][0]["text"])


class FakeResponseStream:
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def __enter__(self):
        return self.data

    def __exit__(self, *_):
        self.data.close()


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_editable_markdown_and_copy(self):
        window = MainWindow()
        window.question_card.editor.setPlainText("# 题目\n$x^2$")
        window.solution_card.editor.setPlainText("## 解答\n$x=2$")
        window.question_card.copy()
        self.assertEqual(self.app.clipboard().text(), "# 题目\n$x^2$")
        window.solution_card.copy()
        self.assertEqual(self.app.clipboard().text(), "## 解答\n$x=2$")
        self.assertFalse(window.solve_toggle.isChecked())
        window.close()

    def test_header_icon_and_side_by_side_results(self):
        window = MainWindow()
        window.show()
        logo = window.findChild(QLabel, "brandIcon")
        self.assertIsNotNone(logo)
        self.assertFalse(logo.pixmap().isNull())
        self.assertFalse(window.windowIcon().isNull())
        window.solve_toggle.setChecked(True)
        QApplication.processEvents()
        self.assertLess(window.question_card.geometry().right(),
                        window.solution_card.geometry().left())
        window.close()

    def test_shortcut_validation_and_custom_binding(self):
        self.assertEqual(windows_hotkey(QKeySequence("Ctrl+Alt+S")),
                         (MOD_ALT | MOD_CONTROL | 0x4000, ord("S")))
        with self.assertRaises(ValueError):
            windows_hotkey(QKeySequence("S"))
        window = MainWindow()
        window.show()
        sequence = QKeySequence("Ctrl+Alt+F8")
        with patch("snap_solve.ui.register_hotkey", return_value=True), \
             patch("snap_solve.ui.save_shortcut") as saved:
            window.bind_shortcut(sequence, persist=True, strict=True)
            saved.assert_called_once()
        self.assertEqual(window.hotkey_sequence.toString(), "Ctrl+Alt+F8")
        self.assertFalse(window.local_shortcut.isEnabled())
        self.assertIn("Ctrl+Alt+F8", window.status.text())
        window.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows global hotkey")
    def test_windows_hotkey_message_starts_capture(self):
        window = MainWindow()
        window.show()
        with patch.object(window, "start_capture") as capture:
            ok = ctypes.windll.user32.PostMessageW(int(window.winId()), WM_HOTKEY, HOTKEY_ID, 0)
            self.assertTrue(ok)
            QTest.qWait(150)
            capture.assert_called_once()
        window.close()

    def test_capture_to_both_markdown_boxes(self):
        window = MainWindow()
        window.show()
        window.solve_toggle.setChecked(True)

        def fake_transcribe(key, image, update, cancelled):
            update("# 测试题")
            return "# 测试题"

        def fake_solve(key, markdown, image, update, cancelled):
            update("## 解答")
            return "## 解答"

        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe_stream", side_effect=fake_transcribe), \
             patch("snap_solve.ui.solve_stream", side_effect=fake_solve):
            window.start_capture()
            QTest.qWait(400)
            self.assertTrue(window.overlays)
            overlay = window.overlays[0]
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(30, 45))
            QTest.mouseMove(overlay, QPoint(210, 165))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(210, 165))
            selected = window.candidate_pixmap
            self.assertIsNotNone(selected)
            window.capture_region = lambda: selected
            window.last_changed_at = time.monotonic() - 2
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if window.worker is None and window.question_card.editor.toPlainText():
                    break
            self.assertEqual(window.question_card.editor.toPlainText(), "# 测试题")
            self.assertEqual(window.solution_card.editor.toPlainText(), "## 解答")
            self.assertTrue(window.solution_card.isVisible())
            self.assertTrue(window.monitor_timer.isActive())
            window.solve_toggle.setChecked(False)
            self.assertFalse(window.solution_card.isVisible())
            window.monitor_toggle.setChecked(False)
            self.assertFalse(window.monitor_timer.isActive())
        window.close()

    def test_retranscribes_only_after_new_stable_image(self):
        window = MainWindow()
        first = QPixmap(200, 100)
        first.fill(QColor("white"))
        second = QPixmap(200, 100)
        second.fill(QColor("black"))
        window.region_rect = window.rect()
        window.candidate_pixmap = first
        window.last_signature = image_signature(first)
        window.last_changed_at = time.monotonic() - 2
        requests = []

        def fake_stream(key, image, update, cancelled):
            requests.append(image)
            update(f"# 第 {len(requests)} 题")
            return f"# 第 {len(requests)} 题"

        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe_stream", side_effect=fake_stream):
            window.capture_region = lambda: first
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 1 and window.worker is None:
                    break
            self.assertEqual(len(requests), 1)
            window.poll_region()
            self.assertEqual(len(requests), 1)
            window.capture_region = lambda: second
            window.poll_region()
            self.assertEqual(len(requests), 1)
            window.last_changed_at = time.monotonic() - 2
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 2 and window.worker is None:
                    break
            self.assertEqual(len(requests), 2)
            self.assertEqual(window.question_card.editor.toPlainText(), "# 第 2 题")
        window.close()

    def test_single_shot_mode_runs_once_without_region(self):
        window = MainWindow()
        window.show()
        window.monitor_toggle.setChecked(False)
        requests = []

        def fake_stream(key, image, update, cancelled):
            requests.append(image)
            text = f"# 单次题目 {len(requests)}"
            update(text)
            return text

        def fake_solve(key, markdown, image, update, cancelled):
            update("## 单次题解")
            return "## 单次题解"

        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe_stream", side_effect=fake_stream), \
             patch("snap_solve.ui.solve_stream", side_effect=fake_solve):
            window.start_capture()
            QTest.qWait(400)
            overlay = window.overlays[0]
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 50))
            QTest.mouseMove(overlay, QPoint(250, 170))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(250, 170))
            for _ in range(30):
                QTest.qWait(100)
                if requests and window.worker is None:
                    break
            self.assertEqual(window.question_card.editor.toPlainText(), "# 单次题目 1")
            self.assertEqual(len(requests), 1)
            self.assertFalse(window.monitor_timer.isActive())
            self.assertIsNone(window.region_rect)
            self.assertIsNone(window.region_frame)
            QTest.qWait(800)
            self.assertEqual(len(requests), 1)
            window.solve_toggle.setChecked(True)
            window.start_capture()
            QTest.qWait(400)
            overlay = window.overlays[0]
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
            QTest.mouseMove(overlay, QPoint(270, 190))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(270, 190))
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 2 and window.worker is None:
                    break
            self.assertEqual(window.question_card.editor.toPlainText(), "# 单次题目 2")
            self.assertEqual(window.solution_card.editor.toPlainText(), "## 单次题解")
            self.assertEqual(len(requests), 2)
        window.close()

    @unittest.skipUnless(sys.platform == "win32" and sys.getwindowsversion().build >= 19041,
                         "Windows capture exclusion requires Windows 10 2004+")
    def test_app_window_is_excluded_from_screen_grab(self):
        window = MainWindow()
        window.show()
        window.raise_()
        cover = QWidget(window)
        cover.setStyleSheet("background: rgb(250, 0, 0);")
        cover.setGeometry(window.rect())
        cover.show()
        QTest.qWait(300)
        self.assertTrue(window.capture_excluded)
        local = window.rect().center()
        global_point = window.mapToGlobal(local)
        screen = window.screen()
        screen_point = global_point - screen.geometry().topLeft()
        captured = screen.grabWindow(0, screen_point.x(), screen_point.y(), 1, 1)
        r, g, b, _ = captured.toImage().pixelColor(0, 0).getRgb()
        self.assertFalse(r > 200 and g < 40 and b < 40)
        window.close()

    def test_live_screen_stays_on_one_recognition(self):
        window = MainWindow()
        window.show()
        screen = window.screen()
        start = window.mapToGlobal(QPoint(90, 110)) - screen.geometry().topLeft()
        end = window.mapToGlobal(QPoint(310, 240)) - screen.geometry().topLeft()
        requests = []

        def fake_stream(key, image, update, cancelled):
            requests.append(image)
            update("# 实时题目")
            return "# 实时题目"

        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe_stream", side_effect=fake_stream):
            window.start_capture()
            QTest.qWait(400)
            overlay = next(item for item in window.overlays if item.screen is screen)
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(overlay, end)
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=end)
            self.assertTrue(window.frameGeometry().intersects(
                window.region_rect.translated(screen.geometry().topLeft())))
            for _ in range(50):
                QTest.qWait(100)
                if requests and window.worker is None:
                    break
            self.assertEqual(len(requests), 1)
            self.assertEqual(window.question_card.editor.toPlainText(), "# 实时题目")
            QTest.qWait(1100)
            self.assertEqual(len(requests), 1)
            window.monitor_toggle.setChecked(False)
        window.close()


if __name__ == "__main__":
    unittest.main()

