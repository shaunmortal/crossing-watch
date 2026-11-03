"""The served v6 adapter judges our real gate letter (out/gate/plan.json) on the product's own judge prompt and inputs:
the measured facts pack.py builds, plus the principal's notes labelled as stated (pack.stated_text). Asked 3 times at
temperature 0 and 3 times as the product asks (pack's JSON schema); every reply, response id and usage is saved.
Run: python3 judge_gate.py MODEL#DEPLOYMENT OUT.json
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

CW = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CW))
import pack  # noqa: E402

URL = "https://api.fireworks.ai/inference/v1/chat/completions"


def ask(model, prompt, schema):
    body = {"model": model, "temperature": 0, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "problems", "schema": pack.PROBLEMS_SCHEMA}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json",
                                 "Authorization": "Bearer " + os.environ["FIREWORKS_API_KEY"]})
    t = time.monotonic()
    r = json.load(urllib.request.urlopen(req, timeout=300))
    text = r["choices"][0]["message"].get("content") or ""
    return {"schema": schema, "reply": text, "problems": pack.read_problems(text), "response_id": r.get("id"),
            "finish": r["choices"][0].get("finish_reason"), "usage": r.get("usage"), "wall_s": round(time.monotonic() - t, 2)}


def main(model, out):
    site = json.loads((CW / "sites/gate.json").read_text())
    data = json.loads((CW / "out/gate/events.json").read_text())
    plan = json.loads((CW / "out/gate/plan.json").read_text())
    events = pack.confirmed(data["events"])
    seen = pack.real_crossers(data["events"], data.get("exposure"))
    measured = pack.facts(site, events, seen, data.get("paths") or {}) + pack.stated_text(plan.get("notes", []))
    prompt = pack.JUDGE_PROMPT.format(facts=measured, letter=plan["letter"])
    runs = [ask(model, prompt, schema) for schema in (False, False, False, True, True, True)]
    record = {"model": model, "letter_sha256": pack.sha256(plan["letter"]), "prompt_sha256": pack.sha256(prompt),
              "fix": plan["fix"], "runs": runs}
    Path(out).write_text(json.dumps(record, indent=1))
    for r in runs:
        print(("schema " if r["schema"] else "plain  ") + json.dumps(r["problems"]), r["finish"], r["wall_s"], "s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
