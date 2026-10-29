"""The evidence page's first screen, summary first: what was filmed, the worst near-miss's clip playing beside the
counts and the fix the school asks for, where the letter stands, and a bar that jumps to each section. pack.page
builds it from the page's own pieces, so nothing here states a number or a claim of its own."""
import html

import ailabel
import fixband
import overlay

SECTIONS = (("clips", "Clips"), ("map", "Map"), ("fix", "Fix"), ("letter", "Letter"), ("law", "Why they can act"),
            ("method", "Method"))  # the jump bar, in page order: (section id, link text)
AI_DRAWN = "AI-drawn proposal by Muse Image, not a photo"  # under Muse Image's whole-photo edit, here and in Fix
BLURRED = "Faces and number plates blurred"  # render.py blurs both in every clip and pack.py in the street photo
THUMB_MAX_PX = 80  # the fix picture's height, so the ask box's status line stays on a 1280x720 first screen

STYLE = """
.kicker { margin: 0; color: var(--muted); font-size: 0.9rem; } @media (max-width: 480px) { h1 { font-size: 1.4rem; } }
.hero { display: grid; gap: 20px; margin-top: 14px; align-items: start; }
.hero.two { grid-template-columns: 1.35fr 1fr; } @media (max-width: 700px) { .hero.two { grid-template-columns: 1fr; } }
.hero figcaption { font-size: 0.9rem; margin-top: 6px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0 0 8px; font-size: 0.8rem; }
.stats b { display: block; font-size: 2rem; line-height: 1.1; color: var(--ink); }
.stats .serious b { color: var(--accent); } .stats .close b { color: var(--warn); }
.ask { border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; margin: 8px 0; }
.ask .label { margin: 0; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
.ask .fix { font-size: 1.15rem; font-weight: 600; margin: 2px 0 8px; } .ask p { margin-bottom: 0; }
.ask img { width: auto; max-width: 100%%; max-height: %dpx; display: block; }
.btn { display: inline-block; margin-top: 8px; padding: 6px 12px; border-radius: 6px; background: var(--ink);
       color: var(--bg); text-decoration: none; font-weight: 600; }
nav.jump { position: sticky; top: 0; z-index: 2; display: flex; gap: 14px; overflow-x: auto; margin-top: 16px;
           padding: 8px 0; background: var(--bg); border-bottom: 1px solid var(--line); font-size: 0.9rem; }
nav.jump a { white-space: nowrap; } @media print { .hero video, nav.jump { display: none; } }
""" % THUMB_MAX_PX


def clip(i, e, title):
    """Card #i's own blurred clip (event `e`'s), the page's only autoplaying video, its StroMotion still the poster
    where there is one. The caption is the card's `title`, linked to the card, and its gap sentence."""
    poster = f' poster="{html.escape(e["strobe"]["image"])}"' if e.get("strobe") else ""
    return (f'<figure><video src="{html.escape(e["clip"])}"{poster} autoplay muted loop playsinline controls></video>'
            f'<figcaption><a href="#event-{i}">{title}</a>. {html.escape(overlay.clock_text(e))}</figcaption></figure>')


def thumbnail(images):
    """The fix picture: the band picture with fixband's caption, else Muse Image's whole-photo edit with its AI label."""
    if images and len(images) > 2:
        return (f'<figure><img src="{html.escape(images[2])}" alt="The proposed fix drawn only inside the measured band">'
                f'<figcaption class="note">{html.escape(fixband.CAPTION)}</figcaption></figure>')
    if images and len(images) > 1:
        return (f'<figure><img src="{html.escape(images[1])}" alt="The street with the fix, drawn by Muse Image">'
                f'<span class="ai-label">{ailabel.LABEL}</span><figcaption class="note">{AI_DRAWN}</figcaption></figure>')
    return ""


def ask(plan, images, signed, status):
    """The fix, as what "The school asks for" only while the sign-off is the letter's (`signed`), else as an AI draft;
    its picture, the letter's button and `status`, where the letter stands."""
    label = "The school asks for" if signed else "Proposed fix (AI draft)"
    return (f'<div class="ask"><p class="label">{label}</p><p class="fix">{html.escape(plan["fix"])}</p>'
            f'{thumbnail(images)}<a class="btn" href="#letter">Read the letter</a>{status}</div>')


def header(site, seen, lead, video, tiles, line, limit, asked, filed):
    """The first screen: the kicker, the site's name, `filed` (the filing line when no ask box holds it), `lead` (the
    headline or the pace warning), then `video` (clip()) beside the count `tiles`, the other counts as one muted
    `line`, SAM's `limit` note that qualifies them, the ask box (`asked`) and the blur badge."""
    once = " of one school dismissal" if site.get("dismissal_minutes") else ""
    minutes = html.escape(str(seen.get("minutes", "?")))
    counts = f'<p class="note">{html.escape(line)}</p>' if line else ""
    return (f'<header><p class="kicker">Crossing Watch &middot; near-miss evidence &middot; {minutes} minutes of '
            f'video{once}</p><h1>{html.escape(site.get("name") or "This crossing")}</h1>{filed}{lead}'
            f'<div class="hero{" two" if video else ""}">{video}<div><div class="stats">{tiles}</div>{counts}{limit}'
            f'{asked}<p class="note">{BLURRED}</p></div></div></header>')


def jump_bar(body):
    """Links to the sections `body`, the page under the first screen, holds."""
    links = "".join(f'<a href="#{key}">{text}</a>' for key, text in SECTIONS if f'id="{key}"' in body)
    return f'<nav class="jump" aria-label="Sections">{links}</nav>'
