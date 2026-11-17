"""The small piece Ludusavi does not provide: relocate save-only directories.

Ludusavi must have successfully backed up the exact files first. Originals are
retained beside their former path for recovery; an on-disk journal records moves.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid


def inventory(root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Expected an ordinary save directory')
    result={}
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            p=Path(base)/name
            if p.is_symlink():raise ValueError(f'Symlink inside save directory: {p}')
            if p.is_dir():continue
            before=p.stat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise ValueError(f'Not an independent regular file: {p}')
            h=hashlib.sha256()
            with p.open('rb') as f:
                for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
            after=p.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('Save changed while reading')
            result[str(p.relative_to(root))]={'bytes':after.st_size,'sha256':h.hexdigest()}
    return result


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('x') as f:
        json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def relocate(source,root,game,journal_dir,expected):
    source=Path(source);root=Path(root).resolve()
    if source.is_symlink():raise ValueError('Source is already linked')
    source=source.resolve(strict=True)
    if source==root or source.is_relative_to(root):return {'state':'Already centralized','source':str(source)}
    if root.is_relative_to(source) or source in [Path.home().resolve(),Path('/')]:raise ValueError('Refusing a shared parent directory')
    before=inventory(source)
    if not before or before!=expected:raise ValueError('Save changed since backup; retry after game exit')
    ident=hashlib.sha256((game+'\0'+str(source)).encode()).hexdigest()[:20]
    destination=root/'Managed'/ident
    if destination.exists() or destination.is_symlink():raise ValueError('Central destination already exists; review journal')
    destination.parent.mkdir(exist_ok=True)
    if destination.parent.is_symlink():raise ValueError('Managed directory must not be a symlink')
    rollback=source.with_name(source.name+'.savehaven-before-'+ident)
    if rollback.exists() or rollback.is_symlink():raise ValueError('Recovery copy already exists; review journal')
    pending=destination.with_name(destination.name+'.pending-'+uuid.uuid4().hex)
    shutil.copytree(source,pending,symlinks=True)
    if inventory(pending)!=before or inventory(source)!=before:raise ValueError('Save changed while copying; original left in place')
    record={'game':game,'source':str(source),'destination':str(destination),'recovery':str(rollback),'files':before,'phase':'prepared'}
    journal=Path(journal_dir)/(ident+'.json');write_json(journal,record)
    os.rename(pending,destination)
    # Check once more immediately before renaming the original.
    if inventory(source)!=before:raise ValueError('Save changed before linking; original left in place')
    os.rename(source,rollback)
    try:source.symlink_to(destination,target_is_directory=True)
    except BaseException:
        os.rename(rollback,source)
        record['phase']='rolled-back';write_json(journal,record)
        raise
    record['phase']='linked';write_json(journal,record)
    return record


def candidates(files,root):
    """Only complete directories covered by Ludusavi, never a mixed install dir."""
    root=Path(root).resolve()
    eligible={Path(p).resolve() for p,m in files.items() if not m.get('ignored') and not m.get('failed') and not m.get('duplicatedBy') and Path(p).is_file()}
    results={}
    parents=set()
    for p in eligible:
        for parent in list(p.parents)[:4]:
            label=parent.name.lower()
            if label in ('save','saves','savegames','savedata','remote') or label.startswith('save0'):
                parents.add(parent)
    for parent in sorted(parents,key=lambda p:len(p.parts)):
        if parent.is_relative_to(root) or any(parent.is_relative_to(p) for p in results):continue
        # Compare paths before hashing so a mixed directory is never read in full.
        allfiles=set();unsafe=False
        for base,dirs,names in os.walk(parent,followlinks=False):
            for name in dirs+names:
                item=Path(base)/name
                if item.is_symlink():unsafe=True
            allfiles.update(Path(base)/n for n in names)
            if unsafe or not allfiles<=eligible:break
        if unsafe or not allfiles or not allfiles<=eligible:continue
        try:contents=inventory(parent)
        except (ValueError,OSError):continue
        if contents:results[parent]=contents
    return results
