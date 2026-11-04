"""The served tuned judge reads the case agent's letter again, 3 times, through the product's own judge call
(pack.open_model_reply with PROBLEMS_SCHEMA, judge=True: JUDGE_MODEL_URL / JUDGE_MODEL, reasoning_effort low) on the
exact prompt ask_plan gave it (pack.JUDGE_PROMPT on the case's measured facts), so each verdict has a response id.
Also re-runs the code checks ask_plan ran first. Run from the repo copy: python3 judge_case.py OUT_DIR RECORD.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
import pack  # noqa: E402

READS = 3


def main(out_dir, record_path):
    p = json.loads((Path(out_dir) / "case" / "progress.json").read_text())
    letter, measured = p["letter"], p["measured"]
    prompt = pack.JUDGE_PROMPT.format(facts=measured, letter=letter["letter"])
    reads = []
    for _ in range(READS):
        text, run = pack.open_model_reply(prompt, None, pack.PROBLEMS_SCHEMA, judge=True)
        reads.append({"reply": text, "problems": pack.read_problems(text), **run})
    facts = json.loads(measured)
    code = {"unmeasured": pack.unmeasured(letter["letter"] + " " + letter["why"], measured),
            "mixed": pack.mixed(letter["letter"], facts.get("worst", [])),
            "accuses": pack.accusing(letter["letter"] + "\n" + letter["why"]),
            "slips": [s for s, _ in pack.slips(letter["letter"], facts)]}
    record = {"letter_sha256": pack.sha256(letter["letter"]), "prompt_sha256": pack.sha256(prompt),
              "code_check": code, "judge_reads": reads}
    Path(record_path).write_text(json.dumps(record, indent=1))
    print("code check:", json.dumps(code))
    for r in reads:
        print("judge:", json.dumps(r["problems"]), r.get("request_id"), r.get("wall_s"), "s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
