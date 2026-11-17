"""Thin web/Decky adapter for Ludusavi, plus centralization and Syncthing status.

All discovery, backup formats, retention, and restores belong to Ludusavi.
There is no periodic scan, second save database, or custom snapshot format.
"""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import fcntl
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import urllib.request
import subprocess
import zipfile
from ludusavi import Ludusavi
from centralize import candidates,relocate,write_json


def now():return datetime.now(timezone.utc).isoformat()


class LiveBackend:
    def __init__(self,home=None,config_dir=None,state_dir=None):
        self.home=Path(home or Path.home())
        self.root=self.home/'Saves'
        self.config_dir=Path(config_dir or self.home/'.config/ludusavi')
        self.state_dir=Path(state_dir or self.home/'.local/state/savehaven')
        self.state_dir.mkdir(parents=True,exist_ok=True)
        self._lockfile=(self.state_dir/'backend.lock').open('a')
        fcntl.flock(self._lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker=json.loads((self.root/'.savehaven.json').read_text())
        if marker.get('kind')!='savehaven-live' or self.root.is_symlink():raise ValueError('Live repository marker missing')
        self.adapter=Ludusavi([[str(self.home/'Games/Tools/ludusavi')],['ludusavi']],str(self.config_dir))
        self.adapter.timeout=300
        self.operation_lock=threading.RLock();self.lock=threading.RLock();self.token=secrets.token_urlsafe(32)
        path=self.state_dir/'settings.json'
        self.settings=json.loads(path.read_text()) if path.exists() else {'enabled':True,'centralize':True,'platforms':{},'aliases':{},'excluded':[]}
        self.settings.setdefault('platforms',{});self.settings.setdefault('aliases',{});self.settings.setdefault('excluded',[])
        cached=self.state_dir/'preview.json'
        self.preview=json.loads(cached.read_text()) if cached.exists() else {'games':{}}
        self.closing=threading.Event();self.jobs=queue.Queue();self.pending=set();self.sessions={};self.active=None;self.result=None;self.error=None;self.scan_count=0
        self.thread=threading.Thread(target=self.worker,daemon=True);self.thread.start()

    def config(self):
        signature=(self.config_dir/'config.yaml').stat().st_mtime_ns
        if getattr(self,'_config_signature',None)!=signature:
            self._config=asyncio.run(self.adapter.get_config());self._config_signature=signature
        return deepcopy(self._config)
    def save_config(self,cfg):
        path=self.config_dir/'config.yaml'
        # Keep each prior configuration; do not silently replace GUI edits read earlier.
        backup=self.state_dir/'config-history'/((now().replace(':','-'))+'.yaml')
        backup.parent.mkdir(exist_ok=True);backup.write_bytes(path.read_bytes())
        write_json(path,cfg) # JSON is valid YAML, understood by Ludusavi's GUI.
    def persist(self):write_json(self.state_dir/'settings.json',self.settings)
    def run(self,args):
        result=asyncio.run(self.adapter._run_command(args))
        if result.get('errors'):raise ValueError('Ludusavi reported errors: '+json.dumps(result['errors']))
        return result
    def status(self):
        with self.lock:
            cfg=self.config()
            return {'live':True,'root':str(self.root),'binary':list(self.adapter.bin_path or []),'version':self.adapter.version.strip(),'enabled':self.settings['enabled'],'centralize':self.settings['centralize'],'platforms':self.settings['platforms'],'excluded':self.settings['excluded'],'backupPath':cfg['backup']['path'],'restorePath':cfg['restore']['path'],'customGames':cfg.get('customGames',[]),'cloudFilter':cfg.get('backup',{}).get('filter',{}).get('cloud',{}),'token':self.token,'active':self.active,'queued':len(self.pending),'preview':self.preview,'result':self.result,'error':self.error,'scanCount':self.scan_count,'syncthing':self.syncthing(False)}
    def syncthing(self,refresh=False):
        if refresh or not hasattr(self,'_syncthing_status'):
            try:
                output=subprocess.check_output(['/usr/bin/python3',str(Path(__file__).with_name('syncthing_status.py')),str(self.home),'refresh' if refresh else 'config'],text=True,timeout=6)
                self._syncthing_status=json.loads(output)
            except Exception as exc:self._syncthing_status={'configured':False,'error':str(exc)}
        return self._syncthing_status
    def submit(self,data):
        action=data.get('action')
        if self.closing.is_set():raise ValueError('Plugin is stopping')
        with self.lock:
            if action=='settings':
                for key in ('enabled','centralize'):
                    if key in data:
                        if not isinstance(data[key],bool):raise ValueError('Expected boolean')
                        self.settings[key]=data[key]
                self.persist();return self.status()
            if action=='platform':
                name=data.get('game');value=data.get('platform')
                if not isinstance(name,str) or not isinstance(value,str) or not value.strip() or len(value)>80:raise ValueError('Invalid platform')
                self.settings['platforms'][name]=value.strip();self.persist();return self.status()
            if action=='syncthing':self.result={'syncthing':self.syncthing(True)};return self.status()
            if action not in ('preview','backup','backups','restore-preview','restore','custom','export','manifest'):raise ValueError('Unknown Ludusavi operation')
            games=data.get('games',[])
            if not isinstance(games,list) or any(not isinstance(g,str) or not g.strip() or g.startswith('-') for g in games):raise ValueError('Invalid game names')
            if action in ('backup','restore','restore-preview','export') and not games:raise ValueError('Select at least one game')
            if action in ('restore','restore-preview') and len(games)!=1:raise ValueError('Restore one game at a time')
            key=json.dumps(data,sort_keys=True)
            if key not in self.pending:self.pending.add(key);self.jobs.put((key,deepcopy(data)))
        return self.status()
    def worker(self):
        while True:
            item=self.jobs.get()
            try:
                if item is None:return
                key,data=item
                if self.closing.is_set():continue
                with self.lock:self.active=data;self.error=None;self.result=None
                result=self.execute(data)
                with self.lock:self.result=result
            except Exception as exc:
                with self.lock:self.error=str(exc)
            finally:
                if item:
                    with self.lock:self.active=None;self.pending.discard(item[0])
                self.jobs.task_done()
    def is_running(self,game):
        return any(running and self.settings['aliases'].get(appid)==game for appid,running in self.sessions.items())
    def allowed(self,game):
        # Ludusavi deliberately treats named CLI games as explicit selections,
        # bypassing cloud filtering. Apply its own config + manifest before a
        # hook supplies a name. A custom per-copy entry has independent rules.
        cfg=self.config()
        if game in cfg.get('backup',{}).get('ignoredGames',[]):return False
        custom=next((g for g in cfg.get('customGames',[]) if g.get('name')==game),None)
        if custom and custom.get('ignore'):return False
        cloud=cfg.get('backup',{}).get('filter',{}).get('cloud',{})
        if not cloud.get('exclude'):return True
        manifest=self.config_dir/'manifest.yaml'
        signature=(manifest.stat().st_mtime_ns,(self.config_dir/'config.yaml').stat().st_mtime_ns)
        if getattr(self,'_manifest_signature',None)!=signature:
            native=self.run(['manifest','show'])
            self._manifest_cloud={name:record.get('cloud',{}) for name,record in native.items()}
            self._manifest_signature=signature
        record={'cloud':self._manifest_cloud[game]} if game in self._manifest_cloud else None
        if record is None:return custom is not None
        return not any(cloud.get(store) and record.get('cloud',{}).get(store) for store in ('steam','gog','epic','origin','uplay'))

    def execute(self,data):
        with self.operation_lock:return self._execute(data)

    def _execute(self,data):
        action=data['action'];games=data.get('games',[])
        if action in ('backup','export'):
            excluded=[g for g in games if not self.allowed(g)]
            games=[g for g in games if g not in excluded]
            if not games:return {'message':'Excluded by Ludusavi rules','excluded':excluded,'games':{}}
        if action=='manifest':
            return {'message':asyncio.run(self.adapter.update_manifest_async())}
        if action=='preview':
            self.scan_count+=1
            result=self.run(['backup','--preview','--no-cloud-sync',*games])
            with self.lock:
                if games:self.preview.setdefault('games',{}).update(result.get('games',{}))
                else:self.preview=result
                write_json(self.state_dir/'preview.json',self.preview)
            return result
        if action=='backups':return self.run(['backups',*games])
        if action=='custom':return self.custom(data)
        if action=='backup':
            if any(self.is_running(g) for g in games):raise ValueError('A selected game is running; wait for exit')
            before=self.run(['backup','--preview','--no-cloud-sync',*games]);self.scan_count+=1
            planned={g:candidates(v.get('files',{}),self.root) for g,v in before.get('games',{}).items() if v.get('decision')=='Processed'} if self.settings['centralize'] else {}
            result=self.run(['backup','--force','--no-cloud-sync',*games])
            moves=[]
            for game,folders in planned.items():
                actual=result.get('games',{}).get(game,{})
                if actual.get('decision')!='Processed' or any(v.get('failed') for v in actual.get('files',{}).values()):continue
                backed={Path(p).resolve() for p,v in actual.get('files',{}).items() if not v.get('ignored') and not v.get('failed')}
                for source,expected in folders.items():
                    if self.is_running(game):raise ValueError('Game restarted; leaving source in place')
                    if not {source/p for p in expected}<=backed:continue
                    move=relocate(source,self.root,game,self.state_dir/'moves',expected);moves.append(move)
                    cfg=self.config();redirect={'kind':'restore','source':move['source'],'target':move['destination']}
                    if redirect not in cfg.setdefault('redirects',[]):cfg['redirects'].append(redirect);self.save_config(cfg)
            with self.lock:
                self.preview.setdefault('games',{}).update(result.get('games',{}));write_json(self.state_dir/'preview.json',self.preview)
            return {**result,'centralized':moves}
        if action in ('restore','restore-preview'):
            backup=data.get('backup')
            if not isinstance(backup,str) or not backup or backup.startswith('-'):raise ValueError('Choose a Ludusavi backup')
            if self.is_running(games[0]):raise ValueError('Close the game before restoring')
            if action=='restore':
                # Use a separate native backup destination so retention cannot delete
                # the version the user selected for restore.
                recovery=self.state_dir/'before-restore'/now().replace(':','-')
                self.run(['backup','--force','--no-cloud-sync','--path',str(recovery),*games])
            return self.run(['restore','--preview' if action=='restore-preview' else '--force','--no-cloud-sync','--backup',backup,*games])
        if action=='export':
            folder=self.state_dir/'exports'/now().replace(':','-');folder.mkdir(parents=True)
            result=self.run(['backup','--force','--no-cloud-sync','--format','zip','--path',str(folder),*games])
            target=folder.with_name(folder.name+'.zip')
            with zipfile.ZipFile(target,'w',zipfile.ZIP_STORED) as z:
                for p in folder.rglob('*'):
                    if p.is_file() and not p.is_symlink():z.write(p,p.relative_to(folder))
            return {'export':target.name,'games':result.get('games',{})}
        raise ValueError('Unsupported operation')
    def custom(self,data):
        name=data.get('name','').strip();path=Path(data.get('path','')).expanduser()
        if not name or name.startswith('-') or len(name)>200 or not path.is_absolute() or not path.is_dir():raise ValueError('Enter a name and existing absolute save-folder path')
        if path.resolve() in [self.home.resolve(),Path('/'),self.root.resolve()]:raise ValueError('Choose one game save folder')
        appid=str(data.get('appId',''))
        if appid and not appid.isdecimal():raise ValueError('Invalid Steam App ID')
        cfg=self.config();custom=cfg.setdefault('customGames',[])
        if any(g.get('name')==name for g in custom):raise ValueError('Custom game already exists; edit it in Ludusavi')
        custom.append({'name':name,'files':[str(path)],'integration':'override','ignore':False})
        self.save_config(cfg)
        platform=data.get('platform','Non-Steam')
        self.settings['platforms'][name]=platform
        appid=str(data.get('appId',''))
        if appid:
            if not appid.isdecimal():raise ValueError('Invalid Steam App ID')
            self.settings['aliases'][appid]=name
        self.persist();return {'message':'Custom game saved in Ludusavi configuration'}
    def hook(self,data):
        appid=str(data.get('appId',''));event=data.get('event')
        if not appid.isdecimal() or event not in ('start','exit'):raise ValueError('Invalid lifecycle event')
        with self.lock:
            duplicate=self.sessions.get(appid) is (event=='start');self.sessions[appid]=event=='start'
        if event=='start' or duplicate or not self.settings['enabled']:return {'accepted':True,'queued':False}
        # Resolve one title with the parent's Ludusavi find API, never a full scan.
        name=self.settings['aliases'].get(appid)
        if not name:
            found=asyncio.run(self.adapter.get_game_name_by_app_id(appid));names=list(found.get('games',{}))
            if not names:return {'accepted':True,'queued':False,'reason':'Unknown game; add a custom game and App ID'}
            name=names[0];self.settings['aliases'][appid]=name;self.persist()
        if name in self.settings['excluded']:return {'accepted':True,'queued':False}
        name=self.settings.get('gameAliases',{}).get(name,name)
        self.submit({'action':'backup','games':[name]});return {'accepted':True,'queued':True}
    def close(self):
        self.closing.set()
        import signal
        for pid in list(self.adapter._active_pids):
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
        self.jobs.put(None);self.thread.join()
        self._lockfile.close()


class LiveService:
    def __init__(self,home,web,port=8765):
        self.automation=LiveBackend(home);self.sandbox=self.automation
        backend=self.automation;web=Path(web)
        class Handler(http.server.BaseHTTPRequestHandler):
            def reply(self,code,data):
                payload=json.dumps(data).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def trusted(self):
                origin=f'127.0.0.1:{self.server.server_port}'
                return self.headers.get('Host')==origin and self.headers.get('Origin','http://'+origin)=='http://'+origin
            def do_GET(self):
                if not self.trusted():return self.reply(403,{'error':'Use the local origin'})
                try:
                    if self.path in ('/api/live','/api/automation'):return self.reply(200,backend.status())
                    if self.path.startswith('/api/export/'):
                        name=self.path.split('/')[-1]
                        if not name.endswith('.zip') or '..' in name:raise ValueError('Invalid export')
                        p=backend.state_dir/'exports'/name
                        if p.is_symlink() or not p.is_file():raise ValueError('Export not found')
                        self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition','attachment; filename="'+name+'"');self.send_header('Content-Length',str(p.stat().st_size));self.end_headers()
                        import shutil
                        with p.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                        return
                    paths={'/':'live.html','/index.html':'live.html','/live.mjs':'live.mjs','/style.css':'style.css'}
                    if self.path not in paths:return self.reply(404,{'error':'Not found'})
                    p=web/paths[self.path];content=p.read_bytes();self.send_response(200);self.send_header('Content-Type',{'html':'text/html','mjs':'text/javascript','css':'text/css'}[p.suffix[1:]]);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
                except (ValueError,OSError) as exc:self.reply(400,{'error':str(exc)})
            def do_POST(self):
                if not self.trusted() or self.headers.get('X-Savehaven-Token')!=backend.token:return self.reply(403,{'error':'Refresh the page'})
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=131072 or self.headers.get('Content-Type')!='application/json':raise ValueError('Expected JSON')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):raise ValueError('Expected object')
                    if self.path=='/api/hooks':result=backend.hook(data)
                    elif self.path=='/api/live':result=backend.submit(data)
                    else:return self.reply(404,{'error':'Not found'})
                    self.reply(200,result)
                except (ValueError,OSError,RuntimeError) as exc:self.reply(400,{'error':str(exc)})
        try:self.server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler)
        except BaseException:backend.close();raise
        self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def close(self):
        self.server.shutdown();self.server.server_close();self.automation.close()
