"""Outline tracing for TRACE: sub-pixel edges, sharp corners, smooth curves.

A black & white bitmap only knows whole pixels, so anything traced from it has to guess where the
edge really was, and the guesses show up as wobbles, flattened corners and lines that are a touch
too thin or too fat.  The grey picture knows more: the soft pixels along an edge say how far into
each pixel the ink reaches.  So this tracer works from the grey "ink field" directly:

  1. OpenCV walks the outline of every ink shape (which pixels, in which order).
  2. Each outline point slides along the edge's normal to the exact spot where the field crosses
     the ink/paper level.  The outline is now accurate to a small fraction of a pixel.
  3. Corners are found (a turn that happens in one place, unlike a curve that turns steadily) and
     rebuilt as the meeting point of their two sides, undoing the rounding that blur adds.
  4. Between corners, straight runs become true straight lines and everything else is fitted with
     as few cubic Bezier curves as the tolerance allows, joined without kinks.

Only numpy and OpenCV are used, in-process: same result on every machine, nothing to crash.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

# Distances are in pixels of the picture the user gave us, not of the enlarged working copy: what
# counts as "detail" and what counts as "pixel noise" is set by the original's resolution.
#   smooth  : how much jitter is ironed out along the outline before fitting
#   tol     : how far a fitted curve may stray from the outline
#   line    : how far a run may bow and still be drawn as a straight line
#   corner  : the smallest turn (degrees) that counts as a corner
PARAMS = {
    "bold": dict(smooth=1.0, tol=0.40, line=0.30, corner=40.0),
    "balanced": dict(smooth=0.5, tol=0.18, line=0.15, corner=32.0),
    "fine": dict(smooth=0.45, tol=0.13, line=0.10, corner=26.0),
}
_NEAR, _REPARAM = 9, 2      # curve fitting: when and how often to refine a near miss
_QUICK = math.radians(90)   # first try: one curve per this much turning
_BOX = np.full(7, 1 / 7)
_STEP = 0.5  # spacing of outline points after resampling; "k points" below means k * _STEP pixels


# ------------------------------------------------------------------ 1+2: sub-pixel outlines
def _sample(field, x, y):
    """Bilinear samples of `field` at float coordinates of any shape."""
    shape = x.shape
    x = np.ascontiguousarray(x, np.float32).ravel()
    y = np.ascontiguousarray(y, np.float32).ravel()
    n, wdt = x.size, 4096                     # remap wants maps narrower than 32768
    rows = -(-n // wdt)
    pad = rows * wdt - n
    if pad:
        x = np.pad(x, (0, pad))
        y = np.pad(y, (0, pad))
    out = cv2.remap(field, x.reshape(rows, wdt), y.reshape(rows, wdt), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE)
    return out.ravel()[:n].reshape(shape)


def outlines(field, mask):
    """Every ink outline as sub-pixel points.

    field: float32, negative = ink, positive = paper, 0 = the edge.
    mask:  uint8, non-zero = ink (the field's sign, minus removed specks).
    -> (list of (n, 2) float64 arrays in pixel-centre coordinates, OpenCV hierarchy rows,
        typical steepness of the field across an edge, in field units per pixel)
    """
    contours, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return [], np.zeros((0, 4), np.int32), 0.0
    lens = np.array([len(c) for c in contours])
    P = np.concatenate(contours).reshape(-1, 2).astype(np.float32)
    start = np.repeat(np.cumsum(lens) - lens, lens)
    length = np.repeat(lens, lens)
    local = np.arange(len(P)) - start

    def nb(k):  # index of the point k steps further along the same (closed) outline
        return start + (local + k) % length

    # outline direction from a lightly smoothed copy, so the normal isn't stuck at 45-degree steps
    w = np.exp(-0.5 * (np.arange(-3, 4) / 1.5) ** 2)
    w /= w.sum()
    Ps = np.zeros_like(P)
    for k, wk in zip(range(-3, 4), w):
        Ps += wk * P[nb(k)]
    T = Ps[nb(1)] - Ps[nb(-1)]
    N = np.stack([-T[:, 1], T[:, 0]], 1)      # OpenCV keeps ink on one side: this one points at paper
    nrm = np.hypot(N[:, 0], N[:, 1])
    bad = nrm < 1e-3                          # tip of a one-pixel-wide line: point away from it
    if bad.any():
        alt = P - 0.5 * (P[nb(1)] + P[nb(-1)])
        N[bad] = alt[bad]
        nrm = np.hypot(N[:, 0], N[:, 1])
    N /= np.maximum(nrm, 1e-6)[:, None]

    # walk each normal from just inside the ink to well outside and find where the field crosses 0
    steps = np.arange(-0.75, 2.01, 0.25, dtype=np.float32)
    V = _sample(field, P[:, 0:1] + N[:, 0:1] * steps, P[:, 1:2] + N[:, 1:2] * steps)
    up = (V[:, :-1] < 0) & (V[:, 1:] >= 0)
    has = up.any(1)
    j = up.argmax(1)
    ar = np.arange(len(P))
    v0, v1 = V[ar, j], V[ar, j + 1]
    s = steps[j] + 0.25 * (-v0) / np.maximum(v1 - v0, 1e-6)
    s = np.where(has, s, 0.5)                 # no crossing (picture border): the pixel's own edge
    Q = P.astype(np.float64) + N.astype(np.float64) * s[:, None]
    slope = float(np.median((v1 - v0)[has])) / 0.25 if has.any() else 0.0
    return np.split(Q, np.cumsum(lens)[:-1]), hier[0], slope


# ------------------------------------------------------------------ small helpers
def _resample(Q, h):
    """Closed outline -> points evenly spaced ~h apart along it."""
    Qc = np.vstack([Q, Q[:1]])
    d = np.hypot(*np.diff(Qc, axis=0).T)
    total = float(d.sum())
    if total < 1e-6:
        return None
    n = max(6, int(round(total / h)))
    s = np.concatenate([[0.0], np.cumsum(d)])
    t = np.arange(n) * (total / n)
    return np.stack([np.interp(t, s, Qc[:, 0]), np.interp(t, s, Qc[:, 1])], 1)


def _kernel(sigma, r):
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    return k / k.sum()


def _smooth_closed(R, sigma):
    r = min(int(3 * sigma + 0.5), (len(R) - 1) // 2)
    if sigma <= 0 or r < 1:
        return R
    k = _kernel(sigma, r)
    ext = np.vstack([R[-r:], R, R[:r]])
    return np.stack([np.convolve(ext[:, 0], k, "valid"), np.convolve(ext[:, 1], k, "valid")], 1)


def _smooth_open(P, sigma):
    """Smooth an open run; both ends stay exactly where they are and keep their direction."""
    n = len(P)
    r = min(int(3 * sigma + 0.5), n - 1)
    if sigma <= 0 or r < 1 or n < 3:
        return P
    k = _kernel(sigma, r)
    ext = np.vstack([2 * P[0] - P[r:0:-1], P, 2 * P[-1] - P[-2:-r - 2:-1]])
    out = np.stack([np.convolve(ext[:, 0], k, "valid"), np.convolve(ext[:, 1], k, "valid")], 1)
    out[0], out[-1] = P[0], P[-1]
    return out


def _unit(v):
    n = math.hypot(v[0], v[1])
    return v / n if n > 1e-9 else None


# ------------------------------------------------------------------ 3: corners
def _angle(a, b):
    """Angle between two sets of vectors, row by row (radians, 0..pi)."""
    return np.abs(np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1]))


def _find_corners(R, min_turn_deg, blur):
    """Indices where the outline turns sharply *in one place*.

    Blur rounds every corner over a stretch about 2 * blur long, so the turn is measured between
    the outline just before that stretch and just after it.  A curve keeps turning the further out
    you look; at a corner the sides beyond the rounded stretch run straight on, so looking further
    out adds nothing.  That difference is the test.
    """
    n = len(R)
    k = max(3, int(round(2 * blur / _STEP)))
    if n < 8 * k:
        return []
    A = _smooth_closed(R, 1.0)
    b1, b2, b3 = np.roll(A, k, 0), np.roll(A, 2 * k, 0), np.roll(A, 3 * k, 0)        # behind
    f1, f2, f3 = np.roll(A, -k, 0), np.roll(A, -2 * k, 0), np.roll(A, -3 * k, 0)     # ahead
    near = _angle(b1 - b2, f2 - f1)           # turn across the rounded stretch
    far = _angle(b2 - b3, f3 - f2)            # the same, measured one step further out
    cand = np.nonzero((near >= math.radians(min_turn_deg)) & (far <= 1.3 * near + math.radians(3)))[0]
    if not len(cand):
        return []
    tip = _angle(A - b1, f1 - A)              # sharpest right at the corner: pins down where it is
    picked: list[int] = []
    taken = np.zeros(n, bool)                 # strongest first; each one claims its neighbourhood
    for i in cand[np.argsort(-tip[cand], kind="stable")].tolist():
        if taken[i]:
            continue
        picked.append(i)
        lo, hi = i - 2 * k, i + 2 * k + 1
        taken[max(lo, 0):min(hi, n)] = True
        if lo < 0:
            taken[lo:] = True
        if hi > n:
            taken[:hi - n] = True
    return sorted(picked)


def _line_through(pts):
    """Best straight line through a few points -> (centre, unit direction first->last)."""
    c = pts.mean(0)
    d = pts - c
    sxx, sxy, syy = float((d[:, 0] ** 2).sum()), float((d[:, 0] * d[:, 1]).sum()), float((d[:, 1] ** 2).sum())
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    v = np.array([math.cos(ang), math.sin(ang)])
    if float(np.dot(v, pts[-1] - pts[0])) < 0:
        v = -v
    return c, v


def _sharpen(R, c, gap_before, gap_after, blur, probe):
    """The true corner near R[c]: where the side arriving and the side leaving would meet.

    Blur (anti-aliasing, a soft scan) rounds every corner in the picture.  Just outside the rounded
    bit both sides are still on course, so their meeting point is the corner before it was blurred.
    -> (point, points to skip on each side) or None when the sides don't give a trustworthy answer.

    Two checks keep this honest, because a wrongly "restored" corner is a spike that was never in
    the picture: the corner may only sit as far beyond the rounded outline as blur of this strength
    would have pulled it back, and the picture itself must agree (see `probe` in trace_paths).
    """
    n = len(R)
    a1 = max(2, math.ceil(2 * blur / _STEP))   # points nearer than this are part of the rounding
    out = []
    for gap, sign in ((gap_before, -1), (gap_after, 1)):
        a2 = min(a1 + 6, gap - a1)
        if a2 - a1 < 2:
            return None
        idx = [(c + sign * k) % n for k in range(a2, a1 - 1, -1)]   # far -> near the corner
        out.append(_line_through(R[idx]))
    (c0, d0), (c1, d1) = out                   # both directions point at the corner
    cross = d0[0] * d1[1] - d0[1] * d1[0]
    if abs(cross) < 0.2:                       # nearly parallel sides: no stable meeting point
        return None
    w = c1 - c0
    a = (w[0] * d1[1] - w[1] * d1[0]) / cross
    b = (w[0] * d0[1] - w[1] * d0[0]) / cross
    if a <= 0 or b <= 0:                       # they'd meet behind us: not a corner of this kind
        return None
    X = c0 + a * d0
    inner = math.acos(max(-1.0, min(1.0, float(np.dot(d0, d1)))))   # angle between the two sides
    if inner < math.radians(20):               # needle tips: the sides say too little about where they end
        return None
    # blurring a wedge pulls its tip back by about this much (exact for a right angle, close elsewhere)
    pulled = 0.72 * blur / math.tan(inner / 2)
    if math.hypot(*(X - R[c])) > 1.3 * pulled + 0.3:
        return None
    if probe is not None:
        # At the true tip of a wedge, a blurred picture shows the wedge's share of a full circle
        # (a right angle: a quarter ink).  Further out than the real tip there is less than that.
        cov = probe(X)
        if min(cov, 1.0 - cov) < 0.55 * inner / (2 * math.pi):
            return None
    return X, a1


# ------------------------------------------------------------------ 4: curve fitting (Schneider)
def _bezier(P, u, t1, t2, arc):
    """Least-squares cubic through P[0], P[-1] leaving along t1 and arriving against t2."""
    p0, p3 = P[0], P[-1]
    iu = 1.0 - u
    b1 = 3 * u * iu * iu
    b2 = 3 * u * u * iu
    left = iu * iu * iu + b1
    c00 = float((b1 * b1).sum())
    c11 = float((b2 * b2).sum())
    c01 = float((b1 * b2).sum()) * float(np.dot(t1, t2))
    tmp = P - (left[:, None] * p0 + (1.0 - left)[:, None] * p3)
    x0 = float((b1 * (tmp @ t1)).sum())
    x1 = float((b2 * (tmp @ t2)).sum())
    det = c00 * c11 - c01 * c01
    seg = math.hypot(*(p3 - p0))
    if abs(det) > 1e-12:
        a1 = (x0 * c11 - x1 * c01) / det
        a2 = (c00 * x1 - c01 * x0) / det
    else:
        a1 = a2 = -1.0
    lo, hi = 1e-6 * max(seg, 1e-6), max(arc, seg)
    if not (lo < a1 <= hi and lo < a2 <= hi):  # unstable solve: fall back to the classic thirds
        a1 = a2 = max(seg, arc * 0.5) / 3.0
    return p0, p0 + t1 * a1, p3 + t2 * a2, p3


def _eval(bz, u):
    p0, p1, p2, p3 = bz
    iu = 1.0 - u
    c = np.stack([iu * iu * iu, 3 * u * iu * iu, 3 * u * u * iu, u * u * u], 1)
    return c @ np.stack([p0, p1, p2, p3])


def _reparam(bz, P, u):
    """One Newton step moving each parameter towards the curve's closest point."""
    p0, p1, p2, p3 = bz
    iu = 1.0 - u
    d = _eval(bz, u) - P
    q1 = np.stack([3 * iu * iu, 6 * u * iu, 3 * u * u], 1) @ np.stack([p1 - p0, p2 - p1, p3 - p2])
    q2 = np.stack([6 * iu, 6 * u], 1) @ np.stack([p2 - 2 * p1 + p0, p3 - 2 * p2 + p1])
    num = (d * q1).sum(1)
    den = (q1 * q1).sum(1) + (d * q2).sum(1)
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    return np.clip(u - num / den, 0.0, 1.0)


def _fit(P, T, i0, i1, t1, t2, tol2, out):
    """Fit P[i0..i1] with cubics, splitting where one curve can't stay within tolerance."""
    stack = [(i0, i1, t1, t2)]
    while stack:
        i0, i1, t1, t2 = stack.pop()
        pts = P[i0:i1 + 1]
        n = len(pts)
        d = np.hypot(*np.diff(pts, axis=0).T)
        arc = float(d.sum())
        if n <= 2 or arc < 1e-9:
            h = arc / 3.0
            out.append((i0, (pts[0], pts[0] + t1 * h, pts[-1] + t2 * h, pts[-1])))
            continue
        u = np.concatenate([[0.0], np.cumsum(d)]) / arc
        bz = _bezier(pts, u, t1, t2, arc)
        e = ((_eval(bz, u) - pts) ** 2).sum(1)
        worst = int(e.argmax())
        if e[worst] > tol2 and e[worst] < tol2 * _NEAR:      # close: nudging the parameters may do it
            for _ in range(_REPARAM):
                u = _reparam(bz, pts, u)
                bz = _bezier(pts, u, t1, t2, arc)
                e = ((_eval(bz, u) - pts) ** 2).sum(1)
                worst = int(e.argmax())
                if e[worst] <= tol2:
                    break
        if e[worst] <= tol2:
            out.append((i0, bz))
            continue
        k = i0 + min(max(worst, 1), n - 2)
        tc = T[k]
        stack.append((k, i1, tc, t2))
        stack.append((i0, k, t1, -tc))


def _quick(S, T, tol2, per_curve):
    """Fit a whole run in one go: a curve for every `per_curve` radians the outline turns.

    Each curve is the cubic that would be exact if its stretch were a circular arc with the measured
    end directions.  All of them are then checked against the outline at once.  Most stretches of
    a smooth outline pass, which leaves only the awkward ones for the slower cut-and-try fitting.
    -> (start index, end index, curve, within tolerance?) for each stretch, in order
    """
    n = len(S)
    turn = np.arctan2(T[:-1, 0] * T[1:, 1] - T[:-1, 1] * T[1:, 0], T[:-1, 0] * T[1:, 0] + T[:-1, 1] * T[1:, 1])
    if n > 8:   # left-right jitter is not turning: average it out before adding the turning up
        turn = np.convolve(turn, _BOX, "same")
    cum = np.concatenate([[0.0], np.cumsum(np.abs(turn))])
    m = max(1, int(math.ceil(cum[-1] / per_curve)))
    kn = np.searchsorted(cum, np.arange(1, m) * (cum[-1] / m)) if m > 1 else np.zeros(0, np.intp)
    kn = np.unique(np.concatenate([[0], kn, [n - 1]]))
    a, b = kn[:-1], kn[1:]
    p0, p3, t0, t3 = S[a], S[b], T[a], T[b]
    chord = np.hypot(p3[:, 0] - p0[:, 0], p3[:, 1] - p0[:, 1])
    bend = np.arccos(np.clip((t0 * t3).sum(1), -1.0, 1.0))        # turn from one end to the other
    safe = np.maximum(bend, 1e-3)
    h = np.where(bend < 1e-3, chord / 3.0, (4.0 / 3.0) * np.tan(safe / 4) * chord / (2 * np.sin(safe / 2)))
    p1, p2 = p0 + t0 * h[:, None], p3 - t3 * h[:, None]
    # check: every outline point against the curve it belongs to, at its share of the way along
    seg = np.repeat(np.arange(len(a)), b - a)
    d = np.hypot(*np.diff(S, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(d)])
    span = s[b] - s[a]
    u = ((s[:-1] - s[a][seg]) / np.maximum(span, 1e-9)[seg])[:, None]
    iu = 1.0 - u
    B = iu * iu * iu * p0[seg] + 3 * u * iu * iu * p1[seg] + 3 * u * u * iu * p2[seg] + u * u * u * p3[seg]
    worst = np.maximum.reduceat(((B - S[:-1]) ** 2).sum(1), a)
    ok = (worst <= tol2) & (span > 1e-9)
    return zip(a.tolist(), b.tolist(), zip(p0, p1, p2, p3), ok.tolist())


def _tangents(S, closed):
    """Unit direction of travel at every point of S."""
    far = _smooth_closed(S, 1.5) if closed else _smooth_open(S, 1.5)
    if closed:
        T = np.roll(far, -2, 0) - np.roll(far, 2, 0)
    else:
        T = np.empty_like(far)
        T[2:-2] = far[4:] - far[:-4]
        T[:2] = far[2:4] - far[0]
        T[-2:] = far[-1] - far[-4:-2]
    nrm = np.hypot(T[:, 0], T[:, 1])
    return T / np.maximum(nrm, 1e-9)[:, None]


def _end_dir(S):
    """Direction the run leaves S[0] in (second-order, so a curved run gets its true tangent)."""
    n = len(S)
    m = min(3, (n - 1) // 2)
    if m >= 1:
        t = _unit(-3 * S[0] + 4 * S[m] - S[2 * m])
        if t is not None:
            return t
    return _unit(S[-1] - S[0])


def _fit_run(P, p, closed, segs):
    """One run of outline (corner to corner, or a whole smooth loop) -> path segments."""
    if not closed:
        chord = P[-1] - P[0]
        ln = math.hypot(*chord)
        if len(P) <= 2:
            segs.append(("L", P[-1]))
            return
        if ln > 1e-6:
            dev = np.abs((P[:, 0] - P[0, 0]) * chord[1] - (P[:, 1] - P[0, 1]) * chord[0]) / ln
            if float(dev.max()) <= p["line"]:
                segs.append(("L", P[-1]))
                return
        S = _smooth_open(P, p["smooth"] / _STEP)
        if len(S) < 5:
            T = None
            t1, t2 = _unit(S[1] - S[0]), _unit(S[-2] - S[-1])
        else:
            T = _tangents(S, False)
            t1, t2 = _end_dir(S), _end_dir(S[::-1])
    else:
        S = _smooth_closed(P, p["smooth"] / _STEP)
        T = _tangents(S, True)
        S = np.vstack([S, S[:1]])
        T = np.vstack([T, T[:1]])
        t1, t2 = T[0], -T[0]
    if t1 is None or t2 is None:
        segs.append(("L", P[-1]))
        return
    if T is None:
        T = np.tile(t1, (len(S), 1))
    T = T.copy()
    T[0], T[-1] = t1, -t2
    tol2 = p["tol"] ** 2
    curves = []
    for i0, i1, bz, ok in _quick(S, T, tol2, p.get("per_curve", _QUICK)):
        if ok:
            curves.append(bz)
            continue
        out: list = []
        _fit(S, T, i0, i1, T[i0], -T[i1], tol2, out)
        out.sort(key=lambda o: o[0])
        curves.extend(c for _i, c in out)
    for p0, p1, p2, p3 in curves:
        ch = p3 - p0
        ln = math.hypot(*ch)
        if ln > 1e-6:  # a "curve" that is really straight is cleaner (and cuts better) as a line
            d1 = abs((p1[0] - p0[0]) * ch[1] - (p1[1] - p0[1]) * ch[0]) / ln
            d2 = abs((p2[0] - p0[0]) * ch[1] - (p2[1] - p0[1]) * ch[0]) / ln
            if max(d1, d2) < 0.04:
                segs.append(("L", p3))
                continue
        segs.append(("C", p1, p2, p3))


def fit_outline(Q, p):
    """One closed sub-pixel outline -> (start point, segments), or None if it is too small to draw."""
    R = _resample(Q, _STEP)
    if R is None:
        return None
    n = len(R)
    corners = _find_corners(R, p["corner"], p["blur"]) if p["corner"] else []
    segs: list = []
    if not corners:
        S0 = _smooth_closed(R, p["smooth"] / _STEP)
        _fit_run(R, p, True, segs)
        return S0[0], segs

    m = len(corners)
    sharp = []
    for j, c in enumerate(corners):
        before = (c - corners[j - 1]) % n or n
        after = (corners[(j + 1) % m] - c) % n or n
        sharp.append(_sharpen(R, c, before, after, p["blur"], p.get("probe")))
    start = sharp[0][0] if sharp[0] else R[corners[0]]
    for j, c in enumerate(corners):
        jn = (j + 1) % m
        cn = corners[jn]
        gap = (cn - c) % n or n
        a0 = sharp[j][1] if sharp[j] else 0
        a1 = sharp[jn][1] if sharp[jn] else 0
        p_from = sharp[j][0] if sharp[j] else R[c]
        p_to = sharp[jn][0] if sharp[jn] else R[cn]
        lo, hi = a0 if sharp[j] else 1, gap - (a1 if sharp[jn] else 1)
        mid = R[[(c + k) % n for k in range(lo, hi + 1)]] if hi >= lo else np.zeros((0, 2))
        parts = [p_from[None]]
        if sharp[j] and len(mid):               # bridge the skipped (blur-rounded) stretch in a straight line
            g = int(math.hypot(*(mid[0] - p_from)))
            if g >= 1:
                parts.append(np.linspace(p_from, mid[0], g + 1)[1:-1])
        parts.append(mid)
        if sharp[jn] and len(mid):
            g = int(math.hypot(*(p_to - mid[-1])))
            if g >= 1:
                parts.append(np.linspace(mid[-1], p_to, g + 1)[1:-1])
        parts.append(p_to[None])
        _fit_run(np.vstack(parts), p, False, segs)
    return start, segs


# ------------------------------------------------------------------ public
def _num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _path_d(start, segs, unit, sx, sy) -> str:
    def pt(q):  # back to working pixels, +0.5 from pixel centre to pixel grid, then to output units
        return f"{_num((q[0] * unit + 0.5) * sx)} {_num((q[1] * unit + 0.5) * sy)}"
    d = ["M" + pt(start)]
    for s in segs:
        d.append("L" + pt(s[1]) if s[0] == "L" else "C" + pt(s[1]) + " " + pt(s[2]) + " " + pt(s[3]))
    return "".join(d) + "Z"


def trace_paths(field, mask, detail: str, scale: tuple[float, float], unit: float = 1.0,
                contrast: float | None = None, loose: bool = False, tick=None) -> list[str]:
    """Ink field -> SVG path data, one string per shape (its holes included).

    scale: output units per working pixel (x, y).  unit: working pixels per pixel of the original
    picture (1 when it wasn't enlarged).  contrast: field difference between solid ink and bare
    paper, if known.  loose: the outlines are an interpretation (lines drawn from a photo's
    shading), not edges that exist in the picture, so favour flowing curves over following every
    wiggle.  tick: called now and then (progress / cancel).
    """
    unit = max(1.0, unit)
    pts, hier, slope = outlines(field, mask)
    # How soft are the edges?  A crisp export goes from paper to ink within a pixel, a scan takes
    # several; corners are rounded over about that distance, so corner handling has to reach past it.
    blur = 0.9
    if contrast and slope > 0:
        blur = min(2.5, max(0.5, contrast / slope / 2.5 / unit))   # as a Gaussian sigma, in original px
    p = dict(PARAMS.get(detail, PARAMS["balanced"]), blur=blur)
    if loose:
        p.update(smooth=p["smooth"] * 2.5, tol=p["tol"] * 1.8, line=p["line"] * 1.5,
                 per_curve=math.radians(60))   # shorter curves pass first time more often: faster
        # A few shapes: a coloured logo or diagram, whose corners matter.  Thousands: a real photo,
        # where the shapes are brush-like and hunting for corners only costs time.
        p["corner"] = max(p["corner"], 40.0) if len(pts) <= 400 else None
    if contrast:
        h, w = field.shape

        def probe(q):
            """Share of ink (0..1) the picture shows at outline-space point q."""
            x = min(max(q[0] * unit, 0.0), w - 1.001)
            y = min(max(q[1] * unit, 0.0), h - 1.001)
            x0, y0 = int(x), int(y)
            fx, fy = x - x0, y - y0
            v = (field[y0, x0] * (1 - fx) * (1 - fy) + field[y0, x0 + 1] * fx * (1 - fy)
                 + field[y0 + 1, x0] * (1 - fx) * fy + field[y0 + 1, x0 + 1] * fx * fy)
            return min(1.0, max(0.0, 0.5 - float(v) / contrast))
        p["probe"] = probe
    sx, sy = scale
    done: dict[int, str] = {}
    for i, Q in enumerate(pts):
        if tick is not None and i % 200 == 0:
            tick(i / max(1, len(pts)))
        if len(Q) < 4:
            continue
        fitted = fit_outline(Q / unit, p)
        if fitted is not None and fitted[1]:
            done[i] = _path_d(fitted[0], fitted[1], unit, sx, sy)
    paths = []
    for i in range(len(pts)):
        if hier[i][3] != -1 or i not in done:   # holes are written with the shape they belong to
            continue
        d = done[i]
        child = hier[i][2]
        while child != -1:
            d += done.get(int(child), "")
            child = hier[child][0]
        paths.append(d)
    return paths
