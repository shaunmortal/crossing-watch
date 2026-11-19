#!/bin/zsh
# Serve Muse Glimmer 30B (base model, vision) once on a Fireworks on-demand deployment, 1 x H200 BF16 ($8/GPU-hour,
# billed per second, start-up not billed; it has no serverless route), run the crop-review sets through
# run_review.py, then ALWAYS delete the deployment (trap on exit; expire_time 2 h is the server-side backstop).
# Needs FIREWORKS_ACCOUNT, CW_PYTHON (a Python with the fireworks SDK), DUT_REPO, and WORK: a private scratch folder
# with WORK/gate (the gate run's events.json, person-*.jpg crops and Spark's replies), WORK/runs-glimmer/{dut-15s,
# dut-vcrowd} (copies of the cached DUT runs) and WORK/smoke.jpg (a blank synthetic image). Crops never leave WORK.
setopt pipefail
CW=$(git rev-parse --show-toplevel)
HERE=${0:A:h}
ACCT=${FIREWORKS_ACCOUNT:?set FIREWORKS_ACCOUNT}; W=${WORK:?set WORK}; DUT=${DUT_REPO:?set DUT_REPO}
PY=${CW_PYTHON:?set CW_PYTHON}
DEP=cw-glimmer-vision
BASE=accounts/fireworks/models/muse-glimmer-30b
SHAPE=accounts/fireworks/deploymentShapes/dkuwotf7   # "Muse Glimmer 30B BF16 1x H200"
API=https://api.fireworks.ai/v1/accounts/$ACCT/deployments/$DEP
set -a; . "$CW/.env"; set +a
mask() { sed "s/$ACCT/<account>/g"; }
sdk() { $PY -c "from fireworks import Fireworks; c = Fireworks(account_id='$ACCT'); $1" 2>&1 | mask; }
cleanup() {
  echo "deleting $DEP $(date -u +%FT%TZ)"
  curl -s -X DELETE -H "Authorization: Bearer $FIREWORKS_API_KEY" "$API?ignoreChecks=true" | mask | head -c 300; echo
  for i in {1..20}; do
    code=$(curl -s -o $W/dep-state.json -w "%{http_code}" -H "Authorization: Bearer $FIREWORKS_API_KEY" "$API")
    state=$(python3 -c "import json; print(json.load(open('$W/dep-state.json')).get('state', '?'))" 2>/dev/null)
    echo "after delete: HTTP $code, state $state $(date -u +%FT%TZ)"
    [[ $code == 404 || $state == DELETED ]] && break
    sleep 30
  done
  sdk "print('deployments listed now:', [(d.name, d.state) for d in c.deployments.list()])"
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
echo "create $(date -u +%FT%TZ)"
sdk "import datetime as t; d = c.deployments.create(base_model='$BASE', deployment_id='$DEP', deployment_shape='$SHAPE', min_replica_count=1, max_replica_count=1, expire_time=t.datetime.now(t.timezone.utc) + t.timedelta(hours=2)); print('created', d.name, d.state)" || exit 1
sdk "
import time
end = time.monotonic() + 45 * 60
while (d := c.deployments.get('$DEP')).state != 'READY':
    if d.state in ('FAILED', 'DELETING', 'DELETED') or time.monotonic() > end:
        raise SystemExit(f'{d.name} is {d.state}: {d.status}')
    time.sleep(20)
print('READY', d.name, 'shape:', getattr(d, 'deployment_shape', None), 'accelerator:', d.accelerator_type, d.accelerator_count, 'precision:', d.precision)" | tee $W/ready.txt
grep -q '^READY' $W/ready.txt || exit 1
echo "ready $(date -u +%FT%TZ)"
cd $CW
export REVIEW_MODEL_URL=https://api.fireworks.ai/inference/v1 REVIEW_MODEL="$BASE#accounts/$ACCT/deployments/$DEP"
export REVIEW_TEMPERATURE=0 PRIVATE_LOG=$W/private-replies-glimmer.jsonl PYTHONDONTWRITEBYTECODE=1
python3 $HERE/run_review.py smoke $W/smoke.jpg $HERE/smoke.jsonl 2>&1 | mask || {
  echo "smoke failed with the product's parameters: retrying without reasoning_effort (RULE.md)"
  export REVIEW_DROP_PARAMS=reasoning_effort
  python3 $HERE/run_review.py smoke $W/smoke.jpg $HERE/smoke.jsonl 2>&1 | mask || exit 1
}
echo "A start $(date -u +%FT%TZ)"
python3 $HERE/run_review.py gate $W/gate $HERE/replies-A-glimmer.jsonl 2>&1 | mask
echo "B start $(date -u +%FT%TZ)"
python3 $HERE/run_review.py dut $HERE/replies-B-glimmer.jsonl $DUT $W/runs-glimmer/dut-15s $W/runs-glimmer/dut-vcrowd \
  --json $W/scores-B-glimmer.json 2>&1 | mask | grep -v '^asking '
echo "done $(date -u +%FT%TZ)"
