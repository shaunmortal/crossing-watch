"""Monday night in one command: the gate recording from filmcheck to the list of things to check by eye.

Run: python3 monday.py VIDEO SITE.json                       $0: filmcheck and analyze's SAM estimate, then stops
     python3 monday.py VIDEO SITE.json --budget N --yes      the paid run: analyze (SAM capped at N), pace guard,
                                                             pack (Spark letter and judge; Spark Open judges too when
                                                             a Fireworks key is set), the case agent, the summary
     add --trap TRAP.csv for G6 (validate_gate.py), --from STEP to resume, --dry-run to print the commands only.
Never --allow-cost. Keys stay in .env: this script asks only whether a Fireworks key is set, never for its value.
Glimmer cannot run here; the end prints the Kaggle steps for the gate pack.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import agent
import analyze
import openweights
import pace
import pack
import review
import sam

STEPS = ("filmcheck", "analyze", "pace", "pack", "agent", "g6")
SPARK_OPEN = {"JUDGE_MODEL_URL": "https://api.fireworks.ai/inference/v1",
              "JUDGE_MODEL": "accounts/fireworks/models/muse-spark-open"}
HERE = Path(__file__).parent


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", help="the phone original, e.g. ~/cw-footage/CLIP.MOV (never trimmed)")
    parser.add_argument("site", help="the site file from calibrate.html, merged with the template, with roadway_m")
    parser.add_argument("--out", help="output folder (default out/<video name>); the agent works in <out>-agent")
    parser.add_argument("--budget", type=float, metavar="USD", help="analyze.py's SAM cap for the paid run")
    parser.add_argument("--yes", action="store_true", help="spend: run the paid steps (needs --budget)")
    parser.add_argument("--trap", metavar="CSV", help="hand-logged line times (G6); without it G6 is skipped")
    parser.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0], help="resume at this step")
    parser.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    args = parser.parse_args(argv)
    if args.budget is not None and not args.budget >= 0:
        parser.error("--budget must be 0 or more US dollars")
    if args.yes and args.budget is None:
        parser.error("--yes spends money: give --budget USD, picked from the free estimate")
    if args.budget is not None and not args.yes:
        parser.error("--budget is for the paid run: add --yes (or leave both out for the free estimate)")
    args.out = args.out or str(Path("out") / Path(args.video).stem)
    return args


def judge_env():
    """(extra environment, the line to print): Spark Open on Fireworks as the second judge when a Fireworks key is set
    and no judge is chosen already. Only whether a key is set is read out, never the key."""
    if pack.JUDGE_URL:
        return {}, f"second judge: {pack.JUDGE_MODEL} at {pack.JUDGE_URL} (already set)"
    if sam.env_value("JUDGE_MODEL_KEY") or sam.env_value(openweights.FIREWORKS_KEY):
        return SPARK_OPEN, "second judge: Muse Spark Open on Fireworks (a Fireworks key is set)"
    return {}, "second judge: none, Muse Spark only (no Fireworks key set)"


def commands(args, site):
    """{step: [command, ...]}; "pace" runs in this script."""
    py, agent_out = sys.executable, f"{args.out}-agent"
    caffeinate = ["caffeinate", "-dims"] if shutil.which("caffeinate") else []  # the Mac stays awake for hours
    budget = f"{args.budget:g}" if args.yes else "0"  # 0: analyze prints the SAM estimate and stops
    # the agent's APFS clone is taken before pack.py writes into out (DEMO_AND_DAYS: agent never in pack's folder)
    clone = [] if Path(agent_out).exists() else [["cp", "-cR", args.out, agent_out]]
    return {"filmcheck": [[py, "filmcheck.py", args.video, *(f"{v:g}" for v in site.get("window_s") or [])]],
            "analyze": [[*caffeinate, py, "analyze.py", args.video, args.site, "--out", args.out, "--budget", budget]],
            "pace": [],
            "pack": [*clone, [py, "pack.py", args.out, args.site]],
            "agent": [*(clone if args.start == "agent" else []), [py, "agent.py", args.video, args.site, "--out",
                                                                  agent_out]],
            "g6": [[py, "validate_gate.py", args.site, args.out, args.trap]] if args.trap else []}


def costs(budget, judge_line):
    return "\n".join([
        "Before spending (--budget caps SAM only; never --allow-cost):",
        f"- analyze: SAM up to ${budget}; its own line prints the estimate first and stops above the cap. Muse "
        f"Spark reviews up to {analyze.MAX_REVIEWS} people and Muse Wonder listens per event (cents each, not capped).",
        "- pack: Spark letter and judge (the sample letter was about $0.018) and one Muse Image picture; " + judge_line,
        f"- agent: turns capped at ${agent.MAX_USD:.2f}; its tracking re-reads SAM's cache at $0."])


def pace_guard(out_dir, site):
    walk = json.loads((Path(out_dir) / "events.json").read_text()).get("walking") or {}
    if untrusted := pace.warning(walk, site):
        raise SystemExit(f"pace guard: {untrusted}\nStop: no letter is written from these numbers; check the clock "
                         "and the calibration")
    judged = walk.get("pieces", 0) >= pace.MIN_PIECES
    print(f"pace: median walk {walk.get('median_mps')} m/s over {walk.get('pieces', 0)} pieces"
          + ("" if judged else f" (fewer than {pace.MIN_PIECES}: not judged, check by eye)"))


def by_eye(args):
    """What to look at by eye, from the run's events.json."""
    data = json.loads((Path(args.out) / "events.json").read_text())
    events, lines = data["events"], []
    for e in events:
        if said := review.unconfirmed_rider(e.get("review")):
            lines.append(f"  at {e['t_person_s']:.1f} s, {e['person']}: {said}")
    unreviewed = sum(e.get("review") is None for e in events)
    walk = data.get("walking") or {}
    hit, total, *_ = data.get("sam_full_requests") or [0, 0]
    print("\nCheck by eye:",
          f"- {len(events)} events; {unreviewed} not reviewed by Spark",
          f"- review_disputed or rider without a bike ({len(lines)}): open each clip on the page", *lines,
          f"- pace: median {walk.get('median_mps')} m/s, flag {walk.get('flag') or 'none'}",
          f"- {hit} of {total} SAM video requests hit the {sam.MAX_OBJECTS}-object limit",
          f"- the page: open {args.out}/index.html; the agent's case: {args.out}-agent/index.html#case", sep="\n")


def kaggle_steps(args):
    gate = "~/cw-footage/kaggle-gate"
    return f"""
Glimmer on the gate pack (Kaggle, notebook <removed-run-record> Version 3; never v2):
 1. mkdir -p {gate} && cp {args.out}/events.json {gate}/ && cp {args.site} {gate}/site.json
    (only these two: never clip.mp4, frames or person crops)
 2. Kaggle > Datasets > New, name it cw-gate, PRIVATE, upload the two files.
 3. Open the v3 notebook > Add Input > cw-gate. In cell "4. Write the evidence pack" replace the OUT line with:
    OUT = f'{{CW}}/gate'; os.makedirs(OUT, exist_ok=True); [shutil.copy(p, OUT) for p in glob.glob('/kaggle/input/**/cw-gate/*.json', recursive=True)]
 4. GPU T4 x2, Internet on, secret MODEL_API_KEY attached if Spark should judge. Delete cells 13-14 (the public
    bench, about 3 h) in this version. Save Version > Save & Run All. Keep the version PRIVATE.
 5. Download glimmer-letter.txt, plan.json and <removed-run-record>; keep them outside the repo until checked."""


def run(step, cmds, env, args):
    for cmd in cmds:
        print("$ " + " ".join(cmd), flush=True)
        if args.dry_run:
            continue
        code = subprocess.run(cmd, cwd=HERE, env=env).returncode
        if code and not (step == "analyze" and not args.yes):  # the $0 estimate stops above $0 by design
            raise SystemExit(f"\nstopped at {step} (exit {code}). Fix what it says, then resume with the same command "
                             f"plus --from {step}" + (" (or --from analyze if each filmcheck line is understood)"
                                                      if step == "filmcheck" else ""))


def main(argv=None):
    args = parse(argv)
    site = analyze.load_site(args.site)
    try:
        agent.check_distance(site)
    except ValueError as err:
        raise SystemExit(f"{args.site}: {err}")
    missing = [k for k in ("window_s", "trap", "check", "roadway_m") if k not in site]
    if missing:
        print(f"warning: {args.site} has no {', '.join(missing)} (see DEMO_AND_DAYS 'Monday's site file')")
    if not args.dry_run and not Path(args.video).is_file():
        raise SystemExit(f"{args.video}: no such file")
    extra, judge_line = judge_env()
    env = {**os.environ, **extra}
    plan = commands(args, site)
    steps = STEPS[STEPS.index(args.start):]
    if not args.yes:
        if "analyze" in steps and (Path(args.out) / "events.json").exists():
            print(f"{args.out}/events.json exists: the paid run happened, so no estimate (it could re-pay Spark)")
            steps = [s for s in steps if s != "analyze"]
        for step in [s for s in steps if s in ("filmcheck", "analyze")]:
            run(step, plan[step], env, args)
        # ponytail: a crashed paid run with SAM all cached but no events.json would re-ask Spark here (cents)
        print(f"\nFree part done. Pick N from the SAM line above, then:\n  python3 monday.py {args.video} "
              f"{args.site} --out {args.out} --budget N --yes" + (f" --trap {args.trap}" if args.trap else ""))
        print(costs("N", judge_line))
        if (Path(args.out) / "events.json").exists():
            by_eye(args)
        return
    print(costs(f"{args.budget:g}", judge_line), flush=True)
    for step in steps:
        print(f"\n== {step}", flush=True)
        if step == "pace" and args.dry_run:
            print("(in this script: the walking-pace guard on events.json)")
        elif step == "pace":
            pace_guard(args.out, site)
        elif step == "g6" and not args.trap:
            print(f"G6 skipped: no --trap. Log 30 vehicles from second {(site.get('window_s') or [0])[0]:g} "
                  f"(GATES.md G6), then: python3 validate_gate.py {args.site} {args.out} TRAP.csv")
        else:
            run(step, plan[step], env, args)
    print(f"\nAgent: answer its tape question with the real taped distance, using the R id it printed:\n"
          f'  python3 agent.py {args.video} {args.site} --out {args.out}-agent --answer R1 "[taped] m"\n'
          "Stop at needs_review. Never --approve on Monday.")
    if not args.dry_run:
        by_eye(args)
    print(kaggle_steps(args))


if __name__ == "__main__":
    main()
