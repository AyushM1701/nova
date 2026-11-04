"use strict";
// Nova's orb: a rotating point-cloud sphere that follows what Nova is doing. Shared source: core/phone.py page() puts it
// into core/app.html (the same way as md.js), so there is one copy and no build step.
//
//   Orb.mount(canvas, { hue })   the canvas to draw on (it fills its CSS size); nothing runs until resume()
//   Orb.setHue(hue)              the colour, 0-360 (the window's colour picker)
//   Orb.set(state)               idle | listening | thinking | speaking | approval | paused | gone
//   Orb.level(v)                 0..1, the microphone while listening; a real level while speaking, if one is ever fed
//   Orb.pause() / Orb.resume()   the animation loop only runs between these: the page calls them as the orb shows or hides
const Orb = (() => {
  const N = 600, K = 3, FOCAL = 3.2;
  // What each state looks like. Targets are eased, so changes glide.
  const STATES = {
    idle:      { spin: .12, bright: 1.00, spread: 1.00, edge: .30, pulse: 0,    scale: 1.00 },
    listening: { spin: .22, bright: 1.00, spread: .88, edge: .42, pulse: .045, scale: .94 },
    thinking:  { spin: .45, bright: .70, spread: 1.18, edge: .20, pulse: .010, scale: 1.02 },
    speaking:  { spin: .16, bright: 1.25, spread: 1.00, edge: .45, pulse: .075, scale: 1.00 },
    approval:  { spin: 0,   bright: .60, spread: 1.08, edge: .22, pulse: 0,    scale: 1.00 },  // waiting for you: no activity
    paused:    { spin: 0,   bright: .45, spread: 1.00, edge: .18, pulse: 0,    scale: .98 },
    gone:      { spin: 0,   bright: .22, spread: 1.00, edge: .10, pulse: 0,    scale: .98 },
  };

  // Milliseconds between pictures when nothing is happening: this runs in a tray app, so it spares the battery.
  const CALM = { idle: 50, approval: 100, paused: 100, gone: 100 };

  function rng(seed) { // mulberry32: the same layout every time
    return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  const rand = rng(7);
  const gauss = () => Math.sqrt(-2 * Math.log(rand() + 1e-9)) * Math.cos(2 * Math.PI * rand());

  // Points: a random direction, radius biased to the centre so the core is dense.
  const P = Array.from({ length: N }, () => {
    const x = gauss(), y = gauss(), z = gauss(), l = Math.hypot(x, y, z) || 1, r = Math.pow(rand(), 0.5);
    return { x: x / l * r, y: y / l * r, z: z / l * r, r, ph: rand() * 6.28, sp: .6 + rand() * 1.6 };
  });
  // Lines: each point joins its K nearest neighbours, built once.
  const E = [], seen = new Set();
  for (let i = 0; i < N; i++) {
    const d = [];
    for (let j = 0; j < N; j++) if (j !== i) d.push([(P[i].x - P[j].x) ** 2 + (P[i].y - P[j].y) ** 2 + (P[i].z - P[j].z) ** 2, j]);
    d.sort((a, b) => a[0] - b[0]);
    for (let k = 0; k < K; k++) {
      const j = d[k][1], key = i < j ? i * N + j : j * N + i;
      if (!seen.has(key)) { seen.add(key); E.push(i < j ? [i, j] : [j, i]); }
    }
  }

  let cv = null, ctx = null, W = 0, H = 0, dpr = 1, hue = 248;
  let sprite = null, state = "idle", cur = { ...STATES.idle }, yaw = 0, t = 0, last = 0, env = 0;
  let ext = 0, extAt = -1e9, reduced = false, raf = 0, frames = 0;
  const px = new Float32Array(N), py = new Float32Array(N), pd = new Float32Array(N);
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

  function makeSprite() { // a soft glow for one node
    const s = document.createElement("canvas"); s.width = s.height = 48; const g = s.getContext("2d");
    const r = g.createRadialGradient(24, 24, 0, 24, 24, 24);
    r.addColorStop(0, `hsla(${hue},90%,92%,1)`); r.addColorStop(.25, `hsla(${hue},85%,70%,.55)`); r.addColorStop(1, `hsla(${hue},80%,50%,0)`);
    g.fillStyle = r; g.fillRect(0, 0, 48, 48); sprite = s;
  }

  function size() {
    const w = cv.clientWidth || 0, h = cv.clientHeight || 0, d = Math.min(2, (typeof devicePixelRatio === "number" && devicePixelRatio) || 1);
    if (w === W && h === H && d === dpr) return;
    W = w; H = h; dpr = d; cv.width = Math.max(1, W * dpr); cv.height = Math.max(1, H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function level(ts) { // the speaking pulse: a real level if one was fed a moment ago, else a made-up one
    if (now() - extAt < 250) return ext;
    const s = ts / 1000;
    return Math.min(1, Math.abs(Math.sin(s * 5.1)) * .6 + Math.abs(Math.sin(s * 2.3 + 1.3)) * .4);
  }

  function frame(ts) {
    raf = 0;
    if (!cv) return;
    raf = requestAnimationFrame(frame);
    if (CALM[state] && ts - last < CALM[state]) return;  // a slow, steady orb doesn't need 60 pictures a second
    frames++;
    size();
    const dt = Math.min(.12, (ts - last) / 1000 || 0); last = ts; t += dt;
    const tgt = STATES[state], k = 1 - Math.exp(-dt * 3);
    for (const key in tgt) cur[key] += (tgt[key] - cur[key]) * k;
    const motion = reduced ? 0 : 1;
    yaw += cur.spin * dt * motion;
    const pitch = Math.sin(t * .15) * .25 * motion;
    const want = state === "speaking" ? level(ts) : state === "listening" ? (now() - extAt < 250 ? ext : 0) : 0;
    env += (want - env) * (1 - Math.exp(-dt * 14));
    // reduced motion keeps only a slow, small swell while speaking instead of the fast pulse
    const pulse = reduced ? (state === "speaking" ? cur.pulse * .3 * (.5 + .5 * Math.sin(t * 1.2)) : 0) : cur.pulse * env;

    const cx = W / 2, cy = H * .5, R = Math.min(W, H) * .36 * cur.scale * (1 + pulse);  // fills the stage it is given
    ctx.clearRect(0, 0, W, H);
    const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.9);
    bg.addColorStop(0, `hsla(${hue},80%,50%,${.16 * cur.bright * (1 + env * .6)})`); bg.addColorStop(1, `hsla(${hue},80%,40%,0)`);
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

    const cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    for (let i = 0; i < N; i++) {
      const p = P[i], w = motion * Math.sin(t * p.sp + p.ph) * .018 * cur.spread;
      const x = (p.x + w) * cur.spread, y = (p.y + w) * cur.spread, z = p.z * cur.spread;
      const x1 = x * cyw + z * syw, z1 = -x * syw + z * cyw, y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp, f = FOCAL / (FOCAL - z2);
      px[i] = cx + x1 * f * R; py[i] = cy + y1 * f * R; pd[i] = Math.max(0, Math.min(1, (z2 + 1.3) / 2.6));
    }

    ctx.globalCompositeOperation = "lighter"; ctx.lineWidth = 1;
    for (let b = 0; b < 3; b++) { // lines in three depth buckets, so the far side stays faint
      ctx.strokeStyle = `hsla(${hue},70%,66%,${Math.min(1, cur.edge * cur.bright * (.35 + .35 * b))})`;
      ctx.beginPath();
      for (const [a, c] of E) {
        if (Math.min(2, Math.floor((pd[a] + pd[c]) * 1.5)) !== b) continue;
        ctx.moveTo(px[a], py[a]); ctx.lineTo(px[c], py[c]);
      }
      ctx.stroke();
    }
    for (let i = 0; i < N; i++) { // nodes: bigger and brighter toward the core
      const p = P[i], core = 1 - p.r * .6, tw = reduced ? 1 : .75 + .25 * Math.sin(t * p.sp * 2.2 + p.ph);
      const s = (5 + 9 * core * pd[i]) * (1 + env * .25);
      ctx.globalAlpha = Math.min(1, cur.bright * (.25 + .75 * pd[i]) * tw * (.45 + core * .8));
      ctx.drawImage(sprite, px[i] - s / 2, py[i] - s / 2, s, s);
    }
    ctx.globalAlpha = 1;
    const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * .5);
    cg.addColorStop(0, `hsla(${hue},90%,85%,${.22 * cur.bright * (1 + env)})`); cg.addColorStop(1, `hsla(${hue},90%,70%,0)`);
    ctx.fillStyle = cg; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
    ctx.globalCompositeOperation = "source-over";

    if (state === "speaking" && !reduced) { // the audio strip, under the orb
      ctx.fillStyle = `hsla(${hue},80%,72%,.85)`;
      for (let i = 0; i < 24; i++) {
        const hgt = 2 + env * 16 * Math.abs(Math.sin(t * 9 + i * 1.7) * .7 + Math.sin(t * 5 + i * .6) * .3);
        ctx.fillRect(cx - 24 * 3.5 + i * 7, H - 20 - hgt / 2, 4, hgt);
      }
    }
  }

  return {
    mount(canvas, opts = {}) {
      cv = canvas; ctx = canvas.getContext("2d"); hue = opts.hue ?? hue; W = H = 0; makeSprite();
      const mq = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
      reduced = !!(mq && mq.matches);
      if (mq && mq.addEventListener) mq.addEventListener("change", e => { reduced = e.matches; });
    },
    setHue(h) { hue = h; if (cv) makeSprite(); },
    set(s) { if (s === "working") s = "thinking"; if (STATES[s]) state = s; },
    level(v) { ext = Math.max(0, Math.min(1, +v || 0)); extAt = now(); },
    pause() { if (raf) cancelAnimationFrame(raf); raf = 0; },
    resume() { if (cv && !raf) { last = 0; raf = requestAnimationFrame(frame); } },
    _peek: () => ({ state, cur: { ...cur }, yaw, frames, running: !!raf, reduced }),  // for tests
  };
})();
