// FileMorph how-to film — motion library.
// Everything is a pure function of time t (seconds), so every frame renders deterministically.
'use strict';

// ------------------------------------------------------------------ easing (ported from motion.py)
const SPRING_SRC = "0,0.009,0.035 2.1%,0.141,0.281 6.7%,0.723 12.9%,0.938 16.7%,1.017,1.077,1.121,1.149 24.3%," +
  "1.159,1.163,1.161,1.154 29.9%,1.129 32.8%,1.051 39.6%,1.017 43.1%,0.991,0.977 51%," +
  "0.974 53.8%,0.975 57.1%,0.997 69.8%,1.003 76.9%,1.004 83.8%,1";
const SPRING = (() => {
  const raw = SPRING_SRC.split(',').map(s => { const b = s.trim().split(/\s+/); return [parseFloat(b[0]), b[1] ? parseFloat(b[1]) / 100 : null]; });
  raw[0][1] ??= 0; raw[raw.length - 1][1] ??= 1;
  for (let i = 0; i < raw.length; i++) {
    if (raw[i][1] === null) {
      let j = i; while (raw[j][1] === null) j++;
      const a = raw[i - 1][1], b = raw[j][1];
      for (let k = i; k < j; k++) raw[k][1] = a + (b - a) * (k - i + 1) / (j - i + 1);
      i = j;
    }
  }
  return raw.map(([v, p]) => [p, v]);
})();
function spring(t) {
  if (t <= 0) return 0; if (t >= 1) return 1;
  for (let i = 0; i < SPRING.length - 1; i++) {
    const [p0, v0] = SPRING[i], [p1, v1] = SPRING[i + 1];
    if (t <= p1) return v0 + (v1 - v0) * (p1 > p0 ? (t - p0) / (p1 - p0) : 1);
  }
  return 1;
}
function bezier(x1, y1, x2, y2) {
  const s = (a1, a2, t) => ((1 - 3 * a2 + 3 * a1) * t + (3 * a2 - 6 * a1)) * t * t + 3 * a1 * t;
  return x => {
    if (x <= 0) return 0; if (x >= 1) return 1;
    let lo = 0, hi = 1, t = x;
    for (let i = 0; i < 26; i++) { const cx = s(x1, x2, t); if (Math.abs(cx - x) < 1e-5) break; if (cx < x) lo = t; else hi = t; t = (lo + hi) / 2; }
    return s(y1, y2, t);
  };
}
const soft = bezier(0.22, 1, 0.36, 1);
const easeOut = bezier(0, 0, 0.58, 1);
const easeInOut = bezier(0.42, 0, 0.58, 1);
const expoOut = t => t >= 1 ? 1 : t <= 0 ? 0 : 1 - Math.pow(2, -10 * t);
const expoInOut = t => t <= 0 ? 0 : t >= 1 ? 1 : t < .5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2;
const cubicIn = t => t * t * t;
const quintInOut = bezier(0.83, 0, 0.17, 1);
const linear = t => Math.max(0, Math.min(1, t));
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
const loop = (period, t) => ((t % period) + period) % period / period;
const wave = ph => easeInOut(1 - Math.abs(1 - 2 * ph));
/** eased progress of t through [a, a+dur] */
const seg = (t, a, dur, ease = soft) => ease(clamp((t - a) / dur));
/** in/out envelope: 0 → 1 over [a, a+fin], 1 → 0 over [b-fout, b] */
const env = (t, a, b, fin = .6, fout = .5, ein = soft, eout = easeInOut) =>
  Math.min(ein(clamp((t - a) / fin)), 1 - eout(clamp((t - (b - fout)) / fout)));
function keyframes(t, frames, ease = easeOut) {
  if (t <= frames[0][0]) return frames[0][1];
  for (let i = 0; i < frames.length - 1; i++) {
    const [p0, v0] = frames[i], [p1, v1] = frames[i + 1];
    if (t <= p1) return v0 + (v1 - v0) * ease((t - p0) / (p1 - p0));
  }
  return frames[frames.length - 1][1];
}
/** piecewise eased path through [time, value] stops (each leg eased) */
function path1(t, stops, ease = quintInOut) {
  if (t <= stops[0][0]) return stops[0][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, v0] = stops[i], [t1, v1] = stops[i + 1];
    if (t <= t1) return lerp(v0, v1, ease(clamp((t - t0) / Math.max(1e-6, t1 - t0))));
  }
  return stops[stops.length - 1][1];
}
/** 2D eased path with optional arc: stops [[t,x,y]] */
function path2(t, stops, ease = quintInOut, arc = 0) {
  if (t <= stops[0][0]) return [stops[0][1], stops[0][2]];
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, x0, y0] = stops[i], [t1, x1, y1] = stops[i + 1];
    if (t <= t1) {
      const k = ease(clamp((t - t0) / Math.max(1e-6, t1 - t0)));
      const dx = x1 - x0, dy = y1 - y0, len = Math.hypot(dx, dy) || 1;
      const bow = Math.sin(Math.PI * k) * arc * len;
      return [lerp(x0, x1, k) - dy / len * bow, lerp(y0, y1, k) + dx / len * bow];
    }
  }
  const l = stops[stops.length - 1]; return [l[1], l[2]];
}
const hex = (h, a = 1) => { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
const mixHex = (a, b, k) => {
  const A = parseInt(a.slice(1), 16), B = parseInt(b.slice(1), 16);
  const c = s => Math.round(lerp(A >> s & 255, B >> s & 255, k));
  return '#' + ((1 << 24) + (c(16) << 16) + (c(8) << 8) + c(0)).toString(16).slice(1);
};

// ------------------------------------------------------------------ app design tokens (style.py)
const WAYS = { Prism: ['#7c5cff', '#22d3ee', '#f472b6'], Citrus: ['#a3e635', '#14b8a6', '#facc15'], Frost: ['#e2e8f0', '#60a5fa', '#ffffff'] };
const INK = '#eef0f6', DIM = '#a3a9ba', SUCCESS = '#7ee2a8';
const KIND = { image: '#6d28d9', video: '#be185d', audio: '#0f766e', document: '#b45309', sheet: '#15803d', slides: '#c2410c', pdf: '#b91c1c', vector: '#0e7490', other: '#475569' };
const SANS = '"Geist", system-ui, sans-serif', MONO = '"Geist Mono", ui-monospace, monospace';

// ------------------------------------------------------------------ Orb (port of node.py painting)
// A "script" is a list of events {t, mode, ...}. The orb's geometry springs between modes exactly like
// the app's Tweens (0.8 s spring), glyphs pop in with the glyph_in pulse, chips cascade in, etc.
const CW = 64;
function geomFor(ev, base) {
  if (ev.mode === 'hover') { const b = base * 1.25; return { w: b, h: b, r: b / 3, inset: 8 * base / 96 }; }
  if (ev.mode === 'picking') { const n = ev.chips.length; return { w: n * CW + 12, h: 68, r: 34, inset: 2 }; }
  if (ev.mode === 'hidden') return { w: base * .2, h: base * .2, r: base * .1, inset: 2 };
  return { w: base, h: base, r: base / 2, inset: 2 };
}
class OrbScript {
  constructor(events, opts = {}) {
    this.ev = events.slice().sort((a, b) => a.t - b.t);
    this.base = opts.base ?? 96;           // can be overridden per event with ev.base
    this.colors = opts.colors ?? WAYS.Prism;
    this._memo = new Map();
  }
  idx(t) { let i = -1; for (let k = 0; k < this.ev.length; k++) if (this.ev[k].t <= t) i = k; return i; }
  baseAt(i) { for (let k = i; k >= 0; k--) if (this.ev[k].base) return this.ev[k].base; return this.base; }
  geomAt(t, i = this.idx(t)) {
    if (i < 0) return geomFor({ mode: 'idle' }, this.base);
    const ev = this.ev[i];
    const target = geomFor(ev, this.baseAt(i));
    if (i === 0) return target;
    const key = i;
    let from = this._memo.get(key);
    if (!from) { from = this.geomAt(ev.t - 1e-6, i - 1); this._memo.set(key, from); }
    const k = spring(clamp((t - ev.t) / 0.8));
    const ki = spring(clamp((t - ev.t) / 0.6));
    return { w: lerp(from.w, target.w, k), h: lerp(from.h, target.h, k), r: lerp(from.r, target.r, k), inset: lerp(from.inset, target.inset, ki) };
  }
  spinAt(t) {   // deg; 60°/s idle, 300°/s while busy (with 0.6 s ease between)
    let a = 0, last = 0, busy = false;
    for (const e of this.ev) {
      if (e.t > t) break;
      a += (e.t - last) * (busy ? 300 : 60); last = e.t; busy = e.mode === 'hover' || e.mode === 'converting';
    }
    return a + (t - last) * (busy ? 300 : 60);
  }
}

const DROP_ARROW = [['M', 12, 4], ['v', 15], ['M', 6, 13], ['l', 6, 6], ['l', 6, -6]];
const SWAP = [['M', 4, 8.5], ['h', 14], ['l', -3.5, -3.5], ['M', 20, 15.5], ['H', 6], ['l', 3.5, 3.5]];
const UP_ARROW = [['M', 12, 19], ['v', -15], ['M', 6, 10], ['l', 6, -6], ['l', 6, 6]];

function iconPath(ctx, cmds, size, width, color) {
  const s = size / 24;
  ctx.save(); ctx.scale(s, s); ctx.translate(-12, -12);
  ctx.beginPath(); let x = 0, y = 0;
  for (const c of cmds) {
    const op = c[0];
    if (op === 'M') { x = c[1]; y = c[2]; ctx.moveTo(x, y); }
    else if (op === 'l') { x += c[1]; y += c[2]; ctx.lineTo(x, y); }
    else if (op === 'h') { x += c[1]; ctx.lineTo(x, y); }
    else if (op === 'H') { x = c[1]; ctx.lineTo(x, y); }
    else if (op === 'v') { y += c[1]; ctx.lineTo(x, y); }
  }
  ctx.lineWidth = width; ctx.strokeStyle = color; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke();
  ctx.restore();
}
function starPath(ctx, cx, cy, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 ? r * 0.45 : r, a = -Math.PI / 2 + i * Math.PI / 5;
    const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.closePath();
}
function rrect(ctx, x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath(); ctx.roundRect(x, y, w, h, r);
}

/**
 * Draw the orb at (cx, cy) with film scale `S` for script time t.
 * extra: { alpha, colors, hover:{idx,t}, progress(t)->0..1, scale (extra uniform), rot }
 */
function drawOrb(ctx, script, t, cx, cy, S = 2, extra = {}) {
  const i = script.idx(t);
  if (i < 0) return;
  const ev = script.ev[i];
  const mode = ev.mode;
  if (mode === 'gone') return;
  const base = script.baseAt(i);
  const osc = base / 96;
  const g = script.geomAt(t, i);
  const dt = t - ev.t;
  const colors = extra.colors ?? ev.colors ?? script.colors;
  const [c1, c2, c3] = colors;
  ctx.save();
  ctx.globalAlpha *= extra.alpha ?? 1;
  ctx.translate(cx, cy);
  ctx.scale(S * (extra.scale ?? 1), S * (extra.scale ?? 1));
  if (extra.rot) ctx.rotate(extra.rot);

  // ---- shock ring (done)
  if (mode === 'done' && dt < 0.85) {
    const k = soft(dt / 0.85);
    ctx.beginPath(); ctx.arc(0, 0, base / 2 * (1 + 1.4 * k), 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(255,255,255,${0.45 * (1 - k)})`; ctx.lineWidth = 1.5; ctx.stroke();
  }
  // ---- whole-shape transform
  ctx.save();
  if (mode === 'idle' || mode === 'converting' && false) { const s = 1 + 0.05 * wave(loop(3.6, t)); ctx.scale(s, s); }
  else if (mode === 'hover') { const k = wave(loop(1.3, dt)); ctx.rotate(9 * k * Math.PI / 180); ctx.scale(1 + .04 * k, 1 + .04 * k); }
  else if (mode === 'done' && dt < 0.75) {
    const p = dt / 0.75;
    ctx.scale(keyframes(p, [[0, 1], [.3, 1.25], [.55, .9], [.78, 1.04], [1, 1]]), keyframes(p, [[0, 1], [.3, .78], [.55, 1.1], [.78, .97], [1, 1]]));
  }
  const w = g.w, h = g.h, rad = Math.max(0, Math.min(g.r, w / 2, h / 2));
  const x = -w / 2, y = -h / 2;
  // ---- soft contact shadow
  for (let L = 0; L < 6; L++) {
    const k = (L + 1) / 6, grow = -4 + 9 * k;
    ctx.fillStyle = `rgba(0,0,0,${0.35 / 6 * (1.25 - k) * 1.6})`;
    rrect(ctx, x - grow, y - grow + 4, w + 2 * grow, h + 2 * grow, rad + grow); ctx.fill();
  }
  // ---- clip to shape
  ctx.save();
  rrect(ctx, x, y, w, h, rad); ctx.clip();
  // aura (conic) — CSS conic runs clockwise from top
  const spin = script.spinAt(t) * Math.PI / 180;
  const cg = ctx.createConicGradient(-Math.PI / 2 + spin, 0, 0);
  cg.addColorStop(0, c1); cg.addColorStop(1 / 3, c2); cg.addColorStop(2 / 3, c3); cg.addColorStop(1, c1);
  ctx.fillStyle = cg; ctx.fillRect(x - 2, y - 2, w + 4, h + 4);
  // inner glass
  const ins = g.inset;
  const iw = w - 2 * ins, ih = h - 2 * ins;
  if (iw > 0 && ih > 0) {
    const gx = x + ins + iw * 0.3, gy = y + ins + ih * 0.2;
    const far = Math.max(...[x + ins, x + ins + iw].flatMap(px => [y + ins, y + ins + ih].map(py => Math.hypot(gx - px, gy - py))));
    const rg = ctx.createRadialGradient(gx, gy, 0, gx, gy, far);
    rg.addColorStop(0, 'rgba(255,255,255,0.16)'); rg.addColorStop(0.62, 'rgba(12,14,21,0.9)'); rg.addColorStop(1, 'rgba(12,14,21,0.9)');
    ctx.fillStyle = rg; rrect(ctx, x + ins, y + ins, iw, ih, Math.max(0, rad - ins)); ctx.fill();
  }
  // liquid
  if (mode === 'converting' && ev.fill) {
    const f = mode === 'done' ? 1 : ev.fill(t);
    const fv = mode === 'done' ? lerp(ev.fillFrom ?? 1, 1, clamp(dt / .15)) : f;
    if (fv > 0.001) {
      ctx.save();
      const ii = Math.max(ins, 3);
      rrect(ctx, x + ii, y + ii, w - 2 * ii, h - 2 * ii, Math.max(0, rad - ii)); ctx.clip();
      // in "done" the liquid drains away softly as the check draws
      const drain = mode === 'done' ? 1 - soft(clamp((dt - .1) / .9)) : 1;
      const hh = h * fv * drain;
      const top = y + h - hh;
      ctx.fillStyle = c2;
      ctx.fillRect(x, top, w, hh + 1);
      const ph = loop(1.1, t), ww = w * 2, x0 = x - ph * w, sx = ww / 200, sy = 11 / 20, yy = top - 10;
      ctx.beginPath(); ctx.moveTo(x0, yy + 10 * sy);
      const pts = [[25, 0, 50, 10], [75, 20, 100, 10], [125, 0, 150, 10], [175, 20, 200, 10]];
      for (const q of pts) ctx.quadraticCurveTo(x0 + q[0] * sx, yy + q[1] * sy, x0 + q[2] * sx, yy + q[3] * sy);
      ctx.lineTo(x0 + ww, yy + 20 * sy); ctx.lineTo(x0, yy + 20 * sy); ctx.closePath(); ctx.fill();
      ctx.restore();
    }
  }
  // content
  if (mode === 'picking') drawChips(ctx, ev, t, x, y, w, h, extra);
  else {
    ctx.save(); ctx.scale(osc, osc);
    const gin = clamp(dt / 0.55), gk = spring(gin);
    const gx = () => { const s = .4 + .6 * gk; ctx.rotate(gin < 1 ? -30 * (1 - gin) * Math.PI / 180 : 0); ctx.scale(s, s); ctx.globalAlpha *= Math.min(1, gin * 2.2); };
    if (mode === 'idle' || mode === 'intro') {
      ctx.save(); if (!ev.noPop) gx(); iconPath(ctx, ev.glyph ?? SWAP, 30, 1.9, '#fff'); ctx.restore();
    } else if (mode === 'hover') {
      ctx.save(); if (dt > .5) ctx.translate(0, 4 * wave(loop(1.0, dt - .5))); gx(); iconPath(ctx, DROP_ARROW, 28, 2.0, '#fff'); ctx.restore();
    } else if (mode === 'converting') {
      const k = (0.5 + 0.5 * osc) / osc; ctx.scale(k, k);
      const pct = Math.round(clamp(ev.fill(t)) * 100) + '%';
      ctx.font = `600 18px ${MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(0,0,0,.31)'; ctx.fillText(pct, 0, 1.2 + 1); ctx.fillStyle = '#fff'; ctx.fillText(pct, 0, 1);
    } else if (mode === 'done') {
      drawCheck(ctx, clamp((dt - 0.15) / 0.5));
    } else if (mode === 'updated') {
      ctx.save(); gx(); iconPath(ctx, [['M', 5, 12.5], ['l', 4.5, 4.5], ['l', 9.5, -9.5]], 34, 2.4, '#fff'); ctx.restore();
    }
    ctx.restore();
  }
  ctx.restore(); // clip
  // hairline outline
  ctx.strokeStyle = 'rgba(255,255,255,0.1)'; ctx.lineWidth = 1;
  rrect(ctx, x - .5, y - .5, w + 1, h + 1, rad + .5); ctx.stroke();
  ctx.restore(); // shape transform

  // caption
  let parts = ev.caption ?? (mode === 'hover' ? [['text', 'Release to convert']] : null), born = ev.capT ?? ev.t;
  for (const [ct, cp] of ev.capSwitch ?? []) if (ct <= t) { parts = cp; born = ct; }
  if (ev.capOff != null && t >= ev.capOff) parts = null;
  if (parts && extra.caption !== false) {
    drawCaption(ctx, parts, t, born, -(188 - 34 - 15.5) + (96 - base) / 2, extra.capFade ?? 1);
  }
  ctx.restore();
}

function drawCheck(ctx, k) {
  if (k <= 0) return;
  k = soft(k);
  const pts = [[5.5, 12.5], [9.7, 16.7], [18.5, 7.3]];
  const s = 34 / 24;
  ctx.save(); ctx.scale(s, s); ctx.translate(-12, -12);
  const l1 = Math.hypot(4.2, 4.2), l2 = Math.hypot(8.8, 9.4), L = (l1 + l2) * k;
  ctx.beginPath(); ctx.moveTo(...pts[0]);
  if (L <= l1) ctx.lineTo(lerp(5.5, 9.7, L / l1), lerp(12.5, 16.7, L / l1));
  else { ctx.lineTo(...pts[1]); const r = (L - l1) / l2; ctx.lineTo(lerp(9.7, 18.5, r), lerp(16.7, 7.3, r)); }
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.4; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke();
  ctx.restore();
}

function drawChips(ctx, ev, t, x, y, w, h, extra) {
  const chips = ev.chips, n = chips.length, cw = (w - 12) / n, dt = t - ev.t;
  // indicator: hover stops ev.hover = [[t, idx], ...] (idx -1 = none)
  const hov = ev.hover ?? [];
  let cur = -1, prevIdx = -1, since = 0, opOn = 0;
  for (const [ht, hi] of hov) if (ht <= t) { prevIdx = cur; cur = hi; since = ht; }
  // indicator x springs between chips; opacity fades in on first hover
  const firstOn = hov.find(([ht, hi]) => hi >= 0 && ht <= t);
  if (cur >= 0 && firstOn) {
    opOn = linear((t - firstOn[0]) / .25);
    let fromIdx = prevIdx >= 0 ? prevIdx : cur;
    const k = spring(clamp((t - since) / .5));
    const ix = lerp(fromIdx, cur, k);
    ctx.fillStyle = `rgba(245,246,250,${opOn})`;
    rrect(ctx, x + 6 + ix * cw, y + 6, cw, h - 12, (h - 12) / 2); ctx.fill();
    // press feedback
    if (ev.press && t >= ev.press && t < ev.press + .25) {
      const pk = Math.sin(clamp((t - ev.press) / .25) * Math.PI);
      ctx.fillStyle = `rgba(255,255,255,${.25 * pk})`;
      rrect(ctx, x + 6 + ix * cw - 3 * pk, y + 6 - 3 * pk, cw + 6 * pk, h - 12 + 6 * pk, (h - 12) / 2 + 3 * pk); ctx.fill();
    }
  }
  ctx.font = `600 13px ${MONO}`; ctx.letterSpacing = '0.52px';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  chips.forEach((c, i) => {
    const r = clamp((dt - 0.2 - i * 0.05) / 0.55); if (r <= 0) return;
    const k = spring(r);
    const ccx = x + 6 + i * cw + cw / 2, ccy = y + h / 2;
    ctx.save(); ctx.translate(ccx, ccy + 8 * (1 - k)); const sc = .7 + .3 * k; ctx.scale(sc, sc);
    ctx.globalAlpha *= Math.min(1, k * 1.4);
    const on = i === cur && opOn > .5;
    const col = on ? '#0a0b10' : INK;
    if (c === '•••') { ctx.fillStyle = col; for (const dx of [-7, 0, 7]) { ctx.beginPath(); ctx.arc(dx, 0, 2.1, 0, Math.PI * 2); ctx.fill(); } }
    else if (c.startsWith('★')) {
      const label = c.slice(1).trim(); const tw = ctx.measureText(label).width; const x0 = -(tw + 13) / 2;
      ctx.fillStyle = on ? '#0a0b10' : '#ffd27a'; starPath(ctx, x0 + 4.5, -0.5, 5); ctx.fill();
      ctx.fillStyle = col; ctx.textAlign = 'left'; ctx.fillText(label, x0 + 13, 1); ctx.textAlign = 'center';
    } else { ctx.fillStyle = col; ctx.fillText(c, 0, 1); }
    ctx.restore();
  });
  ctx.letterSpacing = '0px';
}

/** caption pill above the orb; parts: [kind, text] like node.py */
function drawCaption(ctx, parts, t, born, cy, fade = 1) {
  const r = clamp((t - born) / .55); if (r <= 0) return;
  const k = spring(r);
  const fs = `400 13px ${SANS}`, fk = `700 11px ${MONO}`;
  const items = [];
  for (const [kind, text] of parts) {
    if (kind === 'k') { ctx.font = fk; ctx.letterSpacing = '0.66px'; items.push([kind, text, ctx.measureText(text).width + 12]); ctx.letterSpacing = '0px'; }
    else if (kind === 'ok' || kind === 'star') items.push([kind, text, 14]);
    else { ctx.font = fs; items.push([kind, text, ctx.measureText(text).width]); }
  }
  const gap = 8, inner = items.reduce((a, b) => a + b[2], 0) + gap * (items.length - 1), w = inner + 28, h = 31;
  ctx.save();
  ctx.translate(0, cy - 8 * (1 - k)); const sc = .88 + .12 * k; ctx.scale(sc, sc);
  ctx.globalAlpha *= Math.min(1, r * 2) * fade;
  ctx.fillStyle = 'rgba(13,15,22,0.84)'; rrect(ctx, -w / 2, -h / 2, w, h, h / 2); ctx.fill();
  ctx.strokeStyle = 'rgba(255,255,255,0.1)'; ctx.lineWidth = 1; ctx.stroke();
  let xx = -w / 2 + 14;
  ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  for (const [kind, text, iw] of items) {
    if (kind === 'k') {
      ctx.fillStyle = 'rgba(255,255,255,0.12)'; rrect(ctx, xx, -9.5, iw, 19, 6); ctx.fill();
      ctx.font = fk; ctx.letterSpacing = '0.66px'; ctx.fillStyle = INK; ctx.textAlign = 'center'; ctx.fillText(text, xx + iw / 2, 1); ctx.textAlign = 'left'; ctx.letterSpacing = '0px';
    } else if (kind === 'star') { ctx.fillStyle = '#ffd27a'; starPath(ctx, xx + 7, 0, 6.5); ctx.fill(); }
    else if (kind === 'ok') { ctx.save(); ctx.translate(xx + 7, 0); iconPath(ctx, [['M', 5, 12.5], ['l', 4.5, 4.5], ['l', 9.5, -9.5]], 14, 2.6, SUCCESS); ctx.restore(); }
    else if (kind === 'shiny') {
      ctx.font = fs;
      const ph = loop(1.8, t), span = iw * 2.2, off = xx + (1.2 - 2.4 * ph) * iw * .5 - span * .1;
      const lg = ctx.createLinearGradient(off, -iw * .36, off + span, iw * .36);
      lg.addColorStop(0, '#8f96aa'); lg.addColorStop(.3, '#8f96aa'); lg.addColorStop(.5, '#ffffff'); lg.addColorStop(.7, '#8f96aa'); lg.addColorStop(1, '#8f96aa');
      ctx.fillStyle = lg; ctx.fillText(text, xx, 1);
    } else { ctx.font = fs; ctx.fillStyle = kind === 'dim' ? DIM : INK; ctx.fillText(text, xx, 1); }
    xx += iw + gap;
  }
  ctx.restore();
}

// ------------------------------------------------------------------ DOM helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function el(tag, cls, html, parent) {
  const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; if (parent) parent.appendChild(e); return e;
}
function css(e, o) { for (const k in o) e.style[k] = o[k]; }
/** split an element's text into word spans (keeps inline tags like <b>) for staggered reveals */
function words(e) {
  const walk = node => {
    [...node.childNodes].forEach(ch => {
      if (ch.nodeType === 3) {
        const frag = document.createDocumentFragment();
        ch.textContent.split(/(\s+)/).forEach(w => {
          if (!w) return;
          if (/^\s+$/.test(w)) frag.appendChild(document.createTextNode(' '));
          else { const s = document.createElement('span'); s.className = 'w'; s.textContent = w; frag.appendChild(s); }
        });
        node.replaceChild(frag, ch);
      } else if (ch.nodeType === 1 && ch.tagName !== 'BR') walk(ch);
    });
  };
  walk(e);
  return $$('.w', e);
}
/** blur-rise reveal for a group of word spans */
function revealWords(spans, t, tin, tout, stagger = 0.045, dist = 38) {
  spans.forEach((s, i) => {
    const a = tin + i * stagger;
    const k = expoOut(clamp((t - a) / 0.9));
    const o = tout != null ? easeInOut(clamp((t - tout - Math.min(i * 0.015, .2)) / 0.45)) : 0;
    const y = (1 - k) * dist - o * 18;
    const b = (1 - k) * 14 + o * 10;
    s.style.transform = `translate3d(0,${y.toFixed(2)}px,0)`;
    s.style.opacity = (Math.min(1, k * 1.25) * (1 - o)).toFixed(3);
    s.style.filter = b > .05 ? `blur(${b.toFixed(2)}px)` : 'none';
  });
}
function fadeEl(e, k, y = 0, blur = 0, scale = 1) {
  e.style.opacity = clamp(k).toFixed(3);
  e.style.transform = `translate3d(0,${y.toFixed(2)}px,0) scale(${scale.toFixed(4)})`;
  e.style.filter = blur > .05 ? `blur(${blur.toFixed(2)}px)` : 'none';
  e.style.visibility = k <= 0.001 ? 'hidden' : 'visible';
}
function place(e, x, y, s = 1, rot = 0, o = 1) {
  e.style.transform = `translate3d(${x.toFixed(2)}px,${y.toFixed(2)}px,0) translate(-50%,-50%) rotate(${rot.toFixed(3)}deg) scale(${s.toFixed(4)})`;
  e.style.opacity = clamp(o).toFixed(3);
  e.style.visibility = o <= 0.001 ? 'hidden' : 'visible';
}
