"""Read Syncthing configuration/status with the host Python standard library.

Decky's frozen Python does not ship xml.etree. This short-lived helper keeps
XML parsing and credentials local; stdout contains only non-secret status.
"""
import json
from pathlib import Path
import sys
import urllib.request
from urllib.parse import urlencode
import xml.etree.ElementTree as ET


def status(home,refresh=False):
    home=Path(home);root=home/'Saves'
    for p in [home/'.local/state/syncthing/config.xml',home/'.config/syncthing/config.xml']:
        if not p.exists():continue
        cfg=ET.parse(p).getroot()
        folder=next((f for f in cfg.findall('folder') if Path(f.get('path','').replace('~',str(home),1)).resolve()==root.resolve()),None)
        if folder is None:return {'configured':False}
        result={'configured':True,'id':folder.get('id'),'label':folder.get('label'),'type':folder.get('type'),'devices':len(folder.findall('device'))}
        if refresh:
            gui=cfg.find('gui');address=gui.findtext('address','127.0.0.1:8384') if gui is not None else ''
            if not address.startswith(('127.0.0.1:','localhost:','[::1]:')):return {**result,'error':'Syncthing GUI is not bound to loopback'}
            scheme='https' if gui.get('tls')=='true' else 'http'
            url=scheme+'://'+address+'/rest/db/status?'+urlencode({'folder':folder.get('id')})
            try:
                request=urllib.request.Request(url,headers={'X-API-Key':gui.findtext('apikey','')})
                with urllib.request.urlopen(request,timeout=4) as r:result['status']=json.load(r)
            except Exception as exc:result['error']=str(exc)
        return result
    return {'configured':False}

if __name__=='__main__':
    try:print(json.dumps(status(sys.argv[1],len(sys.argv)>2 and sys.argv[2]=='refresh')))
    except Exception as exc:print(json.dumps({'configured':False,'error':str(exc)}))
