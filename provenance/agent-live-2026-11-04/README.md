# The case agent, live on camera (4 Nov 2026)

The agent scene in the demo video is a screen capture of these runs: `agent.py` on a fresh copy of the 2 Nov gate case,
with live Muse Spark turns (SAM 3.1 replies and crop verdicts come from the 2 Nov cache, so no new SAM cost), and the
tape length typed by a person when the agent asks for it.

| File | Time (IST) | Tape typed | Result |
|---|---|---|---|
| `take-A-1403-tape-15m.jsonl` | 14:03-14:05 | 15 m (the real tape) | 5 turns: "Video 15.0 m, tape 15 m, 0% off: proven", then the letter waits for the head of the school |
| `take-B-1407-tape-12m.jsonl` | 14:07-14:11 | 12 m, typed on purpose to show the check | 12 turns: "video 15.0 m, tape 12 m: 25% off, more than 15%", letter refused 3 times, then handed to a person (R2) |
| `rehearsal-A-1349.jsonl`, `rehearsal-B-1351.jsonl` | 13:49, 13:51 | none, and 12 m | the same two runs rehearsed before recording |

The run's review line, "Muse Spark reviewed 32 pedestrians and rejected 29", counts the 1 track ruled out by eye
(`sites/gate.json`), so 28 were set aside by Muse Spark. Each line holds the turn, tool, summary, model, tokens, wall
time and cost. The run as it was done: `python3 agent.py gate-stable.mp4 sites/gate.json --out RUN`, then
`--answer R1 "15 m"` (take A) or `--answer R1 "12 m"` (take B).
