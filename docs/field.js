// Silver dust in the key light, drawn to the cursor like filings to a magnet, and the merge strike. Two 2D canvases.
// Cursor magnetism is physics; everything on the page clock is a pure function of the sequence-second, so ?t= seeks.
(() => {
  const smooth = (a, b, v) => { const u = Math.min(Math.max((v - a) / (b - a), 0), 1); return u * u * (3 - 2 * u); };
  const hash = (i, s) => { const v = Math.sin(i * 77.819 + s * 19.271) * 43758.5453123; return v - Math.floor(v); };
  const DPR = Math.min(devicePixelRatio || 1, 1.5);
  const B = { LIGHT_START: .1, LIGHT_FULL: 1.3, ATTRACT_START: 1.2, ATTRACT_END: 5.0, LOCK_AT: 5.05, EXIT_AT: 10, EXIT_END: 11.2 };
  const LAYERS = [
    { share: .42, rMin: .35, rMax: .6, aMin: .14, aMax: .28, depth: .45, fill: "rgb(200,205,212)" },
    { share: .34, rMin: .5, rMax: .9, aMin: .2, aMax: .38, depth: .75, fill: "rgb(226,230,236)" },
    { share: .19, rMin: .8, rMax: 1.3, aMin: .3, aMax: .5, depth: 1, fill: "rgb(255,255,255)" },
    { share: .05, rMin: 2.4, rMax: 5, aMin: .08, aMax: .16, depth: 1.3, fill: "rgb(255,255,255)" },
  ];

  window.CWField = (canvas, getT, centre) => {
    const ctx = canvas.getContext("2d");
    const small = () => innerWidth <= 700;
    let N = small() ? 420 : 1100, W = 0, H = 0;
    let hx, hy, x, y, vx, vy, rad, alp, dep, fill;
    let cx = -1e4, cy = -1e4, tx = -1e4, ty = -1e4, power = 0, active = false, last = 0;
    const seed = () => {
      N = small() ? 420 : 1100;
      hx = new Float32Array(N); hy = new Float32Array(N); x = new Float32Array(N); y = new Float32Array(N);
      vx = new Float32Array(N); vy = new Float32Array(N); rad = new Float32Array(N); alp = new Float32Array(N); dep = new Float32Array(N); fill = new Array(N);
      let i = 0;
      LAYERS.forEach((L, li) => {
        const count = li === LAYERS.length - 1 ? N - i : Math.round(N * L.share);
        for (let k = 0; k < count && i < N; k++, i++) {
          hx[i] = x[i] = hash(i, 11) * W; hy[i] = y[i] = hash(i, 12) * H;
          rad[i] = L.rMin + (L.rMax - L.rMin) * hash(i, 13); alp[i] = L.aMin + (L.aMax - L.aMin) * hash(i, 14); dep[i] = L.depth; fill[i] = L.fill;
        }
      });
    };
    const resize = () => { W = canvas.clientWidth; H = canvas.clientHeight; canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR); ctx.setTransform(DPR, 0, 0, DPR, 0, 0); seed(); };
    new ResizeObserver(resize).observe(canvas); resize();
    addEventListener("pointermove", (e) => { if (e.pointerType === "touch") return; const r = canvas.getBoundingClientRect(); tx = e.clientX - r.left; ty = e.clientY - r.top; active = true; }, { passive: true });
    document.documentElement.addEventListener("pointerleave", () => { active = false; });

    const draw = (now) => {
      const dt = Math.min((now - last) / (1000 / 60), 2) || 1; last = now;
      const t = getT();
      const light = .04 + .96 * smooth(B.LIGHT_START, B.LIGHT_FULL, t);
      const attract = smooth(B.ATTRACT_START, B.ATTRACT_END - .6, t) * (1 - smooth(B.ATTRACT_END, B.ATTRACT_END + .7, t));
      const lock = t - B.LOCK_AT, ringR = lock >= 0 && lock < .9 ? (lock / .9) * Math.hypot(W, H) * .6 : -1;
      const exit = smooth(B.EXIT_AT, B.EXIT_END, t);
      power += ((active ? 1 : 0) - power) * .1 * dt;
      cx += (tx - cx) * .3 * dt; cy += (ty - cy) * .3 * dt;
      ctx.clearRect(0, 0, W, H);
      if (light < .02 || exit >= 1) return;
      const ex = centre.x || W / 2, ey = centre.y || H * .4;
      for (let i = 0; i < N; i++) {
        const d = dep[i];
        // home, pulled toward the measured spot while the tracks form, then let go
        let gx = hx[i] + (ex - hx[i]) * attract * .07 * d, gy = hy[i] + (ey - hy[i]) * attract * .07 * d;
        if (ringR > 0) { const dx = x[i] - ex, dy = y[i] - ey, dist = Math.hypot(dx, dy) || 1, g = Math.exp(-(((dist - ringR) / 30) ** 2)); gx += (dx / dist) * 16 * g * d; gy += (dy / dist) * 16 * g * d; }
        // the magnet: a loose corona about the cursor, spiralling in
        const dx = cx - x[i], dy = cy - y[i], dist = Math.hypot(dx, dy);
        let pull = 0;
        if (power > .01 && dist < 220) { const g = 1 - dist / 220; pull = power * g * g * (dist > 44 ? 1 : -(44 - dist) / 44); }
        const ux = dist ? dx / dist : 0, uy = dist ? dy / dist : 0;
        vx[i] += (pull * .75 * d * (ux - .07 * uy) + (gx - x[i]) * .005) * dt;
        vy[i] += (pull * .75 * d * (uy + .07 * ux) + (gy - y[i]) * .005) * dt;
        vx[i] *= Math.pow(.9, dt); vy[i] *= Math.pow(.9, dt);
        x[i] += vx[i] * dt; y[i] += vy[i] * dt;
        // draw: brighter when drawn to the cursor; streaking outward on the exit
        const glow = Math.max(0, pull), a = alp[i] * light * (1 + .5 * glow) * (1 - exit);
        let px = x[i], py = y[i];
        if (exit > 0) { px += (x[i] - ex) * exit * exit * 2.6 * d; py += (y[i] - ey) * exit * exit * 2.6 * d; }
        ctx.globalAlpha = Math.min(1, a);
        ctx.fillStyle = fill[i];
        ctx.beginPath(); ctx.arc(px, py, rad[i] + .7 * glow, 0, 6.283); ctx.fill();
        if (exit > .05) { ctx.globalAlpha = a * .5; ctx.strokeStyle = fill[i]; ctx.lineWidth = rad[i]; ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px - (px - ex) * .35 * exit, py - (py - ey) * .35 * exit); ctx.stroke(); }
      }
      ctx.globalAlpha = 1;
    };
    return { draw };
  };

  /* The merge strike: real lightning leaving the ring, two seconds long. Few channels, a tapering trunk, dim forks,
     the same channel re-lit by return strokes, darkness between discharges, the scene lit from the ring each time. */
  window.CWStrike = (el, centre) => {
    const ctx = el.getContext("2d");
    const DISCHARGES = [[0, 1, 3], [.62, .55, 1], [1.22, .4, 2]], STROKES = [[0, 1], [.07, .55], [.15, .8], [.27, .35]], TAPER = 6;
    let w = 0, h = 0, raf = 0, start = 0, fired = 0, struck = 0, power = 0, bolts = [], starts = [], cx = 0, cy = 0;
    const park = new URLSearchParams(location.search).get("strike");
    function grow(x0, y0, x1, y1, width, alpha, depth) {
      let pts = [x0, y0, x1, y1], sway = Math.hypot(x1 - x0, y1 - y0) * .085;
      for (let level = 0; level < 7; level++, sway *= .56) {
        const next = [];
        for (let i = 0; i < pts.length - 2; i += 2) {
          const ax = pts[i], ay = pts[i + 1], bx = pts[i + 2], by = pts[i + 3], len = Math.hypot(bx - ax, by - ay) || 1, off = (Math.random() + Math.random() - 1) * sway;
          next.push(ax, ay, (ax + bx) / 2 - ((by - ay) / len) * off, (ay + by) / 2 + ((bx - ax) / len) * off);
        }
        next.push(pts[pts.length - 2], pts[pts.length - 1]); pts = next;
      }
      bolts.push({ points: Float32Array.from(pts), width, alpha });
      if (depth >= 2) return;
      const nodes = pts.length / 2, forks = depth === 0 ? 4 + Math.floor(Math.random() * 4) : Math.floor(Math.random() * 3);
      for (let f = 0; f < forks; f++) {
        const n = Math.floor((.08 + .8 * Math.random()) * (nodes - 9)), i = 2 * n;
        const heading = Math.atan2(pts[i + 17] - pts[i + 1], pts[i + 16] - pts[i]) + (Math.random() < .5 ? -1 : 1) * (.22 + .5 * Math.random());
        const reach = Math.hypot(x1 - x0, y1 - y0) * (1 - n / nodes) * (.25 + .4 * Math.random());
        grow(pts[i], pts[i + 1], pts[i] + Math.cos(heading) * reach, pts[i + 1] + Math.sin(heading) * reach, width * .42, alpha * .6, depth + 1);
      }
    }
    const discharge = (channels) => {
      cx = centre.x || w / 2; cy = centre.y || h * .4;
      const r = Math.min(w, h) * .05, far = Math.hypot(w, h), turn = Math.random() * 6.283;
      bolts = [];
      for (let b = 0; b < channels; b++) { const a = turn + (b / channels) * 6.283 + (Math.random() - .5) * 1.6; grow(cx + Math.cos(a) * r, cy + Math.sin(a) * r * .9, cx + Math.cos(a) * far * .8, cy + Math.sin(a) * far * .8, b === 0 ? 1 : .7, 1, 0); }
    };
    const frame = (now) => {
      const t = park === null ? (now - start) / 1000 : Number(park);
      ctx.clearRect(0, 0, w, h);
      if (t >= 2) { raf = 0; return; }
      while (fired < DISCHARGES.length && t >= starts[fired]) { discharge(DISCHARGES[fired][2]); power = DISCHARGES[fired][1]; struck = starts[fired++]; }
      const age = t - struck;
      let light = 0;
      for (const [delay, strength] of STROKES) if (age >= delay) light += strength * Math.exp(-(age - delay) / .045);
      light = Math.min(1.3, light) * power;
      if (light < .01) { raf = requestAnimationFrame(frame); return; }
      const wash = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.hypot(w, h) * .75);
      wash.addColorStop(0, `rgba(205,225,255,${Math.min(.42, .32 * light)})`); wash.addColorStop(.35, `rgba(150,185,255,${Math.min(.22, .16 * light)})`); wash.addColorStop(1, "rgba(120,160,255,0)");
      ctx.fillStyle = wash; ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter"; ctx.strokeStyle = "#f4f8ff"; ctx.lineJoin = ctx.lineCap = "round";
      for (const bolt of bolts) {
        ctx.globalAlpha = Math.min(1, bolt.alpha * light);
        const nodes = bolt.points.length / 2, run = Math.ceil((nodes - 1) / TAPER);
        for (let k = 0; k < TAPER; k++) {
          const from = k * run, to = Math.min(nodes - 1, from + run); if (from >= to) break;
          ctx.lineWidth = Math.max(.7, 4 * bolt.width * (1 - .8 * (k / TAPER)) * (.6 + .4 * light));
          ctx.beginPath(); ctx.moveTo(bolt.points[2 * from], bolt.points[2 * from + 1]);
          for (let i = from + 1; i <= to; i++) ctx.lineTo(bolt.points[2 * i], bolt.points[2 * i + 1]);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(frame);
    };
    const resize = () => { w = el.clientWidth; h = el.clientHeight; el.width = Math.round(w * DPR); el.height = Math.round(h * DPR); ctx.setTransform(DPR, 0, 0, DPR, 0, 0); };
    new ResizeObserver(resize).observe(el); resize();
    return { fire() { start = performance.now(); fired = 0; power = 0; starts = DISCHARGES.map(([at], i) => at + (i ? (Math.random() - .5) * .16 : 0)); if (!raf) raf = requestAnimationFrame(frame); } };
  };
})();
