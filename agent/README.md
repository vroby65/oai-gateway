# OAI Gateway maintenance notes

This is a small Python adapter for personal ChatGPT-plan requests. `server.py`
handles OAuth and HTTP, `tests/live.py` performs a real end-to-end check, and
the other modules in `tests/` use simulations only. `start.sh` and `stop.sh`
provide manual process control.

Preserve these constraints:

- Bind only to loopback or an RFC 1918 private IPv4 address.
- Keep the local bearer key in `~/.config/pi-ai-gateway/api-key` with mode
  `0600`, inside a `0700` directory.
- Never write OAuth tokens, the local key, or authorization URLs to source,
  logs, tests, or fixtures.
- Do not add automatic startup, public proxies, router configuration, or public
  Internet exposure.
- Keep browser origins local or explicitly configured through
  `PI_AI_GATEWAY_ORIGINS`.
- Preserve raw SSE events and tool calls on `/codex/v1/responses`.

OAuth uses PKCE, state, nonce, signed ID-token validation, and the issued client
ID. Credentials live in `~/.config/pi-ai-gateway/auth.json`. Writes are atomic;
the process lock serializes login/server operation, while the thread lock
serializes rotating refresh tokens. Only `response.completed` without a failure
event confirms inference success.

Verify changes with:

```bash
.venv/bin/python -m unittest discover -v -s tests
```

After manual authorization, the optional real check is
`.venv/bin/python tests/live.py`. Simulations do not prove account eligibility,
network access, or real refresh behavior. Update this file and `README.md` when
commands, security boundaries, or credential handling change.
