"""
AnimatedCircle — the listening state visual.

Renders a solid blue filled circle in the centre with thin red rings
that spawn periodically, expand outward, and fade to transparent.
"""

from dataclasses import dataclass, field
from typing import List

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app.core.theme import (
    COLOR_BACKGROUND,
    COLOR_PRIMARY_BLUE,
    RIPPLE_CIRCLE_RADIUS,
    RIPPLE_EXPAND_PX,
    RIPPLE_FADE_STEP,
    RIPPLE_RING_COLOR_B,
    RIPPLE_RING_COLOR_G,
    RIPPLE_RING_COLOR_R,
    RIPPLE_RING_WIDTH,
    RIPPLE_SPAWN_TICKS,
    RIPPLE_TIMER_MS,
)


@dataclass
class _Ring:
    radius: float
    opacity: float = 0.9


class AnimatedCircle(QWidget):
    """Self-contained ripple animation widget.

    Call start_animation() when the listening screen becomes active,
    stop_animation() when it is hidden.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rings: List[_Ring] = []
        self._tick: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(RIPPLE_TIMER_MS)
        self._timer.timeout.connect(self._on_tick)

        # Fixed widget size: large enough to show several rings at full fade
        size = (RIPPLE_CIRCLE_RADIUS + 120) * 2
        self.setFixedSize(size, size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_animation(self) -> None:
        self._rings.clear()
        self._tick = 0
        self._timer.start()

    def stop_animation(self) -> None:
        self._timer.stop()
        self._rings.clear()
        self.update()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_tick(self) -> None:
        self._tick += 1

        # Expand and fade every active ring
        surviving = []
        for ring in self._rings:
            ring.radius += RIPPLE_EXPAND_PX
            ring.opacity -= RIPPLE_FADE_STEP
            if ring.opacity > 0:
                surviving.append(ring)
        self._rings = surviving

        # Spawn a new ring periodically
        if self._tick % RIPPLE_SPAWN_TICKS == 0:
            self._rings.append(_Ring(radius=float(RIPPLE_CIRCLE_RADIUS + 5)))

        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        centre = QPointF(cx, cy)

        # Background
        painter.fillRect(self.rect(), QColor(COLOR_BACKGROUND))

        # Rings — draw largest (most faded) first so newer rings render on top
        for ring in sorted(self._rings, key=lambda r: -r.radius):
            color = QColor(
                RIPPLE_RING_COLOR_R,
                RIPPLE_RING_COLOR_G,
                RIPPLE_RING_COLOR_B,
            )
            color.setAlphaF(max(0.0, ring.opacity))
            pen = QPen(color, RIPPLE_RING_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, ring.radius, ring.radius)

        # Solid blue centre circle
        painter.setPen(QPen(QColor(0, 0, 0, 0)))  # no outline
        painter.setBrush(QColor(COLOR_PRIMARY_BLUE))
        painter.drawEllipse(centre, RIPPLE_CIRCLE_RADIUS, RIPPLE_CIRCLE_RADIUS)

        painter.end()
