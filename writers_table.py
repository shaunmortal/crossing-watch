"""Writers table: who wrote the letter for the synthetic sample/, from each run's record, as one Markdown table:
open weights or not, where it ran, wall seconds, tokens, tries, the checks and the cost of the letter. Offline: it
reads the records and the prices below, never an API.

Run: python3 writers_table.py [RECORD.json ...]
Default records: <removed-run-record> (the Kaggle notebook's) and provenance/spark-open-fireworks-sample.json
(pack.py's letter-provenance.json). A Muse Spark run on the Meta API is read the same way once it has a record with
"model", "host" ("api.meta.ai") and the Responses API "usage".
"""
import json
import sys
from pathlib import Path

import openweights
import pack

HERE = Path(__file__).parent
RECORDS = (HERE / "kaggle" / "<removed-run-record>", HERE / "provenance" / "spark-open-fireworks-sample.json")
META_HOST = "api.meta.ai"
NAMES = {**openweights.NAMES, "muse-spark-1.3": "Muse Spark"}  # API model id -> product name
# USD per 1M tokens (input, cached input, output) by API model id, each quoted from its page on the day it was read
PRICES = {"accounts/fireworks/models/muse-spark-open": (1.25, 0.15, 4.25,
                                                       "https://fireworks.ai/models/fireworks/muse-spark-open"),
          "muse-spark-1.3": (1.25, 0.15, 4.25, "https://dev.meta.ai/docs/pricing-rate-limits.md")}
PRICES_READ = "29 Oct 2026"
PER = 1_000_000
HEADER = ("| Writer | Open weights | Where it ran | Wall s | Prompt tokens (cached) | Completion tokens | Reasoning tokens "
          "| Tries | Number check | Passed by judge | Cost per letter |")


def tokens(usage):
    """(prompt, cached, completion, reasoning) from Chat Completions or Responses API usage; None where not given."""
    usage = usage or {}
    first = lambda *keys: next((usage[k] for k in keys if isinstance(usage.get(k), int)), None)
    detail = lambda keys, k: next((usage[d].get(k) for d in keys if isinstance(usage.get(d), dict)
                                   and isinstance(usage[d].get(k), int)), None)
    return (first("prompt_tokens", "input_tokens"),
            detail(("prompt_tokens_details", "input_tokens_details"), "cached_tokens"),
            first("completion_tokens", "output_tokens"),
            detail(("completion_tokens_details", "output_tokens_details"), "reasoning_tokens"))


def where(record):
    if "nvidia_smi" in record:  # the Kaggle notebook's record
        return f"Kaggle, {record['nvidia_smi'].count('Tesla T4')} x Tesla T4, self-hosted"
    return {openweights.FIREWORKS_HOST: "Fireworks (serverless)", META_HOST: "Meta API"}.get(record.get("host"),
                                                                                             record.get("host") or "?")


def cost(record, usage):
    """The letter's price: $0 on Kaggle's free GPU quota, else tokens x the model's quoted price (uncached prompt at
    the input price, cached at the cached price, completion tokens, which include reasoning, at the output price)."""
    if "nvidia_smi" in record:
        return "$0 (free Kaggle GPU quota)"
    price, (prompt, cached, completion, _) = PRICES.get(record.get("model")), tokens(usage)
    if not price or prompt is None or completion is None:
        return "NOT CHECKED"
    cached = cached or 0
    return f"${((prompt - cached) * price[0] + cached * price[1] + completion * price[2]) / PER:.4f}"


def number_check(letter, tries):
    """passed/failed from the lists pack.ask_plan leaves after the last try; a record without them passed when it was
    kept before the last try, as ask_plan returns early only on a letter no check objected to (plainly "passed" for
    the first try, which no earlier try could have been kept instead of)."""
    if "unmeasured" in letter:
        bad = letter["unmeasured"] + letter.get("mixed", [])
        return f"failed: {len(bad)} left" if bad else "passed"
    if tries == 1:
        return "passed"
    return "passed (kept before the last try)" if isinstance(tries, int) and tries < pack.LETTER_TRIES else "NOT RECORDED"


def judge_check(letter):
    """Who passed the letter, "none ran", or what a judge left on a letter kept after the last try."""
    if "judged_by" in letter:
        return letter["judged_by"] or "none ran"
    left = letter.get("unsupported")
    return f"failed: {len(left)} left" if left else "NOT RECORDED"


def row(record):
    letter = record.get("letter", record)  # the Kaggle record keeps the letter's run under "letter"
    model = record.get("model", {}).get("repo") if isinstance(record.get("model"), dict) else record.get("model")
    name = (letter.get("writer") or NAMES.get(model, model) or "?").split(" (")[0]
    usage = letter.get("usage")
    prompt, cached, completion, reasoning = tokens(usage)
    show = lambda n: "not reported" if n is None else f"{n:,}"
    seconds = record.get("pack_py_s", record.get("wall_s"))
    return (f"| {name} | {'no' if record.get('host') == META_HOST else 'yes'} | {where(record)} "
            f"| {'not reported' if seconds is None else seconds} | {show(prompt)} ({show(cached)}) | {show(completion)} "
            f"| {show(reasoning)} | {letter.get('tries', '?')} | {number_check(letter, letter.get('tries'))} | {judge_check(letter)} "
            f"| {cost(record, usage)} |")


def table(paths):
    rows = [row(json.loads(Path(p).read_text())) for p in paths]
    prices = "; ".join(f"{NAMES[m]} {p[0]} / {p[1]} / {p[2]} ({p[3]})" for m, p in PRICES.items())
    return [HEADER, "|" + "---|" * HEADER.count(" | ") + "---|", *rows, "",
            f"Prices, USD per 1M tokens input / cached input / output, read {PRICES_READ}: {prices}. Tokens are the kept "
            "reply's; wall seconds are the whole pack.py run where the record has it (Kaggle), else the reply's."]


if __name__ == "__main__":
    print("\n".join(table(sys.argv[1:] or RECORDS)))
