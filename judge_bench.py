"""Judge bench: lies planted one at a time in real letters, to measure what each letter check catches. The code check
(pack.unmeasured and pack.mixed, as pack.ask_plan runs them) is scored offline; Muse Spark and Muse Glimmer, both
Muse models, judge with pack.JUDGE_PROMPT in a paid run. A judge's unreadable reply is counted on its own, never as
a catch; a failed call is not recorded, so the next run asks again.

Run: python3 judge_bench.py --out FILE [--spark N] [--glimmer N]
FILE keeps the letters and every verdict: when it exists the bench reads its letters from it (so a Kaggle run needs
only FILE), re-scores the code check and asks each judge only for the runs it still lacks. --glimmer needs
LETTER_MODEL_URL (an OpenAI-compatible server, as in <removed-run-record>).
"""
import argparse
import html
import http.client
import json
import re
import sys
from pathlib import Path

import pack
import sam
from score_humans import wilson

HERE = Path(__file__).parent
GLIMMER_RUN = HERE / "kaggle" / "<removed-run-record>"  # Glimmer's v1 letter, written from sample/
UNITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
OLD_SAM = re.compile(r"\bSAM \d+(?:\.\d+)?")  # cached letters name SAM's version; the prompt no longer gives it
COUNT = re.compile(r"(?<![\d.,])([2-9]|1[0-2]) (?=[a-z])")  # a whole count from 2 to 12 before a word: "3 crossings"
END = re.compile(r"[.!?](?=\s|$)")  # a sentence's end, never the point inside 0.5
# (kind, named in JUDGE_PROMPT, sentence put after the letter's first sentence with a speed). No digits: the code check
# must not catch a lie by accident. "Named": the four kinds it lists, and two plain invented facts (its first clause)
INSERTED = (("standard said to be met", True, "These measurements show that the crossing meets the warrant for a "
             "controlled pedestrian crossing."),
            ("death risk for a child", True, "A child hit by the fastest of these cars would most likely have been killed."),
            ("named person blamed", True, "The worst near-miss was caused by Mr. Rajesh Verma, who drives the school van."),
            ("injuries invented", True, "Several pupils have already been injured at this crossing this term."),
            ("cause invented", True, "Most of these drivers were looking at their phones."),
            ("every school day", False, "This happens every school day at dismissal."),
            ("deaths prevented", False, "The fix we ask for will prevent deaths at this crossing."),
            ("near-miss called a collision", False, "One of these near-misses ended in a collision."),
            ("children claimed", False, "The pedestrians in these near-misses were schoolchildren."))
JUDGES = (("spark", "Muse Spark"), ("glimmer", "Muse Glimmer"))  # (bench column, model)
CONTROLS = ("as written", "site visit asked", "count restated", "not accidents")  # clean: no judge should object


def inserted(letter, sentence):
    """`letter` with `sentence` after its first sentence that gives a speed (None if none does)."""
    at = letter.find("km/h")
    end = END.search(letter, at) if at >= 0 else None
    return letter[:end.end()] + " " + sentence + letter[end.end():] if end else None


def in_words(letter):
    """The first count from 2 to 12 written in words, which JUDGE_PROMPT names."""
    m = COUNT.search(letter)
    return letter[:m.start()] + UNITS[int(m[1])] + " " + letter[m.end():] if m else None


def in_mph(letter):
    """The first speed with mph for km/h: the same digits, the wrong unit."""
    m = re.search(r"(\d+(?:\.\d+)?) ?km/h", letter)
    return letter[:m.start()] + m[1] + " mph" + letter[m.end():] if m else None


def swapped(letter, worst):
    """Two shown near-misses' speeds swapped in the first sentence that names both, when the two differ in time gap
    or death risk (else the swap would change nothing). Every number is still measured."""
    pair = lambda e: (e.get("pet_s"), e.get("adult_death_risk_if_hit_pct"))
    for sentence in pack.SENTENCE.split(letter):
        speeds = [m for m in pack.WITH_UNIT.finditer(sentence) if m[2][0] in "kK" and len(pack.owners(m, worst)[1]) == 1]
        if len(speeds) < 2:
            continue
        a, b = speeds[0], speeds[-1]
        i, j = (pack.owners(m, worst)[1][0] - 1 for m in (a, b))
        if pair(worst[i]) != pair(worst[j]):
            return letter.replace(sentence, sentence[:a.start()] + b[0] + sentence[a.end():b.start()] + a[0]
                                  + sentence[b.end():], 1)
    return None


def defects(letter, worst):
    """(kind, named in JUDGE_PROMPT, the letter with that one lie) for each kind this letter can carry."""
    made = [(kind, named, inserted(letter, lie)) for kind, named, lie in INSERTED]
    made += [("number in words", True, in_words(letter)), ("km/h written as mph", False, in_mph(letter)),
             ("near-misses swapped", False, swapped(letter, worst))]
    return [m for m in made if m[2]]


def controls(letter, facts):
    """(kind, the letter with one true or fact-free sentence) for the clean controls."""
    n = facts["serious_near_misses"]
    true = (None, "We would welcome a visit to the crossing at a time that suits you.",
            f"In all, the video measured {n} serious near-miss{'' if n == 1 else 'es'}.",
            "These are near-misses measured on video, not recorded accidents.")
    return [(kind, inserted(letter, s) if s else letter) for kind, s in zip(CONTROLS, true)]


def scrubbed(letter):
    """A cached letter as today's prompt asks for it: no SAM version, counts up to twelve in digits."""
    words = "|".join(UNITS[2:])
    return re.sub(rf"\b({words})\b(?![- ]wheel)", lambda m: str(UNITS.index(m[1].lower())), OLD_SAM.sub("SAM", letter),
                  flags=re.I)


def measurements(events_file, site):
    """The facts pack.py gives the letter model, rebuilt from an events.json."""
    data = json.loads(events_file.read_text())
    return pack.facts(site, pack.confirmed(data["events"]), pack.real_crossers(data["events"], data.get("exposure") or {}))


def glimmer_base():
    """("glimmer", letter, facts): Glimmer's v1 letter from its run record, and the facts of sample/ it came from."""
    record = GLIMMER_RUN.read_text()
    quoted = re.search(r"\*\*Letter to the road authority\*\*.*?\n\n((?:> .*\n?)+)", record)[1]
    site = json.loads((HERE / "sample" / "site.json").read_text())
    return "glimmer", " ".join(line[2:] for line in quoted.splitlines()), measurements(HERE / "sample" / "events.json", site)


def cached_letter(path):
    """The letter Muse Spark wrote in a cached plan.json or evidence page, or None (another writer, or no letter)."""
    text = path.read_text()
    if path.suffix == ".json":
        plan = json.loads(text)
        return plan.get("letter") if plan.get("writer") == "Muse Spark" else None
    box = re.search(r'<div class="letter"[^>]*>(.*?)</div>', text, re.S)
    if not box or "Glimmer" in text:
        return None
    return "\n".join(html.unescape(re.sub(r"<[^>]+>", "", p)) for p in re.findall(r"<p>(.*?)</p>", box[1], re.S))


def spark_base(out=HERE / "out"):
    """("spark", letter, facts) from the first cached Spark letter that passes the code check against its folder's
    events.json (scrubbed first), or None. Its text stays in the cache and the bench file, never in the repo."""
    for path in sorted(out.glob("**/plan.json")) + sorted(out.glob("**/index.html")):
        events = path.parent / "events.json"
        letter = cached_letter(path) if events.is_file() else None
        if letter:
            facts = measurements(events, {"name": json.loads(events.read_text()).get("site", "")})
            flags = code_flags(scrubbed(letter), facts)
            if not flags:
                return "spark", scrubbed(letter), facts
            print(f"{path}: not a clean base, the code check flags {flags}", file=sys.stderr)
    return None


def bench_letters(bases):
    """Every bench letter: each base's defect copies, then its clean controls, with the facts the checks read."""
    out = []
    for name, letter, facts in bases:
        worst = json.loads(facts)["worst"]
        out += [{"id": f"{name}/{kind}", "kind": kind, "named": named, "planted": True, "letter": text, "measured": facts}
                for kind, named, text in defects(letter, worst)]
        out += [{"id": f"{name}/control: {kind}", "kind": kind, "named": None, "planted": False, "letter": text,
                 "measured": facts} for kind, text in controls(letter, json.loads(facts))]
    return out


def code_flags(letter, measured):
    """What the code layer of pack.ask_plan sends back for this letter ([] if nothing)."""
    return pack.unmeasured(letter, measured) + pack.mixed(letter, json.loads(measured).get("worst", []))


def judged(item, column, ask, runs):
    """`item` with up to `runs` verdicts in `column`: True when the judge listed a problem, False when none, None
    when its reply could not be read. A failed call stops there, for the next run to ask again."""
    verdicts = list(item.get(column, []))
    while len(verdicts) < runs:
        try:
            reply = ask(pack.JUDGE_PROMPT.format(facts=item["measured"], letter=item["letter"]))
        except (OSError, ValueError, KeyError, IndexError, http.client.HTTPException) as err:
            print(f"{item['id']}: {column} call failed, asked again next run: {err}", file=sys.stderr)
            break
        problems = pack.read_problems(reply)
        verdicts.append(None if problems is None else bool(problems))
    return {**item, column: verdicts}


def tally(items, column):
    """(times flagged, times read, unreadable) for one checker over these items."""
    votes = [v for item in items for v in item.get(column, [])]
    read = [v for v in votes if v is not None]
    return sum(read), len(read), len(votes) - len(read)


def letters(items, column):
    """(letters flagged in any of their readable runs, letters with a readable run) for one checker: runs on the same
    letter are not independent trials, so bounds are put on letters, never on runs."""
    read = [[v for v in item.get(column, []) if v is not None] for item in items]
    return sum(any(r) for r in read), sum(bool(r) for r in read)


def anyone(items, columns):
    """(items flagged by any checker in any run, items)."""
    return sum(any(v for c in columns for v in item.get(c, [])) for item in items), len(items)


def cell(k, n, bounds=False):
    if not n:
        return "-"
    lo, hi = wilson(k, n)
    return f"{k}/{n}" + (f" ({100 * lo:.0f}-{100 * hi:.0f}%)" if bounds else "")


def table(items):
    """Markdown: per planted kind, what each checker caught in every run; totals and false alarms per letter, with
    Wilson 95% bounds."""
    columns = ["code"] + [c for c, _ in JUDGES]
    head = ["| Planted lie | Named in JUDGE_PROMPT | Code | " + " | ".join(n for _, n in JUDGES) + " | Any |",
            "|---|---|---|---|---|---|"]
    runs = lambda group, c: tally(group, c)[:2]
    row = lambda label, named, group, count, bounds: (f"| {label} | {named} | " + " | ".join(
        cell(*count(group, c), bounds) for c in columns) + f" | {cell(*anyone(group, columns), bounds)} |")
    planted = [i for i in items if i["planted"]]
    kinds = {i["kind"]: i["named"] for i in planted}
    rows = [row(kind, "yes" if named else "no", [i for i in planted if i["kind"] == kind], runs, False)
            for kind, named in kinds.items()]
    rows += [row("**All planted lies**", "", planted, letters, True),
             row("Named kinds", "yes", [i for i in planted if i["named"]], letters, True),
             row("Kinds not named", "no", [i for i in planted if not i["named"]], letters, True),
             row("**Clean controls: false alarms**", "", [i for i in items if not i["planted"]], letters, True)]
    unread = "; ".join(f"{name} {tally(items, c)[2]} of {sum(len(i.get(c, [])) for i in items)} replies"
                       for c, name in JUDGES)
    return head + rows + ["", "In the rows per kind a checker's cell counts runs; every other cell counts letters, one "
                          "flagged if any of its readable runs flagged it, as runs on one letter are not independent.",
                          f"Unreadable judge replies (in no cell above): {unread}."]


def asker(column):
    """The call that sends one judge prompt to this judge."""
    if column == "spark":
        key = sam.load_api_key()
        return lambda prompt: pack.spark_reply(prompt, None, key)
    if not pack.LETTER_URL:
        raise SystemExit("--glimmer needs LETTER_MODEL_URL, the OpenAI-compatible server running Muse Glimmer")
    return lambda prompt: pack.open_model_reply(prompt, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="the bench file: letters and every verdict so far (JSON)")
    for column, name in JUDGES:
        parser.add_argument(f"--{column}", type=int, default=0, metavar="N", help=f"runs of {name} as judge per letter")
    args = parser.parse_args()
    out = Path(args.out)
    bench = (json.loads(out.read_text()) if out.is_file()
             else bench_letters([glimmer_base()] + [b for b in [spark_base()] if b]))
    bench = [{**i, "code": [bool(code_flags(i["letter"], i["measured"]))]} for i in bench]
    out.write_text(json.dumps(bench, indent=1, ensure_ascii=False))
    for column, _ in JUDGES:
        runs = getattr(args, column)
        if not runs:
            continue
        ask = asker(column)
        for k, item in enumerate(bench):
            bench[k] = judged(item, column, ask, runs)
            out.write_text(json.dumps(bench, indent=1, ensure_ascii=False))  # every paid reply kept at once
    print("\n".join(table(bench)))


if __name__ == "__main__":
    main()
