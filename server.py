"""Local loopback-only radar."""
import hmac, json, secrets, socketserver, sys, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import radar
ROOT = Path(__file__).resolve().parent

class App:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.store = radar.Store(self.root / 'data')
        self.key = secrets.token_urlsafe(32)
        self.scan = None
        self.lock = threading.Lock()

class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    def __init__(self, app):
        self.app = app
        super().__init__(('127.0.0.1', 0), Handler)
        self.expected_host = '127.0.0.1:' + str(self.server_port)
        self.origin = 'http://' + self.expected_host

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, format, *args): pass
    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        for key, value in [('Content-Type',content_type), ('Content-Length',str(len(body))), ('Cache-Control','no-store'), ('X-Content-Type-Options','nosniff'), ('Content-Security-Policy',"default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"), ('Connection','close')]: self.send_header(key, value)
        self.end_headers(); self.wfile.write(body); self.close_connection = True
    def valid_host(self): return self.headers.get_all('Host') == [self.server.expected_host]
    def do_GET(self):
        if not self.valid_host(): return self.send(403, {'error':'Geçersiz Host'})
        if self.path == '/api/bootstrap':
            account, warning, pr = radar.account_pr()
            with self.server.app.lock: current = self.server.app.scan
            try: selection = self.server.app.store.selection()
            except Exception: return self.send(500, {'error':'Veritabanı okunamadı'})
            if selection['issue_id'] is None: selection = None
            try: configured = radar.load_config()['tracked_pr'] is not None
            except ValueError: configured = False
            result = dict(account=account, warning=warning, pr=pr, pr_configured=configured, scan=current, selection=selection)
            result['token'] = self.server.app.key
            return self.send(200, result)
        files = {'/':('index.html','text/html; charset=utf-8'), '/index.html':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8')}
        if self.path not in files: return self.send(404, {'error':'Bulunamadı'})
        name, kind = files[self.path]
        try: body = (self.server.app.root / name).read_bytes()
        except OSError: return self.send(404, {'error':'Dosya bulunamadı'})
        return self.send(200, body, kind)
    def do_POST(self):
        lengths = self.headers.get_all('Content-Length')
        if self.headers.get('Transfer-Encoding') is not None or not lengths or len(lengths) != 1 or not lengths[0].isdigit(): return self.send(400, {'error':'Geçersiz uzunluk'})
        size = int(lengths[0])
        if size > 32768:
            # Drain a bounded amount so Windows can deliver the error before closing.
            self.connection.settimeout(2)
            try: self.rfile.read(min(size, 65536))
            except (OSError, TimeoutError): pass
            return self.send(400, {'error':'Geçersiz uzunluk'})
        self.connection.settimeout(5)
        try: body = self.rfile.read(size)
        except (OSError, TimeoutError): return self.send(400, {'error':'Eksik gövde'})
        if not self.valid_host(): return self.send(403, {'error':'Geçersiz Host'})
        if self.headers.get_all('Origin') != [self.server.origin]: return self.send(403, {'error':'Geçersiz Origin'})
        supplied = self.headers.get_all('X-Radar-Token')
        if not supplied or len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode('utf-8'), self.server.app.key.encode('ascii')): return self.send(403, {'error':'Yetkisiz'})
        if self.headers.get_all('Content-Type') != ['application/json']: return self.send(415, {'error':'JSON gerekli'})
        try:
            data = json.loads(body.decode('utf-8'))
            if not isinstance(data, dict): raise ValueError()
        except (ValueError, UnicodeError): return self.send(400, {'error':'Geçersiz JSON'})
        app = self.server.app
        try:
            if self.path == '/api/scan' and data == {}:
                result = radar.scan()
                with app.lock: app.scan = result
                return self.send(200, {'scan':result})
            if self.path == '/api/detail' and set(data) == {'id'}: return self.send(200, {'detail':radar.detail(data['id'])})
            if self.path == '/api/select' and set(data) == {'id','revision'}:
                radar.parse_id(data['id'])
                with app.lock:
                    if app.scan is None or not any(x['id'] == data['id'] for x in app.scan['items']): return self.send(400, {'error':'Önce taramadaki bir işi seçin'})
                    selected = app.store.select(data['id'], data['revision'])
                return self.send(200, {'selection':selected})
            return self.send(404, {'error':'Bilinmeyen istek'})
        except radar.Conflict: return self.send(409, {'error':'Seçim değişti; yenileyin'})
        except ValueError: return self.send(400, {'error':'Geçersiz istek'})
        except Exception: return self.send(502, {'error':'İşlem tamamlanamadı'})
    def send_error(self, code, message=None, explain=None): self.send(code, {'error':'İstek reddedildi'})
    def do_OPTIONS(self): self.send(403, {'error':'İzin verilmiyor'})
    def do_PUT(self): self.send(405, {'error':'İzin verilmiyor'})
    do_DELETE = do_PUT
    do_PATCH = do_PUT

class InstanceLock:
    def __init__(self, path):
        import msvcrt
        self.file = open(path, 'a+b'); self.file.seek(0)
        try: msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close(); raise RuntimeError('Radar zaten açık')
    def close(self):
        import msvcrt
        self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1); self.file.close()

def main():
    data = ROOT / 'data'
    if data.exists() and (data.is_symlink() or not data.is_dir() or (hasattr(data, 'is_junction') and data.is_junction())): raise RuntimeError('Veri dizini güvenli değil')
    data.mkdir(exist_ok=True)
    lock_path = data / 'radar.lock'
    if lock_path.is_symlink() or (hasattr(lock_path, 'is_junction') and lock_path.is_junction()): raise RuntimeError('Kilit dosyası güvenli değil')
    lock = InstanceLock(lock_path)
    try:
        app = App(); httpd = Server(app)
        print('Radar adresi: ' + httpd.origin, flush=True)
        webbrowser.open(httpd.origin)
        try: httpd.serve_forever()
        except KeyboardInterrupt: pass
        finally: httpd.server_close()
    finally: lock.close()

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Radar başlatılamadı: ' + str(exc), file=sys.stderr); sys.exit(1)
