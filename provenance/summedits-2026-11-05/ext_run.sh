#!/bin/zsh
# Serve the v6 adapter once on 1 x H200 (BF16, $8/GPU-hour), ask it every SummEdits test row (ask_ext.py), then
# ALWAYS delete the deployment (trap; 2-hour expire_time as the server-side backstop). Pre-registered in GATES.md.
D=~/Desktop/META/build-scratch/glimmer-ft/ext
PY=~/Desktop/META/build-scratch/glimmer-ft/venv/bin/python
ACCT=<fireworks-account>; DEP=cw-judge-summedits
MODEL=accounts/$ACCT/models/muse-starter-sl-judge-v6-main
SHAPE=accounts/fireworks/deploymentShapes/dkuwotf7
REF=$MODEL#accounts/$ACCT/deployments/$DEP
set -a; . ~/Desktop/crossing-watch/.env; set +a
sdk() { $PY -c "from fireworks import Fireworks; c = Fireworks(account_id='$ACCT'); $1"; }
cleanup() {
  echo "deleting $DEP ($(date -u +%FT%TZ))"
  sdk "c.deployments.delete('$DEP', ignore_checks=True)" 2>&1 | tail -2
  sleep 25
  sdk "print('deployments listed now:', [(d.name, d.state) for d in c.deployments.list()])" 2>&1 | tail -1
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
python3 $D/ask_ext.py tuned "$REF" $D/dev.jsonl $D/dev-tuned.jsonl || echo "dev failed"
python3 $D/ask_ext.py tuned "$REF" $D/test.jsonl $D/test-tuned.jsonl || echo "test failed"
python3 $D/ask_ext.py tuned "$REF" $D/test.jsonl $D/test-tuned.jsonl || echo "retry failed"
echo "asked $(date -u +%FT%TZ)"
