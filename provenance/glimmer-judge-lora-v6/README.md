# Tuned judge v6: file map

| Organizers' item (1 Nov 2026) | Files |
|---|---|
| Model ids | `main/summary.json` (training session, promoted model), `live/run.json` and `base/run.log` (deployment names; the account id is masked and goes to the organizers with the submission) |
| Training logs | `main/metrics.jsonl` (512 logged steps: loss, grad norms), `main/command.txt` (the launch command), `main/summary.json` |
| Eval outputs | `main/predictions_tuned.jsonl`, `main/predictions_base.jsonl` and `main/holdout.jsonl` (the training session's own evaluation, 256-token cap); `live/predictions_served.jsonl` (2 Nov, a Fireworks response id on every row); `base/predictions_base.jsonl` (base Glimmer, 8,192-token cap, 4 Nov, response ids); `kaggle/predictions_kaggle.jsonl` (free 2 x T4, 4 Nov); `labels/` and `labels-frozen.json` (Muse Spark and Spark Open replies with request ids; labels frozen before any tuned reply was read) |
| Re-score | from the repo root, standard library, no key, under a second each: `python3 judge_v3_score.py v6`, `python3 provenance/glimmer-judge-lora-v6/kaggle/score_kaggle.py provenance/glimmer-judge-lora-v6/kaggle/predictions_kaggle.jsonl`, `python3 provenance/glimmer-judge-lora-v6/base/score_base.py provenance/glimmer-judge-lora-v6/base/predictions_base.jsonl` |
| Served | `live/live_v6.sh` (re-serve on Fireworks), `live/product-bench.md` (the public bench through the product's judge path: 21 of 23 lies, 0 of 8 false alarms), `live/gate-letter-judge.json` and `kaggle/gate-letter-judge-kaggle.json` (our real letter) |
| Downloadable adapter | [huggingface.co/shaunmortal/crossing-watch-glimmer-judge-v6](https://huggingface.co/shaunmortal/crossing-watch-glimmer-judge-v6): PEFT safetensors, a GGUF for llama.cpp, sha256 of every file on the card |

`live/replay_v6.py`, `base/replay_base.py`, `base/base_v6.sh` and `live/live_gate.sh` are the runs as they were done; they need a Fireworks key. Everything else runs offline.
