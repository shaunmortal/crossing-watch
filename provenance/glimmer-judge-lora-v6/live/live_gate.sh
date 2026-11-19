#!/bin/zsh
# Serve the v6 adapter once on 1 x H200 (BF16, live merge; $8/GPU-hour, billed per second), have it judge our real
# gate letter 6 times (judge_gate.py), then ALWAYS delete it.
# Needs a payment method on the Fireworks account. Run only with Ayush's approval for this spend.
CW=$(git rev-parse --show-toplevel)
D=${CW_DEPLOY_DIR:?set CW_DEPLOY_DIR to a scratch folder}
PY=${CW_PYTHON:-python3}
ACCT=${FIREWORKS_ACCOUNT:?set FIREWORKS_ACCOUNT}; DEP=cw-judge-gate
MODEL=accounts/$ACCT/models/muse-starter-sl-judge-v6-main
SHAPE=accounts/fireworks/deploymentShapes/dkuwotf7
REF=$MODEL#accounts/$ACCT/deployments/$DEP  # live merge: full model path # full deployment path
set -a; . "$CW/.env"; set +a
sdk() { $PY -c "from fireworks import Fireworks; c = Fireworks(account_id='$ACCT'); $1"; }
cleanup() {
  echo "deleting $DEP ($(date))"
  sdk "c.deployments.delete('$DEP', ignore_checks=True)" 2>&1 | tail -2
  sleep 20
  sdk "print([(d.name, d.state) for d in c.deployments.list()])" 2>&1 | tail -1
}
trap cleanup EXIT
echo "create $(date)"
sdk "c.deployments.create(base_model='$MODEL', deployment_id='$DEP', deployment_shape='$SHAPE', min_replica_count=1, max_replica_count=1, expire_time=__import__('datetime').datetime.now(__import__('datetime').timezone.utc) + __import__('datetime').timedelta(hours=2))" || exit 1  # expire_time: auto-deletes even if this script dies
sdk "
import time
end = time.monotonic() + 45 * 60
while (d := c.deployments.get('$DEP')).state != 'READY':
    if d.state in ('FAILED', 'DELETING', 'DELETED') or time.monotonic() > end:
        raise SystemExit(f'{d.name} is {d.state}: {d.status}')
    time.sleep(30)
print('READY', d.name)" || exit 1
echo "ready $(date)"
python3 $D/judge_gate.py "$REF" $D/gate-judge.json || echo "gate judge failed"
echo "gate done $(date)"
