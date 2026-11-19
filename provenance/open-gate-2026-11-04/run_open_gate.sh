#!/bin/zsh
# The open-weights gate run of 4 Nov 2026, as it ran (local paths and the account id replaced by variables).
# CW: a frozen copy of the repo (no .env, no .git) with out/gate copied to out/gate-open; VIDEO: the gate recording;
# SDK_PY: a Python with the fireworks SDK. Phase 1 runs without the judge; the judge is deployed only for phase 2.
set -a; . ./.env; set +a; unset MODEL_API_KEY      # the Fireworks key only
FW=https://api.fireworks.ai/inference/v1; SPARK_OPEN=accounts/fireworks/models/muse-spark-open
export AGENT_MODEL_URL=$FW REVIEW_MODEL_URL=$FW LETTER_MODEL_URL=$FW
export AGENT_MODEL=$SPARK_OPEN REVIEW_MODEL=$SPARK_OPEN LETTER_MODEL=$SPARK_OPEN
# network guard: every host except Fireworks goes to a dead proxy, so no Meta API call can succeed
export https_proxy=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9
export no_proxy=api.fireworks.ai NO_PROXY=api.fireworks.ai
cd ${CW:?}
# phase 1: person review on Spark Open, then the case agent until it asks for the tape. analyze.py will not start
# without MODEL_API_KEY even when it calls no Meta model, so it gets a placeholder that is not a key.
MODEL_API_KEY=placeholder-not-a-key python3 analyze.py "${VIDEO:?}" sites/gate.json --out out/gate-open --budget 0
MODEL_API_KEY=placeholder-not-a-key python3 agent.py "$VIDEO" sites/gate.json --out out/gate-open   # stops at R1
# phase 2: serve the v6 judge, answer R1 (no Meta key at all now), re-read the letter, ALWAYS delete the deployment
ACCT=${FIREWORKS_ACCOUNT:?}; DEP=cw-judge-open-gate; MODEL=accounts/$ACCT/models/muse-starter-sl-judge-v6-main
export JUDGE_MODEL_URL=$FW JUDGE_MODEL="$MODEL#accounts/$ACCT/deployments/$DEP"
sdk() { env -u https_proxy -u HTTPS_PROXY -u http_proxy -u HTTP_PROXY ${SDK_PY:?} -c "from fireworks import Fireworks; c = Fireworks(account_id='$ACCT'); $1"; }
cleanup() {
  echo "deleting $DEP ($(date))"; sdk "c.deployments.delete('$DEP', ignore_checks=True)" 2>&1 | tail -2; sleep 30
  sdk "print('deployments now:', [(d.name, d.state) for d in c.deployments.list()])" 2>&1 | tail -1
}
trap cleanup EXIT INT TERM
echo "create $(date)"
sdk "c.deployments.create(base_model='$MODEL', deployment_id='$DEP', deployment_shape='accounts/fireworks/deploymentShapes/dkuwotf7', min_replica_count=1, max_replica_count=1, expire_time=__import__('datetime').datetime.now(__import__('datetime').timezone.utc) + __import__('datetime').timedelta(hours=1))" || exit 1
sdk "
import time
end = time.monotonic() + 15 * 60
while (d := c.deployments.get('$DEP')).state != 'READY':
    if d.state in ('FAILED', 'DELETING', 'DELETED') or time.monotonic() > end:
        raise SystemExit(f'{d.name} is {d.state}: {d.status}')
    time.sleep(20)
print('READY', d.name)" || exit 1
echo "ready $(date)"
python3 agent.py "$VIDEO" sites/gate.json --out out/gate-open --answer R1 "15 m" || echo "agent step failed"
echo "agent done $(date)"
python3 "${0:A:h}/judge_case.py" out/gate-open judge-reads.json || echo "judge reads failed"
echo "judge reads done $(date)"
