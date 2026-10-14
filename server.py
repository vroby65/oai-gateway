#!/usr/bin/env python3
"""Small personal ChatGPT-plan Responses gateway. Python 3.9+; pip install requests PyJWT cryptography."""
import argparse, base64, fcntl, hashlib, hmac, ipaddress, json, os, secrets, signal, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
import requests
import jwt
from jwt import PyJWKClient

LOCAL_API_KEY = None
DEFAULT_HOST = os.environ.get('PI_AI_GATEWAY_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('PI_AI_GATEWAY_PORT', '18765'))
ALLOWED_ORIGINS = frozenset(
    origin.strip().rstrip('/')
    for origin in os.environ.get('PI_AI_GATEWAY_ORIGINS', '').split(',')
    if origin.strip()
)
DATA = Path.home() / '.config' / 'pi-ai-gateway' / 'auth.json'
API_KEY_FILE = DATA.parent / 'api-key'
AUTH = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
TOKEN_URL = AUTH + '/api/accounts/oauth/token'
LOCK = threading.RLock()


def load():
    return json.loads(DATA.read_text()) if DATA.exists() else {}


def save(info):
    DATA.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA.parent, 0o700)
    tmp = DATA.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(info, f, indent=2)
    os.replace(tmp, DATA)


def prepare_api_key(renew=False):
    API_KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(API_KEY_FILE.parent, 0o700)
    if API_KEY_FILE.exists() and not renew:
        key = API_KEY_FILE.read_text().strip()
        if key:
            os.chmod(API_KEY_FILE, 0o600)
            return key
    key = secrets.token_urlsafe(48)
    tmp = API_KEY_FILE.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as key_file:
        key_file.write(key + '\n')
    os.replace(tmp, API_KEY_FILE)
    print('API key (shown once): ' + key, flush=True)
    return key


def token():
    with LOCK:
        info = load()
        if not info.get('access_token'):
            raise RuntimeError('Run: python3 server.py login')
        if 'chatgpt.tokens.use.direct' not in info.get('scopes', []):
            raise RuntimeError('ChatGPT plan permission missing; run login again')
        if time.time() < info.get('expires_at', 0) - 120:
            return info['access_token']
        if not info.get('refresh_token'):
            raise RuntimeError('OAuth refresh token missing; run login again')
        r = requests.post(TOKEN_URL, data={
            'grant_type': 'refresh_token', 'client_id': info['client_id'],
            'refresh_token': info['refresh_token'], 'resource': RESOURCE,
        }, timeout=25)
        r.raise_for_status()
        new = r.json()
        info.update({k: new[k] for k in ('access_token', 'refresh_token', 'id_token') if k in new})
        info['expires_at'] = time.time() + int(new.get('expires_in', 3600))
        if 'scope' in new:
            info['scopes'] = new['scope'].split()
        save(info)
        if 'chatgpt.tokens.use.direct' not in info.get('scopes', []):
            raise RuntimeError('ChatGPT plan permission missing')
        return info['access_token']


def login():
    with LOCK:
        old = load()
        host_id = old.get('host_id') or 'urn:uuid:' + str(uuid.uuid4())
        save(dict(old, host_id=host_id))
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    redirect = 'http://127.0.0.1:1455/auth/callback'
    params = {
        'client_id': old.get('client_id', 'dynamic_agent_client'),
        'ext_agent_host_id': host_id, 'response_type': 'code', 'redirect_uri': redirect,
        'scope': 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',
        'resource': RESOURCE, 'state': state, 'nonce': nonce,
        'code_challenge_method': 'S256', 'code_challenge': challenge,
    }
    if not old.get('client_id'):
        params['agent_name_hint'] = 'Pi AI Gateway'
    elif old.get('id_token'):
        params['id_token_hint'] = old['id_token']
    captured = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            p = urlparse(self.path)
            if p.path != '/auth/callback':
                self.send_error(404); return
            q = parse_qs(p.query)
            if q.get('state', [''])[0] != state:
                self.send_error(400, 'Invalid OAuth state'); return
            captured.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers(); self.wfile.write(b'Authorization received. You can close this tab.')
        def log_message(self, *args):
            pass  # Never log OAuth callback URL/code.

    url = AUTH + '/api/accounts/authorize?' + urlencode(params)
    srv = HTTPServer(('127.0.0.1', 1455), Callback)
    print('\nOpen this URL in your desktop browser:\n' + url + '\n', flush=True)
    print('If running on a headless Pi, use SSH port forwarding: ssh -L 1455:127.0.0.1:1455 pi@PI_IP', flush=True)
    srv.timeout = 1
    try:
        deadline = time.monotonic() + 600
        while not captured and time.monotonic() < deadline:
            srv.handle_request()
    finally:
        srv.server_close()
    if not captured:
        raise RuntimeError('Login timed out')
    if captured.get('error'):
        raise RuntimeError('OAuth denied: ' + captured['error'])
    client_id = captured.get('client_id', old.get('client_id'))
    if not client_id or client_id == 'dynamic_agent_client':
        raise RuntimeError('Missing issued OAuth client ID')
    if old.get('client_id') and old['client_id'] != client_id:
        raise RuntimeError('Unexpected changed client ID')
    r = requests.post(TOKEN_URL, data={
        'grant_type': 'authorization_code', 'client_id': client_id,
        'code': captured['code'], 'code_verifier': verifier,
        'redirect_uri': redirect, 'resource': RESOURCE,
    }, timeout=30)
    r.raise_for_status()
    d = r.json()
    jwks = PyJWKClient(AUTH + '/.well-known/jwks.json')
    key = jwks.get_signing_key_from_jwt(d['id_token'])
    identity = jwt.decode(d['id_token'], key.key, algorithms=['RS256'], audience=client_id,
                          issuer=AUTH, options={'require': ['exp', 'iss', 'aud', 'sub']})
    if identity.get('nonce') != nonce:
        raise RuntimeError('Invalid OIDC nonce')
    if old.get('subject') and old['subject'] != identity['sub']:
        raise RuntimeError('Account changed; remove stored auth file only if intentional')
    scopes = d.get('scope', '').split()
    if 'chatgpt.tokens.use.direct' not in scopes:
        raise RuntimeError('Permission chatgpt.tokens.use.direct not granted')
    save(dict(host_id=host_id, client_id=client_id, subject=identity['sub'],
              email=identity.get('email'), id_token=d['id_token'],
              access_token=d['access_token'], refresh_token=d['refresh_token'],
              scopes=scopes, expires_at=time.time() + int(d.get('expires_in', 3600))))
    print('Login successful. Start the server: python3 server.py serve')


def browser_origin(origin):
    if origin in ALLOWED_ORIGINS:
        return True
    parsed = urlparse(origin)
    return (parsed.scheme in ('http', 'https') and
            parsed.hostname in ('127.0.0.1', 'localhost') and
            not parsed.username and not parsed.password and
            not parsed.path and not parsed.query and not parsed.fragment)


def bind_host_allowed(host):
    if host == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    private_v4 = (
        ipaddress.ip_network('10.0.0.0/8'),
        ipaddress.ip_network('172.16.0.0/12'),
        ipaddress.ip_network('192.168.0.0/16'),
    )
    return isinstance(address, ipaddress.IPv4Address) and (
        address.is_loopback or any(address in network for network in private_v4)
    )


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        origin = self.headers.get('Origin', '')
        if browser_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self):
        origin = self.headers.get('Origin', '')
        if not browser_origin(origin):
            self.respond(403, {'error': 'origin_not_allowed'}); return
        if self.path not in ('/health', '/v1/models', '/v1/responses'):
            self.respond(404, {'error': 'not_found'}); return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        if self.headers.get('Access-Control-Request-Private-Network') == 'true':
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, fmt, *args):
        # No request paths or credentials in access logs.
        pass

    def respond(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        origin = self.headers.get('Origin')
        if origin is not None and not browser_origin(origin):
            return False
        sent = self.headers.get('Authorization', '')
        if not LOCAL_API_KEY:
            return False
        expected = 'Bearer ' + LOCAL_API_KEY
        return hmac.compare_digest(sent, expected)

    def relay_codex_response(self, body):
        with requests.post(RESOURCE + '/responses', json=body,
                           headers={'Authorization': 'Bearer ' + token()},
                           stream=True, timeout=(15, 240)) as upstream:
            if upstream.status_code != 200:
                content = upstream.content[:64 * 1024]
                self.send_response(upstream.status_code)
                self.send_header('Content-Type',
                                 upstream.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(content)
                return
            self.send_response(200)
            self.send_header('Content-Type',
                             upstream.headers.get('Content-Type', 'text/event-stream'))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                for chunk in upstream.iter_content(chunk_size=8192):
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, requests.RequestException):
                pass
            self.close_connection = True

    def do_GET(self):
        if not self.authorized():
            self.respond(401, {'error': 'unauthorized'}); return
        if self.path == '/health':
            self.respond(200, {'ok': True, 'account_configured': bool(load().get('refresh_token'))}); return
        if self.path == '/v1/models':
            try:
                r = requests.get(RESOURCE + '/models', headers={'Authorization': 'Bearer ' + token()}, timeout=30)
                data = r.json()
                if r.status_code == 200:
                    data = {'models': [{k: model[k] for k in ('slug', 'display_name', 'visibility') if k in model}
                                       for model in data['models']]}
                self.respond(r.status_code, data)
            except Exception as e:
                self.respond(502, {'error': str(e)})
            return
        self.respond(404, {'error': 'not_found'})

    def do_POST(self):
        if not self.authorized():
            self.respond(401, {'error': 'unauthorized'}); return
        if self.path not in ('/v1/responses', '/codex/v1/responses'):
            self.respond(404, {'error': 'not_found'}); return
        try:
            n = int(self.headers.get('Content-Length', '0'))
            limit = 4 * 1024 * 1024 if self.path == '/codex/v1/responses' else 512 * 1024
            if n < 1 or n > limit:
                self.respond(413, {'error': 'bad_request_size'}); return
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict) or not body.get('model') or 'input' not in body:
                self.respond(400, {'error': 'model and input required'}); return
            if isinstance(body['input'], str):
                body['input'] = [{'role': 'user', 'content': body['input']}]
            if not isinstance(body['input'], list):
                self.respond(400, {'error': 'input must be text or an array'}); return
            body['store'] = False
            body['stream'] = True
            if self.path == '/codex/v1/responses':
                self.relay_codex_response(body)
                return
            with requests.post(RESOURCE + '/responses', json=body,
                               headers={'Authorization': 'Bearer ' + token()},
                               stream=True, timeout=(15, 240)) as r:
                if r.status_code != 200:
                    self.respond(r.status_code, {'error': r.text[:3000]}); return
                # Convert mandatory upstream SSE into a compact synchronous JSON reply.
                r.encoding = 'utf-8'
                chunks, completed, failed = [], False, None
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith('data: '):
                        continue
                    payload = line[6:]
                    if payload == '[DONE]':
                        continue
                    event = json.loads(payload)
                    if event.get('type') == 'response.output_text.delta':
                        chunks.append(event.get('delta', ''))
                    elif event.get('type') == 'response.completed':
                        completed = True
                    elif event.get('type') in ('response.failed', 'response.incomplete', 'error'):
                        failed = event
                if not completed or failed is not None:
                    self.respond(502, {'error': 'upstream_not_completed', 'details': failed}); return
                self.respond(200, {'model': body['model'], 'output_text': ''.join(chunks)})
        except (ValueError, json.JSONDecodeError) as e:
            self.respond(400, {'error': str(e)})
        except (requests.RequestException, RuntimeError) as e:
            self.respond(502, {'error': str(e)})


def main():
    global LOCAL_API_KEY
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['login', 'serve', 'key'])
    parser.add_argument('-renew', action='store_true', help='replace the private API key')
    parser.add_argument('--host', default=DEFAULT_HOST, help='private LAN IPv4 address or loopback')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if args.renew and args.command == 'login':
        parser.error('-renew is only valid when starting the server')
    DATA.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA.parent, 0o700)
    lock_fd = os.open(DATA.parent / 'runtime.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Gateway or OAuth login already running; stop it first')
    if args.command == 'login':
        login()
    elif args.command == 'key':
        prepare_api_key(args.renew)
    else:
        LOCAL_API_KEY = prepare_api_key(args.renew)
        if not bind_host_allowed(args.host):
            parser.error('Only a private LAN IPv4 address or loopback is allowed')
        s = ThreadingHTTPServer((args.host, args.port), Handler)
        pid_path = DATA.parent / 'server.pid'
        fd = os.open(pid_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as pid_file:
            pid_file.write(str(os.getpid()))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f'Gateway listening on http://{args.host}:{args.port}')
        try:
            s.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            s.server_close()
            pid_path.unlink(missing_ok=True)

if __name__ == '__main__':
    main()
