"""Motion primitives matching the design canvas.

`spring` is a direct port of the CSS `linear(...)` spring used in the Morph design;
`soft` is cubic-bezier(.22, 1, .36, 1). Tweens are time-based (not frame-based) so
animation speed is identical whatever the frame rate.
"""
from __future__ import annotations

import math
import time
from typing import Callable

Ease = Callable[[float], float]

# CSS: linear(0,0.009,0.035 2.1%,0.141,0.281 6.7%,0.723 12.9%,...) — values with optional stops.
_SPRING_SRC = ("0,0.009,0.035 2.1%,0.141,0.281 6.7%,0.723 12.9%,0.938 16.7%,1.017,1.077,1.121,1.149 24.3%,"
               "1.159,1.163,1.161,1.154 29.9%,1.129 32.8%,1.051 39.6%,1.017 43.1%,0.991,0.977 51%,"
               "0.974 53.8%,0.975 57.1%,0.997 69.8%,1.003 76.9%,1.004 83.8%,1")


def _parse_linear(src: str) -> list[tuple[float, float]]:
    """Resolve CSS linear() stops: missing positions are spread evenly between known ones."""
    raw = []
    for part in src.split(","):
        bits = part.split()
        raw.append([float(bits[0]), float(bits[1].rstrip("%")) / 100 if len(bits) > 1 else None])
    raw[0][1] = 0.0 if raw[0][1] is None else raw[0][1]
    raw[-1][1] = 1.0 if raw[-1][1] is None else raw[-1][1]
    i = 0
    while i < len(raw):
        if raw[i][1] is None:
            j = i
            while raw[j][1] is None:
                j += 1
            a, b = raw[i - 1][1], raw[j][1]
            for k in range(i, j):
                raw[k][1] = a + (b - a) * (k - i + 1) / (j - i + 1)
            i = j
        i += 1
    return [(p, v) for v, p in raw]


_SPRING = _parse_linear(_SPRING_SRC)


def spring(t: float) -> float:
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    for (p0, v0), (p1, v1) in zip(_SPRING, _SPRING[1:]):
        if t <= p1:
            return v0 + (v1 - v0) * ((t - p0) / (p1 - p0) if p1 > p0 else 1)
    return 1.0


def cubic_bezier(x1: float, y1: float, x2: float, y2: float) -> Ease:
    def sample(a1, a2, t):
        return ((1 - 3 * a2 + 3 * a1) * t + (3 * a2 - 6 * a1)) * t * t + 3 * a1 * t

    def ease(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        lo, hi, t = 0.0, 1.0, x
        for _ in range(24):  # bisection on x(t)
            cx = sample(x1, x2, t)
            if abs(cx - x) < 1e-5:
                break
            lo, hi = (t, hi) if cx < x else (lo, t)
            t = (lo + hi) / 2
        return sample(y1, y2, t)
    return ease


soft = cubic_bezier(0.22, 1, 0.36, 1)
ease_out = cubic_bezier(0, 0, 0.58, 1)
ease_in_out = cubic_bezier(0.42, 0, 0.58, 1)


def linear(t: float) -> float:
    return max(0.0, min(1.0, t))


def now() -> float:
    return time.monotonic()


class Tween:
    """A value that animates toward its target over `dur` seconds with an easing curve."""

    def __init__(self, value: float, dur: float = 0.8, ease: Ease = spring):
        self.start = self.end = float(value)
        self.t0 = 0.0
        self.dur = dur
        self.ease = ease
        self.delay = 0.0

    def to(self, target: float, dur: float | None = None, ease: Ease | None = None, delay: float = 0.0):
        target = float(target)
        if target == self.end and dur is None:
            return
        self.start = self.value()  # retarget from where we are now (no jumps)
        self.end = target
        self.t0 = now()
        self.delay = delay
        if dur is not None:
            self.dur = dur
        if ease is not None:
            self.ease = ease

    def set(self, value: float):
        self.start = self.end = float(value)
        self.t0 = 0.0

    def progress(self) -> float:
        if self.dur <= 0:
            return 1.0
        return max(0.0, min(1.0, (now() - self.t0 - self.delay) / self.dur))

    def value(self) -> float:
        p = self.progress()
        if p >= 1:
            return self.end
        return self.start + (self.end - self.start) * self.ease(p)

    @property
    def active(self) -> bool:
        return self.progress() < 1


class Pulse:
    """A one-shot 0->1 timeline (e.g. shockwave, check-mark draw)."""

    def __init__(self, dur: float, ease: Ease = linear, delay: float = 0.0):
        self.dur, self.ease, self.delay = dur, ease, delay
        self.t0: float | None = None

    def fire(self, delay: float | None = None):
        self.t0 = now()
        if delay is not None:
            self.delay = delay

    def raw(self) -> float:
        if self.t0 is None:
            return 1.0
        return max(0.0, min(1.0, (now() - self.t0 - self.delay) / self.dur))

    def value(self) -> float:
        return self.ease(self.raw())

    @property
    def running(self) -> bool:
        return self.t0 is not None and self.raw() < 1

    @property
    def started(self) -> bool:
        return self.t0 is not None and now() - self.t0 >= self.delay


def loop(period: float, t: float | None = None) -> float:
    """0..1 sawtooth for repeating animations."""
    t = now() if t is None else t
    return (t % period) / period


def keyframe_wave(phase: float) -> float:
    """0 -> 1 -> 0 over one period with ease-in-out (CSS `50% {...}` keyframes)."""
    return ease_in_out(1 - abs(1 - 2 * phase))


def keyframes(t: float, frames: list[tuple[float, float]], ease: Ease = ease_out) -> float:
    """Piecewise keyframes [(pos, value)], pos in 0..1, eased between frames."""
    if t <= frames[0][0]:
        return frames[0][1]
    for (p0, v0), (p1, v1) in zip(frames, frames[1:]):
        if t <= p1:
            return v0 + (v1 - v0) * ease((t - p0) / (p1 - p0))
    return frames[-1][1]


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_angle(deg: float) -> float:
    return math.radians(deg)
