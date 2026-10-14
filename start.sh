#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
umask 077
if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != '-renew' ]; }; then
    echo 'Usage: ./start.sh [-renew]' >&2
    exit 2
fi
key_notice=$(.venv/bin/python server.py key "$@")
if [ -n "$key_notice" ]; then
    printf '%s\n' "$key_notice"
fi
gateway_host=${PI_AI_GATEWAY_HOST:-127.0.0.1}
gateway_port=${PI_AI_GATEWAY_PORT:-18765}
nohup .venv/bin/python -u server.py serve --host "$gateway_host" --port "$gateway_port" >> gateway.log 2>&1 &
gateway_pid=$!
pid_file="$HOME/.config/pi-ai-gateway/server.pid"
for _ in {1..100}; do
    if ! kill -0 "$gateway_pid" 2>/dev/null; then
        echo 'Gateway did not start; inspect gateway.log locally.' >&2
        exit 1
    fi
    if [ -f "$pid_file" ] && [ "$(cat "$pid_file")" = "$gateway_pid" ]; then
        echo "Gateway started: http://$gateway_host:$gateway_port (PID $gateway_pid)"
        exit 0
    fi
    sleep 0.1
done
echo 'Gateway startup not confirmed; inspect gateway.log locally.' >&2
exit 1
