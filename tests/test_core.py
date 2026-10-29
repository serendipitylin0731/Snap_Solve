import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from snap_solve import deepseek
from snap_solve.ui import MainWindow


class FakeResponse:
    def __init__(self, payload):
        self.content = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self.content

    def __exit__(self, *_):
        self.content.close()


class DeepSeekTests(unittest.TestCase):
    def test_image_request_and_markdown_response(self):
        captured = []

        def fake_urlopen(request, timeout):
            captured.append(request)
            self.assertEqual(timeout, 120)
            return FakeResponse({"choices": [{"message": {"content": "  # 题目\n\n$x^2$  "}, "finish_reason": "stop"}]})

        with patch.object(deepseek, "urlopen", fake_urlopen):
            result = deepseek.transcribe("test-key", b"\x89PNG\r\n")
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
                deepseek.transcribe("bad-key", b"image")


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
        self.assertTrue(window.solve_toggle.isChecked())
        window.close()

    def test_capture_to_both_markdown_boxes(self):
        window = MainWindow()
        window.show()
        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe", return_value="# 测试题"), \
             patch("snap_solve.ui.solve", return_value="## 解答"):
            window.start_capture()
            QTest.qWait(400)
            self.assertTrue(window.overlays)
            overlay = window.overlays[0]
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(30, 45))
            QTest.mouseMove(overlay, QPoint(210, 165))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(210, 165))
            for _ in range(30):
                QTest.qWait(100)
                if window.worker is None:
                    break
            self.assertEqual(window.question_card.editor.toPlainText(), "# 测试题")
            self.assertEqual(window.solution_card.editor.toPlainText(), "## 解答")
            self.assertTrue(window.image_bytes.startswith(b"\x89PNG"))
        window.close()


if __name__ == "__main__":
    unittest.main()

