"""Screen change detection for a persistent capture region."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage


STABLE_SECONDS = 1.5
POLL_MILLISECONDS = 550


def image_signature(pixmap: QPixmap) -> bytes:
    image = pixmap.toImage().scaled(
        512, 320, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    ).convertToFormat(QImage.Format.Format_RGB888)
    return bytes(image.constBits())


def has_meaningful_change(previous: bytes | None, current: bytes) -> bool:
    if previous is None or len(previous) != len(current):
        return True
    changed = 0
    for index in range(0, len(current), 3):
        difference = (abs(current[index] - previous[index]) +
                      abs(current[index + 1] - previous[index + 1]) +
                      abs(current[index + 2] - previous[index + 2]))
        if difference >= 36:
            changed += 1
            if changed >= 6:
                return True
    return False

