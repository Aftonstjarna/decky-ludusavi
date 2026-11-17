"""Shared backend owned by the Decky plugin or standalone web launcher."""
import http.server
import json
import threading
from pathlib import Path
from sandbox_api import Sandbox, make_handler
from automation import Automation
MARKER = '.savehaven.json'
def prepare(root, web_source):
    if root.is_symlink():
        raise SystemExit('Refusing a symlinked SaveDemo directory.')
    marker = root / MARKER
    if root.exists():
        if marker.is_symlink() or not marker.is_file():
            raise SystemExit('Existing SaveDemo has no sandbox marker; refusing to overwrite it.')
        data = json.loads(marker.read_text())
        if data.get('kind') != 'savehaven-demo-sandbox' or data.get('demo') is not True:
            raise SystemExit('SaveDemo is not marked as this demo sandbox.')
    else:
        root.mkdir()
        with marker.open('x') as f:
            json.dump({'schemaVersion': 1, 'kind': 'savehaven-demo-sandbox', 'managedBy': 'savehaven', 'managed': True, 'demo': True, 'repositoryId': 'local-save-demo', 'settings': {'preserveExistingLayout': True, 'cloudSelection': 'installed-copy', 'unknownCoverage': 'review'}}, f, indent=2)
    # Refuse links anywhere inside the sandbox before writing generated assets.
    for p in root.rglob('*'):
        if p.is_symlink():
            raise SystemExit(f'Refusing sandbox symlink: {p}')
    for game in ['Dark Souls III', 'Arx Fatalis', 'Jak and Daxter']:
        folder = root / game
        folder.mkdir(exist_ok=True)
        save = folder / 'sample-save.json'
        if not save.exists():
            with save.open('x') as f:
                json.dump({'demo': True, 'game': game, 'progress': 'Synthetic fixture; not a real game save.'}, f, indent=2)
    web = root / '.app'
    web.mkdir(exist_ok=True)
    for source in web_source.iterdir():
        if not source.is_file():
            continue
        text = source.read_text()
        text = text.replace('~/Saves', '~/SaveDemo')
        text = text.replace('DEMO · NO LIVE CONNECTION', 'LOCAL root · ~/SaveDemo')
        text = text.replace('Sample installation scenarios using titles from your inventory.', 'Sandbox at ~/SaveDemo · synthetic save fixtures.')
        # Separate local policy edits from the hosted demo.
        text = text.replace('savehaven-v1', 'savehaven-local-sandbox-v1')
        (web / source.name).write_text(text)
    return web

class Service:
    def __init__(self, root, web_source, port=8765):
        web = prepare(Path(root), Path(web_source))
        self.sandbox = Sandbox(Path(root))
        self.automation = Automation(self.sandbox)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', port), make_handler(self.sandbox, web, self.automation))
        self.thread = None
    def start(self):
        self.automation.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def close(self):
        self.automation.shutdown()
        if self.thread:self.server.shutdown()
        self.server.server_close()
