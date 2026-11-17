"""Local-only file management for Savehaven's synthetic sandbox saves."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import uuid
from datetime import datetime, timezone

GAMES = {'ds3': 'Dark Souls III', 'arx': 'Arx Fatalis', 'jak': 'Jak and Daxter'}
MAX_SIZE = 65536

class Sandbox:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)

    def safe(self, relative):
        p = self.root
        if p.is_symlink():
            raise ValueError('Sandbox root cannot be a symlink')
        for part in Path(relative).parts:
            if part in ('..', '/'):
                raise ValueError('Invalid path')
            p = p / part
            if p.is_symlink():
                raise ValueError('Symlinks are not managed in this sandbox')
        if p.exists() and p.is_file() and p.stat().st_nlink != 1:
            raise ValueError('Hard-linked files are not managed in this sandbox')
        return p

    def validate(self):
        marker = json.loads(self.safe('.savehaven.json').read_text())
        if marker.get('kind') != 'savehaven-demo-sandbox' or marker.get('demo') is not True:
            raise ValueError('Sandbox marker is missing or invalid')

    def file(self, game):
        if game not in GAMES:
            raise ValueError('Unknown managed file')
        return self.safe(Path(GAMES[game]) / 'sample-save.json')

    def read(self, p):
        if p.stat().st_size > MAX_SIZE:
            raise ValueError('File exceeds the sandbox size limit')
        return p.read_bytes()

    def revision(self, data):
        return hashlib.sha256(data).hexdigest()

    def snapshot(self, game, data):
        folder = self.safe(Path('.backups') / game)
        folder.mkdir(parents=True, exist_ok=True)
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex + '.json'
        with (folder / name).open('xb') as f:
            f.write(data)
        return name

    def replace(self, path, data):
        fd, temp = tempfile.mkstemp(prefix='.savehaven-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def listing(self):
        with self.lock:
            self.validate()
            files = []
            for game, name in GAMES.items():
                path = self.file(game)
                data = self.read(path)
                folder = self.safe(Path('.backups') / game)
                backups = sorted([p.name for p in folder.glob('*.json')], reverse=True) if folder.exists() else []
                files.append({'id': game, 'game': name, 'path': str(path.relative_to(self.root)), 'content': data.decode('utf-8'), 'bytes': len(data), 'revision': self.revision(data), 'backups': backups})
            return {'root': str(self.root), 'files': files, 'token': self.token}

    def action(self, request):
        with self.lock:
            self.validate()
            game = request.get('id')
            path = self.file(game)
            current = self.read(path)
            if request.get('revision') != self.revision(current):
                raise ValueError('File changed since it was loaded. Refresh before trying again.')
            action = request.get('action')
            if action == 'backup':
                return {'message': 'Backup created', 'backup': self.snapshot(game, current)}
            if action == 'save':
                content = request.get('content')
                if not isinstance(content, str):
                    raise ValueError('Content must be text')
                data = content.encode('utf-8')
                if len(data) > MAX_SIZE:
                    raise ValueError('File exceeds 64 KiB')
                json.loads(content)
            elif action == 'restore':
                name = request.get('backup')
                if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
                    raise ValueError('Invalid backup name')
                data = self.read(self.safe(Path('.backups') / game / name))
                json.loads(data)
            else:
                raise ValueError('Unknown action')
            backup = self.snapshot(game, current)
            self.replace(path, data)
            return {'message': 'Save updated' if action == 'save' else 'Backup restored', 'previousVersion': backup}


def make_handler(sandbox, web, automation=None):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web), **kwargs)

        def trusted(self):
            host = self.headers.get('Host', '')
            expected = f'127.0.0.1:{self.server.server_port}'
            return host == expected and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected

        def reply(self, status, obj):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.trusted():
                return self.reply(403, {'error': 'Use the local demo origin'})
            if self.path == '/api/automation' and automation:
                return self.reply(200, automation.status())
            if self.path == '/api/files':
                try:
                    return self.reply(200, sandbox.listing())
                except (ValueError, OSError) as exc:
                    return self.reply(400, {'error': str(exc)})
            if self.path not in ['/', '/index.html', '/app.mjs', '/policy.mjs', '/style.css', '/files.mjs', '/automation.mjs']:
                return self.reply(404, {'error': 'Not found'})
            name = 'index.html' if self.path == '/' else self.path[1:]
            if Path(web).is_symlink() or (Path(web) / name).is_symlink():
                return self.reply(403, {'error': 'Symlinked assets are not served'})
            super().do_GET()

        def do_POST(self):
            if not self.trusted() or self.headers.get('X-Savehaven-Token') != sandbox.token:
                return self.reply(403, {'error': 'Refresh the local file manager before trying again'})
            if self.path not in ['/api/files','/api/automation','/api/export','/api/hooks'] or self.headers.get('Content-Type') != 'application/json':
                return self.reply(400, {'error': 'Expected JSON file action'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_SIZE * 2:
                    raise ValueError('Invalid request size')
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError('Expected a JSON object')
                if self.path == '/api/export' and automation:
                    name, data = automation.export()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Disposition', f'attachment; filename="{name}"')
                    self.send_header('X-Backup-Filename', name)
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path == '/api/hooks' and automation:
                    self.reply(200, automation.hook(request))
                elif self.path == '/api/automation' and automation:
                    self.reply(200, automation.action(request))
                elif self.path == '/api/files':
                    result = sandbox.action(request)
                    if automation and request.get('action') in ('save','restore') and automation.settings['enabled']:
                        automation.enqueue([request['id']], 'web-file-edit')
                    self.reply(200, result)
                else:
                    self.reply(404, {'error':'Automation not available'})
            except (ValueError, OSError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
    return Handler
