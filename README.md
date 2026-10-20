# OAI Gateway

An unofficial, self-hosted HTTP gateway for using eligible ChatGPT plans from
trusted LAN applications. It runs on a Raspberry Pi or another Linux host,
completes the official open-source OAuth flow, and exposes a deliberately small
API.

> [!WARNING]
> This project is for personal use on a trusted private network. Do not expose
> it to the public Internet. Plain HTTP does not encrypt the local bearer key.

## What it provides

- Sign in with ChatGPT using dynamic client registration, PKCE, state, nonce,
  ID-token validation, and refresh-token rotation.
- `GET /health` for local status.
- `GET /v1/models` for the signed-in account's compact model catalog.
- `POST /v1/responses` for a synchronous `{model, output_text}` response.
- `POST /codex/v1/responses` for transparent Responses SSE and tool calls.
- A random local bearer key stored outside the repository with mode `0600`.
- Exact-origin CORS for browser applications on `/health`, `/v1/models`, and
  `/v1/responses`.

This is not a drop-in OpenAI-compatible server. It intentionally implements
only the endpoints above. The regular endpoint converts the required upstream
event stream into compact JSON; the Codex endpoint relays that stream unchanged.
All endpoints, including `/health`, require the local bearer key. The Codex
endpoint is intended for native clients and does not support browser CORS.

## Requirements

- Linux (the process lock uses `fcntl`)
- Python 3.9 or newer
- An eligible ChatGPT plan with permission to use it in open-source apps

The original deployment was tested on Raspberry Pi OS 12, ARMv7, and Python
3.11.

## Install

```bash
git clone https://github.com/vroby65/oai-gateway.git
cd oai-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On a memory-constrained Raspberry Pi with compatible system packages already
installed, the virtual environment may instead be created with
`python3 -m venv --system-site-packages .venv`.

## Configure the LAN listener

The safe default is `127.0.0.1:18765`. To accept connections from your private
LAN, set the host to an IPv4 address assigned to the server:

```bash
export PI_AI_GATEWAY_HOST=192.168.1.50
export PI_AI_GATEWAY_PORT=18765
```

The server rejects wildcard, public, hostname, and IPv6 bind values. It accepts
only loopback or RFC 1918 private IPv4 addresses.

For a browser client, provide a comma-separated list of exact origins. Localhost
and `127.0.0.1` origins are always accepted.

```bash
export PI_AI_GATEWAY_ORIGINS=https://username.github.io,http://192.168.1.20:8080
```

Keep these variables in the shell used to run `start.sh`.

## Sign in with ChatGPT

Run the login command on the gateway host:

```bash
.venv/bin/python server.py login
```

For a headless Raspberry Pi, first open an SSH tunnel from the computer running
your browser:

```bash
ssh -t -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:1455:127.0.0.1:1455 pi@PI_IP /bin/bash
```

Then run the login command in that SSH session and open the printed URL in your
local browser. The callback listener waits for up to ten minutes.

OAuth credentials are written atomically to
`~/.config/pi-ai-gateway/auth.json`. The file uses mode `0600` and its directory
uses mode `0700`. Authorization URLs can contain an ID-token hint; do not share
or log them.

## Start and stop

```bash
./start.sh
./stop.sh
```

On the first start, the gateway creates and displays its local bearer key once.
It is stored at `~/.config/pi-ai-gateway/api-key`, outside the repository. To
replace the key and display the new one, stop the server first and run:

```bash
./stop.sh
./start.sh -renew
```

There is no automatic startup, router configuration, public proxy, or Internet
exposure. The local log is `gateway.log`; it is ignored by Git.

## Call the gateway

Supply the local bearer key and a model slug returned by `/v1/models`:

```bash
curl --fail-with-body --silent --show-error \
  http://192.168.1.50:18765/v1/responses \
  -H 'Authorization: Bearer <LOCAL_GATEWAY_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"<MODEL_SLUG>","input":"Reply with exactly: gateway working"}'
```

The request body limit is 4 MiB on both Responses routes, allowing compact
Base64 image inputs. The gateway forwards Responses input content items without
logging them, forces `store: false` and `stream: true` upstream, and reports
success on `/v1/responses` only after `response.completed`. The Codex route
returns the upstream SSE stream and tool calls unchanged. Use the bearer key
only with trusted clients on the local machine or private network.

## Test

The offline suite never contacts OpenAI and uses only fake credentials:

```bash
.venv/bin/python -m unittest discover -v -s tests
```

After completing OAuth, a real end-to-end check can be run on the gateway host:

```bash
.venv/bin/python tests/live.py
```

Pass a different base URL or model slug as positional arguments when needed.

## Codex clients

Codex CLI clients can use `/codex/v1` as a custom Responses provider. Client
launchers are intentionally maintained outside this server project.

## Security model

- Tokens and the local gateway key stay under `~/.config/pi-ai-gateway/`.
- Secrets, logs, virtual environments, and Python caches are ignored by Git.
- OAuth callback paths and codes are not written to access logs.
- Token refresh is serialized so rotating refresh tokens are not raced.
- Browser origins are denied unless local or explicitly configured.
- The listener refuses non-private addresses, including `0.0.0.0`.
- Codex clients receive raw upstream events from `/codex/v1/responses`.

If OAuth credentials are exposed, disconnect the app in ChatGPT settings and
remove the local credential file before signing in again.

## OpenAI documentation

- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## License

[MIT](LICENSE)
