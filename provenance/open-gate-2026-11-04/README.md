# Our real gate: every reasoning step on open weights (4 Nov 2026)

The real gate case (LNCT Excellence main gate, Bhopal, 8.6 minutes analysed) worked again with every reasoning step
on Meta open-weights models: the person review, the case agent and the letter on **Muse Spark Open**
(Fireworks serverless), and the letter's judge on **our LoRA-tuned Muse Glimmer judge (v6)**, served on a Fireworks
on-demand deployment for 4 minutes and then deleted. No Meta API key was set for these steps, and every host except
api.fireworks.ai went to a dead proxy for the whole run, so no Meta API call could succeed.

| Step | Open-weights model | Where | Result |
|---|---|---|---|
| Is each tracked near-miss pedestrian a person? | Muse Spark Open | Fireworks serverless | 32 people reviewed, 29 rejected (28 by the model, 1 ruled out by eye in `sites/gate.json`): **the same keep-or-reject as Muse Spark on all 32** |
| Case agent (tools, asks a person for the tape) | Muse Spark Open | Fireworks serverless, tool calling | 5 turns: track, measure, review, request_measurement, then submit_letter after the tape (15 m; video 15.0 m, 0% off) |
| Letter to the road authority | Muse Spark Open | Fireworks serverless | written on the first try in 51.8 s, request `chatcmpl-45c5ea24b9654c75bdbc9b1617c586c2` ([letter](letter.txt)) |
| Letter judge | Muse Glimmer 30B + our v6 LoRA | Fireworks on-demand, 1 x H200 | no unsupported claim, in the product and in 3 more reads with response ids ([judge.json](judge.json)) |
| Code check (every number measured, no mixed-up events, no blame, no slips) | none (code) | here | clean: nothing to fix |

## Against the hosted run (Muse Spark)

- **Same near-misses kept after review:** the same 5 of 75 (2 serious, 3 close passes), the same people, vehicles
  and gaps. **The same 51 people who crossed.** The measurements the letter is written from are identical.
- **One label differs**, not the outcome: one rejected track is "rider" for Spark Open, "not a person" for Muse Spark.
- **The letter passes the code check and the tuned judge on its first try**, as Muse Spark's letter did in the
  hosted case agent run (2 Nov). Spark Open asks for a raised zebra crossing; the hosted agent's first letter asked for a
  raised zebra crossing with 20 km/h signs (the certified letter asks for a painted one after the college's notes).
- Spark Open's agent called measure before review; Muse Spark called review first. Same five tools, same stop for a person.

## Not open weights here

SAM 3.1 tracking re-read the hosted run's cached replies ($0 new). Muse Wonder (listening) has no open-weights
equivalent: its 5 cached replies were reused. Muse Image has no open-weights equivalent: not called, so this run drew
no new picture of the fix.

## Spend and the deployment

About **$0.62** (at most $0.68): Spark Open tokens $0.083 at list price, the judge's H200 for 241 s from create to
delete at $8 per GPU-hour. Deployment `cw-judge-open-gate` was created 19:47:42 UTC and deleted 19:51:43 UTC (3 Nov,
i.e. 01:17-01:21 IST on 4 Nov); the account listed no deployment right after, and the deployment reads DELETED
([run.json](run.json)).

## Files

- [run.json](run.json): what ran where, model ids, the deployment's shape and log, timings, tokens, cost.
- [review.json](review.json): Muse Spark vs Muse Spark Open on each of the 32 people; the 5 near-misses and 51 people compared.
- [agent_log.jsonl](agent_log.jsonl): the case agent's turns (model, tool, tokens, wall time).
- [letter.txt](letter.txt) and [letter-provenance.json](letter-provenance.json): the letter Spark Open wrote and its run record.
- [judge.json](judge.json): the code check and the tuned judge's verdicts with response ids.
- [run_open_gate.sh](run_open_gate.sh), [judge_case.py](judge_case.py): the run as it was done.

Limits: `analyze.py` will not start without `MODEL_API_KEY` even when it calls no Meta model, so its tracking runs got
a placeholder that is not a key (behind the network guard); the letter step had no Meta key at all. The review and
agent tools still print "Spark" in a few labels when Spark Open does the work. Review replies and the in-product judge
call keep no response id. Crops, clips and reply texts stay with the private outputs.
