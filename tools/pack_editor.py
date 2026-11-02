#!/usr/bin/env python3
"""Start the Card Workshop in your browser. It runs offline."""
import argparse
import hashlib
import http.server
import io
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import urlsplit
import webbrowser
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'community_editor'))
from model import QOL, encode, read_project, to_file

STATIC = HERE / 'community_editor'


class Editor(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, data, mime='application/json', status=200, filename=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, data, status=200):
        self.send(json.dumps(data, ensure_ascii=False).encode(), status=status)

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == '/api/session':
                self.json({'token': self.server.token, 'loaded': self.server.adapter is not None, 'qol': QOL,
                           'opening_ready': bool(self.server.adapter and self.server.adapter.opening_assets)})
            elif path == '/api/project':
                with self.server.lock:
                    a = self.server.adapter
                    if a is None:
                        raise ValueError('Open a clean ROM first.')
                    self.json({'project': a.fresh(), 'catalog': a.catalog()})
            elif path == '/api/cpus':
                with self.server.lock:
                    if self.server.adapter is None:
                        raise ValueError('Open a clean ROM first.')
                    self.json(self.server.adapter.cpu_metadata())
            elif path == '/api/points-preset':
                with self.server.lock:
                    if self.server.adapter is None:
                        raise ValueError('Open a clean ROM first.')
                    self.json(self.server.adapter.points_preset())
            elif path == '/api/banlists':
                with self.server.lock:
                    if self.server.adapter is None:
                        raise ValueError('Open a clean ROM first.')
                    self.json(self.server.adapter.base_banlists())
            elif path.startswith('/api/image/'):
                _, _, _, kind, ident = path.split('/')
                with self.server.lock:
                    if self.server.adapter is None:
                        raise ValueError('Open a clean ROM first.')
                    raw = self.server.adapter.image(kind, int(ident))
                self.send(raw, 'image/png')
            elif path in ('/', '/app.js', '/style.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
                self.send((STATIC / name).read_bytes(), {'index.html': 'text/html; charset=utf-8',
                          'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css'}[name])
            else:
                self.json({'error': 'Not found'}, 404)
        except (ValueError, KeyError, OSError, SystemExit) as e:
            self.json({'error': str(e)}, 400)

    def do_POST(self):
        # Reject cross-site writes, including forms and DNS-rebinding hosts.
        if self.headers.get('X-Editor-Token') != self.server.token:
            self.json({'error': 'This session has ended. Reload the page.'}, 403)
            return
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{self.headers.get("Host")}':
            self.json({'error': 'Cross-origin writes are disabled.'}, 403)
            return
        try:
            path = urlsplit(self.path).path
            size = int(self.headers.get('Content-Length', '0'))
            limit = (280 if path == '/api/donor/wc2010' else 140 if path == '/api/rom' else 24) * 1024 * 1024
            if not 0 < size <= limit:
                raise ValueError('The file is empty or too large.')
            raw = self.rfile.read(size)
            with self.server.lock:
                if path == '/api/rom':
                    from adapter import Adapter
                    # Validate before replacing the active session; no filesystem path from the browser.
                    profile_sha1 = '7617788d197ffd45d2ab2bb6deadbf0f9874e2fa'
                    if hashlib.sha1(raw).hexdigest() != profile_sha1:
                        raise ValueError('This is not a clean WC2011 Europe ROM. Modified ROMs and other versions do not work.')
                    dest = Path(self.server.workspace.name) / 'source.nds'
                    dest.write_bytes(raw)
                    self.server.adapter = Adapter(dest)
                    self.json({'ok': True})
                    return
                a = self.server.adapter
                if a is None:
                    raise ValueError('Open a clean ROM first.')
                if path == '/api/donor/wc2010':
                    from opening_assets import prepare
                    suffix = '.zip' if raw.startswith(b'PK\x03\x04') else '.nds'
                    donor = Path(self.server.workspace.name) / ('wc2010' + suffix)
                    donor.write_bytes(raw)
                    imported = prepare(donor, a.rom)
                    a.opening_assets = imported
                    self.json({'ok': True, 'sha1': imported['donor_sha1']})
                    return
                p = a.tidy(read_project(json.loads(raw), a.sha1))
                if path == '/api/open':
                    self.json(p)
                elif path == '/api/save':
                    self.send(encode(to_file(p)), filename='project.wcmod.json')
                elif path == '/api/validate':
                    self.json({'issues': a.validate(p)})
                elif path == '/api/export':
                    bps, report = a.build(p)
                    out = io.BytesIO()
                    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                        z.writestr('mod.bps', bps)
                        z.writestr('project.wcmod.json', encode(to_file(p)))
                        z.writestr('build-report.json', json.dumps(report, indent=2))
                    self.send(out.getvalue(), 'application/zip', filename='mod-export.zip')
                else:
                    self.json({'error': 'Not found'}, 404)
        except (ValueError, KeyError, TypeError, OSError, SystemExit) as e:
            self.json({'error': str(e)}, 400)
        except Exception as e:
            print(f'Editor error: {type(e).__name__}: {e}', file=sys.stderr)
            self.json({'error': f'{type(e).__name__}: {e}'}, 500)

    def parse_request(self):
        if not super().parse_request():
            return False
        host = self.headers.get('Host', '')
        if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            self.send_error(403, 'Local connections only')
            return False
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rom', help='clean WC2011 Europe ROM to open at start; you can also open it in the Workshop')
    ap.add_argument('--rom10', help='WC2010 ROM, USA or Europe (.nds or .zip), for Better pack opening')
    ap.add_argument('--port', type=int, default=8792)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='wc-pack-editor-') as work:
        server = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), Editor)
        server.token = secrets.token_urlsafe(32)
        server.lock = threading.Lock()
        server.workspace = type('Workspace', (), {'name': work})()
        server.adapter = None
        if a.rom:
            from adapter import Adapter
            try:
                server.adapter = Adapter(a.rom)
                if a.rom10:
                    from opening_assets import prepare
                    server.adapter.opening_assets = prepare(a.rom10, server.adapter.rom)
            except (ValueError, OSError) as e:
                server.server_close()
                ap.error(str(e))
        url = f'http://127.0.0.1:{server.server_port}'
        print(f'Card Workshop: {url}', flush=True)
        if not a.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
