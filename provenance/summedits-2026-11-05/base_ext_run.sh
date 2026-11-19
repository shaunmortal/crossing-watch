#!/bin/zsh
# Serve BASE Muse Glimmer 30B once on 1 x H200 ($8/GPU-hour), ask the SummEdits replication rows in two arms
# (ask_base_ext.py), then ALWAYS delete the deployment (trap; 2-hour expire_time backstop). Pre-registered in GATES.md.
D=~/Desktop/META/build-scratch/glimmer-ft/ext
PY=~/Desktop/META/build-scratch/glimmer-ft/venv/bin/python
ACCT=<fireworks-account>; DEP=cw-glimmer-base-summedits
MODEL=accounts/fireworks/models/muse-glimmer-30b
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
python3 $D/ask_base_ext.py "$REF" cap256 $D/rep.jsonl $D/rep-base-cap256.jsonl 1200 || echo "cap256 failed"
python3 $D/ask_base_ext.py "$REF" cap8192 $D/rep.jsonl $D/rep-base-cap8192.jsonl 4500 || echo "cap8192 failed"
echo "asked $(date -u +%FT%TZ)"
