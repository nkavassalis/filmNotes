#!/usr/bin/env bash
# Supervised server loop for filmNotes (the container has no init).
#
# Why a loop: a setsid'd server whose parent shell exits becomes an orphan
# (ppid=1) and has been observed to get killed on this box; a live parent
# that respawns it is the proven-surviving topology (rssgate, sparky).
# Launch detached:
#   cd /home/nick/filmNotes && setsid nohup scripts/serve-loop.sh >/dev/null 2>&1 &
# /etc/profile.d/zz-ensure-filmnotes.sh does this at every login.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
while true; do
  # maintenance flag: UI tests (or a human) own the port while this exists
  [ -e .no-serve ] && exit 0
  # adopt an existing listener instead of double-launching (e.g. an
  # orphaned server still holding the port after the loop was restarted)
  if ss -tln 2>/dev/null | grep -q ':8961 '; then
    echo "$(date '+%F %T') serve-loop: 8961 already served; waiting" >> filmnotes.log
    sleep 10
    continue
  fi
  .venv/bin/python run.py --host 0.0.0.0 --port 8961 >> filmnotes.log 2>&1
  echo "$(date '+%F %T') serve-loop: server exited rc=$?; restarting in 3s" >> filmnotes.log
  sleep 3
done
