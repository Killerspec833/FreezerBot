"""
SnowflakeWidget — animated mic-active indicator.

Draws a 6-armed snowflake whose colour pulses from blue (#1565C0) to white
and back on a continuous sine-wave cycle.  Transparent background so it
floats cleanly over any underlying widget.

Public API:
    start()  — begin animation and show
    stop()   — stop animation and hide
    set_status(text)  — update the small label to the right of the snowflake
"""

import math

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.core.theme import FONT_SMALL, COLOR_TEXT_SECONDARY


# Blue (#1565C0) channel values
_BLUE_R, _BLUE_G, _BLUE_B = 21, 101, 192


class SnowflakeWidget(QWidget):
    """Transparent overlay widget: animated snowflake + small status label."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Pass mouse events through to whatever is underneath
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._phase: float = 0.0   # 0.0 → 1.0 drives sine wave

        # Animation timer
        self._timer = QTimer(self)
        self._timer.setInterval(30)   # ~33 fps
        self._timer.timeout.connect(self._tick)

        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._phase = 0.0
        self._timer.start()
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Snowflake canvas (paints itself)
        self._canvas = _SnowflakeCanvas(self)
        layout.addWidget(self._canvas, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Status label (e.g. "Listening…", "Transcribing…")
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SMALL}pt;"
            "background: transparent;"
        )
        layout.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Size: canvas (48) + spacing (6) + label (~110) = 164 wide, 48 tall
        self.setFixedHeight(48)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        # lerp: blue → white → blue
        t = (math.sin(self._phase * 2 * math.pi) + 1) / 2   # 0.0 .. 1.0
        r = int(_BLUE_R + t * (255 - _BLUE_R))
        g = int(_BLUE_G + t * (255 - _BLUE_G))
        b = int(_BLUE_B + t * (255 - _BLUE_B))
        self._canvas.set_color(QColor(r, g, b))


class _SnowflakeCanvas(QWidget):
    """48×48 widget that draws the actual snowflake shape."""

    _ARM_LEN    = 18      # px from centre to tip  (+10 %)
    _BRANCH_LEN = 7       # px for each branch     (+10 %)
    _BRANCH_T   = 0.55    # fraction along arm where branches start
    _PEN_W      = 2.8     # line width             (+10 %)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._color = QColor(21, 101, 192)   # start blue

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2

        pen = QPen(self._color, self._PEN_W, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        for i in range(6):
            angle = math.radians(i * 60)
            # Main arm
            tip_x = cx + self._ARM_LEN * math.cos(angle)
            tip_y = cy + self._ARM_LEN * math.sin(angle)
            painter.drawLine(QPointF(cx, cy), QPointF(tip_x, tip_y))

            # Two branches at BRANCH_T × arm_len
            bx = cx + self._ARM_LEN * self._BRANCH_T * math.cos(angle)
            by = cy + self._ARM_LEN * self._BRANCH_T * math.sin(angle)
            for sign in (-1, 1):
                ba = angle + sign * math.radians(60)
                ex = bx + self._BRANCH_LEN * math.cos(ba)
                ey = by + self._BRANCH_LEN * math.sin(ba)
                painter.drawLine(QPointF(bx, by), QPointF(ex, ey))

        # Centre dot
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)

        painter.end()
