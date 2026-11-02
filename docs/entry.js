// The entry: one WebGL road scene and one clock. Every pose is a PURE function of the clock (seconds), so ?t=<s>
// seeks to any frame: the beats below, then the type, then the CTA; the CTA runs the exit and opens the platform.
import * as THREE from "three";

const SEQ = { START: 0, ATTRACT: 1.2, EMERGE: 2.6, BUILD: 3.5, ALMOST: 4.3, MERGED: 5.0, REST: 6.4, EXIT_START: 10, EXIT_END: 11.4 };
const CAPTION_AT = [SEQ.START, SEQ.ATTRACT, SEQ.EMERGE, SEQ.BUILD, SEQ.ALMOST, SEQ.MERGED];
const params = new URLSearchParams(location.search);
const seekParam = params.get("t") === null ? NaN : Number(params.get("t"));
const reduced = params.get("motion") === "reduce";
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const smooth = (a, b, v) => { const u = clamp01((v - a) / (b - a)); return u * u * (3 - 2 * u); };
const hash = (i, s) => { const v = Math.sin(i * 77.819 + s * 19.271) * 43758.5453123; return v - Math.floor(v); };
const lightAt = (t) => 0.04 + 0.96 * smooth(0, 1.1, t);
const $ = (s) => document.querySelector(s);

const entry = $("#entry"), cta = $("#cta"), tag = $("#tag"), platform = $("#platform");
const seq = { value: reduced ? SEQ.REST : 0 };
let stage = "boot";
const go = (next) => { stage = next; entry.className = `entry entry--${next}`; cta.disabled = next !== "ready"; };

/* ── data: the real near-miss, in road metres (x along the road 0..15, y across 0..7, wall side 0) ── */
const T = window.CW_TRACKS;
const toScene = ([x, y]) => [x - 7.5, y - 3.5];
const W2 = T.hero.where, W = new THREE.Vector3(W2[0] - 7.5, 0.2, W2[1] - 3.5);
const upTo = (path) => { let best = 0, bd = 1e9; path.forEach((p, i) => { const d = Math.hypot(p[0] - W2[0], p[1] - W2[1]); if (d < bd) { bd = d; best = i; } }); return [...path.slice(0, best + 1), W2]; };
const PERSON = upTo(T.hero.person).map(toScene), BIKE = upTo(T.hero.vehicle).map(toScene);

/* ── renderer, camera, lights ── */
const canvas = $("#scene");
let renderer = null;
try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" }); } catch { canvas.hidden = true; }
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 300);
const TARGET = new THREE.Vector3(0.8, 0.2, 0.6), BASE = new THREE.Vector3(15, 15.5, 18), Y = new THREE.Vector3(0, 1, 0);
scene.add(new THREE.HemisphereLight(0xffffff, 0x1b1e26, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.0); key.position.set(10, 20, 8); scene.add(key);
const flash = new THREE.PointLight(0xdfe8ff, 0, 30, 1.6); flash.position.copy(W).add(new THREE.Vector3(0, 1.5, 0)); scene.add(flash);

/* ── materials whose opacity follows the lights ── */
const lit = [];
const litMat = (m, base) => { m.transparent = true; m.opacity = 0; lit.push([m, base]); return m; };
const add = (m, x, y, z) => { m.position.set(x, y, z); scene.add(m); return m; };
function block(w, h, d, color, opacity, edge) {
  const g = new THREE.BoxGeometry(w, h, d);
  const m = new THREE.Mesh(g, litMat(new THREE.MeshStandardMaterial({ color, roughness: .4, metalness: .25, depthWrite: false }), opacity));
  if (edge) m.add(new THREE.LineSegments(new THREE.EdgesGeometry(g), litMat(new THREE.LineBasicMaterial({ color: 0xc6cad1 }), edge)));
  return m;
}
add(block(24, .18, 7, 0x1a1d24, .96, .22), 0, 0, 0);                                   // the road
for (let x = -11; x < 12; x += 2.6) add(block(1.3, .02, .1, 0xffffff, .45, 0), x, .11, 0);
add(block(24, 4.4, .8, 0x262a33, .28, .35), 0, 2.2, -4.0);                             // retaining wall
add(block(24, .3, 4, 0x30343f, .28, .3), 0, 4.55, -6.6);                               // highway deck
add(new THREE.Mesh(new THREE.BoxGeometry(.45, .8, .2), litMat(new THREE.MeshBasicMaterial({ color: 0xf2f4f8 }), 1)), 2.5, 5.3, -5.4); // the phone
const PHONE = new THREE.Vector3(2.5, 5.3, -5.4);
const cone = [];
for (const [x, z] of [[-7.5, 3.5], [7.5, 3.5], [7.5, -3.5], [-7.5, -3.5]]) cone.push(PHONE.clone(), new THREE.Vector3(x, .15, z));
scene.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(cone), litMat(new THREE.LineBasicMaterial({ color: 0x9aa3b8 }), .22)));

// the taped rectangle (8 x 7 m), the dashed outline, and lines A and B 15 m apart
const CORNERS = [[-4, 3.5], [4, 3.5], [4, -3.5], [-4, -3.5]];
const marks = CORNERS.map(([x, z]) => add(new THREE.Mesh(new THREE.BoxGeometry(.6, .05, .6), litMat(new THREE.MeshBasicMaterial({ color: 0xf4f6f9 }), 1)), x, .13, z));
const rect = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([...CORNERS, CORNERS[0]].map(([x, z]) => new THREE.Vector3(x, .14, z))),
  new THREE.LineDashedMaterial({ color: 0xef4444, dashSize: .45, gapSize: .25, transparent: true, opacity: 0 }));
rect.computeLineDistances(); scene.add(rect);
const abLines = [-7.5, 7.5].map((x) => add(block(.1, .04, 7, 0x5b9dff, .9, 0), x, .13, 0));
const bottles = [];
for (const x of [-7.5, 7.5]) for (const z of [-3.6, 3.6]) bottles.push(add(new THREE.Mesh(new THREE.CylinderGeometry(.16, .16, .7, 14), litMat(new THREE.MeshStandardMaterial({ color: 0x5b9dff, roughness: .5 }), 1)), x, .5, z));

/* ── the track cloud: every point scatters in from the dark and lands on a measured path ── */
function dotTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(.3, "rgba(255,255,255,.75)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const homes = [], tint = [], kind = [];  // kind 0 silver, 1 person (cyan), 2 bike (red)
for (const path of T.others) for (const p of path) { const [x, z] = toScene(p); homes.push(x, .16, z); tint.push(.78, .8, .85); kind.push(0); }
for (let i = 0; i < 820; i++) {                                                          // the rest of the dismissal's traffic, along the lanes
  const lane = [-2.3, -.9, .8, 2.3][i % 4] + (hash(i, 1) - .5) * .9, x = (hash(i, 2) - .5) * 22;
  homes.push(x, .16, lane); tint.push(.7, .72, .78); kind.push(0);
}
for (const [x, z] of PERSON) { homes.push(x, .2, z); tint.push(.5, .95, 1); kind.push(1); }
for (const [x, z] of BIKE) { homes.push(x, .2, z); tint.push(1, .45, .45); kind.push(2); }
const N = kind.length, pos = new Float32Array(N * 3), scatter = new Float32Array(N * 3), stagger = new Float32Array(N);
for (let i = 0; i < N; i++) {
  const r = 9 + 7 * hash(i, 4), a = hash(i, 5) * 6.283, b = (hash(i, 6) - .5) * 2.4;
  scatter.set([Math.cos(a) * r * Math.cos(b), 3 + Math.sin(b) * r * .6, Math.sin(a) * r * Math.cos(b) * .8], i * 3);
  stagger[i] = hash(i, 3);
}
const cloud = new THREE.BufferGeometry();
cloud.setAttribute("position", new THREE.BufferAttribute(pos, 3));
cloud.setAttribute("color", new THREE.BufferAttribute(Float32Array.from(tint), 3));
const cloudMat = new THREE.PointsMaterial({ size: .2, map: dotTexture(), vertexColors: true, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
scene.add(new THREE.Points(cloud, cloudMat));

// the two paths that met: drawn in from BUILD to ALMOST, ending on the same spot
function trail(points, color) {
  const geo = new THREE.BufferGeometry().setFromPoints(points.map(([x, z]) => new THREE.Vector3(x, .2, z)));
  geo.setDrawRange(0, 0);
  const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0 }));
  scene.add(line); return line;
}
const personLine = trail(PERSON, 0x7ee8f5), bikeLine = trail(BIKE, 0xff6b6b);
const personHead = add(new THREE.Mesh(new THREE.CapsuleGeometry(.22, .5, 4, 10), new THREE.MeshStandardMaterial({ color: 0x7ee8f5, emissive: 0x2bb5c6, emissiveIntensity: .6, roughness: .4 })), 0, .6, 0);
const bikeHead = add(new THREE.Mesh(new THREE.BoxGeometry(1.7, .7, .6), new THREE.MeshStandardMaterial({ color: 0xff6b6b, emissive: 0xc0392b, emissiveIntensity: .5, roughness: .4 })), 0, .5, 0);
const ring = add(new THREE.Mesh(new THREE.RingGeometry(.55, .72, 56), new THREE.MeshBasicMaterial({ color: 0xff5a5a, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })), W.x, .22, W.z);
ring.rotation.x = -Math.PI / 2;

/* ── per-frame pose, a pure function of t (plus a damped pointer and the wall clock for idle) ── */
const look = new THREE.Vector3(), camPos = new THREE.Vector3(), dive = new THREE.Vector3(W.x, 1.1, W.z), proj = new THREE.Vector3();
let px = 0, py = 0, tx = 0, ty = 0;
addEventListener("pointermove", (e) => { if (e.pointerType !== "touch") { tx = e.clientX / innerWidth - .5; ty = e.clientY / innerHeight - .5; } }, { passive: true });
const centre = { x: 0, y: 0 };  // the ring, in canvas px: the dust and the strike aim at it

function pose(t, now) {
  const light = lightAt(t), e = smooth(SEQ.EXIT_START, SEQ.EXIT_END, t), ee = e ** 1.7;
  for (const [m, base] of lit) m.opacity = base * light * (1 - e);
  // marks snap in one by one, the outline draws, then the 15 m lines rise
  marks.forEach((m, k) => { const s = smooth(SEQ.EMERGE + k * .16, SEQ.EMERGE + .4 + k * .16, t); m.scale.setScalar(Math.max(.001, s * (1 + .35 * Math.sin(s * Math.PI)))); });
  rect.material.opacity = smooth(SEQ.EMERGE + .55, SEQ.BUILD, t) * light * (1 - e);
  const ab = smooth(SEQ.EMERGE + .85, SEQ.BUILD + .25, t);
  abLines.forEach((m) => m.scale.z = Math.max(.001, ab));
  bottles.forEach((m, k) => m.scale.y = Math.max(.001, smooth(SEQ.BUILD - .1 + k * .06, SEQ.BUILD + .3 + k * .06, t)));
  // the cloud
  const p = cloud.attributes.position.array;
  for (let i = 0; i < N; i++) {
    const s = stagger[i], hero = kind[i] > 0;
    const u = hero ? smooth(SEQ.ATTRACT + s * .5, SEQ.BUILD - .25 + s * .3, t) : smooth(SEQ.ATTRACT + s * 1.1, SEQ.EMERGE + .5 + s * 1.0, t);
    const lift = Math.sin(u * Math.PI) * (1.2 + 1.6 * hash(i, 7));
    for (let c = 0; c < 3; c++) {
      let v = scatter[i * 3 + c] + (homes[i * 3 + c] - scatter[i * 3 + c]) * u + (c === 1 ? lift : 0);
      if (e > 0) v += (v - (c === 0 ? W.x : c === 1 ? W.y : W.z)) * ee * 2.6;
      p[i * 3 + c] = v;
    }
  }
  cloud.attributes.position.needsUpdate = true;
  cloudMat.opacity = (.55 + .45 * smooth(SEQ.ATTRACT, SEQ.EMERGE, t)) * light * (1 - e);
  // the two paths meet
  const draw = smooth(SEQ.BUILD, SEQ.ALMOST, t), trailOpacity = draw * (1 - e);
  for (const [line, pts, head, h] of [[personLine, PERSON, personHead, .6], [bikeLine, BIKE, bikeHead, .5]]) {
    const n = Math.round(pts.length * draw);
    line.geometry.setDrawRange(0, n);
    line.material.opacity = .9 * trailOpacity;
    const tip = pts[Math.max(0, Math.min(pts.length - 1, n - 1))];
    head.visible = n > 0 && e < .6;
    head.position.set(tip[0], h, tip[1]);
    if (head === bikeHead && n > 1) { const prev = pts[Math.max(0, n - 2)]; head.rotation.y = -Math.atan2(tip[1] - prev[1], tip[0] - prev[0]); }
  }
  // the ring: a pulse as they meet, the shock as it is measured, a slow breath at rest
  const a = t - SEQ.ALMOST, m = t - SEQ.MERGED, idle = smooth(SEQ.REST - .4, SEQ.REST + .6, t);
  let scale = .001, opacity = 0;
  if (a >= 0 && a < .9) { scale = 1 + 2.4 * a; opacity = (1 - a / .9) ** 2 * .9; }
  if (m >= 0 && m < 1.2) { scale = 1 + 7 * m; opacity = Math.max(opacity, (1 - m / 1.2) ** 2); }
  if (idle > 0 && !(m >= 0 && m < 1.2)) { scale = 1 + .18 * Math.sin(now * .0025); opacity = Math.max(opacity, .38 * idle); }
  ring.scale.setScalar(scale); ring.material.opacity = opacity * (1 - e);
  flash.intensity = m >= 0 && m < .7 ? 60 * (1 - m / .7) ** 2 : 0;
  // camera: a slow dolly in, idle parallax from REST, the dive on exit
  px += (tx - px) * .06; py += (ty - py) * .06;
  const k = 1.32 - .32 * smooth(0, SEQ.REST, t), ease = smooth(SEQ.MERGED, SEQ.REST, t);
  camPos.copy(BASE).multiplyScalar(k * (canvas.clientWidth < 600 ? 1.3 : 1)).applyAxisAngle(Y, ease * (Math.sin(now * .00013) * .1 + px * .22));
  camPos.y -= ease * py * 5;
  camera.position.lerpVectors(camPos, dive, ee);
  camera.fov = 30 + 50 * e; camera.updateProjectionMatrix();
  camera.lookAt(look.lerpVectors(TARGET, dive, e));
  // the tag and the shared centre, in screen space
  proj.copy(W).add(new THREE.Vector3(0, .9, 0)).project(camera);
  const r = canvas.getBoundingClientRect();
  centre.x = (proj.x + 1) / 2 * r.width; centre.y = (1 - proj.y) / 2 * r.height;
  tag.style.left = `${centre.x}px`; tag.style.top = `${centre.y}px`;
  tag.style.opacity = t >= SEQ.ALMOST && e < .2 && proj.z < 1 ? 1 : 0;
}

/* ── loop ── */
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer?.setPixelRatio(Math.min(devicePixelRatio, 1.5)); renderer?.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener("resize", resize); resize();
let running = true, firstFrame = false;
const field = window.CWField ? window.CWField($("#field"), () => seq.value, centre) : null;
const strike = window.CWStrike ? window.CWStrike($("#strike"), centre) : null;
function frame(now) {
  if (!running) return;
  pose(seq.value, now);
  renderer?.render(scene, camera);
  field?.draw(now);
  if (!firstFrame) { firstFrame = true; launch(); }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

/* ── the clock: one gsap timeline; every DOM beat sits on it at its sequence-second ── */
let master = null, started = false;
const name = $(".og-name"), restTrack = parseFloat(getComputedStyle(name).getPropertyValue("--track")) || .3;
function build() {
  const captions = [...document.querySelectorAll(".og-caption:not(.og-caption--exit)")];
  const tl = gsap.timeline({ paused: true, defaults: { ease: "none" } })
    .fromTo(seq, { value: SEQ.START }, { value: SEQ.REST, duration: SEQ.REST }, 0)
    .fromTo(".entry-pool", { opacity: 0 }, { opacity: 1, duration: 1.6, ease: "sine.inOut" }, 0);
  CAPTION_AT.forEach((at, i) => {
    const out = i + 1 < CAPTION_AT.length ? CAPTION_AT[i + 1] : SEQ.MERGED + .5;
    tl.fromTo(captions[i], { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: .3, ease: "power2.out" }, at + .1).to(captions[i], { opacity: 0, duration: .2 }, out - .1);
  });
  tl.fromTo(name, { "--track": restTrack * 2.6 }, { "--track": restTrack, duration: 1.1, ease: "expo.out", onComplete: () => name.style.removeProperty("--track") }, SEQ.MERGED)
    .fromTo(name, { opacity: 0 }, { opacity: 1, duration: .6, ease: "power1.out" }, SEQ.MERGED)
    .fromTo(name, { "--sweep": "100%" }, { "--sweep": "0%", duration: .9, ease: "power2.inOut" }, SEQ.MERGED + .2)
    .fromTo(".og-rule", { clipPath: "inset(0% 50% 0% 50%)" }, { clipPath: "inset(0% 0% 0% 0%)", duration: .65, ease: "power3.out" }, SEQ.MERGED + .2)
    .fromTo(".og-rule__star", { opacity: 0, scale: 0, rotate: -90 }, { opacity: 1, scale: 1, rotate: 0, duration: .35, ease: "back.out(2.4)" }, SEQ.MERGED + .7)
    .fromTo(".og-tagline", { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: .5, ease: "power2.out" }, SEQ.MERGED + .6)
    .fromTo(".entry-cta", { opacity: 0 }, { opacity: 1, duration: .45, ease: "power1.out" }, SEQ.MERGED + .6)
    .fromTo(".entry-sub", { opacity: 0 }, { opacity: 1, duration: .35 }, SEQ.MERGED + .75)
    .call(() => strike?.fire(), [], SEQ.MERGED + .05)
    .call(() => go("ready"), [], SEQ.REST);
  return tl;
}
function launch() {
  if (started) return; started = true;
  if (reduced) { go("ready"); return; }
  master = build();
  if (Number.isNaN(seekParam)) { go("sequence"); master.play(0); return; }
  go("sequence");
  master.seek(Math.min(seekParam, master.duration()), false);  // QA: ?t= parks the intro there
  if (seekParam >= SEQ.REST) go("ready");
  if (seekParam >= SEQ.EXIT_START) enter(seekParam - SEQ.EXIT_START);
}
setTimeout(launch, 3200);  // watchdog: the clock starts even if WebGL never draws

/* ── exit: the camera dives through the ring, the type goes in a third of a second, the platform opens ── */
function enter(freeze) {
  if (stage !== "ready") return;
  go("exit");
  const tl = gsap.timeline({ paused: freeze !== undefined, defaults: { ease: "none" } })
    .fromTo(seq, { value: SEQ.EXIT_START }, { value: SEQ.EXIT_END, duration: SEQ.EXIT_END - SEQ.EXIT_START }, 0)
    .to(name, { "--track": restTrack * 2.4, duration: .35, ease: "power2.in" }, 0)
    .to(".og-wordmark", { opacity: 0, duration: .35 }, 0)
    .to(".og-rule", { clipPath: "inset(0% 50% 0% 50%)", duration: .3 }, 0)
    .to(".og-tagline, .entry-cta, .entry-sub, .entry-skip", { opacity: 0, duration: .25 }, 0)
    .fromTo(".og-caption--exit", { opacity: 0 }, { opacity: 1, duration: .3 }, .3)
    .to(".entry-pool", { opacity: 0, duration: 1.2 }, 0)
    .to(".entry-overlay", { opacity: 1, duration: .4 }, .95)
    .call(reveal, [], 1.4);
  if (freeze !== undefined) { tl.seek(Math.min(freeze, 1.39)); if (freeze >= 1.4) reveal(); }
}
function reveal() {
  running = false;
  entry.hidden = true; document.querySelector(".corner").hidden = true;
  document.documentElement.classList.remove("entry-mode");
  platform.hidden = false;
  gsap.to(platform, { opacity: 1, duration: .7, ease: "power1.out" });
  const seen = new IntersectionObserver((entries) => entries.forEach((x) => { if (x.isIntersecting) { x.target.classList.add("is-in"); seen.unobserve(x.target); } }), { rootMargin: "0px 0px -8% 0px" });
  const instant = reduced || !Number.isNaN(seekParam);  // a seek or reduced motion shows the page composed, no reveals
  document.querySelectorAll(".pf-reveal").forEach((el, i) => { if (instant) { el.style.transition = "none"; el.classList.add("is-in"); return; } el.style.transitionDelay = `${(i % 4) * 70}ms`; seen.observe(el); });
  if (instant) gsap.set(platform, { opacity: 1 });
  document.querySelectorAll(".pf-tile").forEach((tile) => tile.addEventListener("pointermove", (ev) => { const b = tile.getBoundingClientRect(); tile.style.setProperty("--mx", `${ev.clientX - b.left}px`); tile.style.setProperty("--my", `${ev.clientY - b.top}px`); }));
  if (location.hash && location.hash !== "#gate") document.querySelector(location.hash)?.scrollIntoView();
}
cta.addEventListener("click", () => enter());
$("#skip").addEventListener("click", (ev) => { ev.preventDefault(); if (stage === "ready") enter(); else { master?.progress(1, false); go("ready"); enter(); } });

/* ── magnetic CTA: it leans toward the cursor as the cursor approaches, and springs back ── */
if (!matchMedia("(pointer: coarse)").matches) {
  const MAX = 14, LERP = .18, radius = 120, strength = .28, inner = .4;
  let raf = 0, last = 0, x = 0, y = 0, cx = 0, cy = 0, inside = false;
  const tick = (now) => {
    let ax = 0, ay = 0;
    if (inside && !cta.disabled) {
      const box = cta.getBoundingClientRect(), l = box.left - x, t = box.top - y;
      const gap = Math.hypot(Math.max(l - cx, 0, cx - l - box.width), Math.max(t - cy, 0, cy - t - box.height));
      if (gap < radius) {
        const g = 1 - gap / radius, pull = strength * g * g * (3 - 2 * g);
        ax = (cx - l - box.width / 2) * pull; ay = (cy - t - box.height / 2) * pull;
        const m = Math.hypot(ax, ay); if (m > 0) { const soft = (MAX * Math.tanh(m / MAX)) / m; ax *= soft; ay *= soft; }
      }
    }
    const k = 1 - Math.pow(1 - LERP, Math.min(now - last, 34) / (1000 / 60)); last = now;
    x += (ax - x) * k; y += (ay - y) * k;
    const rest = Math.abs(ax - x) < .02 && Math.abs(ay - y) < .02; if (rest) { x = ax; y = ay; }
    cta.style.setProperty("--mag-x", `${x.toFixed(2)}px`); cta.style.setProperty("--mag-y", `${y.toFixed(2)}px`);
    cta.style.setProperty("--mag-ix", `${(x * inner).toFixed(2)}px`); cta.style.setProperty("--mag-iy", `${(y * inner).toFixed(2)}px`);
    raf = rest ? 0 : requestAnimationFrame(tick);
  };
  const wake = () => { if (!raf) { last = performance.now() - 1000 / 60; raf = requestAnimationFrame(tick); } };
  addEventListener("pointermove", (e) => { if (e.pointerType === "touch") return; cx = e.clientX; cy = e.clientY; inside = true; wake(); }, { passive: true });
  addEventListener("blur", () => { inside = false; wake(); });
  document.documentElement.addEventListener("pointerleave", () => { inside = false; wake(); });
}
