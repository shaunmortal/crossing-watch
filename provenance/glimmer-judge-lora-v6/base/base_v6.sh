#!/bin/zsh
# Serve BASE Muse Glimmer 30B (no LoRA) once on 1 x H200 (BF16; $8/GPU-hour, billed per second), replay the v6
# holdout prompts through it with a long reply cap (replay_base.py), then ALWAYS delete it. The pre-registration
# for this run is in GATES.md ("Base Glimmer against the tuned judge"), committed before the deployment is created.
# Needs a payment method on the Fireworks account. Run only with Ayush's approval for this spend.
D=~/Desktop/META/build-scratch/glimmer-ft/deploy
PY=~/Desktop/META/build-scratch/glimmer-ft/venv/bin/python
ACCT=<fireworks-account>; DEP=cw-glimmer-base-judge
MODEL=accounts/fireworks/models/muse-glimmer-30b
SHAPE=accounts/fireworks/deploymentShapes/dkuwotf7   # "Muse Glimmer 30B BF16 1x H200"
REF=$MODEL#accounts/$ACCT/deployments/$DEP
MAX_TOKENS=${MAX_TOKENS:-8192}; WALL=${WALL:-4200}
set -a; . ~/Desktop/crossing-watch/.env; set +a
sdk() { $PY -c "from fireworks import Fireworks; c = Fireworks(account_id='$ACCT'); $1"; }
cleanup() {
  echo "deleting $DEP ($(date -u +%FT%TZ))"
  sdk "c.deployments.delete('$DEP', ignore_checks=True)" 2>&1 | tail -2
  sleep 25
  sdk "print('deployments listed now:', [(d.name, d.state) for d in c.deployments.list()])" 2>&1 | tail -1
  echo "deleted-check done ($(date -u +%FT%TZ))"
}
trap cleanup EXIT
echo "create $(date -u +%FT%TZ)"
sdk "c.deployments.create(base_model='$MODEL', deployment_id='$DEP', deployment_shape='$SHAPE', min_replica_count=1, max_replica_count=1, expire_time=__import__('datetime').datetime.now(__import__('datetime').timezone.utc) + __import__('datetime').timedelta(hours=2))" || exit 1
sdk "
import time
end = time.monotonic() + 45 * 60
while (d := c.deployments.get('$DEP')).state != 'READY':
    if d.state in ('FAILED', 'DELETING', 'DELETED') or time.monotonic() > end:
        raise SystemExit(f'{d.name} is {d.state}: {d.status}')
    time.sleep(30)
print('READY', d.name)" || exit 1
echo "ready $(date -u +%FT%TZ)"
python3 $D/replay_base.py "$REF" $D/base-v6.jsonl $MAX_TOKENS $WALL || echo "replay failed"
echo "replay done $(date -u +%FT%TZ)"
