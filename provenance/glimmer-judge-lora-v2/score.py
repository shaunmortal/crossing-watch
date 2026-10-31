"""Score v2 sweep runs with pack.read_problems. Default: DEV rows only (the pre-registered winner rule).
--reveal-public CONFIG prints public-bench scores, allowed only after the winner is named in GATES.md."""
import json, sys
sys.path.insert(0, "CROSSING_WATCH")
import pack
V2 = "GLIMMER_FT/v2"
LOGS = "GLIMMER_FT/cookbook/training/muse_starter_logs"
split = json.load(open(f"{V2}/split.json"))
labels = split["holdout"]  # post-shuffle order = holdout.jsonl order = predictions index

def score(cfg, which):
    preds = {p["index"]: p for p in map(json.loads, open(f"{LOGS}/judge-v2-{cfg.lower()}/predictions_tuned.jsonl"))}
    t = {"lies": [0, 0], "clean": [0, 0], "unreadable": 0}
    for i, lab in enumerate(labels):
        if lab["set"] != which:
            continue
        problems = pack.read_problems(preds[i]["answer_text"])
        t["unreadable"] += problems is None
        k = "lies" if lab["planted"] else "clean"
        t[k][1] += 1
        t[k][0] += bool(problems)
    return {**t, "score": t["lies"][0] - 2 * t["clean"][0]}

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--reveal-public":
        print("public", sys.argv[2], json.dumps(score(sys.argv[2], "public")))
    else:
        for cfg in "ABCD":
            try:
                print("dev", cfg, json.dumps(score(cfg, "dev")))
            except FileNotFoundError:
                print("dev", cfg, "not run")
