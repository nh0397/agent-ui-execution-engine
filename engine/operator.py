"""A loopback operator view forwarding user commands to the existing browser session."""
import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HTML = r'''<!doctype html><html><head><meta charset="utf-8"><title>Live session operator</title>
<style>body{font:16px system-ui;background:#f0f3f6;color:#183149;margin:24px}header{display:flex;gap:12px;align-items:center;flex-wrap:wrap}button,input{font:inherit;padding:10px;margin:4px}button{cursor:pointer}img{max-width:100%;border:2px solid #347b69;background:white;cursor:crosshair}#status{padding:12px;background:#e1eee8}small{display:block;margin:8px 0}</style></head><body>
<h1>Live session operator</h1><p id="status">Human control — the image below is the automation's existing browser session.</p>
<header><button onclick="send({kind:'resume'})">Resume automation</button><button onclick="send({kind:'abort'})">Abort run</button>
<button onclick="send({kind:'key',key:'Tab'})">Tab</button><button onclick="send({kind:'key',key:'Enter'})">Enter</button>
<button onclick="send({kind:'scroll',delta:500})">Scroll down</button><button onclick="send({kind:'scroll',delta:-500})">Scroll up</button>
<input id="entry" type="password" placeholder="Text for focused field" autocomplete="off"><button onclick="typeText()">Type into field</button></header>
<small>Click controls directly in the live image. For text entry, click a field first. Review the result, then resume automation.</small>
<img id="screen" alt="Live browser session"><script>
const token='__TOKEN__';const image=document.getElementById('screen');let pending=false;
async function send(command){const r=await fetch('/command',{method:'POST',headers:{'Content-Type':'application/json','X-Operator-Token':token},body:JSON.stringify(command)});if(!r.ok){document.getElementById('status').textContent='Command rejected';return}if(['resume','abort'].includes(command.kind))document.getElementById('status').textContent=command.kind+' requested — check the run result in Codex.';}
function typeText(){const input=document.getElementById('entry');send({kind:'type',text:input.value});input.value='';}
image.onclick=e=>{const r=image.getBoundingClientRect();send({kind:'click',x:(e.clientX-r.left)*image.naturalWidth/r.width,y:(e.clientY-r.top)*image.naturalHeight/r.height})};
async function refresh(){if(pending)return;pending=true;try{const r=await fetch('/frame',{cache:'no-store'});if(r.ok){const u=URL.createObjectURL(await r.blob());const old=image.src;image.src=u;if(old.startsWith('blob:'))URL.revokeObjectURL(old)}}catch(e){}finally{pending=false}}
setInterval(refresh,600);refresh();
</script></body></html>'''


class OperatorBridge:
    def __init__(self, port=8766):
        self.commands = queue.Queue(maxsize=32)
        self.frame = b""
        self.token = secrets.token_urlsafe(32)
        bridge = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, status, content, kind):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(content)

            def do_GET(self):
                if self.headers.get("Host") != f"127.0.0.1:{port}":
                    return self.respond(403, b"Forbidden", "text/plain")
                if self.path == "/":
                    return self.respond(200, HTML.replace("__TOKEN__", bridge.token).encode(), "text/html; charset=utf-8")
                if self.path == "/frame":
                    return self.respond(200 if bridge.frame else 204, bridge.frame, "image/png")
                self.respond(404, b"Not found", "text/plain")

            def do_POST(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 1 or size > 4096:
                        raise ValueError()
                    self.connection.settimeout(5)
                    payload = self.rfile.read(size)
                except (ValueError, TimeoutError):
                    return self.respond(400, b"Invalid request", "text/plain")
                if self.path != "/command" or self.headers.get("Host") != f"127.0.0.1:{port}" or self.headers.get("Origin") != f"http://127.0.0.1:{port}" or not secrets.compare_digest(self.headers.get("X-Operator-Token", ""), bridge.token):
                    return self.respond(403, b"Forbidden", "text/plain")
                try:
                    command = json.loads(payload)
                    if command.get("kind") not in {"click", "type", "key", "scroll", "resume", "abort"}:
                        raise ValueError()
                    bridge.commands.put_nowait(command)
                except (ValueError, AttributeError, queue.Full):
                    return self.respond(400, b"Invalid command", "text/plain")
                self.respond(202, b"Accepted", "text/plain")
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        port = self.server.server_address[1]
        self.port = port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
