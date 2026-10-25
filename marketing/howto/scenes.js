// FileMorph how-to film — scenes & timeline.
'use strict';

const TOTAL = 104;
const FPS = 60;
const SCENES = [];
const OX = 1250, OY = 590, S = 2;     // the stage orb: centre and film scale (orb = 192 px)
const ctx0 = $('#cv0').getContext('2d'), ctx1 = $('#cv1').getContext('2d');
const root = $('#scenes');

function scene(def) { def.layer = el('div', 'layer', null, root); def.layer.style.display = 'none'; SCENES.push(def); def.build?.(def.layer); return def; }

// ------------------------------------------------------------------ shared building blocks
class Head {
  constructor(parent, { n, label, title, sub, top = 360, center = false }) {
    this.e = el('div', 'head' + (center ? ' center' : ''), null, parent);
    this.e.style.top = top + 'px';
    this.chap = el('div', 'chap', `<span class="n">${n}</span><span class="bar"></span><span>${label}</span>`, this.e);
    this.bar = $('.bar', this.chap);
    this.ws = words(el('h1', null, title, this.e));
    this.ps = sub ? words(el('p', null, sub, this.e)) : [];
  }
  update(t, tin, tout) {
    const vis = t > tin - .05 && t < tout + 1;
    this.e.style.visibility = vis ? 'visible' : 'hidden';
    if (!vis) return;
    const k = expoOut(clamp((t - tin) / .8)), o = easeInOut(clamp((t - tout) / .45));
    this.chap.style.opacity = (k * (1 - o)).toFixed(3);
    this.chap.style.transform = `translateY(${((1 - k) * 12 - o * 10).toFixed(2)}px)`;
    this.bar.style.transform = `scaleX(${expoOut(clamp((t - tin - .1) / 1)).toFixed(3)})`;
    revealWords(this.ws, t, tin + .08, tout, .05, 46);
    revealWords(this.ps, t, tin + .4, tout + .04, .014, 22);
  }
}
const ICONS = {
  star: '<svg viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/></svg>',
  dots: '<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="18" cy="12" r="1" fill="currentColor"/></svg>',
  pin: '<svg viewBox="0 0 24 24"><path d="M9 4h6M10 4v6l-3 4h10l-3-4V4M12 14v6"/></svg>',
  min: '<svg viewBox="0 0 24 24"><path d="M6 12h12"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M14.5 6l-6 6 6 6"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M12 19V5M6.5 10.5L12 5l5.5 5.5M5 20h14" /></svg>',
};
function panelHead(p, title, back = false) {
  const h = el('div', 'ph', null, p);
  h.innerHTML = (back ? `<div class="ic">${ICONS.back}</div>` : '<i class="logo"></i>') +
    `<div class="tt">${title}</div><div class="ic">${ICONS.star}</div><div class="ic">${ICONS.dots}</div><div class="ic on">${ICONS.pin}</div><div class="ic">${ICONS.min}</div>`;
  return h;
}
const EXTCOL = { PDF: KIND.pdf, DOCX: '#2563eb', XLSX: KIND.sheet, JPG: KIND.image, HEIC: KIND.image, PNG: KIND.image, MOV: KIND.video, EPUB: '#b45309', SVG: KIND.vector };
function fileCard(parent, name, ext, opts = {}) {
  const f = el('div', 'file', null, parent);
  const sh = el('div', 'sheet', null, f);
  if (opts.img) { const im = el('div', 'img', null, sh); im.style.background = opts.img; }
  else [26, 38, 50, 62].forEach((y, i) => { const l = el('i', null, null, sh); l.style.top = y + 'px'; l.style.width = [44, 56, 50, 32][i] + 'px'; });
  const x = el('span', 'ext', ext, sh); x.style.background = EXTCOL[ext] ?? KIND.other;
  if (name) el('div', 'fname', name, f);
  if (opts.badge) el('div', 'badge', opts.badge, sh);
  return f;
}
/** cursor track: stops [[t,x,y]], presses [t,...], vis [tin,tout] */
function track(stops, presses = [], vis = null, ease = quintInOut) {
  return t => {
    const [x, y] = path2(t, stops, ease, 0.08);
    let o = 1;
    if (vis) o = env(t, vis[0], vis[1], .35, .35);
    if (o <= 0) return null;
    const down = presses.some(p => t >= p && t < p + .16);
    const lastPress = presses.filter(p => p <= t).pop();
    return { x, y, o, down, ripple: lastPress != null && t - lastPress < .5 ? (t - lastPress) / .5 : null };
  };
}
function chipX(i, n = 6, cx = OX, s = S) { return cx + s * (-(n * CW + 12) / 2 + 6 + i * CW + CW / 2); }
const fillKF = (a, b) => t => keyframes(clamp((t - a) / (b - a)), [[0, 0], [.18, .17], [.38, .4], [.52, .52], [.78, .84], [1, 1]], easeInOut);

// =================================================================== A · intro
scene({
  a: 0, b: 6.2, chap: 0, hud: false,
  build(L) {
    this.mark = el('div', null, 'FileMorph', L);
    css(this.mark, { position: 'absolute', left: 0, right: 0, top: '690px', textAlign: 'center', font: '600 112px/1 Geist', letterSpacing: '-.045em' });
    this.chars = [...'FileMorph'].map(c => c);
    this.mark.innerHTML = this.chars.map(c => `<span class="w">${c}</span>`).join('');
    this.cs = $$('.w', this.mark);
    this.tag = el('div', null, 'Convert any file into any format. Just drop it.', L);
    css(this.tag, { position: 'absolute', left: 0, right: 0, top: '832px', textAlign: 'center', font: '400 28px Geist', color: 'var(--dim)', letterSpacing: '-.01em' });
    this.tw = words(this.tag);
    this.pill = el('div', 'mono', 'WINDOWS &nbsp;·&nbsp; OFFLINE &nbsp;·&nbsp; FREE', L);
    css(this.pill, { position: 'absolute', left: '50%', top: '908px', transform: 'translateX(-50%)', font: '600 14px "Geist Mono"', letterSpacing: '.22em', color: '#8d93a6', padding: '10px 18px', border: '1px solid rgba(255,255,255,.1)', borderRadius: '20px' });
    this.orb = new OrbScript([{ t: 1.25, mode: 'idle' }]);
  },
  update(t) {
    revealWords(this.cs, t, 2.0, 5.0, .04, 70);
    revealWords(this.tw, t, 2.55, 5.05, .03, 26);
    const k = expoOut(clamp((t - 3.1) / .9)), o = easeInOut(clamp((t - 5.1) / .4));
    this.pill.style.opacity = (k * (1 - o)).toFixed(3);
  },
  draw(c0, c1, t) {
    // orb travels from the title position to its spot on the desktop of scene B
    const m = quintInOut(clamp((t - 5.0) / 1.2));
    const x = lerp(960, B_ORB.x, m), y = lerp(470, B_ORB.y, m), s = lerp(2.6, B_ORB.s, m);
    const r = 48 * 2.6;
    // ring draws itself
    const d = expoInOut(clamp((t - .25) / 1.3));
    const ringFade = 1 - soft(clamp((t - 1.3) / .5));
    if (d > 0 && ringFade > 0) {
      c0.save(); c0.translate(960, 470);
      const g = c0.createConicGradient(-Math.PI / 2 + t * .9, 0, 0);
      g.addColorStop(0, WAYS.Prism[0]); g.addColorStop(1 / 3, WAYS.Prism[1]); g.addColorStop(2 / 3, WAYS.Prism[2]); g.addColorStop(1, WAYS.Prism[0]);
      c0.globalAlpha = ringFade;
      c0.strokeStyle = g; c0.lineWidth = 4; c0.lineCap = 'round';
      c0.beginPath(); c0.arc(0, 0, r - 2, -Math.PI / 2, -Math.PI / 2 + d * Math.PI * 2); c0.stroke();
      // glowing head
      const a = -Math.PI / 2 + d * Math.PI * 2;
      if (d < 1) {
        const hx = Math.cos(a) * (r - 2), hy = Math.sin(a) * (r - 2);
        const hg = c0.createRadialGradient(hx, hy, 0, hx, hy, 26);
        hg.addColorStop(0, 'rgba(255,255,255,.9)'); hg.addColorStop(1, 'rgba(255,255,255,0)');
        c0.fillStyle = hg; c0.beginPath(); c0.arc(hx, hy, 26, 0, Math.PI * 2); c0.fill();
      }
      c0.restore();
    }
    const appear = soft(clamp((t - 1.1) / .7));
    if (appear > 0) drawOrb(c1, this.orb, t, x, y, s, { alpha: appear, scale: lerp(.92, 1, spring(clamp((t - 1.1) / .8))) });
  },
});

// =================================================================== B · desktop / meet the orb
const SCR = { x: 1230, y: 540, w: 1100, h: 620 };
const B_ORB = { x: SCR.x + 360, y: SCR.y + 150, s: 1.15 };
scene({
  a: 5.0, b: 12.4, chap: 1,
  build(L) {
    this.scr = el('div', 'glass', null, L);
    css(this.scr, { left: SCR.x - SCR.w / 2 + 'px', top: SCR.y - SCR.h / 2 + 'px', width: SCR.w + 'px', height: SCR.h + 'px', borderRadius: '22px', background: '#0b0c12' });
    const wall = el('div', null, null, this.scr);
    css(wall, { position: 'absolute', inset: 0, background: 'radial-gradient(60% 70% at 85% 10%,rgba(124,92,255,.38),transparent 70%),radial-gradient(50% 60% at 100% 100%,rgba(34,211,238,.22),transparent 70%),radial-gradient(55% 60% at 0% 100%,rgba(244,114,182,.24),transparent 70%),#0a0b12' });
    // desktop icons
    const icons = [['Q3 Report.pdf', 'PDF'], ['Budget.xlsx', 'XLSX'], ['Vacation.heic', 'HEIC', 'linear-gradient(160deg,#fbbf24,#f472b6 55%,#7c3aed)'], ['Interview.mov', 'MOV'], ['Logo.png', 'PNG', 'linear-gradient(160deg,#e2e8f0,#94a3b8)']];
    icons.forEach(([n, x, img], i) => {
      const f = fileCard(this.scr, n, x, { img }); place(f, 80 + (i % 2) * 120, 90 + Math.floor(i / 2) * 150, .72);
    });
    // taskbar
    const tb = el('div', null, null, this.scr);
    css(tb, { position: 'absolute', left: 0, right: 0, bottom: 0, height: '48px', background: 'rgba(16,18,26,.85)', borderTop: '1px solid rgba(255,255,255,.06)', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px' });
    ['#3b82f6', '#a3a9ba', '#f59e0b', '#22c55e', '#e11d48'].forEach(c => { const b = el('i', null, null, tb); css(b, { width: '26px', height: '26px', borderRadius: '7px', background: c, opacity: .75 }); });
    const clk = el('div', 'mono', '9:41', tb); css(clk, { position: 'absolute', right: '18px', font: '500 12px "Geist Mono"', color: '#a3a9ba' });
    this.head = new Head(L, { n: '01', label: 'Meet the orb', title: 'It floats on<br>your desktop.', sub: 'A small orb that sits above your windows, ready for files. Drag it anywhere.', top: 330 });
    this.head.e.style.width = '480px';
    this.orb = new OrbScript([{ t: 0, mode: 'idle', noPop: true, caption: [['dim', 'Drop a file · click to open']], capT: 6.6, capOff: 8.6 }]);
    this.cur = track([[8.3, 1500, 980], [9.1, B_ORB.x + 4, B_ORB.y + 10], [9.3, B_ORB.x + 4, B_ORB.y + 10], [10.3, B_ORB.x - 60 + 4, B_ORB.y - 120 + 10], [10.5, B_ORB.x - 60 + 4, B_ORB.y - 120 + 10], [11.2, B_ORB.x + 120, B_ORB.y + 60]], [9.2], [8.3, 11.0]);
  },
  orbPos(t) {
    const m = quintInOut(clamp((t - 9.3) / 1.0));
    return [B_ORB.x - 60 * m, B_ORB.y - 120 * m];
  },
  update(t) {
    const k = expoOut(clamp((t - 5.3) / 1.1));
    const [ox, oy] = this.orbPos(t);
    const z = expoInOut(clamp((t - 10.9) / 1.3));
    const sc = lerp(.94, 1, k) * (1 + 1.6 * z);
    // zoom toward the orb
    css(this.scr, { transformOrigin: `${ox - (SCR.x - SCR.w / 2)}px ${oy - (SCR.y - SCR.h / 2)}px`, transform: `translateY(${(1 - k) * 40}px) scale(${sc})`, opacity: (k * (1 - z)).toFixed(3), filter: z > .01 ? `blur(${(z * 10).toFixed(1)}px)` : 'none' });
    this.head.update(t, 5.9, 10.6);
  },
  draw(c0, c1, t) {
    if (t < 6.2) return; // scene A's orb owns the frame until it lands
    const [ox, oy] = this.orbPos(t);
    const z = expoInOut(clamp((t - 10.9) / 1.3));
    drawOrb(c1, this.orb, t, lerp(ox, OX, z), lerp(oy, OY, z), lerp(B_ORB.s, S, z), { capFade: 1 - z });
  },
  cursor(t) { return this.cur(t); },
});

// =================================================================== C · drop → pick → done
const PDF_AT = [930, 805], DOCX_AT = [1090, 805];
scene({
  a: 12.2, b: 30.2, chap: t => t < 16.8 ? 2 : t < 20.35 ? 3 : 4,
  build(L) {
    this.h1 = new Head(L, { n: '02', label: 'Drop', title: 'Drop a file<br>on the orb.', sub: 'Documents, PDFs, photos, slides, spreadsheets, video, audio. If it’s a file, drop it.' });
    this.h2 = new Head(L, { n: '03', label: 'Pick', title: 'Pick a format.', sub: 'The orb opens into your best matches. One click picks one. <b>•••</b> shows the rest.' });
    this.h3 = new Head(L, { n: '04', label: 'Convert', title: 'Watch it<br>morph.', sub: 'It fills as it works, entirely on your PC. Changed your mind? <b>Click the orb</b> or press <b>Esc</b> to cancel.' });
    this.h4 = new Head(L, { n: '04', label: 'Done', title: 'Done. Saved next<br>to the original.', sub: 'Same folder, same name, new format. Your original is never touched.' });
    this.pdf = fileCard(L, 'Q3 Report.pdf', 'PDF');
    this.ghost = fileCard(L, null, 'PDF');
    this.docx = fileCard(L, 'Q3 Report.docx', 'DOCX');
    const chips = ['DOCX', 'XLSX', 'SHRINK', 'JPG', 'PNG', '•••'];
    this.orb = new OrbScript([
      { t: 0, mode: 'idle', noPop: true },
      { t: 14.75, mode: 'hover', capT: 14.85 },
      { t: 16.0, mode: 'picking', chips, caption: [['k', 'PDF'], ['text', 'Q3 Report.pdf'], ['dim', '→ pick a format']], hover: [[17.85, 1], [18.75, 0]], press: 19.7 },
      { t: 19.95, mode: 'converting', caption: [['shiny', 'Converting to DOCX…']], fill: fillKF(20.3, 23.9) },
      { t: 24.15, mode: 'done', caption: [['ok', ''], ['text', 'Q3 Report.docx'], ['dim', 'saved']], fill: () => 1, capOff: 28.6 },
      { t: 28.6, mode: 'idle' },
    ]);
    this.cur = track([[13.0, 1720, 1010], [13.9, PDF_AT[0] + 6, PDF_AT[1] - 20], [14.05, PDF_AT[0] + 6, PDF_AT[1] - 20], [15.45, OX + 8, OY + 14], [15.8, OX + 8, OY + 14], [16.9, OX + 150, OY + 130],
      [17.85, chipX(1) + 6, OY + 12], [18.75, chipX(0) + 6, OY + 12], [19.75, chipX(0) + 6, OY + 12], [21.0, 1560, 940]], [14.0, 19.7], [12.9, 20.7]);
  },
  update(t) {
    this.h1.update(t, 12.5, 16.4);
    this.h2.update(t, 16.8, 19.95);
    this.h3.update(t, 20.35, 24.0);
    this.h4.update(t, 24.4, 29.5);
    // original pdf on the desktop
    const pin = expoOut(clamp((t - 12.6) / .9)), pout = env(t, 0, 30.2, .1, .7);
    place(this.pdf, PDF_AT[0], PDF_AT[1] + (1 - pin) * 30, 1.12, 0, Math.min(pin, pout) * (t > 14.05 && t < 16.1 ? .55 : 1));
    // drag ghost
    if (t >= 14.05 && t < 16.2) {
      const c = this.cur(t);
      const ab = soft(clamp((t - 15.8) / .38));
      const lift = spring(clamp((t - 14.05) / .5));
      const gx = lerp(c.x - 8, OX, ab), gy = lerp(c.y + 6, OY, ab);
      place(this.ghost, gx, gy, lerp(1.12, 1.2, lift) * (1 - ab * .8), -6 * lift * (1 - ab), .85 * (1 - ab));
    } else place(this.ghost, 0, 0, 1, 0, 0);
    // the new docx
    const d = clamp((t - 24.75) / .9);
    if (d > 0) {
      const k = spring(d), m = expoOut(d);
      place(this.docx, lerp(OX, DOCX_AT[0], m), lerp(OY, DOCX_AT[1], m) - Math.sin(Math.PI * m) * 60, lerp(.3, 1.12, k), lerp(-14, 0, m), Math.min(1, d * 3) * pout);
    } else place(this.docx, 0, 0, 1, 0, 0);
  },
  draw(c0, c1, t) { if (t >= 12.4) drawOrb(c0, this.orb, t, OX, OY, S); },
  cursor(t) { return this.cur(t); },
});

// =================================================================== D · every format (••• → All formats)
scene({
  a: 30.0, b: 37.8, chap: 5,
  build(L) {
    this.head = new Head(L, { n: '05', label: 'Every format', title: 'Need something<br>else?', sub: '<b>•••</b> opens every format your file can become, with options. 42 formats in, 38 out.' });
    const p = this.panel = el('div', 'panel', null, L);
    panelHead(p, 'All formats', true);
    el('div', 'fmt-file', '<span class="k">PDF</span><span>Q3 Report.pdf</span>', p);
    const cats = [['Documents', ['DOCX', 'DOC', 'ODT', 'RTF', 'TXT', 'MD', 'HTML', 'EPUB']], ['Spreadsheets', ['XLSX', 'CSV']], ['Images', ['PNG', 'JPG', 'WEBP', 'TIFF']], ['Tools', ['SHRINK', 'OCR', 'TRACE']]];
    this.chipEls = [];
    for (const [c, list] of cats) {
      el('div', 'lbl', c, p).style.margin = '18px 6px 9px';
      const g = el('div', 'chips', null, p);
      list.forEach(x => { const e = el('div', 'chp' + (x === 'DOCX' ? ' sel' : ''), x, g); e.dataset.k = x; this.chipEls.push(e); });
    }
    this.btn = el('div', 'btn', 'Convert to DOCX', p);
    el('div', 'lnk', 'Save as recipe…', p);
    css(p, { left: OX - 200 + 'px', top: '120px' });
    this.epub = this.chipEls.find(e => e.dataset.k === 'EPUB');
    this.docxEl = this.chipEls.find(e => e.dataset.k === 'DOCX');
    const chips = ['DOCX', 'XLSX', 'SHRINK', 'JPG', 'PNG', '•••'];
    this.orb = new OrbScript([
      { t: 0, mode: 'idle', noPop: true },
      { t: 30.35, mode: 'picking', chips, caption: [['k', 'PDF'], ['text', 'Q3 Report.pdf'], ['dim', '→ pick a format']], hover: [[31.1, 5]], press: 31.55 },
      { t: 31.85, mode: 'idle' },
      { t: 36.05, mode: 'converting', caption: [['shiny', 'Converting to EPUB…']], fill: fillKF(36.1, 36.85) },
      { t: 36.95, mode: 'done', caption: [['ok', ''], ['text', 'Q3 Report.epub'], ['dim', 'saved']], fill: () => 1 },
    ]);
    // chip centres (panel coords → stage) are measured once laid out
    this.cur = track([[30.3, 1580, 960], [31.1, chipX(5) + 6, OY + 12], [31.6, chipX(5) + 6, OY + 12], [33.3, 0, 0], [34.1, 0, 0], [35.0, 0, 0], [35.6, 0, 0], [36.4, 1600, 960]], [31.55, 34.1, 35.6], [30.2, 36.3]);
  },
  layoutOnce() {
    if (this._lo) return; this._lo = true;
    // panel is drawn at 1x then scaled 1.18 about its centre; resolve chip & button centres in stage coords
    const p = this.panel, s = 1.18;
    const pr = { x: OX - 200, y: 120, w: 400, h: p.offsetHeight };
    this.pr = pr;
    const at = e => { let x = e.offsetLeft + e.offsetWidth / 2, y = e.offsetTop + e.offsetHeight / 2, n = e.offsetParent; while (n && n !== p) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; } return [pr.x + pr.w / 2 + (x - pr.w / 2) * s, pr.y + pr.h / 2 + (y - pr.h / 2) * s]; };
    const e = at(this.epub), b = at(this.btn);
    const st = this.cur; const stops = [[30.3, 1580, 960], [31.1, chipX(5) + 6, OY + 12], [31.6, chipX(5) + 6, OY + 12], [33.3, e[0] + 8, e[1] + 10], [34.15, e[0] + 8, e[1] + 10], [35.0, b[0] + 30, b[1] + 8], [35.65, b[0] + 30, b[1] + 8], [36.4, 1600, 960]];
    this.cur = track(stops, [31.55, 34.1, 35.6], [30.2, 36.3]);
  },
  update(t) {
    this.layoutOnce();
    this.head.update(t, 30.45, 37.2);
    const o = spring(clamp((t - 31.75) / .7)), c = easeInOut(clamp((t - 35.7) / .28));
    const vis = o * (1 - c);
    const sc = 1.18 * (lerp(.25, 1, o) - .5 * c);
    css(this.panel, { opacity: Math.min(1, vis * 1.6).toFixed(3), transform: `translateY(${((1 - o) * 120 + c * 60).toFixed(1)}px) scale(${Math.max(.01, sc).toFixed(4)})`, visibility: vis > .001 ? 'visible' : 'hidden' });
    this.chipEls.forEach((e, i) => { const k = expoOut(clamp((t - 32.0 - i * .025) / .6)); e.style.opacity = k.toFixed(3); e.style.transform = `translateY(${((1 - k) * 10).toFixed(1)}px)`; });
    const picked = t >= 34.15;
    this.epub.classList.toggle('sel', picked); this.docxEl.classList.toggle('sel', !picked);
    this.btn.textContent = picked ? 'Convert to EPUB' : 'Convert to DOCX';
    const pr = t >= 35.6 && t < 35.85 ? 1 - Math.abs(1 - (t - 35.6) / .125) : 0;
    this.btn.style.transform = `scale(${1 - .04 * pr})`;
  },
  draw(c0, c1, t) {
    const hide = 1 - soft(clamp((t - 31.75) / .3)), back = soft(clamp((t - 35.98) / .25));
    const a = t < 34 ? hide : back;
    if (a > 0.001) drawOrb(c0, this.orb, t, OX, OY, S, { alpha: a });
  },
  cursor(t) { return this.cur(t); },
});

// =================================================================== E · batches
const PH = [['Receipt 1.jpg', 'JPG', 'linear-gradient(170deg,#fde68a,#f59e0b 60%,#b45309)', 860, 815, -5], ['Receipt 2.jpg', 'JPG', 'linear-gradient(170deg,#c4b5fd,#7c3aed 60%,#4c1d95)', 1000, 800, 2], ['Receipt 3.heic', 'HEIC', 'linear-gradient(170deg,#a5f3fc,#06b6d4 60%,#0e7490)', 1140, 815, 6]];
scene({
  a: 37.6, b: 45.4, chap: 6,
  build(L) {
    this.head = new Head(L, { n: '06', label: 'Batches', title: 'Drop a whole<br>stack at once.', sub: 'Select as many files as you like. Photos can even come out as <b>one PDF</b>.' });
    this.cards = PH.map(([n, x, img]) => fileCard(L, n, x, { img }));
    this.sel = el('div', null, null, L);
    css(this.sel, { position: 'absolute', left: 0, top: 0, border: '1px solid rgba(96,165,250,.9)', background: 'rgba(96,165,250,.14)', borderRadius: '4px' });
    this.stack = [0, 1, 2].map(i => fileCard(L, null, PH[i][1], { img: PH[i][2], badge: i === 2 ? '3' : null }));
    this.out = fileCard(L, 'Receipt 1 (combined).pdf', 'PDF');
    this.orb = new OrbScript([
      { t: 0, mode: 'idle' },
      { t: 40.4, mode: 'hover', capT: 40.5 },
      { t: 41.35, mode: 'picking', chips: ['PDF', 'PNG', 'WEBP', 'SHRINK', 'AVIF', '•••'], caption: [['k', '3'], ['text', '3 files'], ['dim', '→ pick a format']], hover: [[42.05, 0]], press: 42.55 },
      { t: 42.8, mode: 'converting', caption: [['shiny', 'Converting 3 files to PDF…']], fill: fillKF(42.95, 43.95) },
      { t: 44.05, mode: 'done', caption: [['ok', ''], ['text', 'Receipt 1 (combined).pdf'], ['dim', 'saved']], fill: () => 1 },
    ]);
    this.cur = track([[38.2, 1650, 1000], [38.75, 770, 715], [38.95, 770, 715], [39.55, 1215, 905], [39.75, 1215, 905], [40.25, 1004, 790], [40.4, 1004, 790], [41.1, OX + 8, OY + 14], [41.4, OX + 8, OY + 14], [42.05, chipX(0) + 6, OY + 12], [42.6, chipX(0) + 6, OY + 12], [43.4, 1580, 950]], [38.9, 40.35, 42.55], [38.0, 43.2], quintInOut);
  },
  update(t) {
    this.head.update(t, 37.95, 44.9);
    const marquee = t >= 38.95 && t < 39.8;
    const selected = t >= 39.3;
    const out = env(t, 0, 45.4, .1, .6);
    this.cards.forEach((c, i) => {
      const k = expoOut(clamp((t - 37.9 - i * .08) / .9));
      place(c, PH[i][3], PH[i][4] + (1 - k) * 30, 1.12, PH[i][5], k * out * (t > 40.4 && t < 44.3 ? .5 : 1));
      c.querySelector('.sheet').style.outline = selected && t < 41.3 ? '2px solid rgba(96,165,250,.95)' : 'none';
      c.querySelector('.sheet').style.outlineOffset = '4px';
    });
    if (marquee) {
      const c = this.cur(t), x0 = 770, y0 = 715;
      const f = clamp((t - 39.7) / .1);
      css(this.sel, { display: 'block', left: Math.min(x0, c.x) + 'px', top: Math.min(y0, c.y) + 'px', width: Math.abs(c.x - x0) + 'px', height: Math.abs(c.y - y0) + 'px', opacity: 1 - f });
    } else this.sel.style.display = 'none';
    if (t >= 40.4 && t < 41.75) {
      const c = this.cur(t), ab = soft(clamp((t - 41.4) / .35)), lift = spring(clamp((t - 40.4) / .5));
      this.stack.forEach((s, i) => place(s, lerp(c.x - 8 + (i - 1) * 9 * lift, OX, ab), lerp(c.y + 8 + (i - 1) * 4, OY, ab), 1.12 * (1 - ab * .8), (i - 1) * 7 * lift * (1 - ab), .9 * (1 - ab)));
    } else this.stack.forEach(s => place(s, 0, 0, 1, 0, 0));
    const d = clamp((t - 44.45) / .9);
    if (d > 0) { const m = expoOut(d); place(this.out, lerp(OX, 1310, m), lerp(OY, 830, m) - Math.sin(Math.PI * m) * 50, lerp(.3, 1.12, spring(d)), lerp(-12, 0, m), Math.min(1, d * 3) * out); }
    else place(this.out, 0, 0, 1, 0, 0);
  },
  draw(c0, c1, t) { drawOrb(c0, this.orb, t, OX, OY, S, { alpha: 1 - soft(clamp((t - 44.9) / .5)) }); },
  cursor(t) { return this.cur(t); },
});

// =================================================================== F · power tools
const TOOL_X = [420, 960, 1500], TOOL_Y = 620, TOOL_W = 500, TOOL_H = 590;
scene({
  a: 45.0, b: 60.6, chap: 7,
  build(L) {
    this.head = new Head(L, { n: '07', label: 'Built-in tools', title: 'Three tools that do the heavy lifting.', top: 110, center: true });
    this.head.e.querySelector('h1').style.fontSize = '58px';
    const defs = [
      ['TRACE', '#0e7490', 'Image to vector.', 'A logo, sketch or photo becomes a clean black &amp; white SVG, ready for cutters, lasers and print.'],
      ['OCR', '#b45309', 'Scans to real text.', 'Scanned PDFs and photos of pages turn into editable Word, Excel, or a searchable PDF.'],
      ['SHRINK', '#7c3aed', 'Same file, smaller.', 'Too big to email? Shrink PDFs, photos, Office files, video and audio.'],
    ];
    this.cards = defs.map(([tag, col, title, desc], i) => {
      const c = el('div', 'glass', null, L);
      css(c, { left: TOOL_X[i] - TOOL_W / 2 + 'px', top: TOOL_Y - TOOL_H / 2 + 'px', width: TOOL_W + 'px', height: TOOL_H + 'px' });
      const vis = el('div', null, null, c);
      css(vis, { position: 'absolute', left: '22px', top: '22px', right: '22px', height: '310px', borderRadius: '18px', background: '#090a10', border: '1px solid rgba(255,255,255,.06)', overflow: 'hidden' });
      const tg = el('div', 'mono', tag, c);
      css(tg, { position: 'absolute', left: '30px', top: '360px', font: '700 13px "Geist Mono"', letterSpacing: '.12em', padding: '7px 11px', borderRadius: '8px', background: hex(col, .22), color: mixHex(col, '#ffffff', .55), border: `1px solid ${hex(col, .5)}` });
      const h = el('div', null, title, c); css(h, { position: 'absolute', left: '30px', top: '410px', font: '600 32px Geist', letterSpacing: '-.025em' });
      const d = el('div', null, desc, c); css(d, { position: 'absolute', left: '30px', right: '30px', top: '462px', font: '400 18px/1.45 Geist', color: 'var(--dim)' });
      return { c, vis };
    });
    this.buildTrace(this.cards[0].vis);
    this.buildOcr(this.cards[1].vis);
    this.buildShrink(this.cards[2].vis);
  },
  buildTrace(v) {
    // the same artwork twice: a soft, low-res colour bitmap, and the traced black vector on a transparency grid
    const W = 456, H = 310;
    const art = (fill1, fill2, fill3, stroke) => `<svg viewBox="0 0 200 136" width="${W}" height="${H}" style="position:absolute;inset:0">
      <g transform="translate(100 70)">
        <circle r="52" fill="${fill1}" ${stroke}/>
        <circle cx="16" cy="-14" r="13" fill="${fill2}"/>
        <path d="M-44 28 L-18 -6 L-4 12 L10 -4 L44 28 Z" fill="${fill3}"/>
        <path d="M-40 34 Q0 22 40 34" stroke="${fill3}" stroke-width="5" fill="none" stroke-linecap="round"/>
      </g></svg>`;
    const bmp = el('div', null, null, v);
    css(bmp, { position: 'absolute', inset: 0, background: 'linear-gradient(160deg,#1d2336,#0e1220)' });
    const cv = el('canvas', null, null, bmp); cv.width = 76; cv.height = 52;
    css(cv, { position: 'absolute', inset: 0, width: W + 'px', height: H + 'px', imageRendering: 'pixelated', filter: 'blur(.6px) saturate(1.1)' });
    const img = new Image();
    img.onload = () => { const g = cv.getContext('2d'); g.fillStyle = '#e9dcc7'; g.fillRect(0, 0, 76, 52); g.drawImage(img, 0, 0, 76, 52);
      const d = g.getImageData(0, 0, 76, 52); for (let i = 0; i < d.data.length; i += 4) { const n = (Math.sin(i * 12.9898) * 43758.5453 % 1) * 26; d.data[i] += n; d.data[i + 1] += n; d.data[i + 2] += n; } g.putImageData(d, 0, 0); };
    img.src = 'data:image/svg+xml;utf8,' + encodeURIComponent(art('#2b3a67', '#f59e0b', '#e9dcc7', '').replace(`width="${W}" height="${H}" style="position:absolute;inset:0"`, 'xmlns="http://www.w3.org/2000/svg" width="76" height="52"'));
    this.traceReady = new Promise(r => { img.addEventListener('load', r); });
    const vec = this.vec = el('div', null, null, v);
    css(vec, { position: 'absolute', inset: 0, background: 'repeating-conic-gradient(#f4f4f6 0 25%,#e6e7ea 0 50%) 0 0/22px 22px' });
    vec.innerHTML = `<svg viewBox="0 0 200 136" width="${W}" height="${H}" style="position:absolute;inset:0"><g transform="translate(100 70)">
      <path class="tp" d="M0 -52 A52 52 0 1 1 -0.01 -52 Z M16 -27 A13 13 0 1 0 16.01 -27 Z M-44 28 L-18 -6 L-4 12 L10 -4 L44 28 Z" fill="#0a0b10" fill-rule="evenodd"/>
      <path d="M-40 34 Q0 22 40 34" stroke="#f4f4f6" stroke-width="5" fill="none" stroke-linecap="round"/>
      <g class="nodes" fill="#fff" stroke="#22d3ee" stroke-width=".9">${[[0, -52], [52, 0], [0, 52], [-52, 0], [16, -27], [3, -14], [-44, 28], [-18, -6], [-4, 12], [10, -4], [44, 28], [-40, 34], [40, 34]].map(([x, y]) => `<rect x="${x - 1.8}" y="${y - 1.8}" width="3.6" height="3.6"/>`).join('')}</g>
      </g></svg>`;
    this.nodes = $('.nodes', vec);
    this.scan = el('div', null, null, v);
    css(this.scan, { position: 'absolute', top: 0, bottom: 0, width: '2px', background: '#22d3ee', boxShadow: '0 0 24px 6px rgba(34,211,238,.6)' });
    this.tlabel = el('div', 'mono', 'logo.png → logo.svg', v);
    css(this.tlabel, { position: 'absolute', left: '14px', bottom: '12px', font: '600 12px "Geist Mono"', color: '#0a0b10', background: 'rgba(255,255,255,.85)', padding: '5px 8px', borderRadius: '6px', letterSpacing: '.04em' });
  },
  buildOcr(v) {
    css(v, { background: 'linear-gradient(160deg,#151826,#0b0d16)' });
    const page = this.page = el('div', null, null, v);
    css(page, { position: 'absolute', left: '88px', top: '24px', width: '280px', height: '340px', background: '#ecebe6', borderRadius: '4px', transform: 'rotate(-2.2deg)', boxShadow: '0 20px 40px rgba(0,0,0,.5)', overflow: 'hidden' });
    const lines = [['INVOICE', 700, 20, 26], ['No. 1042 · Oct 2026', 400, 12, 58], ['Laser engraving', 400, 13, 104, '$420.00'], ['CNC putter heads ×4', 400, 13, 130, '$760.00'], ['Finishing', 400, 13, 156, '$104.00'], ['Total', 700, 15, 202, '$1,284.00']];
    this.ocrRows = lines.map(([txt, w, fs, y, amt]) => {
      const blur = el('div', null, null, page);
      css(blur, { position: 'absolute', left: '22px', top: y + 'px', height: fs * .8 + 'px', width: (txt.length * fs * .55) + 'px', background: '#6b6a66', borderRadius: '2px', filter: 'blur(1.4px)', opacity: .65 });
      const b2 = amt ? el('div', null, null, page) : null;
      if (b2) css(b2, { position: 'absolute', right: '22px', top: y + 'px', height: fs * .8 + 'px', width: amt.length * fs * .55 + 'px', background: '#6b6a66', borderRadius: '2px', filter: 'blur(1.4px)', opacity: .65 });
      const real = el('div', null, `<span>${txt}</span>${amt ? `<span>${amt}</span>` : ''}`, page);
      css(real, { position: 'absolute', left: '22px', right: '22px', top: (y - 3) + 'px', display: 'flex', justifyContent: 'space-between', font: `${w} ${fs}px Geist`, color: '#14151a', letterSpacing: w > 600 ? '.02em' : '0' });
      return { blur, b2, real, y };
    });
    const sep = el('div', null, null, page); css(sep, { position: 'absolute', left: '22px', right: '22px', top: '188px', height: '1px', background: '#b9b7b0' });
    this.hl = el('div', null, null, page);
    css(this.hl, { position: 'absolute', left: '18px', top: '196px', height: '24px', background: 'rgba(59,130,246,.35)', borderRadius: '3px', width: 0 });
    this.beam = el('div', null, null, page);
    css(this.beam, { position: 'absolute', left: 0, right: 0, height: '2px', background: '#f59e0b', boxShadow: '0 0 22px 6px rgba(245,158,11,.55)' });
    this.otag = el('div', 'mono', '✓ Selectable text', v);
    css(this.otag, { position: 'absolute', right: '14px', bottom: '12px', font: '600 12px "Geist Mono"', color: '#fff', background: 'rgba(59,130,246,.9)', padding: '6px 9px', borderRadius: '6px', letterSpacing: '.04em' });
  },
  buildShrink(v) {
    css(v, { background: 'radial-gradient(80% 90% at 50% 0%,rgba(124,92,255,.18),transparent 70%),#090a10' });
    this.sfile = fileCard(v, 'Report.pdf', 'PDF'); place(this.sfile, 228, 110, 1.05);
    this.mb = el('div', null, '12.4 MB', v);
    css(this.mb, { position: 'absolute', left: 0, right: 0, top: '196px', textAlign: 'center', font: '600 44px "Geist Mono"', letterSpacing: '-.02em' });
    const trk = el('div', null, null, v); css(trk, { position: 'absolute', left: '50px', right: '50px', top: '262px', height: '8px', borderRadius: '4px', background: 'rgba(255,255,255,.07)' });
    this.bar = el('div', null, null, trk); css(this.bar, { position: 'absolute', left: 0, top: 0, bottom: 0, width: '100%', borderRadius: '4px', background: 'linear-gradient(90deg,#7c5cff,#22d3ee)' });
    this.save = el('div', 'mono', '−85%', v);
    css(this.save, { position: 'absolute', right: '50px', top: '204px', font: '700 15px "Geist Mono"', color: '#0a0b10', background: '#7ee2a8', padding: '6px 9px', borderRadius: '8px' });
    const seg3 = el('div', null, '<span>Light</span><span class="on">Balanced</span><span>Strong</span>', v);
    css(seg3, { position: 'absolute', left: '50%', top: '18px', transform: 'translateX(-50%)', display: 'flex', gap: '2px', padding: '3px', borderRadius: '10px', background: 'rgba(255,255,255,.06)', font: '500 12px Geist', color: '#a3a9ba' });
    $$('span', seg3).forEach(s => css(s, { padding: '5px 10px', borderRadius: '7px' })); css($('.on', seg3), { background: '#f5f6fa', color: '#0a0b10' });
    this.seg3 = seg3;
  },
  update(t) {
    this.head.update(t, 45.3, 59.9);
    const focus = t < 46.8 || t > 57.9 ? -1 : t < 50.4 ? 0 : t < 54.3 ? 1 : 2;
    this.cards.forEach(({ c }, i) => {
      const k = expoOut(clamp((t - 45.7 - i * .14) / 1.0)), o = easeInOut(clamp((t - 59.7 - i * .06) / .5));
      const f = focus < 0 ? 1 : focus === i ? 1 : 0;
      const fk = this._fk ??= [1, 1, 1];
      const dim = lerp(.42, 1, f);
      // smooth focus via time-based blend
      const ff = focusBlend(t, i);
      c.style.opacity = (k * (1 - o) * lerp(.45, 1, ff)).toFixed(3);
      c.style.transform = `translateY(${((1 - k) * 60 - o * 20).toFixed(1)}px) scale(${lerp(.965, 1, ff).toFixed(4)})`;
      c.style.borderColor = `rgba(255,255,255,${lerp(.07, .16, ff * (focus === i ? 1 : 0)).toFixed(3)})`;
      c.style.filter = o > .01 ? `blur(${(o * 8).toFixed(1)}px)` : 'none';
    });
    // TRACE 47.0 → 50.0
    const sx = expoInOut(clamp((t - 47.2) / 1.6));
    this.scan.style.left = (sx * 456) + 'px'; this.scan.style.opacity = sx > 0 && sx < 1 ? 1 : 0;
    this.vec.style.clipPath = `inset(0 ${((1 - sx) * 100).toFixed(2)}% 0 0)`;
    const nk = env(t, 48.8, 50.6, .4, .5);
    this.nodes.style.opacity = nk.toFixed(3);
    this.tlabel.style.opacity = expoOut(clamp((t - 49.0) / .5)).toFixed(3);
    // OCR 50.6 → 54
    const by = expoInOut(clamp((t - 50.7) / 1.7)), beamY = -10 + by * 260;
    this.beam.style.top = beamY + 'px'; this.beam.style.opacity = by > 0 && by < 1 ? 1 : 0;
    this.ocrRows.forEach(r => {
      const k = clamp((beamY - r.y) / 18);
      r.blur.style.opacity = (.65 * (1 - k)).toFixed(3); if (r.b2) r.b2.style.opacity = (.65 * (1 - k)).toFixed(3);
      r.real.style.opacity = k.toFixed(3); r.real.style.filter = k < 1 ? `blur(${((1 - k) * 3).toFixed(1)}px)` : 'none';
    });
    this.hl.style.width = (expoOut(clamp((t - 52.7) / .8)) * 248) + 'px';
    this.otag.style.opacity = expoOut(clamp((t - 53.1) / .5)).toFixed(3);
    // SHRINK 54.4 → 57
    const sk = expoOut(clamp((t - 54.9) / 1.6));
    this.mb.textContent = lerp(12.4, 1.8, sk).toFixed(1) + ' MB';
    this.bar.style.width = lerp(100, 14.5, sk) + '%';
    const sp = clamp((t - 56.3) / .5);
    this.save.style.opacity = Math.min(1, sp * 2).toFixed(3); this.save.style.transform = `scale(${lerp(.6, 1, spring(sp)).toFixed(3)})`;
    const fs = spring(clamp((t - 54.9) / .8)); place(this.sfile, 228, 112, lerp(1.05, .82, fs));
  },
  cursor() { return null; },
});
function focusBlend(t, i) {
  // 1 = in focus. Before 46.8 and after 57.9 all cards are in focus; between, one at a time, each change eased over .5 s
  const marks = [[46.8, 0], [50.4, 1], [54.3, 2], [57.9, -1]];
  let v = 1, prevT = 0, prevF = -1;
  const fOf = f => f < 0 || f === i ? 1 : 0;
  let cur = 1;
  for (const [mt, f] of marks) { if (t < mt) break; const from = cur; cur = fOf(f); prevT = mt; v = from; }
  return lerp(v, cur, easeInOut(clamp((t - prevT) / .5)));
}

// =================================================================== G · recipes + watch folders
const FOLDER = [1260, 560];
scene({
  a: 60.2, b: 70.6, chap: 8,
  build(L) {
    this.h1 = new Head(L, { n: '08', label: 'Recipes', title: 'Save it once.<br>Run it in one click.', sub: 'A recipe remembers the format, options, folder and file names. It shows up first, marked with a <b>★</b>.' });
    this.h2 = new Head(L, { n: '08', label: 'Watch folders', title: 'Or let a folder<br>do it for you.', sub: 'Point a recipe at a folder. New files that land there convert on their own.' });
    this.inv = fileCard(L, null, 'PDF');
    this.orb = new OrbScript([
      { t: 0, mode: 'idle' },
      { t: 61.15, mode: 'hover', capT: 61.2 },
      { t: 61.75, mode: 'picking', chips: ['★ Books', 'XLSX', 'DOCX', 'OCR', 'SHRINK', '•••'], caption: [['k', 'PDF'], ['text', 'Invoice-0193.pdf'], ['dim', '→ pick a format']], capSwitch: [[62.75, [['star', ''], ['text', 'Books'], ['dim', 'Excel · saved to Bookkeeping']]]], hover: [[62.75, 0]], press: 63.55 },
      { t: 63.8, mode: 'converting', caption: [['shiny', 'Converting to XLSX…']], fill: fillKF(63.9, 64.6) },
      { t: 64.7, mode: 'done', caption: [['ok', ''], ['text', 'Invoice-0193.xlsx'], ['dim', 'saved to Bookkeeping']], fill: () => 1 },
    ]);
    this.cur = track([[61.8, 1600, 980], [62.75, chipX(0) + 6, OY + 12], [63.6, chipX(0) + 6, OY + 12], [64.3, 1560, 930]], [63.55], [61.7, 64.2]);
    // watch folder
    const f = this.folder = el('div', null, null, L);
    css(f, { position: 'absolute', left: FOLDER[0] - 150 + 'px', top: FOLDER[1] - 115 + 'px', width: '300px', height: '230px' });
    f.innerHTML = `<svg viewBox="0 0 300 230" width="300" height="230" style="position:absolute;inset:0;overflow:visible">
      <defs><linearGradient id="fg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2f45"/><stop offset="1" stop-color="#161925"/></linearGradient>
      <linearGradient id="ff" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff" stop-opacity=".55"/><stop offset=".5" stop-color="#22d3ee" stop-opacity=".35"/><stop offset="1" stop-color="#f472b6" stop-opacity=".45"/></linearGradient></defs>
      <path d="M14 30 Q14 14 30 14 H112 Q122 14 128 24 L136 36 H270 Q286 36 286 52 V200 Q286 216 270 216 H30 Q14 216 14 200 Z" fill="url(#fg)" stroke="rgba(255,255,255,.12)"/>
      <path class="front" d="M8 76 Q8 62 22 62 H278 Q292 62 292 76 V202 Q292 218 276 218 H24 Q8 218 8 202 Z" fill="url(#ff)" stroke="rgba(255,255,255,.22)"/>
    </svg><div style="position:absolute;left:0;right:0;top:120px;text-align:center;font:600 26px Geist;letter-spacing:-.02em">Scans</div>
    <div class="wb" style="position:absolute;left:50%;top:166px;transform:translateX(-50%);display:flex;align-items:center;gap:8px;font:600 12px 'Geist Mono';letter-spacing:.12em;color:#7ee2a8;background:rgba(126,226,168,.12);border:1px solid rgba(126,226,168,.35);padding:6px 11px;border-radius:14px"><i style="width:7px;height:7px;border-radius:50%;background:#7ee2a8"></i>WATCHING</div>`;
    this.dot = $('.wb i', f);
    this.ins = [0, 1, 2].map(i => fileCard(L, null, 'PDF'));
    this.outs = [['Scan-0412.xlsx'], ['Scan-0413.xlsx'], ['Scan-0414.xlsx']].map(([n]) => fileCard(L, n, 'XLSX'));
    this.toast = el('div', 'toast', '<i class="o"></i><div><b>FileMorph</b><span>3 files converted to XLSX · Bookkeeping</span></div>', L);
  },
  update(t) {
    this.h1.update(t, 60.5, 64.75);
    this.h2.update(t, 65.1, 70.0);
    // invoice flies onto the orb on its own
    const d = clamp((t - 60.75) / .95);
    if (d > 0 && d < 1) { const m = quintInOut(d); place(this.inv, lerp(1640, OX, m), lerp(940, OY, m) - Math.sin(Math.PI * m) * 120, lerp(1.1, .3, cubicIn(d)), lerp(12, -8, m), Math.min(1, d * 4) * (1 - cubicIn(clamp((d - .7) / .3)))); }
    else place(this.inv, 0, 0, 1, 0, 0);
    // folder
    const fk = spring(clamp((t - 65.2) / .9)), fo = easeInOut(clamp((t - 70.0) / .5));
    css(this.folder, { opacity: (Math.min(1, fk * 1.5) * (1 - fo)).toFixed(3), transform: `scale(${lerp(.6, 1.15, fk).toFixed(4)})`, visibility: t > 65.1 ? 'visible' : 'hidden' });
    this.dot.style.opacity = (.55 + .45 * Math.cos(t * 5)).toFixed(3);
    [65.9, 66.55, 67.2].forEach((a, i) => {
      const k = clamp((t - a) / .8);
      if (k > 0 && k < 1) place(this.ins[i], lerp(FOLDER[0] - 30 + i * 30, FOLDER[0], k), lerp(150, FOLDER[1] - 40, quintInOut(k)), lerp(1, .4, cubicIn(k)), lerp(-8 + i * 8, 0, k), Math.min(1, k * 5) * (1 - cubicIn(clamp((k - .75) / .25))));
      else place(this.ins[i], 0, 0, 1, 0, 0);
      const o = clamp((t - a - .75) / .8);
      const yy = [430, 580, 730][i];
      if (o > 0) place(this.outs[i], lerp(FOLDER[0] + 60, 1620, expoOut(o)), lerp(FOLDER[1], yy, expoOut(o)), lerp(.4, 1, spring(o)), 0, Math.min(1, o * 3) * (1 - fo));
      else place(this.outs[i], 0, 0, 1, 0, 0);
    });
    const tk = expoOut(clamp((t - 68.3) / .8)), to = easeInOut(clamp((t - 69.9) / .5));
    css(this.toast, { left: '1460px', top: '870px', opacity: (tk * (1 - to)).toFixed(3), transform: `translateX(${((1 - tk) * 60).toFixed(1)}px)` });
  },
  draw(c0, c1, t) {
    const a = env(t, 60.2, 65.4, .5, .5);
    if (a > 0) drawOrb(c0, this.orb, t, OX, OY, S, { alpha: a });
  },
  cursor(t) { return this.cur(t); },
});

// =================================================================== H · right-click in Explorer
const WIN = { x: 1270, y: 560, w: 920, h: 560 };
scene({
  a: 70.4, b: 76.9, chap: 9,
  build(L) {
    this.head = new Head(L, { n: '09', label: 'Right-click', title: 'Already in Explorer?<br>Right-click.', sub: '<b>Convert with FileMorph</b> and your recipes are right there in the menu.' });
    const w = this.win = el('div', 'glass', null, L);
    css(w, { left: WIN.x - WIN.w / 2 + 'px', top: WIN.y - WIN.h / 2 + 'px', width: WIN.w + 'px', height: WIN.h + 'px', borderRadius: '14px', background: '#16171d' });
    w.innerHTML = `<div style="height:46px;display:flex;align-items:center;padding:0 18px;gap:12px;border-bottom:1px solid rgba(255,255,255,.06);font:500 14px Geist;color:#c9cdd8">
      <span style="opacity:.6">‹ ›</span><span style="flex:1;background:#202128;border-radius:8px;padding:7px 12px;font:400 13px Geist;color:#a3a9ba">This PC › Downloads</span><span style="opacity:.5">— ▢ ✕</span></div>
      <div style="display:flex;padding:10px 26px;font:500 12px Geist;color:#8d93a6;border-bottom:1px solid rgba(255,255,255,.04)"><span style="flex:1">Name</span><span style="width:160px">Type</span><span style="width:90px;text-align:right">Size</span></div>`;
    const rows = [['Interview.mov', 'MOV', 'Video', '84.2 MB'], ['Budget.xlsx', 'XLSX', 'Spreadsheet', '48 KB'], ['Q3 Report.pdf', 'PDF', 'PDF', '2.1 MB'], ['Logo.png', 'PNG', 'Image', '640 KB'], ['Vacation.heic', 'HEIC', 'Image', '3.4 MB'], ['Notes.docx', 'DOCX', 'Document', '22 KB']];
    this.rows = rows.map(([n, x, ty, sz]) => {
      const r = el('div', null, `<i style="width:22px;height:26px;border-radius:4px;background:${EXTCOL[x] ?? '#475569'};opacity:.85;margin-right:14px;flex:none"></i><span style="flex:1">${n}</span><span style="width:160px;color:#8d93a6">${ty}</span><span style="width:90px;text-align:right;color:#8d93a6">${sz}</span>`, w);
      css(r, { display: 'flex', alignItems: 'center', height: '46px', margin: '2px 12px', padding: '0 14px', borderRadius: '8px', font: '400 15px Geist', color: '#e6e8ef' });
      return r;
    });
    const m = this.menu = el('div', 'menu winmenu', null, L);
    const items = [['Open'], ['Open with', '›'], ['Share'], null, ['Convert with FileMorph', '', 'orb'], ['FileMorph recipes', '›', 'star'], null, ['Copy'], ['Rename'], ['Delete']];
    this.hl = el('div', 'hl', null, m);
    this.itemEls = items.map(it => {
      if (!it) return el('div', 'sep', null, m);
      const [n, ar, ic] = it;
      const icon = ic === 'orb' ? '<i style="width:16px;height:16px;border-radius:50%;background:radial-gradient(circle at 35% 30%,rgba(255,255,255,.35),#0c0e15 62%);box-shadow:inset 0 0 0 2px #7c5cff"></i>' : ic === 'star' ? '<svg width="16" height="16" viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z" fill="#ffd27a"/></svg>' : '';
      return el('div', 'it', `<span class="ico">${icon}</span><span>${n}</span>${ar ? `<span class="ar">${ar}</span>` : ''}`, m);
    });
    this.sub = el('div', 'menu winmenu', null, L);
    this.sub.innerHTML = '<div class="it"><span class="ico">★</span>Books</div><div class="it"><span class="ico">★</span>Web images</div><div class="it"><span class="ico">★</span>Email-size PDF</div>';
    $$('.ico', this.sub).forEach(e => e.style.color = '#ffd27a');
    css(this.sub, { minWidth: '220px' });
    this.orb = new OrbScript([
      { t: 0, mode: 'gone' },
      { t: 73.35, mode: 'idle', noPop: true },
      { t: 73.4, mode: 'picking', chips: ['MP4', 'MP3', 'GIF', 'SHRINK', 'WEBM', '•••'], caption: [['k', 'MOV'], ['text', 'Interview.mov'], ['dim', '→ pick a format']], hover: [[74.6, 1]], press: 75.2 },
      { t: 75.45, mode: 'converting', caption: [['shiny', 'Converting to MP3…']], fill: fillKF(75.5, 76.1) },
      { t: 76.15, mode: 'done', caption: [['ok', ''], ['text', 'Interview.mp3'], ['dim', 'saved']] },
    ]);
    this.menuAt = [1010, 370];
    this.cur = track([[70.8, 1600, 980], [71.5, 1000, 345], [71.7, 1000, 345], [72.35, 1040, 556], [72.9, 1040, 590], [73.25, 1040, 556], [73.4, 1040, 556], [74.6, chipX(1) + 6, OY + 12], [75.25, chipX(1) + 6, OY + 12], [75.9, 1600, 960]], [71.65, 73.3, 75.2], [70.7, 75.8]);
  },
  update(t) {
    this.head.update(t, 70.7, 76.3);
    const k = expoOut(clamp((t - 70.6) / 1.0)), o = easeInOut(clamp((t - 76.2) / .6));
    const dim = 1 - .55 * soft(clamp((t - 73.4) / .5));
    css(this.win, { opacity: (k * (1 - o) * dim).toFixed(3), transform: `translateY(${((1 - k) * 50).toFixed(1)}px) scale(${lerp(.96, 1, k).toFixed(4)})` });
    this.rows[0].style.background = t >= 71.65 ? 'rgba(96,165,250,.18)' : 'transparent';
    // context menu (Windows 11 style)
    const mo = spring(clamp((t - 71.75) / .5)), mc = easeInOut(clamp((t - 73.3) / .18));
    const mv = mo * (1 - mc);
    css(this.menu, { left: this.menuAt[0] + 'px', top: this.menuAt[1] + 'px', opacity: Math.min(1, mv * 1.5).toFixed(3), transform: `scale(${lerp(.92, 1, mo).toFixed(4)})`, visibility: mv > .001 ? 'visible' : 'hidden' });
    // highlight follows cursor rows: Convert (index 4) then recipes (5) then back
    const idx = t < 72.2 ? -1 : t < 72.75 ? 4 : t < 73.1 ? 5 : 4;
    const target = idx < 0 ? null : this.itemEls[idx];
    if (target) { css(this.hl, { display: 'block', top: target.offsetTop + 'px' }); } else this.hl.style.display = 'none';
    const so = t >= 72.75 && t < 73.1 ? 1 : 0;
    css(this.sub, { left: this.menuAt[0] + 296 + 'px', top: this.menuAt[1] + (this.itemEls[5].offsetTop - 5) + 'px', opacity: so * mv, visibility: so * mv > 0 ? 'visible' : 'hidden' });
  },
  draw(c0, c1, t) { drawOrb(c1, this.orb, t, OX, OY, S, { capFade: 1 - soft(clamp((t - 76.55) / .3)) }); },
  cursor(t) { return this.cur(t); },
});

// =================================================================== I · the panel
scene({
  a: 76.9, b: 82.6, chap: 10,
  build(L) {
    this.head = new Head(L, { n: '10', label: 'The panel', title: 'Click the orb<br>for the panel.', sub: 'A drop zone, your recent conversions, and where new files are saved.' });
    const p = this.panel = el('div', 'panel', null, L);
    panelHead(p, 'FileMorph');
    el('div', 'dz', `<div class="up">${ICONS.up}</div><b>Drop a file to convert</b><span>or <u>browse</u> your files</span>`, p);
    el('div', 'lbl', 'Recent', p);
    const rec = [['Interview.mp3', 'MOV → MP3', 'just now', KIND.audio], ['Invoice-0193.xlsx', 'PDF → XLSX', '1m ago', KIND.sheet], ['Receipt 1 (combined).pdf', 'JPG → PDF', '2m ago', KIND.image], ['Q3 Report.docx', 'PDF → DOCX', '3m ago', KIND.document]];
    this.recs = rec.map(([n, cv, tm, c]) => el('div', 'row', `<i class="d" style="background:${c}"></i><span class="nm">${n}</span><span class="cv">${cv}</span><span class="tm">${tm}</span>`, p));
    this.tog = el('div', 'tog', '<span>Save next to original</span><span class="sw"></span>', p);
    css(p, { left: OX - 200 + 'px', top: '150px' });
    this.ring = el('div', null, null, L);
    css(this.ring, { position: 'absolute', border: '2px solid #22d3ee', borderRadius: '16px', boxShadow: '0 0 30px rgba(34,211,238,.35)' });
    this.note = el('div', null, 'Turn it off to choose a folder', L);
    css(this.note, { position: 'absolute', font: '500 16px Geist', color: '#eef0f6', padding: '10px 14px', borderRadius: '12px', background: 'rgba(34,211,238,.14)', border: '1px solid rgba(34,211,238,.4)', whiteSpace: 'nowrap' });
    this.orb = new OrbScript([{ t: 76.9, mode: 'idle' }]);
    this.cur = track([[76.95, 1560, 950], [77.4, OX + 6, OY + 12], [77.6, OX + 6, OY + 12], [78.4, 1620, 900]], [77.5], [76.9, 78.2]);
  },
  update(t) {
    this.head.update(t, 77.0, 81.9);
    const o = spring(clamp((t - 77.6) / .75)), c = easeInOut(clamp((t - 81.8) / .4));
    const vis = o * (1 - c), s = 1.15 * (lerp(.2, 1, o) - .3 * c);
    css(this.panel, { opacity: Math.min(1, vis * 1.6).toFixed(3), transform: `translateY(${((1 - o) * 80).toFixed(1)}px) scale(${Math.max(.01, s).toFixed(4)})`, visibility: vis > .001 ? 'visible' : 'hidden' });
    this.recs.forEach((r, i) => { const k = expoOut(clamp((t - 78.2 - i * .1) / .7)); r.style.opacity = k.toFixed(3); r.style.transform = `translateX(${((1 - k) * 24).toFixed(1)}px)`; });
    // focus ring on the toggle (panel at 1x → stage via the 1.15 scale about its centre)
    if (!this.tg) { const ph = this.panel.offsetHeight; const ty = this.tog.offsetTop + this.tog.offsetHeight / 2; this.tg = [OX, 150 + ph / 2 + (ty - ph / 2) * 1.15, ph]; }
    const rk = env(t, 79.5, 81.7, .5, .4);
    const rw = 400 * 1.15 - 10, rh = 50;
    css(this.ring, { left: OX - rw / 2 + 'px', top: this.tg[1] - rh / 2 + 'px', width: rw + 'px', height: rh + 'px', opacity: rk.toFixed(3), transform: `scale(${lerp(1.08, 1, expoOut(clamp((t - 79.5) / .6))).toFixed(4)})` });
    const nk = env(t, 79.8, 81.7, .6, .4);
    css(this.note, { left: OX + 252 + 'px', top: this.tg[1] - 22 + 'px', opacity: nk.toFixed(3), transform: `translateX(${((1 - expoOut(clamp((t - 79.8) / .7))) * -20).toFixed(1)}px)` });
  },
  draw(c0, c1, t) {
    const a = 1 - soft(clamp((t - 77.6) / .3)) + soft(clamp((t - 82.0) / .3));
    drawOrb(c0, this.orb, t, OX, OY, S, { alpha: clamp(a) });
  },
  cursor(t) { return this.cur(t); },
});

// =================================================================== J · make it yours
const TRAY = [1824, 1052];
scene({
  a: 82.3, b: 90.6, chap: 11,
  build(L) {
    this.head = new Head(L, { n: '11', label: 'Make it yours', title: 'Right-click<br>the orb.', sub: 'Pick a color, change its size, or hide it in the tray. FileMorph keeps working either way.' });
    const m = this.menu = el('div', 'menu', null, L);
    const items = [['Hide to tray'], null, ['Open FileMorph'], ['Convert files…'], ['Recipes…'], ['Pause watching folders'], null, ['Show floating orb', '✓'], ['Keep on top', '✓'], ['Colorway', 'val'], ['Orb size', 'val'], null, ['Check for updates…'], ['FileMorph 0.4.1', 'dis'], ['Quit FileMorph']];
    this.hl = el('div', 'hl', null, m);
    this.items = items.map(it => {
      if (!it) return el('div', 'sep', null, m);
      const [n, x] = it;
      const e = el('div', 'it' + (x === 'dis' ? ' dis' : ''), `<span>${n}</span>${x === 'val' ? '<span class="val"></span><span class="ar" style="margin-left:10px">›</span>' : x === '✓' ? '<span class="val">✓</span>' : ''}`, m);
      return e;
    });
    this.valColor = $('.val', this.items[9]); this.valSize = $('.val', this.items[10]);
    css(m, { left: OX + 150 + 'px', top: '250px' });
    this.tb = el('div', null, null, L);
    css(this.tb, { position: 'absolute', left: 0, right: 0, bottom: 0, height: '56px', background: 'rgba(14,15,22,.92)', borderTop: '1px solid rgba(255,255,255,.07)', backdropFilter: 'blur(20px)' });
    this.tb.innerHTML = `<div style="position:absolute;left:50%;top:14px;transform:translateX(-50%);display:flex;gap:10px">${['#3b82f6', '#a3a9ba', '#f59e0b', '#22c55e', '#e11d48'].map(c => `<i style="width:28px;height:28px;border-radius:8px;background:${c};opacity:.7"></i>`).join('')}</div>
      <div style="position:absolute;right:26px;top:0;height:56px;display:flex;align-items:center;gap:18px;font:500 13px 'Geist Mono';color:#a3a9ba"><span style="opacity:.6">⌃</span><span class="tray-slot" style="width:22px"></span><span>9:41</span></div>`;
    this.orb = new OrbScript([
      { t: 0, mode: 'idle', noPop: true },
      { t: 86.65, mode: 'idle', base: 76, noPop: true },
      { t: 87.25, mode: 'idle', base: 60, noPop: true },
      { t: 87.85, mode: 'idle', base: 96, noPop: true },
    ]);
    // menu rows (1x) → stage. measured lazily
    this.cur = track([[82.6, 1560, 950], [83.2, OX + 10, OY + 12], [83.4, OX + 10, OY + 12]], [83.35], [82.5, 90.0]);
  },
  measure() {
    if (this.rowY) return;
    const m = this.menu, top = 250, s = 1.2;
    this.rowY = this.items.map(e => top + (e.offsetTop + e.offsetHeight / 2) * s);
    const x = OX + 150 + 130 * s;
    const cy = i => this.rowY[i] + 6;
    this.cur = track([[82.6, 1560, 950], [83.2, OX + 10, OY + 12], [83.4, OX + 10, OY + 12], [84.0, x, cy(9)], [86.3, x, cy(9)], [86.55, x, cy(10)], [88.4, x, cy(10)], [88.75, x, cy(0)], [89.0, x, cy(0)], [89.7, TRAY[0] - 40, TRAY[1] - 6], [90.2, TRAY[0] - 40, TRAY[1] - 6]],
      [83.35, 84.6, 85.2, 85.8, 86.95, 87.55, 88.15, 88.95], [82.5, 90.4]);
  },
  colorsAt(t) {
    const st = [[84.6, 'Citrus'], [85.2, 'Frost'], [85.8, 'Prism']];
    let from = 'Prism', to = 'Prism', at = 0;
    for (const [tt, n] of st) if (t >= tt) { from = to; to = n; at = tt; }
    const k = easeInOut(clamp((t - at) / .35));
    return [0, 1, 2].map(i => mixHex(WAYS[from][i], WAYS[to][i], k));
  },
  update(t) {
    this.measure();
    this.head.update(t, 82.65, 89.9);
    const mo = spring(clamp((t - 83.45) / .5)), mc = easeInOut(clamp((t - 88.95) / .2));
    const v = mo * (1 - mc);
    css(this.menu, { opacity: Math.min(1, v * 1.5).toFixed(3), transform: `scale(${(1.2 * lerp(.9, 1, mo)).toFixed(4)})`, visibility: v > .001 ? 'visible' : 'hidden' });
    const idx = t < 83.95 ? -1 : t < 86.45 ? 9 : t < 88.65 ? 10 : 0;
    if (idx >= 0) css(this.hl, { display: 'block', top: this.items[idx].offsetTop + 'px' }); else this.hl.style.display = 'none';
    this.valColor.textContent = t < 84.6 ? 'Prism' : t < 85.2 ? 'Citrus' : t < 85.8 ? 'Frost' : 'Prism';
    this.valSize.textContent = t < 86.95 ? 'Standard' : t < 87.55 ? 'Compact' : t < 88.15 ? 'Mini' : 'Standard';
    const tk = expoOut(clamp((t - 88.3) / .7)), tout = easeInOut(clamp((t - 90.1) / .5));
    this.tb.style.transform = `translateY(${((1 - tk) * 70 + tout * 70).toFixed(1)}px)`;
  },
  orbPos(t) {
    // Hide to tray: fly into the tray at 89.05; click the tray icon at 89.9 to bring it back (scene K)
    const k = quintInOut(clamp((t - 89.05) / .7));
    return { x: lerp(OX, TRAY[0], k), y: lerp(OY, TRAY[1] - 2, k) - Math.sin(Math.PI * k) * 80, s: lerp(S, .2, k) };
  },
  draw(c0, c1, t) {
    const p = this.orbPos(t);
    drawOrb(c1, this.orb, t, p.x, p.y, p.s, { colors: this.colorsAt(t), alpha: t > 89.6 ? 1 - clamp((t - 89.6) / .15) : 1 });
    // tray icon
    const tk = expoOut(clamp((t - 88.3) / .7)), tout = easeInOut(clamp((t - 90.1) / .5));
    if (tk > 0) {
      const y = TRAY[1] - 24 + (1 - tk) * 70 + tout * 70 + 24 - 24;
      c1.save(); c1.translate(TRAY[0], TRAY[1] + (1 - tk) * 70 + tout * 70);
      const pulse = t > 89.7 ? spring(clamp((t - 89.7) / .5)) : 0;
      c1.scale(1 + .25 * Math.sin(pulse * Math.PI), 1 + .25 * Math.sin(pulse * Math.PI));
      const g = c1.createConicGradient(t, 0, 0); g.addColorStop(0, '#7c5cff'); g.addColorStop(1 / 3, '#22d3ee'); g.addColorStop(2 / 3, '#f472b6'); g.addColorStop(1, '#7c5cff');
      c1.fillStyle = g; c1.beginPath(); c1.arc(0, 0, 10, 0, Math.PI * 2); c1.fill();
      c1.fillStyle = '#0c0e15'; c1.beginPath(); c1.arc(0, 0, 7.6, 0, Math.PI * 2); c1.fill();
      c1.restore();
    }
  },
  cursor(t) { return this.cur(t); },
  hudFade(t) { return 1 - env(t, 88.2, 90.6, .4, .4); },
});

// =================================================================== K · updates
scene({
  a: 90.1, b: 96.0, chap: 12,
  build(L) {
    this.head = new Head(L, { n: '12', label: 'Updates', title: 'Updates, only when<br>you want them.', sub: 'Check from the <b>⋯</b> menu. Nothing installs until you click <b>Update &amp; restart</b>.' });
    const p = this.panel = el('div', 'panel', null, L);
    panelHead(p, 'Updates', true);
    p.insertAdjacentHTML('beforeend', `<div style="display:flex;gap:16px;align-items:center;margin:10px 6px 0">
        <div style="width:52px;height:52px;border-radius:14px;background:#1b1e2b;display:grid;place-items:center;flex:none"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4f7cff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6.5 10.5L12 5l5.5 5.5"/></svg></div>
        <div><div style="font:600 19px Geist;letter-spacing:-.01em">Version 0.4.1 is available</div><div style="font:400 13px Geist;color:#a3a9ba;margin-top:4px">You have 0.4.0 · 9.8 MB download</div></div></div>
      <div class="lbl" style="margin-top:26px">What's new</div>
      <div style="border-radius:14px;background:#141722;padding:16px 16px 18px;font:400 14px/1.5 Geist;color:#dfe2ea;height:210px">
        <div><b>A smaller orb, if you like.</b> Standard, Compact or Mini.</div>
        <div style="margin-top:10px"><b>Hide to tray.</b> FileMorph keeps running: Explorer's menu and watch folders still work.</div></div>`);
    this.btn = el('div', 'btn', '<span class="pg"></span><span class="tx" style="position:relative">Update &amp; restart</span>', p);
    this.pg = $('.pg', this.btn); css(this.pg, { position: 'absolute', left: 0, top: 0, bottom: 0, background: 'linear-gradient(90deg,#c7d2fe,#a5f3fc)', width: 0 });
    this.tx = $('.tx', this.btn);
    el('div', 'lnk', 'Not now', p);
    css(p, { left: OX - 200 + 'px', top: '150px' });
    this.orb = new OrbScript([{ t: 0, mode: 'idle', noPop: true }, { t: 95.0, mode: 'updated', caption: [['ok', ''], ['text', 'Updated to 0.4.1']] }]);
  },
  measure() {
    if (this.bc) return;
    const ph = this.panel.offsetHeight, by = this.btn.offsetTop + this.btn.offsetHeight / 2;
    this.bc = [OX, 150 + ph / 2 + (by - ph / 2) * 1.15];
    this.cur = track([[90.4, TRAY[0] - 40, TRAY[1] - 6], [91.6, 1500, 860], [92.6, OX + 30, this.bc[1] + 8], [93.6, OX + 30, this.bc[1] + 8], [94.4, 1560, 940]], [92.95], [90.2, 94.2]);
  },
  update(t) {
    this.measure();
    this.head.update(t, 90.5, 95.5);
    const o = spring(clamp((t - 91.35) / .75)), c = easeInOut(clamp((t - 94.45) / .4));
    const vis = o * (1 - c), s = 1.15 * (lerp(.2, 1, o) - .3 * c);
    css(this.panel, { opacity: Math.min(1, vis * 1.6).toFixed(3), transform: `translateY(${((1 - o) * 80).toFixed(1)}px) scale(${Math.max(.01, s).toFixed(4)})`, visibility: vis > .001 ? 'visible' : 'hidden' });
    const pk = easeInOut(clamp((t - 93.05) / 1.25));
    this.pg.style.width = (pk * 100) + '%';
    this.tx.textContent = t < 93.05 ? 'Update & restart' : t < 94.3 ? 'Updating…' : 'Restarting…';
  },
  draw(c0, c1, t) {
    // the orb comes back from the tray, then hides behind the panel, then returns updated
    const k = quintInOut(clamp((t - 90.1) / .9));
    const x = lerp(TRAY[0], OX, k), y = lerp(TRAY[1] - 2, OY, k) - Math.sin(Math.PI * k) * 80, s = lerp(.2, S, k);
    const a = Math.min(clamp((t - 90.1) / .12), 1 - soft(clamp((t - 91.35) / .3)) + soft(clamp((t - 94.6) / .3)));
    drawOrb(c0, this.orb, t, x, y, s, { alpha: clamp(a) * (1 - soft(clamp((t - 95.55) / .45))) });
  },
  cursor(t) { return this.cur(t); },
});

// =================================================================== L · outro
scene({
  a: 95.6, b: TOTAL, chap: 0, hud: false,
  build(L) {
    this.s1 = el('div', null, 'Everything happens on your PC.', L);
    css(this.s1, { position: 'absolute', left: 0, right: 0, top: '420px', textAlign: 'center', font: '600 76px/1.05 Geist', letterSpacing: '-.04em' });
    this.s1w = words(this.s1);
    this.s2 = el('div', null, 'No uploads. No accounts. Works offline.', L);
    css(this.s2, { position: 'absolute', left: 0, right: 0, top: '530px', textAlign: 'center', font: '400 30px Geist', color: 'var(--dim)' });
    this.s2w = words(this.s2);
    this.mark = el('div', null, [...'FileMorph'].map(c => `<span class="w">${c}</span>`).join(''), L);
    css(this.mark, { position: 'absolute', left: 0, right: 0, top: '640px', textAlign: 'center', font: '600 104px/1 Geist', letterSpacing: '-.045em' });
    this.mw = $$('.w', this.mark);
    this.tag = el('div', null, 'Drop it. Pick a format. Done.', L);
    css(this.tag, { position: 'absolute', left: 0, right: 0, top: '772px', textAlign: 'center', font: '400 30px Geist', color: 'var(--dim)', letterSpacing: '-.01em' });
    this.tw = words(this.tag);
    this.url = el('div', null, '<span style="color:#8d93a6">FREE &amp; OPEN SOURCE FOR WINDOWS</span><span style="margin:0 18px;opacity:.35">|</span>github.com/JuicedSystems/FileMorph', L);
    css(this.url, { position: 'absolute', left: 0, right: 0, top: '870px', textAlign: 'center', font: '600 17px "Geist Mono"', letterSpacing: '.08em', color: '#eef0f6' });
    this.orb = new OrbScript([{ t: 99.6, mode: 'idle' }]);
  },
  update(t) {
    revealWords(this.s1w, t, 96.0, 98.75, .06, 50);
    revealWords(this.s2w, t, 96.7, 98.8, .03, 24);
    revealWords(this.mw, t, 99.9, null, .04, 70);
    revealWords(this.tw, t, 100.4, null, .03, 24);
    const k = expoOut(clamp((t - 100.9) / 1)); this.url.style.opacity = k.toFixed(3); this.url.style.transform = `translateY(${((1 - k) * 14).toFixed(1)}px)`;
    this.layer.style.opacity = (1 - easeInOut(clamp((t - (TOTAL - 1.0)) / .9))).toFixed(3);
  },
  draw(c0, c1, t) {
    const d = expoInOut(clamp((t - 98.85) / 1.0));
    const fade = 1 - easeInOut(clamp((t - (TOTAL - 1.0)) / .9));
    if (d > 0 && d < 1) {
      c0.save(); c0.translate(960, 420); c0.globalAlpha = fade * (1 - soft(clamp((t - 99.75) / .4)));
      const g = c0.createConicGradient(-Math.PI / 2 + t, 0, 0);
      g.addColorStop(0, WAYS.Prism[0]); g.addColorStop(1 / 3, WAYS.Prism[1]); g.addColorStop(2 / 3, WAYS.Prism[2]); g.addColorStop(1, WAYS.Prism[0]);
      c0.strokeStyle = g; c0.lineWidth = 3; c0.lineCap = 'round';
      c0.beginPath(); c0.arc(0, 0, 112, -Math.PI / 2, -Math.PI / 2 + d * Math.PI * 2); c0.stroke(); c0.restore();
    }
    const ap = soft(clamp((t - 99.5) / .6));
    if (ap > 0) drawOrb(c1, this.orb, t, 960, 420, 2.4, { alpha: ap * fade, scale: lerp(.9, 1, spring(clamp((t - 99.5) / .8))) });
  },
  cursor() { return null; },
});

// ------------------------------------------------------------------ background, hud, grain
const blobs = [$('#b1'), $('#b2'), $('#b3')];
const BL = [{ c: '#7c5cff', s: 900, x: 1500, y: 160, a: .32 }, { c: '#22d3ee', s: 820, x: 1750, y: 1000, a: .2 }, { c: '#f472b6', s: 860, x: 160, y: 980, a: .22 }];
BL.forEach((b, i) => css(blobs[i], { width: b.s + 'px', height: b.s + 'px', background: b.c, opacity: b.a }));
const grainTiles = [0, 1, 2, 3].map(i => {
  const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d'); const d = g.createImageData(256, 256);
  let s = 1234567 + i * 999;
  for (let p = 0; p < d.data.length; p += 4) { s = (s * 1103515245 + 12345) & 0x7fffffff; const v = s % 255; d.data[p] = d.data[p + 1] = d.data[p + 2] = v; d.data[p + 3] = 255; }
  g.putImageData(d, 0, 0); return c;
});
const gctx = $('#grain').getContext('2d');
const hud = $('#hud'), hudFill = $('#hud .fill'), hudCnt = $('#hud .cnt b');
const track$ = $('#hud .track');
// chapter ticks
(() => { const starts = [6.0, 12.4, 16.8, 20.35, 30.45, 37.95, 45.3, 60.5, 70.7, 77.0, 82.65, 90.5]; const span = [6, 95.6]; starts.forEach(s => { const e = el('i', 'tick', null, track$); e.style.left = ((s - span[0]) / (span[1] - span[0]) * 100) + '%'; }); })();
const cursorEl = $('#cursor'), ripple = $('#ripple');

function render(t) {
  // background drift
  BL.forEach((b, i) => {
    const x = b.x + Math.sin(t * .11 + i * 2) * 120, y = b.y + Math.cos(t * .09 + i) * 90;
    blobs[i].style.transform = `translate3d(${(x - b.s / 2).toFixed(1)}px,${(y - b.s / 2).toFixed(1)}px,0)`;
  });
  // intro/outro background fade
  $('#bg').style.opacity = (Math.min(soft(clamp(t / 1.5)), 1 - easeInOut(clamp((t - (TOTAL - 1)) / .9)))).toFixed(3);
  $('#dots').style.opacity = (env(t, 5.6, 99.0, 1.2, 1.2) * .9).toFixed(3);
  ctx0.clearRect(0, 0, 1920, 1080); ctx1.clearRect(0, 0, 1920, 1080);
  let cur = null, chap = 0, hudOn = 0, hudMul = 1;
  for (const s of SCENES) {
    const on = t >= s.a && t < s.b;
    s.layer.style.display = on ? 'block' : 'none';
    if (!on) continue;
    s.update?.(t);
    s.draw?.(ctx0, ctx1, t);
    const c = s.cursor?.(t); if (c) cur = c;
    const cc = typeof s.chap === 'function' ? s.chap(t) : s.chap; if (cc) chap = cc;
    if (s.hudFade) hudMul = Math.min(hudMul, s.hudFade(t));
  }
  // hud
  hudOn = env(t, 6.2, 95.5, .8, .6) * hudMul;
  hud.style.opacity = hudOn.toFixed(3);
  hudFill.style.transform = `scaleX(${clamp((t - 6) / (95.6 - 6)).toFixed(4)})`;
  if (chap) hudCnt.textContent = String(chap).padStart(2, '0');
  // cursor
  if (cur) {
    css(cursorEl, { display: 'block', opacity: cur.o.toFixed(3), transform: `translate3d(${(cur.x - 3).toFixed(1)}px,${(cur.y - 2).toFixed(1)}px,0) scale(${cur.down ? .86 : 1})` });
    if (cur.ripple != null) { const k = soft(cur.ripple); css(ripple, { display: 'block', opacity: ((1 - k) * .8 * cur.o).toFixed(3), transform: `translate3d(${(cur.x - 30).toFixed(1)}px,${(cur.y - 30).toFixed(1)}px,0) scale(${lerp(.25, 1.25, k).toFixed(3)})` }); }
    else ripple.style.display = 'none';
  } else { cursorEl.style.display = 'none'; ripple.style.display = 'none'; }
  // grain
  const fr = Math.round(t * FPS);
  const tile = grainTiles[fr % 4], ox = (fr * 73) % 256, oy = (fr * 151) % 256;
  gctx.clearRect(0, 0, 1920, 1080);
  for (let x = -ox; x < 1920; x += 256) for (let y = -oy; y < 1080; y += 256) gctx.drawImage(tile, x, y);
}

window.seek = t => { render(t); return true; };
window.TOTAL = TOTAL;
window.ready = (async () => {
  await document.fonts.load('600 20px Geist'); await document.fonts.load('400 20px Geist'); await document.fonts.load('500 20px Geist'); await document.fonts.load('700 20px Geist');
  await document.fonts.load('600 20px "Geist Mono"'); await document.fonts.load('700 20px "Geist Mono"'); await document.fonts.load('500 20px "Geist Mono"');
  await document.fonts.ready;
  await SCENES[5].traceReady;
  render(0);
  return true;
})();
