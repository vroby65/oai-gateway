#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
.venv/bin/python - <<'PY'
import os, signal, time
from pathlib import Path
pid_file = Path.home() / '.config/pi-ai-gateway/server.pid'
if not pid_file.exists():
    print('Gateway is stopped.')
    raise SystemExit(0)
pid = int(pid_file.read_text())
proc = Path('/proc') / str(pid)
if not proc.exists():
    pid_file.unlink()
    print('Gateway is stopped; removed stale PID file.')
    raise SystemExit(0)
args = (proc / 'cmdline').read_bytes().split(b'\0')
command = args[1:]
if command and command[0] == b'-u':
    command = command[1:]
if (proc / 'cwd').resolve() != Path.cwd() or command[:2] != [b'server.py', b'serve']:
    raise SystemExit('PID belongs to another process; no signal sent.')
os.kill(pid, signal.SIGTERM)
for _ in range(50):
    if not pid_file.exists():
        print('Gateway stopped.')
        break
    time.sleep(0.1)
else:
    raise SystemExit('Gateway is draining active requests; check again shortly.')
PY
