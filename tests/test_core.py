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
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QKeySequence, QPixmap
from PySide6.QtTest import QTest

from snap_solve import deepseek
from snap_solve.hotkey import HOTKEY_ID, WM_HOTKEY, MOD_ALT, MOD_CONTROL, windows_hotkey
from snap_solve.monitor import image_signature
from snap_solve.ui import MainWindow, RegionFrame, SettingsDialog


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
        self.assertIn("行内公式用 $...$，独立公式用 $$...$$", requests[1]["messages"][0]["content"][0]["text"])

    def test_image_only_solution_and_effort_levels(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data))
            chunk = json.dumps({"choices": [{"delta": {"content": "## 解答"}}]})
            return FakeResponseStream(f"data: {chunk}\n\ndata: [DONE]\n\n".encode())

        with patch.object(deepseek, "urlopen", fake_urlopen):
            for effort in ("low", "high", "max"):
                self.assertEqual(deepseek.solve_stream("test-key", None, b"image", lambda _: None,
                                                        effort=effort), "## 解答")
        self.assertEqual([item["reasoning_effort"] for item in requests], ["low", "high", "max"])
        for request in requests:
            contents = request["messages"][0]["content"]
            self.assertNotIn("题目转写：", contents[0]["text"])
            self.assertTrue(contents[1]["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertEqual(request["thinking"], {"type": "enabled"})

    def test_answer_only_uses_distinct_prompt(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data))
            chunk = json.dumps({"choices": [{"delta": {"content": "$x=2$"}}]})
            return FakeResponseStream(f"data: {chunk}\n\ndata: [DONE]\n\n".encode())

        with patch.object(deepseek, "urlopen", fake_urlopen):
            deepseek.solve_stream("test-key", "题目", b"image", lambda _: None, answer_only=True)
            deepseek.solve_stream("test-key", "题目", b"image", lambda _: None, answer_only=False)
        answer_prompt = requests[0]["messages"][0]["content"][0]["text"]
        solution_prompt = requests[1]["messages"][0]["content"][0]["text"]
        self.assertIn("只输出每道题的最终答案", answer_prompt)
        self.assertIn("不要输出解析", answer_prompt)
        self.assertNotIn("说明关键步骤", answer_prompt)
        self.assertIn("说明关键步骤", solution_prompt)
        self.assertIn("行内公式用 $...$，独立公式用 $$...$$", answer_prompt)


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
        self.assertEqual(window.windowTitle(), "Snap Solve")
        logo = window.findChild(QLabel, "brandIcon")
        self.assertIsNotNone(logo)
        self.assertFalse(logo.pixmap().isNull())
        self.assertFalse(window.windowIcon().isNull())
        window.solve_toggle.setChecked(True)
        QApplication.processEvents()
        self.assertLess(window.question_card.geometry().right(),
                        window.solution_card.geometry().left())
        window.close()

    def test_theme_switch_and_settings_selection(self):
        window = MainWindow()
        window.show()
        with patch("snap_solve.ui.save_theme_mode") as saved:
            window.set_theme_mode("dark")
            self.assertTrue(window.dark_mode)
            self.assertIn("#111b2b", window.styleSheet())
            dialog = SettingsDialog(window)
            self.assertEqual(dialog.theme_input.currentData(), "dark")
            dialog.close()
            window.set_theme_mode("light")
            self.assertFalse(window.dark_mode)
            self.assertIn("#f3f7fd", window.styleSheet())
            self.assertEqual(saved.call_count, 2)
        window.close()

    def test_bring_to_front_setting_and_capture_completion(self):
        window = MainWindow()
        window.bring_to_front_after_capture = False
        with patch("snap_solve.ui.get_api_key", return_value=""), \
             patch("snap_solve.ui.QSettings") as settings, \
             patch.object(window, "bind_shortcut"), patch.object(window, "set_theme_mode"):
            dialog = SettingsDialog(window)
            self.assertFalse(dialog.bring_to_front_input.isChecked())
            dialog.bring_to_front_input.setChecked(True)
            dialog.save()
            settings.return_value.setValue.assert_called_with("bring_to_front_after_capture", True)
            self.assertTrue(window.bring_to_front_after_capture)
        with patch.object(window, "raise_") as raise_window, \
             patch.object(window, "activateWindow") as activate_window:
            window.dismiss_overlays(bring_to_front=False)
            raise_window.assert_not_called()
            activate_window.assert_not_called()
            window.dismiss_overlays(bring_to_front=True)
            raise_window.assert_called_once()
            activate_window.assert_called_once()
        window.close()

    def test_region_frame_resizes_and_moves(self):
        frame = RegionFrame(self.app.primaryScreen(), QRect(100, 100, 200, 140))
        frame.show()
        top_left = QPoint(frame.MARGIN, frame.MARGIN)
        QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=top_left)
        QTest.mouseMove(frame, top_left - QPoint(20, 15), delay=50)
        QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=top_left)
        self.assertEqual(frame.region, QRect(80, 85, 220, 155))

        handle = QPoint(frame.width() // 2, frame.MARGIN - 5)
        QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=handle)
        QTest.mouseMove(frame, handle + QPoint(30, 20), delay=50)
        QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=handle)
        self.assertEqual(frame.region, QRect(110, 105, 220, 155))
        frame.close()

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
        requests = []

        def fake_transcribe(key, image, update, cancelled):
            requests.append(image)
            update("# 测试题")
            return "# 测试题"

        def fake_solve(key, markdown, image, update, cancelled, effort, answer_only):
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

            frame = window.region_frame
            self.assertFalse(frame.mask().contains(frame.rect().center()))
            self.assertTrue(frame.mask().contains(QPoint(frame.MARGIN, frame.MARGIN)))
            corner = QPoint(frame.width() - frame.MARGIN, frame.height() - frame.MARGIN)
            old_width = window.region_rect.width()
            QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=corner)
            self.assertFalse(window.monitor_timer.isActive())
            QTest.mouseMove(frame, corner + QPoint(30, 20), delay=50)
            QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=corner + QPoint(30, 20))
            self.assertEqual(window.region_rect.width(), old_width + 30)
            self.assertTrue(window.monitor_timer.isActive())
            window.poll_region()
            self.assertEqual(len(requests), 1)
            window.last_changed_at = time.monotonic() - 2
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 2 and window.worker is None:
                    break
            self.assertEqual(len(requests), 2)
            window.solve_toggle.setChecked(False)
            self.assertFalse(window.solution_card.isVisible())
            window.monitor_toggle.setChecked(False)
            self.assertFalse(window.monitor_timer.isActive())
            self.assertTrue(frame.isVisible())
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

    def test_single_shot_mode_keeps_adjustable_region(self):
        window = MainWindow()
        window.show()
        window.monitor_toggle.setChecked(False)
        requests = []

        def fake_stream(key, image, update, cancelled):
            requests.append(image)
            text = f"# 单次题目 {len(requests)}"
            update(text)
            return text

        def fake_solve(key, markdown, image, update, cancelled, effort, answer_only):
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
            self.assertIsNotNone(window.region_rect)
            self.assertTrue(window.region_frame.isVisible())
            QTest.qWait(800)
            self.assertEqual(len(requests), 1)

            frame = window.region_frame
            original_region = window.region_rect
            corner = QPoint(frame.width() - frame.MARGIN, frame.height() - frame.MARGIN)
            QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=corner)
            QTest.mouseMove(frame, corner + QPoint(35, 25), delay=50)
            QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=corner + QPoint(35, 25))
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 2 and window.worker is None:
                    break
            self.assertEqual(window.region_rect.width(), original_region.width() + 35)
            self.assertEqual(window.region_rect.height(), original_region.height() + 25)
            self.assertEqual(len(requests), 2)
            self.assertFalse(window.monitor_timer.isActive())
            self.assertTrue(frame.isVisible())

            window.solve_toggle.setChecked(True)
            window.start_capture()
            QTest.qWait(400)
            overlay = window.overlays[0]
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
            QTest.mouseMove(overlay, QPoint(270, 190))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(270, 190))
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 3 and window.worker is None:
                    break
            self.assertEqual(window.question_card.editor.toPlainText(), "# 单次题目 3")
            self.assertEqual(window.solution_card.editor.toPlainText(), "## 单次题解")
            self.assertEqual(len(requests), 3)
        window.close()

    def test_solve_only_skips_transcription_and_uses_selected_effort(self):
        window = MainWindow()
        window.show()
        window.monitor_toggle.setChecked(False)
        window.transcribe_toggle.setChecked(False)
        self.assertTrue(window.solve_toggle.isChecked())
        self.assertFalse(window.question_card.isVisible())
        self.assertTrue(window.solution_card.isVisible())
        self.assertTrue(window.effort_panel.isVisible())
        with patch("snap_solve.ui.QSettings") as settings:
            window.effort_slider.setValue(0)
            window.effort_slider.setValue(2)
            settings.return_value.setValue.assert_called_with("solve_effort", "max")
            window.answer_only_toggle.setChecked(False)
            window.answer_only_toggle.setChecked(True)
            settings.return_value.setValue.assert_called_with("answer_only", True)
        self.assertEqual(window.effort_label.text(), "当前：最高")
        requests = []

        def fake_solve(key, markdown, image, update, cancelled, effort, answer_only):
            requests.append((markdown, image, effort, answer_only))
            update("$x=2$")
            return "$x=2$"

        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe_stream") as transcribe, \
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
            transcribe.assert_not_called()
            self.assertEqual(len(requests), 1)
            self.assertIsNone(requests[0][0])
            self.assertTrue(requests[0][1])
            self.assertEqual(requests[0][2], "max")
            self.assertTrue(requests[0][3])
            self.assertEqual(window.solution_card.editor.toPlainText(), "$x=2$")
            self.assertIn("解题完成", window.status.text())
        window.solve_toggle.setChecked(False)
        self.assertTrue(window.transcribe_toggle.isChecked())
        self.assertFalse(window.solution_card.isVisible())
        self.assertFalse(window.effort_panel.isVisible())
        window.close()

    def test_live_solve_restarts_after_effort_change(self):
        window = MainWindow()
        window.show()
        window.transcribe_toggle.setChecked(False)
        with patch("snap_solve.ui.QSettings"):
            window.effort_slider.setValue(0)
            window.answer_only_toggle.setChecked(False)
        pixmap = QPixmap(200, 100)
        pixmap.fill(QColor("white"))
        window.region_rect = QRect(0, 0, 200, 100)
        window.capture_region = lambda: pixmap
        window.candidate_pixmap = pixmap
        window.last_signature = image_signature(pixmap)
        window.last_changed_at = time.monotonic() - 2
        requests = []

        def fake_solve(key, markdown, image, update, cancelled, effort, answer_only):
            requests.append((markdown, effort, answer_only))
            update("## 解答")
            return "## 解答"

        with patch("snap_solve.ui.get_api_key", return_value="test-key"), \
             patch("snap_solve.ui.transcribe_stream") as transcribe, \
             patch("snap_solve.ui.solve_stream", side_effect=fake_solve):
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if requests and window.worker is None:
                    break
            self.assertEqual(requests, [(None, "low", False)])
            with patch("snap_solve.ui.QSettings"):
                window.effort_slider.setValue(2)
            window.poll_region()
            self.assertEqual(len(requests), 1)
            window.last_changed_at = time.monotonic() - 2
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 2 and window.worker is None:
                    break
            self.assertEqual(requests, [(None, "low", False), (None, "max", False)])
            with patch("snap_solve.ui.QSettings"):
                window.answer_only_toggle.setChecked(True)
            window.poll_region()
            self.assertEqual(len(requests), 2)
            window.last_changed_at = time.monotonic() - 2
            window.poll_region()
            for _ in range(30):
                QTest.qWait(100)
                if len(requests) == 3 and window.worker is None:
                    break
            self.assertEqual(requests[-1], (None, "max", True))
            transcribe.assert_not_called()
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

