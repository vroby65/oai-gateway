"""Offline regression tests; no OpenAI requests or real credentials."""
import json
import io
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import server


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'auth' / 'auth.json'
        self.api_key_file = self.data.parent / 'api-key'
        self.data_patch = patch.object(server, 'DATA', self.data)
        self.api_key_patch = patch.object(server, 'API_KEY_FILE', self.api_key_file,
                                          create=True)
        self.data_patch.start()
        self.api_key_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(self.api_key_patch.stop)

    def test_api_key_is_created_displayed_once_and_private(self):
        output = io.StringIO()
        with patch.object(server.secrets, 'token_urlsafe', return_value='first-key') as generate, \
             redirect_stdout(output):
            self.assertEqual(server.prepare_api_key(), 'first-key')
            self.assertEqual(server.prepare_api_key(), 'first-key')
        generate.assert_called_once_with(48)
        self.assertEqual(output.getvalue(), 'API key (shown once): first-key\n')
        self.assertEqual(self.api_key_file.read_text(), 'first-key\n')
        self.assertEqual(self.api_key_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.api_key_file.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.api_key_file.with_suffix('.tmp').exists())

    def test_api_key_renew_replaces_and_displays_it(self):
        self.api_key_file.parent.mkdir(mode=0o700)
        self.api_key_file.write_text('old-key\n')
        output = io.StringIO()
        with patch.object(server.secrets, 'token_urlsafe', return_value='new-key'), \
             redirect_stdout(output):
            self.assertEqual(server.prepare_api_key(renew=True), 'new-key')
        self.assertEqual(output.getvalue(), 'API key (shown once): new-key\n')
        self.assertEqual(self.api_key_file.read_text(), 'new-key\n')
        self.assertEqual(self.api_key_file.stat().st_mode & 0o777, 0o600)

    def credentials(self, expires_at=0):
        return dict(client_id='test-client', access_token='old-access',
                    refresh_token='old-refresh', expires_at=expires_at,
                    scopes=['chatgpt.tokens.use.direct'])

    def test_atomic_save_enforces_private_permissions(self):
        self.data.parent.mkdir()
        self.data.with_suffix('.tmp').touch(mode=0o644)
        server.save(self.credentials())
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.data.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.data.with_suffix('.tmp').exists())

    def test_bind_host_is_limited_to_loopback_or_private_ipv4(self):
        for host in ('localhost', '127.0.0.1', '10.0.0.2', '172.16.0.2', '192.168.1.2'):
            self.assertTrue(server.bind_host_allowed(host), host)
        for host in ('0.0.0.0', '8.8.8.8', 'gateway.example.com', '::1'):
            self.assertFalse(server.bind_host_allowed(host), host)

    def test_refresh_is_serialized_and_rotates_credentials(self):
        server.save(self.credentials())
        reply = Mock()
        reply.json.return_value = dict(access_token='new-access',
                                       refresh_token='new-refresh', expires_in=3600,
                                       scope='chatgpt.tokens.use.direct offline_access')
        result = []
        with patch.object(server.requests, 'post', return_value=reply) as post:
            threads = [threading.Thread(target=lambda: result.append(server.token()))
                       for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(result, ['new-access'] * 4)
        post.assert_called_once()
        grant = post.call_args.kwargs['data']
        self.assertEqual(grant['grant_type'], 'refresh_token')
        self.assertEqual(grant['resource'], server.RESOURCE)
        self.assertNotIn('scope', grant)
        self.assertEqual(server.load()['refresh_token'], 'new-refresh')

    def test_http_auth_input_and_stream_completion(self):
        key = 'offline-test-key'
        captured = []
        events = [{'type': 'response.output_text.delta', 'delta': 'gateway working'},
                  {'type': 'response.completed', 'response': {'status': 'completed'}}]
        upstream = Mock()
        upstream.status_code = 200
        upstream.__enter__ = Mock(return_value=upstream)
        upstream.__exit__ = Mock(return_value=False)
        upstream.iter_lines.side_effect = lambda **kw: iter(
            'data: ' + json.dumps(event) for event in events)

        def post(*args, **kwargs):
            captured.append(kwargs['json'])
            return upstream

        with patch.object(server, 'LOCAL_API_KEY', key), \
             patch.object(server, 'token', return_value='offline-access'), \
             patch.object(server.requests, 'post', side_effect=post):
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{http.server_port}'
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def request(path, body=None, authorized=True):
                headers = {'Authorization': 'Bearer ' + (key if authorized else 'wrong')}
                data = json.dumps(body).encode() if body is not None else None
                req = urllib.request.Request(base + path, data=data, headers=headers)
                try:
                    with opener.open(req, timeout=5) as response:
                        return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    return error.code, json.load(error)

            try:
                self.assertEqual(request('/health', authorized=False)[0], 401)
                self.assertEqual(request('/health')[1],
                                 {'ok': True, 'account_configured': False})
                body = {'model': 'test-model', 'input': 'Hello'}
                status, reply = request('/v1/responses', body)
                self.assertEqual(status, 200)
                self.assertEqual(reply['output_text'], 'gateway working')
                self.assertEqual(captured[0]['input'], [{'role': 'user', 'content': 'Hello'}])
                self.assertIs(captured[0]['store'], False)
                self.assertIs(captured[0]['stream'], True)
                events[:] = [{'type': 'response.output_text.delta', 'delta': 'partial'}]
                self.assertEqual(request('/v1/responses', body)[0], 502)
                events[:] = [{'type': 'response.completed'}, {'type': 'response.failed'}]
                self.assertEqual(request('/v1/responses', body)[0], 502)
            finally:
                http.shutdown()
                http.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
