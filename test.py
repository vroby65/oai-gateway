#!/usr/bin/env python3
"""Usage: python3 test.py [http://LAN_IP:18765] [model_slug]"""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path

API_KEY_FILE = Path.home() / '.config' / 'pi-ai-gateway' / 'api-key'
try:
    API_KEY = API_KEY_FILE.read_text().strip()
except FileNotFoundError:
    sys.exit('API key missing; start the gateway first.')
if not API_KEY:
    sys.exit('API key file is empty; start the gateway with -renew.')
default_base = f"http://{os.environ.get('PI_AI_GATEWAY_HOST', '127.0.0.1')}:{os.environ.get('PI_AI_GATEWAY_PORT', '18765')}"
BASE = (sys.argv[1] if len(sys.argv) > 1 else default_base).rstrip('/')
MODEL = sys.argv[2] if len(sys.argv) > 2 else None

def request(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={
        'Authorization': 'Bearer ' + API_KEY,
        'Content-Type': 'application/json'
    })
    try:
        with urllib.request.urlopen(req, timeout=270) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        print('HTTP error', err.code, err.read().decode()[:3000]); sys.exit(1)

print('Health:', request('/health'))
models = request('/v1/models')
visible = [m['slug'] for m in models.get('models', []) if m.get('slug') and m.get('visibility') == 'list']
print('Models:', ', '.join(visible[:15]) or '(no visible models; inspect server response)')
chosen = MODEL or (visible[0] if visible else None)
if not chosen:
    sys.exit('No model found. Supply model slug as second argument.')
print('Testing model:', chosen)
reply = request('/v1/responses', {'model': chosen, 'input': 'Reply with exactly: gateway working'})
if not isinstance(reply.get('output_text'), str) or not reply['output_text'].strip():
    sys.exit('FAIL: no text response received from the model')
print('Reply:', reply['output_text'])
print('PASS: completed real OpenAI inference')
