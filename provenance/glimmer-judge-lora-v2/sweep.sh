#!/bin/zsh
# Pre-registered v2 sweep (GATES.md, Sat 31 Oct 2026): A r8 e1 1e-4, B r32 e1 1e-4, C r8 e2 1e-4, D r32 e2 5e-5.
# Runs one after another (one serverless training slot); stops at the first failure.
V2=GLIMMER_FT/v2
cd GLIMMER_FT/cookbook/training
set -a; . CROSSING_WATCH/.env; set +a
N=$(python3 -c "import json;print(json.load(open('$V2/split.json'))['n_eval'])")
for cfg in "B 32 1 1e-4" "C 8 2 1e-4" "D 32 2 5e-5"; do
  set -- ${=cfg}
  echo "=== config $1: rank $2, epochs $3, lr $4 ($(date))"
  for try in {1..36}; do  # one serverless slot: a 429 means the last session has not expired yet; wait 5 min
    if caffeinate -dims ../../venv/bin/python -m examples.sft.muse_glimmer_starter launch --surface serverless \
      --file $V2/judge_v2.jsonl --run-id judge-v2-${1:l} --n-eval $N --max-seq-len 3072 --max-eval-tokens 256 \
      --lora-rank $2 --epochs $3 --learning-rate $4 > $V2/launch-$1.log 2>&1; then break; fi
    grep -q "RATE_LIMIT_EXCEEDED" $V2/launch-$1.log || exit 1
    echo "slot busy, try $try, waiting 5 min ($(date))"; sleep 300
  done
  tail -3 $V2/launch-$1.log
  sleep 120  # the training slot frees when the session expires
done
echo "sweep done $(date)"
