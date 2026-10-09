"""Exercise the repository Nginx rules using only temporary files and loopback."""
import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from threading import Thread
import time


def check(nginx, effective_config=None):
    binary = shutil.which(nginx)
    if not binary:
        raise SystemExit('BLOCKED: Nginx binary unavailable; pass --nginx /path/to/nginx.')

    seen = []

    class SyntheticUpstream(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            public = self.path == '/documents/1/public.txt'
            private = self.path == '/documents/2/restricted.txt'
            authorized = self.headers.get('Cookie') == 'synthetic_authorized=yes'
            status = 200 if public or (private and authorized) else 302 if private else 404
            body = b'synthetic public document' if public else b'synthetic restricted document' if status == 200 else b''
            self.send_response(status)
            if status == 302:
                self.send_header('Location', '/synthetic-login/')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix='portfolio-nginx-security-') as directory:
        root = Path(directory)
        files = {
            'media/documents/public.txt': b'synthetic public document',
            'media/documents/restricted.txt': b'synthetic restricted document',
            'media/images/rendition.png': b'synthetic rendition',
            'media/original_images/original.png': b'synthetic original',
            'media/other.txt': b'synthetic other media',
            'static/example.css': b'synthetic static file',
        }
        for path, content in files.items():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        (root / 'logs').mkdir()
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticUpstream)
        thread = Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            source = (Path(__file__).resolve().parents[1] / 'nginx.conf').read_text()
            assert source.count('${NGINX_LOCAL_RESOLVERS}') == 1
            source = source.replace('${NGINX_LOCAL_RESOLVERS}', '127.0.0.1')
            staged = root / 'site.conf'
            staged.write_text(source)
            wrapper = root / 'nginx.conf'
            wrapper.write_text(
                'daemon off;\nmaster_process off;\nerror_log stderr;\n'
                f'pid "{root}/nginx.pid";\nevents {{}}\n'
                f'http {{ access_log off; include "{staged}"; }}\n'
            )
            command = [binary, '-p', str(root) + '/', '-c', str(wrapper)]
            subprocess.run([*command, '-t'], check=True, capture_output=True, text=True)
            dumped = subprocess.run([*command, '-T'], check=True, capture_output=True, text=True)
            if effective_config:
                Path(effective_config).write_text(dumped.stdout)
            print('PASS nginx -t and nginx -T (repository template with synthetic resolver)')
            replacements = {
                'listen 8080;': f'listen 127.0.0.1:{port};',
                'alias /media/;': f'alias "{root}/media/";',
                'alias /static/;': f'alias "{root}/static/";',
                'set $upstream "portfolio_web:8000";': f'set $upstream "127.0.0.1:{upstream.server_port}";',
            }
            for original, replacement in replacements.items():
                assert source.count(original) == 1, f'Unexpected Nginx configuration: {original}'
                source = source.replace(original, replacement)
            staged.write_text(source)
            subprocess.run([*command, '-t'], check=True, capture_output=True, text=True)
            subprocess.run([*command, '-T'], check=True, capture_output=True, text=True)
            print('PASS nginx -t and nginx -T (staged repository config)')
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise AssertionError(process.communicate()[1].decode())
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    raise AssertionError('Nginx did not become ready on loopback.')

                def request(path, method='GET', headers=None):
                    connection = HTTPConnection('127.0.0.1', port, timeout=5)
                    try:
                        connection.request(method, path, headers=headers or {})
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()

                for filename in ('public.txt', 'restricted.txt'):
                    for path in (
                        f'/media/documents/{filename}', f'/media/documents/{filename}?download=1',
                        f'/media//documents/{filename}', f'/media/%64ocuments/{filename}',
                        f'/media/documents%2F{filename}', f'/media/images/../documents/{filename}',
                    ):
                        status, body = request(path)
                        assert status == 403, f'Direct document path was accessible: {path}'
                        assert files[f'media/documents/{filename}'] not in body, f'Document bytes leaked: {path}'
                        assert request(path, 'HEAD')[0] == 403, f'HEAD bypass: {path}'
                    assert request(f'/media/documents/{filename}', headers={
                        'Cookie': 'synthetic_authorized=yes',
                    })[0] == 403
                assert not seen, f'Direct documents reached the upstream: {seen}'
                print('PASS direct public/restricted documents blocked (GET, HEAD, normalized paths, cookies)')
                for path, content in files.items():
                    if not path.startswith('media/documents/'):
                        assert request('/' + path) == (200, content), f'Media/static regression: {path}'
                assert request('/documents/1/public.txt') == (200, b'synthetic public document')
                assert request('/documents/2/restricted.txt')[0] == 302
                assert request('/documents/2/restricted.txt', headers={
                    'Cookie': 'synthetic_authorized=yes',
                }) == (200, b'synthetic restricted document')
                print('PASS canonical document URLs proxy to upstream; renditions, originals and other media/static remain accessible')
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nginx', default='nginx', help='Nginx executable (prefer the deployed 1.29 family)')
    parser.add_argument('--effective-config', help='Save nginx -T output for review')
    args = parser.parse_args()
    try:
        check(args.nginx, args.effective_config)
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr)
