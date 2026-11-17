#!/usr/bin/env python3
"""Run the forked Decky Ludusavi backend and Savehaven web UI in a sandbox."""
import argparse
from pathlib import Path
import sys
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent / 'py_modules'))
from savehaven_service import Service, prepare

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--live', action='store_true', help='Use real Ludusavi saves and ~/Saves')
    parser.add_argument('--prepare-only', action='store_true')
    args=parser.parse_args()
    root=Path.home()/'SaveDemo';web=Path(__file__).resolve().parent/'web'
    if args.prepare_only:
        prepare(root,web);return
    if args.live:
        from live_backend import LiveService
        service=LiveService(Path.home(),web,args.port)
    else:service=Service(root,web,args.port)
    service.start()
    print(f'Savehaven fork: http://127.0.0.1:{args.port}',flush=True)
    print('Waiting for game-exit hooks. No periodic scans. '+('LIVE Ludusavi mode.' if args.live else 'Sandbox only.'),flush=True)
    try:threading.Event().wait()
    except KeyboardInterrupt:service.close()

if __name__=='__main__':main()
