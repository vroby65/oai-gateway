# Verification

The offline test suite covers:

- atomic credential writes and Unix permissions;
- local gateway-key creation and rotation;
- serialized OAuth token refresh and rotating refresh-token storage;
- authenticated HTTP requests and input validation;
- required streaming behavior through `response.completed`;
- transparent Responses SSE and tool-call relay for Codex CLI;
- interrupted and failed upstream streams;
- exact-origin CORS and private-network preflight responses;
- compact model-catalog responses;
- loopback and RFC 1918 listener restrictions;

Run it with:

```bash
.venv/bin/python -m unittest discover -v -s tests
```

`tests/live.py` performs the separate live verification after manual OAuth approval.
It checks health, retrieves the account-specific model catalog, selects a model,
and requires a non-empty completed response. Live verification consumes plan
usage and cannot be replaced by the offline simulations.
