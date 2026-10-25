"""Synthesize the soundtrack: a soft ambient pad + gentle plucks, and UI sound effects synced to the film.

usage: python audio.py out.wav
"""
import sys
import wave

import numpy as np

SR = 48000
DUR = 104.0
N = int(SR * DUR)
rng = np.random.default_rng(7)
L = np.zeros(N)
R = np.zeros(N)


def note(name):
    names = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}
    n, o = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[n] + 12 * (o + 1) - 69) / 12)


def add(sig, t0, gain=1.0, pan=0.0):
    i0 = int(t0 * SR)
    if i0 >= N:
        return
    sig = sig[: N - i0]
    lg, rg = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    L[i0:i0 + len(sig)] += sig * gain * lg * 1.414
    R[i0:i0 + len(sig)] += sig * gain * rg * 1.414


def env_adsr(n, a, d, s, r, total):
    t = np.arange(n) / SR
    e = np.where(t < a, t / a, np.where(t < a + d, 1 - (1 - s) * (t - a) / d, s))
    rel = np.clip((total - t) / r, 0, 1)
    return e * rel


def onepole(x, cutoff):
    """time-varying one-pole lowpass; cutoff array or scalar (Hz)"""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


# ------------------------------------------------------------------ pad (D major-ish, airy)
CHORDS = [
    ['D3', 'A3', 'E4', 'F#4', 'C#5'],      # Dmaj9
    ['B2', 'F#3', 'D4', 'A4', 'C#5'],      # Bm9
    ['G2', 'D3', 'B3', 'F#4', 'A4'],       # Gmaj9
    ['A2', 'E3', 'B3', 'D4', 'F#4'],       # A6sus
]
BAR = 8.0
pad_start, pad_end = 0.3, 103.4
t = pad_start
k = 0
while t < pad_end:
    ch = CHORDS[k % 4]
    seg = min(BAR + 3.0, pad_end - t + 1.0)
    n = int(seg * SR)
    tt = np.arange(n) / SR
    sig = np.zeros(n)
    for j, nm in enumerate(ch):
        f = note(nm)
        for det in (-0.07, 0.0, 0.065):
            ff = f * 2 ** (det / 12)
            for h in range(1, 7):
                amp = (1 / h) * np.exp(-(h - 1) * 0.75)
                sig += amp * np.sin(2 * np.pi * ff * h * tt + rng.uniform(0, 6.28))
    # slow breathing filter feel via amplitude LFO
    sig *= 0.75 + 0.25 * np.sin(2 * np.pi * tt / 6.0 + k)
    e = env_adsr(n, 2.5, 1.0, 1.0, 3.0, seg)
    sig = sig * e / 60
    add(sig, t, 0.55, pan=-0.25 if k % 2 else 0.25)
    t += BAR
    k += 1
# sub
sub_t = np.arange(N) / SR
for i, ch in enumerate(CHORDS * 4):
    pass

# ------------------------------------------------------------------ plucks (eighth notes, 96 bpm)
EIGHTH = 60 / 96 / 2
pl = 6.2
step = 0
while pl < 97.5:
    bar = int((pl - pad_start) // BAR)
    ch = CHORDS[bar % 4]
    pattern = [4, 2, 3, 1, 4, 3, 2, 3]
    nm = ch[pattern[step % 8]]
    f = note(nm) * (2 if step % 16 in (0, 6, 11) else 1)
    dur = 0.6
    n = int(dur * SR)
    tt = np.arange(n) / SR
    sig = (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(2 * np.pi * 2 * f * tt) + 0.08 * np.sin(2 * np.pi * 3 * f * tt)) * np.exp(-tt / 0.16)
    sig *= np.minimum(1, tt / 0.003)
    accent = 1.0 if step % 4 == 0 else 0.62
    # quieter during the busier demo moments, fade near the outro
    g = 0.05 * accent
    if 45 < pl < 60:
        g *= 0.8
    if pl > 94:
        g *= max(0, (97.5 - pl) / 3.5)
    if pl < 8:
        g *= (pl - 6.2) / 1.8
    add(sig, pl, g, pan=0.35 if step % 2 else -0.35)
    pl += EIGHTH
    step += 1

# soft kick-like heartbeat on bar downbeats (very subtle)
for b in np.arange(12.4, 96, BAR / 2):
    n = int(0.35 * SR)
    tt = np.arange(n) / SR
    f = 52 + 40 * np.exp(-tt / 0.03)
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.12)
    add(sig, b, 0.13)


# ------------------------------------------------------------------ sfx
def click(t0, g=0.32):
    n = int(0.04 * SR)
    tt = np.arange(n) / SR
    nz = rng.standard_normal(n) * np.exp(-tt / 0.004)
    nz = nz - onepole(nz, 2500)  # highpass-ish
    tone = np.sin(2 * np.pi * 2100 * tt) * np.exp(-tt / 0.012) * 0.5
    add((nz * 0.6 + tone), t0, g)


def pop(t0, g=0.28, f0=320, f1=720):
    n = int(0.16 * SR)
    tt = np.arange(n) / SR
    f = f0 + (f1 - f0) * (1 - np.exp(-tt / 0.03))
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.05) * np.minimum(1, tt / 0.002)
    add(sig, t0, g)


def whoosh(t0, dur=0.7, g=0.22, up=True, pan=0.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    nz = rng.standard_normal(n)
    p = tt / dur
    cut = (300 + 5000 * p ** 1.5) if up else (5300 - 5000 * p ** 0.7)
    y = onepole(onepole(nz, cut), cut)
    e = np.sin(np.pi * np.clip(p, 0, 1)) ** 1.6
    add(y * e * 2.2, t0, g, pan)


def chime(t0, g=0.22, base=1318.5):
    n = int(1.8 * SR)
    tt = np.arange(n) / SR
    sig = np.zeros(n)
    for ratio, amp, dec in ((1, 1, .9), (2.0, .35, .5), (2.76, .25, .35), (5.4, .1, .18)):
        sig += amp * np.sin(2 * np.pi * base * ratio * tt) * np.exp(-tt / dec)
    sig2 = np.zeros(n)
    b2 = base * 1.5
    for ratio, amp, dec in ((1, .7, .8), (2.76, .2, .3)):
        sig2 += amp * np.sin(2 * np.pi * b2 * ratio * tt) * np.exp(-tt / dec)
    d = int(0.07 * SR)
    sig[d:] += sig2[:-d]
    sig *= np.minimum(1, tt / 0.004)
    add(sig / 2, t0, g, 0.1)


def swell(t0, dur=0.6, g=0.12, f0=220, f1=440):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (tt / dur)
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * tt / dur) ** 2
    add(sig, t0, g)


def fill_tone(t0, dur, g=0.06):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = 330 * (2 ** (tt / dur))
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * (0.5 + 0.5 * np.sin(2 * np.pi * 9 * tt)) * np.sin(np.pi * tt / dur) ** .8
    add(sig, t0, g)


def tick(t0, g=0.08):
    n = int(0.05 * SR)
    tt = np.arange(n) / SR
    add(np.sin(2 * np.pi * 3200 * tt) * np.exp(-tt / 0.006), t0, g)


# intro
whoosh(0.2, 1.4, 0.18)
chime(1.3, 0.2, 880)
whoosh(4.95, 1.2, 0.12, up=False)
# headline ticks
for h in (5.9, 12.5, 16.8, 20.35, 24.4, 30.45, 37.95, 45.3, 60.5, 65.1, 70.7, 77.0, 82.65, 90.5):
    tick(h + 0.08)
# scene B drag
click(9.2); whoosh(10.9, 1.3, 0.14)
# C drop / pick / convert / done
click(14.0); swell(14.75, 0.7); click(15.75, 0.18); pop(16.0); pop(16.25, .12, 500, 900)
tick(17.9, .05); tick(18.8, .05); click(19.7); fill_tone(20.3, 3.6); chime(24.15); pop(24.8, .18, 400, 800)
# D
pop(30.35); click(31.55); whoosh(31.7, .6, .12); click(34.1); click(35.6); whoosh(35.7, .5, .1, up=False); fill_tone(36.1, .8); chime(36.95, .18)
# E
click(38.9); click(40.35); swell(40.4, .7); click(41.0, .16); pop(41.35); click(42.55); fill_tone(42.95, 1.0); chime(44.05, .18); pop(44.5, .16, 400, 800)
# F tools
whoosh(45.2, 1.0, .14)
for i in range(3):
    pop(45.75 + i * .14, .12, 260 + 60 * i, 520 + 120 * i)
whoosh(47.2, 1.6, .1); tick(49.0, .06)
whoosh(50.7, 1.7, .08, up=False); click(52.7, .12)
fill_tone(54.9, 1.4, .05); pop(56.3, .2, 600, 1100)
# G recipes
whoosh(60.75, .9, .12); swell(61.15, .55); pop(61.75); tick(62.75, .05); click(63.55); fill_tone(63.9, .7); chime(64.7, .18)
pop(65.2, .16, 200, 400)
for a in (65.9, 66.55, 67.2):
    whoosh(a, .7, .06, up=False); pop(a + .75, .14, 450, 900)
chime(68.3, .14, 1046.5)
# H explorer
click(71.65); pop(71.75, .1, 600, 900); tick(72.2, .04); tick(72.75, .04); click(73.3); pop(73.4); click(75.2); fill_tone(75.5, .6); chime(76.15, .16)
# I panel
click(77.5); whoosh(77.55, .6, .12); tick(79.5, .06)
for i in range(4):
    tick(78.2 + i * .1, .035)
whoosh(81.8, .45, .08, up=False)
# J personalize
click(83.35); pop(83.45, .1, 600, 900)
for p in (84.6, 85.2, 85.8, 86.95, 87.55, 88.15):
    click(p, .2); pop(p + .02, .1, 500, 750)
click(88.95); whoosh(89.0, .8, .14, up=False); pop(89.7, .12, 700, 1000)
# K updates
whoosh(90.1, .9, .14); whoosh(91.3, .6, .1); click(92.95); fill_tone(93.05, 1.25, .05); chime(95.0, .2)
# outro
whoosh(95.6, 1.2, .1, up=False)
whoosh(98.8, 1.2, .14)
chime(99.6, .22, 880)
chime(99.65, .12, 1318.5)

# ------------------------------------------------------------------ master
mix = np.stack([L, R])
fade_in = np.minimum(1, np.arange(N) / (0.3 * SR))
fade_out = np.clip((DUR - np.arange(N) / SR) / 1.6, 0, 1)
mix *= fade_in * fade_out
mix = np.tanh(mix * 1.3) / 1.3
peak = np.abs(mix).max()
mix = mix / peak * 0.85
out = (mix.T * 32767).astype(np.int16)
with wave.open(sys.argv[1], 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(out.tobytes())
print('wrote', sys.argv[1], 'peak', peak)
