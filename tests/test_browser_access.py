import unittest,threading,tempfile
from pathlib import Path
from http.client import HTTPConnection
from unittest.mock import patch,Mock
import server
class BrowserTests(unittest.TestCase):
 def test_browser_origins_and_preflight(self):
  with tempfile.TemporaryDirectory() as temp, patch.object(server,'DATA',Path(temp)/'auth.json'),patch.object(server,'LOCAL_API_KEY','fake-browser-key'),patch.object(server,'ALLOWED_ORIGINS',frozenset({'https://app.example'})):
   http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
   worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
   try:
    for origin,expected in [('https://app.example',204),('http://127.0.0.1:8013',204),('https://untrusted.example',403),('null',403)]:
     c=HTTPConnection('127.0.0.1',http.server_port)
     c.request('OPTIONS','/v1/responses',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type','Access-Control-Request-Private-Network':'true'})
     r=c.getresponse();self.assertEqual(r.status,expected)
     self.assertEqual(r.getheader('Access-Control-Allow-Origin'),origin if expected==204 else None)
     if expected==204:self.assertEqual(r.getheader('Access-Control-Allow-Private-Network'),'true')
     r.read();c.close()
    for origin,expected in [('https://app.example',200),('https://untrusted.example',401)]:
     c=HTTPConnection('127.0.0.1',http.server_port)
     c.request('GET','/health',headers={'Origin':origin,'Authorization':'Bearer fake-browser-key'})
     r=c.getresponse();self.assertEqual(r.status,expected)
     self.assertEqual(r.getheader('Access-Control-Allow-Origin'),origin if expected==200 else None)
     r.read();c.close()
   finally:http.shutdown();http.server_close();worker.join()
 def test_cad_conversation_budget(self):
  import json
  reply=Mock();reply.status_code=200
  reply.__enter__=Mock(return_value=reply);reply.__exit__=Mock(return_value=False)
  reply.iter_lines.side_effect=lambda **kwargs:iter(['data: '+json.dumps({'type':'response.output_text.delta','delta':'test reply'}),'data: '+json.dumps({'type':'response.completed'})])
  self.assertEqual(server.REGULAR_REQUEST_LIMIT,4*1024*1024)
  with patch.object(server,'LOCAL_API_KEY','fake-browser-key'),patch.object(server,'token',return_value='fake-access'),patch.object(server.requests,'post',return_value=reply):
   http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
   worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
   try:
    for size,expected in [(70*1024,200),(3*1024*1024,200)]:
     c=HTTPConnection('127.0.0.1',http.server_port)
     c.request('POST','/v1/responses',body=json.dumps({'model':'fake-model','input':'x'*size}),headers={'Authorization':'Bearer fake-browser-key','Content-Type':'application/json'})
     r=c.getresponse();self.assertEqual(r.status,expected);r.read();c.close()
    with patch.object(server,'REGULAR_REQUEST_LIMIT',512*1024):
     c=HTTPConnection('127.0.0.1',http.server_port)
     c.request('POST','/v1/responses',body=json.dumps({'model':'fake-model','input':'x'*(513*1024)}),headers={'Authorization':'Bearer fake-browser-key','Content-Type':'application/json'})
     r=c.getresponse();self.assertEqual(r.status,413);r.read();c.close()
   finally:http.shutdown();http.server_close();worker.join()
 def test_compact_model_catalog(self):
  import json
  upstream={'models':[{'slug':'test-model','display_name':'Test model','visibility':'list','internal_metadata':'x'*660000}]}
  reply=Mock();reply.status_code=200;reply.json.return_value=upstream
  with patch.object(server,'LOCAL_API_KEY','fake-browser-key'),patch.object(server,'token',return_value='fake-access'),patch.object(server.requests,'get',return_value=reply),patch.object(server,'ALLOWED_ORIGINS',frozenset({'https://app.example'})):
   http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
   worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
   try:
    c=HTTPConnection('127.0.0.1',http.server_port)
    c.request('GET','/v1/models',headers={'Authorization':'Bearer fake-browser-key','Origin':'https://app.example'})
    r=c.getresponse();body=r.read()
    self.assertEqual(r.status,200)
    self.assertLess(len(body),512*1024)
    self.assertEqual(json.loads(body),{'models':[{'slug':'test-model','display_name':'Test model','visibility':'list'}]})
    self.assertEqual(r.getheader('Access-Control-Allow-Origin'),'https://app.example')
    c.close()
   finally:http.shutdown();http.server_close();worker.join()
if __name__=='__main__':unittest.main()
