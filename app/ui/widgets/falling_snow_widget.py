"""
FallingSnowWidget — full-screen falling snowflake screensaver animation.

Renders 50 snowflake particles on a black background.  Each flake has a
random size (small/medium/large), fall speed, horizontal sway, rotation,
and opacity so the scene has visible depth.

Snowflake geometry is identical to SnowflakeWidget: 6 arms with two
branches each at 55 % along the arm, ±60° from the arm angle.

Public API:
    start()  — populate flakes (if needed), start timer, show widget
    stop()   — stop timer, hide widget
"""

import math
import random
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app.core.theme import SCREEN_H, SCREEN_W

# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------
_NUM_FLAKES   = 50
_ARM_SIZES    = (14, 20, 26)      # small / medium / large  (px)
_BRANCH_T     = 0.55              # branch start at 55 % of arm
_BRANCH_RATIO = 0.39              # branch length = arm_len * ratio  (~7/18)
_BASE_PEN_W   = 2.8               # pen width for the largest arm size
_TIMER_MS     = 30                # ~33 fps


@dataclass
class _Flake:
    x:          float
    y:          float
    base_x:     float   # sway origin — randomised on respawn
    arm_len:    float
    speed:      float   # px per tick
    sway_amp:   float   # max horizontal displacement (px)
    sway_speed: float   # oscillation frequency
    sway_phase: float   # per-flake phase so they don't sync
    rotation:   float   # current draw angle (degrees)
    rot_speed:  float   # degrees per tick
    alpha:      int     # 160–240; lower for smaller flakes (depth cue)


def _make_flake(initial: bool = False) -> _Flake:
    """Create a flake with randomised properties.

    If *initial* is True the y position is spread across the full screen
    height so the scene looks populated immediately on start.
    """
    arm = float(random.choice(_ARM_SIZES))
    # Smaller flakes appear farther away — dimmer and slower
    alpha = {14: random.randint(160, 190),
             20: random.randint(185, 215),
             26: random.randint(210, 240)}[int(arm)]
    speed = {14: random.uniform(1.5, 2.5),
             20: random.uniform(2.5, 3.5),
             26: random.uniform(3.0, 4.5)}[int(arm)]

    base_x = random.uniform(0.0, float(SCREEN_W))
    y = random.uniform(-arm * 2, float(SCREEN_H)) if initial else -arm * 2
    return _Flake(
        x=base_x,
        y=y,
        base_x=base_x,
        arm_len=arm,
        speed=speed,
        sway_amp=random.uniform(1.0, 4.0),
        sway_speed=random.uniform(0.02, 0.06),
        sway_phase=random.uniform(0.0, 2 * math.pi),
        rotation=random.uniform(0.0, 360.0),
        rot_speed=random.uniform(-1.2, 1.2),
        alpha=alpha,
    )


class FallingSnowWidget(QWidget):
    """Animated falling-snow canvas.  Sized to its parent; black background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._flakes: list[_Flake] = []
        self._t: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(_TIMER_MS)
        self._timer.timeout.connect(self._tick)

        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._flakes:
            self._flakes = [_make_flake(initial=True) for _ in range(_NUM_FLAKES)]
        self._t = 0
        self._timer.start()
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    # ------------------------------------------------------------------
    # Animation tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        for f in self._flakes:
            f.y += f.speed
            f.rotation += f.rot_speed
            f.x = f.base_x + f.sway_amp * math.sin(
                self._t * f.sway_speed + f.sway_phase
            )
            if f.y > self.height() + f.arm_len * 2:
                f.y = -f.arm_len * 2
                f.base_x = random.uniform(0.0, float(self.width()))
        self._t += 1
        self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Black background
        painter.fillRect(self.rect(), Qt.GlobalColor.black)

        # Draw smallest (farthest) flakes first
        for f in sorted(self._flakes, key=lambda fl: fl.arm_len):
            self._draw_flake(painter, f)

        painter.end()

    def _draw_flake(self, painter: QPainter, f: _Flake) -> None:
        color = QColor(255, 255, 255, f.alpha)
        pen_w = max(1.5, _BASE_PEN_W * f.arm_len / 26.0)
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        painter.save()
        painter.translate(f.x, f.y)
        painter.rotate(f.rotation)
        painter.setPen(pen)

        arm   = f.arm_len
        blen  = arm * _BRANCH_RATIO
        bt    = arm * _BRANCH_T

        for i in range(6):
            angle = math.radians(i * 60)
            cos_a, sin_a = math.cos(angle), math.sin(angle)

            # Main arm
            tip_x = arm * cos_a
            tip_y = arm * sin_a
            painter.drawLine(
                _pt(0, 0), _pt(tip_x, tip_y)
            )

            # Two branches
            bx = bt * cos_a
            by = bt * sin_a
            for sign in (-1, 1):
                ba = angle + sign * math.radians(60)
                ex = bx + blen * math.cos(ba)
                ey = by + blen * math.sin(ba)
                painter.drawLine(_pt(bx, by), _pt(ex, ey))

        # Centre dot
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(_ptF(0.0, 0.0), pen_w * 1.2, pen_w * 1.2)

        painter.restore()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

from PyQt6.QtCore import QPoint, QPointF  # noqa: E402 (after class def)


def _pt(x: float, y: float) -> QPointF:
    return QPointF(x, y)


def _ptF(x: float, y: float) -> QPointF:
    return QPointF(x, y)
