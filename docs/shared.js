// Shared by the app, explorer and manual pages: the Hindi / English switch (same "cw-lang" choice as the landing
// page) and gentle motion. Hindi strings live in hi.json, keyed by each element's exact English innerHTML.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SEL = "h1,h2,h3,p,li,.kick,.what,.need div,label,summary,.card,.steps a,.legend span,.stat span,th,.top a,.btn,.tip,button";
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const script = document.currentScript;

  const css = document.createElement("style");
  css.textContent = `
    html[lang=hi] body { font-family: Inter, "Noto Sans Devanagari", system-ui, sans-serif; }
    .cw-lang { margin-left: 14px; border: 1px solid currentColor; border-radius: 99px; padding: 5px 12px; background: transparent;
      color: inherit; font: 600 13px/1 "Noto Sans Devanagari", Inter, sans-serif; cursor: pointer; opacity: .85; }
    .cw-lang:hover { opacity: 1; }
    #cw-progress { position: fixed; top: 0; left: 0; height: 3px; width: 0; background: #e08a12; z-index: 99; }
    .cw-glow { position: fixed; z-index: -1; width: 70vmax; height: 70vmax; border-radius: 50%; pointer-events: none; filter: blur(30px); }
    .cw-glow.a { background: radial-gradient(circle, rgba(224,138,18,.16), transparent 62%); top: -30vmax; left: -20vmax; animation: cwDrift 26s ease-in-out infinite alternate; }
    .cw-glow.b { background: radial-gradient(circle, rgba(229,72,47,.10), transparent 62%); bottom: -35vmax; right: -25vmax; animation: cwDrift 32s ease-in-out infinite alternate-reverse; }
    @keyframes cwDrift { to { transform: translate(14vmax, 10vmax) scale(1.15); } }
    .cw-up { opacity: 0; transform: translateY(26px); transition: opacity .8s cubic-bezier(.2,.7,.2,1), transform .8s cubic-bezier(.2,.7,.2,1); }
    .cw-up.cw-in { opacity: 1; transform: none; }
    .btn, .card, .stat, .need div, .steps a { transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease; }
    .btn:hover, .stat:hover, .need div:hover { transform: translateY(-3px); box-shadow: 0 10px 24px rgba(23,24,28,.12); }
    .btn { position: relative; overflow: hidden; }
    .btn::after { content: ""; position: absolute; inset: 0; background: linear-gradient(110deg, transparent 30%, rgba(255,255,255,.45) 50%, transparent 70%);
      transform: translateX(-120%); transition: transform .7s ease; }
    .btn:hover::after { transform: translateX(120%); }
    h1 .cw-w { display: inline-block; opacity: 0; transform: translateY(.5em); animation: cwRise .8s cubic-bezier(.2,.7,.2,1) forwards; }
    @keyframes cwRise { to { opacity: 1; transform: none; } }
    @media (prefers-reduced-motion: reduce) { .cw-glow { animation: none; } .cw-up { opacity: 1; transform: none; } h1 .cw-w { animation: none; opacity: 1; transform: none; } }`;
  document.head.append(css);

  // Motion: drifting light, scroll progress, words of the title rise, blocks fade up as they enter
  document.body.insertAdjacentHTML("afterbegin", '<div id="cw-progress"></div><div class="cw-glow a"></div><div class="cw-glow b"></div>');
  // the Meta models this page runs on (nominative: Meta's mark beside the models' names, linked to the table)
  document.body.insertAdjacentHTML("beforeend", '<p style="text-align:center;margin:28px 0 22px"><a class="cw-meta" href="https://github.com/shaunmortal/crossing-watch#-seven-meta-models-each-doing-real-work" style="display:inline-block;margin:6px 0"><img src="https://img.shields.io/badge/Built%20with-Meta%20AI%20models-0467DF?style=flat&logo=meta&logoColor=white" alt="Built with Meta AI models: SAM 3.1, Muse Spark, Muse Image, Muse Wonder, Muse Voice Transcribe, Muse Glimmer, Muse Spark Open" height="20" style="height:20px;vertical-align:middle"></a></p>');
  const bar = document.getElementById("cw-progress");
  addEventListener("scroll", () => { const h = document.documentElement; bar.style.width = (100 * h.scrollTop / Math.max(1, h.scrollHeight - innerHeight)) + "%"; }, { passive: true });
  const riseTitle = () => document.querySelectorAll("h1").forEach((h1) => {
    if (reduce) return;
    if (h1.dataset.en === undefined) h1.dataset.en = norm(h1.innerHTML);   // keep the plain English for the language switch
    let i = 0;
    const walk = (n) => [...n.childNodes].forEach((c) => {
      if (c.nodeType === 3) {
        const f = document.createDocumentFragment();
        c.textContent.split(/(\s+)/).forEach((w) => { if (!w) return; if (/^\s+$/.test(w)) { f.append(w); return; }
          const s = document.createElement("span"); s.className = "cw-w"; s.style.animationDelay = (0.08 * i++) + "s"; s.textContent = w; f.append(s); });
        c.replaceWith(f);
      } else walk(c);
    });
    walk(h1);
  });
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("cw-in"); io.unobserve(e.target); } }), { threshold: .12 });
  document.querySelectorAll(".panel, .stat, .need div, .faq h3, .faq p, header .lede, .cards .card").forEach((el, i) => {
    if (el.closest(".step") && !el.matches(".card")) return;   // steps already animate themselves
    el.classList.add("cw-up"); el.style.transitionDelay = ((i % 5) * 0.07) + "s"; io.observe(el);
  });

  // Language: swap each element whose English innerHTML has a Hindi entry; remember the choice across pages
  let HI = {};
  const saved = () => { try { return localStorage.getItem("cw-lang"); } catch { return null; } };
  const want = () => new URLSearchParams(location.search).get("lang") || saved() || "en";
  const btn = document.createElement("button");
  btn.className = "cw-lang"; btn.type = "button"; btn.setAttribute("aria-label", "Switch language"); btn.textContent = "हिंदी";
  const apply = (lang) => {
    document.documentElement.lang = lang === "hi" ? "hi" : "en";
    document.querySelectorAll(SEL).forEach((el) => {
      if (el.closest("pre,.term,#chat,#detail,#rows,#tl,svg") || el === btn) return;
      if (lang === "hi") {
        const en = el.dataset.en ?? norm(el.innerHTML);
        if (HI[en]) { el.dataset.en = en; el.innerHTML = HI[en]; }
      } else if (el.dataset.en !== undefined) { el.innerHTML = el.dataset.en; }
    });
    btn.textContent = lang === "hi" ? "EN" : "हिंदी";
    try { localStorage.setItem("cw-lang", lang); } catch {}
  };
  (document.querySelector(".top > span:last-child") || document.querySelector(".top") || document.body).append(btn);
  const base = script ? new URL(".", script.src) : new URL("../", location.href);
  fetch(new URL("hi.json", base)).then((r) => r.json()).then((d) => {
    HI = d;
    btn.addEventListener("click", () => apply(document.documentElement.lang === "hi" ? "en" : "hi"));
    if (want() === "hi") apply("hi"); else riseTitle();
  }).catch(() => { btn.remove(); riseTitle(); });
})();
