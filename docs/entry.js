// The entry: one WebGL emblem and one clock. Every pose is a PURE function of the clock (seconds), so ?t=<s> seeks to
// any frame: the beats below, then the type, then the CTA; the CTA runs the exit and opens the platform.
// The emblem is the measured moment itself: two luminous paths (the real tracks) meeting on a ring, over a dark
// polished floor, lit by a studio environment and bloomed.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

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

/* ── data: the real near-miss, in road metres (x along the road 0..15, y across 0..7) ── */
const T = window.CW_TRACKS;
const toScene = ([x, y]) => [x - 7.5, y - 3.5];
const W2 = T.hero.where, W = new THREE.Vector3(W2[0] - 7.5, 0.06, W2[1] - 3.5);
const upTo = (path) => { let best = 0, bd = 1e9; path.forEach((p, i) => { const d = Math.hypot(p[0] - W2[0], p[1] - W2[1]); if (d < bd) { bd = d; best = i; } }); return [...path.slice(0, best + 1), W2]; };
const PERSON = upTo(T.hero.person).map(toScene), BIKE = upTo(T.hero.vehicle).map(toScene);

/* ── renderer, studio, camera ── */
const canvas = $("#scene");
let renderer = null, composer = null, bloom = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x050506, 1);
} catch { canvas.hidden = true; }
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x050506, 0.062);
if (renderer) { const pmrem = new THREE.PMREMGenerator(renderer); scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; pmrem.dispose(); }
const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
const TARGET = new THREE.Vector3(0.4, -0.7, 0.4), BASE = new THREE.Vector3(10.5, 6.6, 12.5), Y = new THREE.Vector3(0, 1, 0);
const key = new THREE.DirectionalLight(0xe8ecf5, 1.2); key.position.set(-6, 14, 6); scene.add(key);
const rim = new THREE.DirectionalLight(0x9fb4ff, .6); rim.position.set(8, 6, -10); scene.add(rim);
scene.add(new THREE.AmbientLight(0x30343f, .5));
const flash = new THREE.PointLight(0xffd0d0, 0, 26, 1.5); flash.position.copy(W).add(new THREE.Vector3(0, 2, 0)); scene.add(flash);

/* ── materials whose intensity follows the lights ── */
const lit = [];                                     // [material, baseOpacity]
const glow = [];                                    // [material, baseEmissive]
const litMat = (m, base) => { m.transparent = true; m.opacity = 0; lit.push([m, base]); return m; };
const glowMat = (m, base) => { m.emissiveIntensity = 0; glow.push([m, base]); return m; };
const add = (m, x, y, z) => { m.position.set(x, y, z); scene.add(m); return m; };

// the floor: dark, polished, the studio and the glow reflect in it
const floor = add(new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshStandardMaterial({ color: 0x0b0c10, roughness: .22, metalness: .85, envMapIntensity: 1.1 })), 0, 0, 0);
floor.rotation.x = -Math.PI / 2;
// the taped rectangle (8 x 7 m) as four marks and a hairline, and lines A and B 15 m apart
const CORNERS = [[-4, 3.5], [4, 3.5], [4, -3.5], [-4, -3.5]];
const markMat = glowMat(new THREE.MeshStandardMaterial({ color: 0xf4f6f9, emissive: 0xf4f6f9, roughness: .3, metalness: .1 }), .55);
const marks = CORNERS.map(([x, z]) => add(new THREE.Mesh(new THREE.BoxGeometry(.55, .05, .55), markMat), x, .03, z));
const hairline = (points, color, base) => { const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), litMat(new THREE.LineBasicMaterial({ color }), base)); scene.add(l); return l; };
const rect = hairline([...CORNERS, CORNERS[0]].map(([x, z]) => new THREE.Vector3(x, .04, z)), 0xff8a8a, .55);
const abLines = [-7.5, 7.5].map((x) => hairline([new THREE.Vector3(x, .04, -3.5), new THREE.Vector3(x, .04, 3.5)], 0x8db4ff, .7));
const bottleMat = glowMat(new THREE.MeshStandardMaterial({ color: 0x5b9dff, emissive: 0x3b7dff, roughness: .35 }), 1.6);
const bottles = [];
for (const x of [-7.5, 7.5]) for (const z of [-3.6, 3.6]) bottles.push(add(new THREE.Mesh(new THREE.SphereGeometry(.11, 16, 16), bottleMat), x, .11, z));

// the track cloud: points scatter in from the dark and settle on the floor where the dismissal's traffic ran
function dotTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(.3, "rgba(255,255,255,.7)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const homes = [];
for (const path of T.others) for (const p of path) { const [x, z] = toScene(p); homes.push(x, .05, z); }
for (let i = 0; i < 520; i++) { const lane = [-2.3, -.9, .8, 2.3][i % 4] + (hash(i, 1) - .5) * .9; homes.push((hash(i, 2) - .5) * 24, .05, lane); }
const N = homes.length / 3, pos = new Float32Array(N * 3), scatter = new Float32Array(N * 3), stagger = new Float32Array(N);
for (let i = 0; i < N; i++) {
  const r = 8 + 8 * hash(i, 4), a = hash(i, 5) * 6.283, b = (hash(i, 6) - .5) * 2.2;
  scatter.set([Math.cos(a) * r * Math.cos(b), 2.5 + Math.sin(b) * r * .5, Math.sin(a) * r * Math.cos(b) * .8], i * 3);
  stagger[i] = hash(i, 3);
}
const cloud = new THREE.BufferGeometry();
cloud.setAttribute("position", new THREE.BufferAttribute(pos, 3));
const cloudMat = new THREE.PointsMaterial({ size: .16, map: dotTexture(), color: 0xc9ced8, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
scene.add(new THREE.Points(cloud, cloudMat));

// the two paths that met, as luminous ribbons drawn in from BUILD to ALMOST, ending on the same spot
const SEGS = 120, RADIAL = 10;
function ribbon(points, color) {
  const curve = new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, .14, z)), false, "catmullrom", .3);
  const geo = new THREE.TubeGeometry(curve, SEGS, .075, RADIAL, false);
  geo.setDrawRange(0, 0);
  const mat = glowMat(new THREE.MeshStandardMaterial({ color, emissive: color, roughness: .3, metalness: .2 }), 2.6);
  const mesh = new THREE.Mesh(geo, mat); scene.add(mesh);
  return { mesh, curve };
}
const person = ribbon(PERSON, 0x6fe3f2), bike = ribbon(BIKE, 0xff5c5c);
const headMat = (c) => glowMat(new THREE.MeshStandardMaterial({ color: c, emissive: c, roughness: .25 }), 3.2);
const personHead = add(new THREE.Mesh(new THREE.SphereGeometry(.16, 24, 24), headMat(0x9ff1fb)), 0, .14, 0);
const bikeHead = add(new THREE.Mesh(new THREE.SphereGeometry(.2, 24, 24), headMat(0xff8a8a)), 0, .14, 0);
const ringMat = glowMat(new THREE.MeshStandardMaterial({ color: 0xff6b6b, emissive: 0xff3b3b, roughness: .3, metalness: .3, transparent: true, opacity: 0 }), 3.5);
const ring = add(new THREE.Mesh(new THREE.TorusGeometry(.8, .05, 16, 96), ringMat), W.x, .1, W.z);
ring.rotation.x = -Math.PI / 2;
const haloMat = new THREE.SpriteMaterial({ map: dotTexture(), color: 0xff4040, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
const halo = add(new THREE.Sprite(haloMat), W.x, .25, W.z);

/* ── per-frame pose: a pure function of t, plus a damped pointer and the wall clock for the idle breath ── */
const look = new THREE.Vector3(), camPos = new THREE.Vector3(), dive = new THREE.Vector3(W.x, .9, W.z), proj = new THREE.Vector3();
let px = 0, py = 0, tx = 0, ty = 0;
addEventListener("pointermove", (e) => { if (e.pointerType !== "touch") { tx = e.clientX / innerWidth - .5; ty = e.clientY / innerHeight - .5; } }, { passive: true });
const centre = { x: 0, y: 0 };  // the ring in canvas px: the dust and the strike aim at it

function pose(t, now) {
  const light = lightAt(t), e = smooth(SEQ.EXIT_START, SEQ.EXIT_END, t), ee = e ** 1.7, fade = light * (1 - e);
  floor.material.envMapIntensity = 1.1 * fade;
  key.intensity = 1.2 * fade; rim.intensity = .6 * fade;
  for (const [m, base] of lit) m.opacity = base * fade;
  // marks snap in one by one, the outline draws, then the 15 m lines and their markers rise
  marks.forEach((m, k) => { const s = smooth(SEQ.EMERGE + k * .16, SEQ.EMERGE + .4 + k * .16, t); m.scale.setScalar(Math.max(.001, s * (1 + .35 * Math.sin(s * Math.PI)))); });
  markMat.emissiveIntensity = .55 * fade;
  rect.material.opacity = .55 * smooth(SEQ.EMERGE + .55, SEQ.BUILD, t) * fade;
  const ab = smooth(SEQ.EMERGE + .85, SEQ.BUILD + .25, t);
  abLines.forEach((l) => { l.scale.z = Math.max(.001, ab); l.material.opacity = .7 * ab * fade; });
  bottles.forEach((m, k) => m.scale.setScalar(Math.max(.001, smooth(SEQ.BUILD - .1 + k * .06, SEQ.BUILD + .3 + k * .06, t))));
  bottleMat.emissiveIntensity = 1.6 * fade;
  // the cloud settles
  const p = cloud.attributes.position.array;
  for (let i = 0; i < N; i++) {
    const s = stagger[i], u = smooth(SEQ.ATTRACT + s * 1.1, SEQ.EMERGE + .5 + s * 1.0, t), lift = Math.sin(u * Math.PI) * (1 + 1.4 * hash(i, 7));
    for (let c = 0; c < 3; c++) {
      let v = scatter[i * 3 + c] + (homes[i * 3 + c] - scatter[i * 3 + c]) * u + (c === 1 ? lift : 0);
      if (e > 0) v += (v - (c === 0 ? W.x : c === 1 ? W.y : W.z)) * ee * 2.6;
      p[i * 3 + c] = v;
    }
  }
  cloud.attributes.position.needsUpdate = true;
  cloudMat.opacity = (.45 + .35 * smooth(SEQ.ATTRACT, SEQ.EMERGE, t)) * fade;
  // the ribbons meet
  const draw = smooth(SEQ.BUILD, SEQ.ALMOST, t);
  for (const [r, head] of [[person, personHead], [bike, bikeHead]]) {
    const n = Math.floor(SEGS * draw);
    r.mesh.geometry.setDrawRange(0, n * RADIAL * 6);
    r.mesh.material.emissiveIntensity = 2.6 * fade;
    head.visible = draw > 0 && e < .6;
    head.material.emissiveIntensity = 3.2 * fade;
    const tip = r.curve.getPointAt(Math.min(1, Math.max(0, draw)));
    head.position.copy(tip);
  }
  // the ring: a pulse as they meet, the shock as it is measured, a slow breath at rest
  const a = t - SEQ.ALMOST, m = t - SEQ.MERGED, idle = smooth(SEQ.REST - .4, SEQ.REST + .6, t);
  let scale = .001, opacity = 0;
  if (a >= 0 && a < .9) { scale = 1 + 2.2 * a; opacity = (1 - a / .9) ** 2; }
  if (m >= 0 && m < 1.3) { scale = 1 + 6 * m; opacity = Math.max(opacity, (1 - m / 1.3) ** 2); }
  if (idle > 0 && !(m >= 0 && m < 1.3)) { scale = 1 + .12 * Math.sin(now * .0022); opacity = Math.max(opacity, .9 * idle); }
  ring.scale.setScalar(scale); ringMat.opacity = opacity * (1 - e); ringMat.emissiveIntensity = 3.5 * fade * opacity;
  haloMat.opacity = (t >= SEQ.ALMOST ? .55 * (idle > 0 ? idle : 1) : 0) * (1 - e); halo.scale.setScalar(2.4 + .3 * Math.sin(now * .0022));
  flash.intensity = m >= 0 && m < .7 ? 90 * (1 - m / .7) ** 2 : 0;
  if (bloom) bloom.strength = .85 + .9 * (m >= 0 && m < .7 ? (1 - m / .7) : 0);
  // camera: a slow dolly in, idle parallax from REST, the dive on exit
  px += (tx - px) * .06; py += (ty - py) * .06;
  const k = 1.3 - .3 * smooth(0, SEQ.REST, t), ease = smooth(SEQ.MERGED, SEQ.REST, t);
  camPos.copy(BASE).multiplyScalar(k * (canvas.clientWidth < 600 ? 1.35 : 1)).applyAxisAngle(Y, ease * (Math.sin(now * .00013) * .12 + px * .25));
  camPos.y -= ease * py * 2.5;
  camera.position.lerpVectors(camPos, dive, ee);
  camera.fov = 32 + 48 * e; camera.updateProjectionMatrix();
  camera.lookAt(look.lerpVectors(TARGET, dive, e));
  // the tag and the shared centre, in screen space
  proj.copy(W).add(new THREE.Vector3(0, .7, 0)).project(camera);
  const r = canvas.getBoundingClientRect();
  centre.x = (proj.x + 1) / 2 * r.width; centre.y = (1 - proj.y) / 2 * r.height;
  tag.style.left = `${centre.x}px`; tag.style.top = `${centre.y}px`;
  tag.style.opacity = t >= SEQ.ALMOST && e < .2 && proj.z < 1 ? 1 : 0;
}

/* ── loop ── */
function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight, dpr = Math.min(devicePixelRatio, 1.5);
  renderer?.setPixelRatio(dpr); renderer?.setSize(w, h, false); composer?.setPixelRatio(dpr); composer?.setSize(w, h);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
if (renderer) {
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), .85, .55, .72);
  composer.addPass(bloom); composer.addPass(new OutputPass());
}
addEventListener("resize", resize); resize();
let running = true, firstFrame = false;
const field = window.CWField ? window.CWField($("#field"), () => seq.value, centre) : null;
const strike = window.CWStrike ? window.CWStrike($("#strike"), centre) : null;
function frame(now) {
  if (!running) return;
  pose(seq.value, now);
  composer?.render();
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
