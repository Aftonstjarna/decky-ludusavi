"""Ludusavi-driven automation confined to three marked demo directories."""
from datetime import datetime, timezone
import asyncio
import queue
from ludusavi import Ludusavi
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid
import zipfile
from sandbox_api import GAMES

SAMPLES = {
 'port': {'name': 'Majora’s Mask · sandbox port', 'platform': 'Non-Steam', 'cloud': 'none'},
 'gog': {'name': 'GOG installation · sandbox', 'platform': 'GOG', 'cloud': 'none'},
 'cloud': {'name': 'Steam Cloud installation · sandbox', 'platform': 'Steam', 'cloud': 'working'},
 'unknown': {'name': 'Unverified installation · sandbox', 'platform': 'Steam', 'cloud': 'unknown'},
}

def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')

def checked(root, relative='.'):
    root = Path(root)
    if root.is_symlink():
        raise ValueError(f'Refusing linked root: {root}')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe relative path')
    p = root
    for part in path.parts:
        p = p / part
        if p.is_symlink():
            raise ValueError(f'Unexpected symlink: {p}')
    if p.exists() and p.is_file() and p.stat().st_nlink != 1:
        raise ValueError(f'Unexpected hard link: {p}')
    return p


def tree(root):
    checked(root)
    if not root.is_dir():
        raise ValueError(f'Save directory missing: {root}')
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = checked(root, (Path(parent) / name).relative_to(root))
            if p.is_file():
                if p.stat().st_size > 1024 * 1024:
                    raise ValueError('Sandbox files must be under 1 MiB')
                result[str(p.relative_to(root))] = p.read_bytes()
                if sum(map(len, result.values())) > 8 * 1024 * 1024:
                    raise ValueError('Sandbox tree exceeds 8 MiB')
    return result


def digest(files):
    h = hashlib.sha256()
    for name, data in sorted(files.items()):
        h.update(name.encode() + b'\0' + hashlib.sha256(data).digest())
    return h.hexdigest()


def decide(entry, override, coverage):
    if override == 'exclude': return 'Excluded', 'Explicit exclusion'
    if override == 'include': return 'Included', 'Explicit exception'
    if entry.get('curated'): return 'Included', 'Curated baseline'
    if coverage == 'working': return 'Excluded', 'Working Steam Cloud for this copy'
    if coverage == 'none': return 'Included', 'No working Steam Cloud for this copy'
    return 'Review', 'Cloud coverage is unverified'


class Automation:
    def __init__(self, sandbox, binary=None):
        self.sandbox = sandbox
        self.root = sandbox.root
        self.sources = self.root.parent / (self.root.name + 'Sources')
        self.mirror = self.root.parent / (self.root.name + 'Mirror')
        preferred = Path(os.environ.get('DECKY_USER_HOME', str(Path.home()))) / 'Games/Tools/ludusavi'
        self.binary = binary or (str(preferred) if preferred.is_file() else None) or shutil.which('ludusavi') or '/var/lib/flatpak/app/com.github.mtkennerly.ludusavi/current/active/files/bin/ludusavi'
        self.lock = sandbox.lock
        self.stop = threading.Event()
        self.thread = None
        self.observed = {}
        self.jobs = queue.Queue()
        self.queue_lock = threading.RLock()
        self.pending = set()
        self.rerun = {}
        self.sessions = {}
        self.running_samples = set()
        self.events = []
        self.unmapped = {}
        self.active_job = None
        self.scan_count = 0
        self.settle_seconds = 0.25
        self.rows = []
        self.error = None
        self.last_scan = None
        self.last_mirror = None
        self.initialize()
        self.adapter = Ludusavi([[self.binary], ["flatpak", "run", "com.github.mtkennerly.ludusavi"], ["ludusavi"]], config_dir=str(self.root/".ludusavi-demo"))

    def companion(self, root, role):
        marker = checked(root, '.savehaven.json')
        if root.exists():
            if not marker.is_file():
                raise ValueError(f'Refusing unmarked existing directory: {root}')
            data = json.loads(marker.read_text())
            if data.get('kind') != 'savehaven-demo-' + role or data.get('repository') != str(self.root):
                raise ValueError(f'Marker mismatch: {root}')
        else:
            root.mkdir()
            marker.write_text(json.dumps({'kind':'savehaven-demo-'+role,'demo':True,'repository':str(self.root)},indent=2))

    def initialize(self):
        self.sandbox.validate()
        self.companion(self.sources, 'sources')
        self.companion(self.mirror, 'mirror')
        state = self.sandbox.safe('.automation.json')
        self.settings = json.loads(state.read_text()) if state.exists() else {'enabled': True, 'overrides': {}, 'coverage': {}, 'migrations': {}}
        self.settings.setdefault('steamAppIds', {})
        self.settings.setdefault('platforms', {})
        self.settings['triggerMode']='game-exit-hooks'
        for ident in SAMPLES:
            source = self.sources / ident / 'saves'
            if not source.exists() and not source.is_symlink() and ident not in self.settings['migrations']:
                checked(self.sources, Path(ident)/'saves').mkdir(parents=True)
                (source/'save.json').write_text(json.dumps({'demo':True,'game':SAMPLES[ident]['name'],'level':1},indent=2))
        self.persist()

    def persist(self):
        self.sandbox.replace(self.sandbox.safe('.automation.json'), json.dumps(self.settings,indent=2).encode())

    def entries(self):
        entries = []
        for ident, sample in SAMPLES.items():
            entries.append({'id':ident,**sample,'curated':False,'source':self.sources/ident/'saves','destination':self.root/'Managed'/ident})
        for ident,name in GAMES.items():
            entries.append({'id':ident,'name':name,'platform':{'ds3':'Steam','arx':'GOG','jak':'Non-Steam'}[ident],'cloud':'none','curated':True,'source':self.root/name,'destination':self.root/name})
        return entries

    def location(self, e, recover=True):
        if e['curated']:
            return self.sandbox.safe(e['destination'].relative_to(self.root))
        src,dst=e['source'],e['destination']
        checked(self.sources, src.parent.relative_to(self.sources))
        checked(self.root, dst.relative_to(self.root))
        if src.is_symlink():
            if e['id'] not in self.settings['migrations'] or src.resolve() != dst.resolve() or not dst.is_dir():
                raise ValueError('Original link differs from the recorded destination')
            return dst
        if not src.exists() and dst.exists() and e['id'] in self.settings['migrations']:
            if not recover:return dst
            # Resume a recorded move interrupted before the link was created.
            src.symlink_to(dst, target_is_directory=True)
            self.settings['migrations'][e['id']]['phase']='linked'
            self.persist()
            return dst
        return checked(self.sources, src.relative_to(self.sources))

    def scan_ludusavi(self, entries):
        config_dir=self.sandbox.safe('.ludusavi-demo')
        config_dir.mkdir(exist_ok=True)
        custom=[]
        for e in entries:
            location=self.location(e,recover=False)
            custom.append({'name':e['name'],'files':[str(location)]})
        config={'manifest':{'enable':False},'roots':[],'release':{'check':False},'cloud':{'synchronize':False},'backup':{'path':str(self.root/'.ludusavi-backups')},'customGames':custom}
        self.sandbox.replace(self.sandbox.safe('.ludusavi-demo/config.yaml'),json.dumps(config).encode())
        return asyncio.run(self.adapter.preview_saves()).get('games',{})

    def migrate(self, e, files):
        src,dst=e['source'],e['destination']
        if e['curated'] or src.is_symlink(): return
        if dst.exists(): raise ValueError('Destination already exists; reconcile it before migration')
        backup=self.sandbox.safe(Path('.migration-backups')/e['id']/stamp())
        backup.mkdir(parents=True)
        for name,data in files.items():
            p=backup/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        if tree(src)!=files: raise ValueError('Save changed during migration; retry after it settles')
        dst.parent.mkdir(exist_ok=True)
        self.settings['migrations'][e['id']]={'phase':'prepared','backup':str(backup),'source':str(src),'destination':str(dst)}
        self.persist()
        # Sandbox roots are siblings on one filesystem. Refuse unsupported moves without deleting source.
        os.rename(src,dst)
        try:
            src.symlink_to(dst,target_is_directory=True)
        except Exception:
            os.rename(dst,src)
            raise
        self.settings['migrations'][e['id']]['phase']='linked'
        self.persist()

    def selected_files(self):
        files={}
        for e in self.entries():
            status,_=decide(e,self.settings['overrides'].get(e['id'],'auto'),self.settings['coverage'].get(e['id'],e['cloud']))
            if status!='Included': continue
            if not e['curated'] and not e['source'].is_symlink():continue
            for name,data in tree(self.location(e)).items():
                files[str(e['destination'].relative_to(self.root)/name)]=data
        return files

    def cycle(self, force=False, ids=None):
        """Explicit or hook-triggered work. No periodic caller."""
        with self.lock:
            if not self.settings['enabled'] and not force:return
            self.error=None
            try:
                self.sandbox.validate();self.companion(self.sources,'sources')
                requested=[e for e in self.entries() if ids is None or e['id'] in ids]
                eligible=[]
                for e in requested:
                    status,_=decide(e,self.settings['overrides'].get(e['id'],'auto'),self.settings['coverage'].get(e['id'],e['cloud']))
                    if status=='Included' and e['id'] not in self.running_ids():eligible.append(e)
                if not eligible:return
                self.scan_count+=1
                discovered=self.scan_ludusavi(eligible)
                updates={}
                for e in eligible:
                    row=self.row(e)
                    try:
                        files=tree(self.location(e))
                        if not discovered.get(e['name'],{}).get('files'):
                            row['state']='No saves detected';updates[e['id']]=row;continue
                        # Bounded quiescence check only after a job; never background polling.
                        if self.stop.wait(self.settle_seconds):return
                        if tree(self.location(e))!=files:
                            raise ValueError('Save is still changing; retry after the game finishes')
                        if e['id'] in self.running_ids():
                            raise ValueError('Game restarted; management deferred until next exit')
                        self.migrate(e,files)
                        row.update(state='Curated' if e['curated'] else 'Managed',linked=e['source'].is_symlink(),detectedFiles=len(files))
                        self.mirror_entry(e)
                    except (ValueError,OSError) as exc:
                        row.update(state='Error',error=str(exc))
                        self.error=str(exc)
                    updates[e['id']]=row
                self.rows=[updates.get(e['id'],self.cached_row(e)) for e in self.entries()]
                self.last_scan=datetime.now(timezone.utc).isoformat()
            except (ValueError,OSError,RuntimeError,subprocess.SubprocessError) as exc:self.error=str(exc)

    def running_ids(self):
        with self.queue_lock:
            return {ident for ident,appid in self.settings.get('steamAppIds',{}).items() if self.sessions.get(appid,False)} | self.running_samples

    def row(self,e):
        coverage=self.settings['coverage'].get(e['id'],e['cloud'])
        override=self.settings['overrides'].get(e['id'],'auto')
        status,reason=decide(e,override,coverage)
        return {**{k:v for k,v in e.items() if k not in ('source','destination')},'source':str(e['source']),'destination':str(e['destination']),'cloud':coverage,'override':override,'decision':status,'reason':reason,'state':'Waiting for game exit' if status=='Included' else status,'linked':e['source'].is_symlink(),'appId':self.settings.get('steamAppIds',{}).get(e['id'],''),'platform':self.settings.get('platforms',{}).get(e['id'],e['platform'])}

    def cached_row(self,e):
        base=self.row(e)
        cached=next((r for r in self.rows if r['id']==e['id']),None)
        if cached and cached['decision']==base['decision']:
            base.update({k:cached[k] for k in ('state','detectedFiles','bytes','error') if k in cached})
        return base

    def mirror_entry(self,e):
        """Only read and mirror the installation that triggered this job."""
        self.companion(self.mirror,'mirror')
        files=tree(self.location(e))
        relative=e['destination'].relative_to(self.root)
        current=checked(self.mirror,Path('current')/relative)
        if current.exists() and tree(current)==files:
            self.last_mirror=datetime.now(timezone.utc).isoformat();return
        pending=checked(self.mirror,'.pending-'+uuid.uuid4().hex);pending.mkdir()
        for name,data in files.items():
            p=pending/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        if tree(pending)!=files:raise ValueError('Mirror verification failed')
        history=checked(self.mirror,Path('versions')/stamp()/relative)
        current.parent.mkdir(parents=True,exist_ok=True)
        if current.exists():history.parent.mkdir(parents=True,exist_ok=True);os.rename(current,history)
        try:os.rename(pending,current)
        except Exception:
            if history.exists():os.rename(history,current)
            raise
        self.last_mirror=datetime.now(timezone.utc).isoformat()

    def preview(self):
        with self.lock:
            self.sandbox.validate()
            eligible=[e for e in self.entries() if self.row(e)['decision']=='Included']
            found=self.scan_ludusavi(eligible) if eligible else {}
            self.scan_count+=bool(eligible)
            self.rows=[]
            for e in self.entries():
                row=self.row(e)
                files=found.get(e['name'],{}).get('files',{})
                if row['decision']=='Included':
                    row.update(state='Previewed' if files else 'No saves detected',detectedFiles=len(files),bytes=sum(f.get('bytes',0) for f in files.values()))
                self.rows.append(row)
            return self.status()

    def status(self):
        with self.lock,self.queue_lock:
            return {'enabled':self.settings['enabled'],'mode':'game-exit-hooks','engine':'Forked Decky Ludusavi backend · sandbox entries','root':str(self.root),'sources':str(self.sources),'mirror':str(self.mirror),'lastScan':self.last_scan,'lastMirror':self.last_mirror,'error':self.error,'entries':[self.cached_row(e) for e in self.entries()],'token':self.sandbox.token,'queued':len(self.pending),'activeJob':self.active_job,'scanCount':self.scan_count,'recentEvents':self.events[-15:],'unmappedApps':self.unmapped,'hookEndpoint':'/api/hooks','runningIds':sorted(self.running_ids()),'binary':self.adapter.bin_path,'version':self.adapter.version.strip()}

    def enqueue(self,ids,reason='game-exit',force=False):
        with self.queue_lock:
            accepted=[]
            for ident in ids:
                if ident not in self.pending:
                    self.pending.add(ident);accepted.append(ident)
                elif reason in ('game-exit','sample-exit','web-file-edit'):
                    self.rerun[ident]=(reason,force)
            if accepted:self.jobs.put((accepted,reason,force))
            return accepted

    def hook(self,data):
        appid=str(data.get('appId',''))
        if not appid.isdecimal() or len(appid)>12:raise ValueError('Expected Steam app ID')
        event=data.get('event')
        if event not in ('start','exit'):raise ValueError('Expected start or exit')
        name=str(data.get('name',''))[:200]
        with self.queue_lock:
            duplicate=self.sessions.get(appid) is (event=='start')
            self.sessions[appid]=event=='start'
            self.events.append({'appId':appid,'name':name,'event':event,'at':stamp()});self.events=self.events[-50:]
            ids=[i for i,a in self.settings.get('steamAppIds',{}).items() if a==appid]
            if not ids:self.unmapped[appid]={'name':name,'event':event}
            queued=self.enqueue(ids) if event=='exit' and not duplicate and self.settings['enabled'] else []
        return {'accepted':True,'queued':queued,'mapped':bool(ids)}

    def action(self,data):
        action=data.get('action')
        with self.lock:
            if action=='enabled':
                if not isinstance(data.get('enabled'),bool):raise ValueError('Expected enabled boolean')
                self.settings['enabled']=data['enabled'];self.persist()
            elif action=='rule':
                ident=data.get('id')
                if ident not in [e['id'] for e in self.entries()]:raise ValueError('Unknown installation')
                for key,allowed,store in [('override',('auto','include','exclude'),'overrides'),('cloud',('none','working','unknown'),'coverage')]:
                    if key in data:
                        if data[key] not in allowed:raise ValueError('Invalid rule')
                        self.settings[store][ident]=data[key]
                if 'platform' in data:
                    value=data['platform']
                    if not isinstance(value,str) or not value.strip() or len(value)>80:raise ValueError('Invalid platform')
                    self.settings['platforms'][ident]=value.strip()
                if 'appId' in data:
                    appid=str(data['appId']).strip()
                    if appid and (not appid.isdecimal() or len(appid)>12):raise ValueError('Invalid Steam app ID')
                    if appid and any(i!=ident and a==appid for i,a in self.settings['steamAppIds'].items()):raise ValueError('App ID already mapped')
                    self.settings['steamAppIds'][ident]=appid
                self.persist()
            elif action in ('sample-start','sample-exit','simulate'):
                e=next((e for e in self.entries() if e['id']==data.get('id') and not e['curated']),None)
                if not e:raise ValueError('Unknown sample')
                with self.queue_lock:
                    if action=='sample-start':self.running_samples.add(e['id'])
                    elif action=='sample-exit':
                        self.running_samples.discard(e['id'])
                        if self.settings['enabled']:self.enqueue([e['id']],'sample-exit')
                if action=='simulate':
                    target=self.location(e)/'save.json'
                    if target.is_symlink() or (target.exists() and target.stat().st_nlink!=1):raise ValueError('Unsafe save')
                    current=json.loads(target.read_text());current['level']=int(current.get('level',0))+1
                    self.sandbox.replace(e['source']/'save.json',json.dumps(current,indent=2).encode())
            elif action=='preview':return self.preview()
            elif action=='scan':
                ids=data.get('ids',[e['id'] for e in self.entries()])
                known={e['id'] for e in self.entries()}
                if not isinstance(ids,list) or not all(isinstance(i,str) and i in known for i in ids):raise ValueError('Invalid game selection')
                for e in self.entries():
                    if e['id'] in ids and e['curated'] and self.row(e)['decision']=='Included' and e['id'] not in self.running_ids():
                        self.sandbox.snapshot(e['id'],self.sandbox.read(self.sandbox.file(e['id'])))
                self.enqueue(ids,'manual',True)
            else:raise ValueError('Unknown action')
        return self.status()


    def export(self):
        with self.lock:
            self.sandbox.validate()
            files=self.selected_files()
            # Include historical manual and migration backups as well as current selected saves.
            for name in ('.backups','.migration-backups'):
                folder=self.sandbox.safe(name)
                if folder.exists():
                    for rel,data in tree(folder).items():files[str(Path(name)/rel)]=data
            files['.savehaven.json']=self.sandbox.safe('.savehaven.json').read_bytes()
            files['export-manifest.json']=json.dumps({'createdAt':stamp(),'demo':True,'settings':self.settings,'files':{p:hashlib.sha256(d).hexdigest() for p,d in files.items()}},indent=2).encode()
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
                for name,data in files.items():z.writestr(name,data)
            data=stream.getvalue();name='savehaven-backup-'+stamp()+'.zip'
            folder=self.sandbox.safe('.exports');folder.mkdir(exist_ok=True)
            self.sandbox.replace(folder/name,data)
            return name,data

    def start(self):
        if self.thread and self.thread.is_alive():return
        def run():
            while True:
                job=self.jobs.get()
                try:
                    if job is None:return
                    ids,reason,force=job
                    with self.queue_lock:self.active_job={'ids':ids,'reason':reason}
                    if not self.stop.is_set():self.cycle(force=force,ids=ids)
                except Exception as exc:
                    self.error=str(exc)
                finally:
                    if job:
                        with self.queue_lock:
                            self.pending.difference_update(job[0]);self.active_job=None
                            for ident in job[0]:
                                if ident in self.rerun:
                                    reason,force=self.rerun.pop(ident)
                                    self.enqueue([ident],reason,force)
                    self.jobs.task_done()
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()

    def shutdown(self):
        self.stop.set();self.jobs.put(None)
        if self.thread:self.thread.join(timeout=50)
