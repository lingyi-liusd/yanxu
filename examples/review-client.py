#!/usr/bin/env python3
"""External adapter example. Reads granted work; replies only with --reply FILE.

Requires the human-created project credential in YANXU_AGENT_TOKEN. No model,
file discovery, subprocess, background polling or automatic execution.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--core',default='http://127.0.0.1:8765')
    parser.add_argument('--room',help='Reply only to this requested room ID')
    parser.add_argument('--reply',type=Path,help='Explicit JSON reply file; omitted means read only')
    args=parser.parse_args();url=urlsplit(args.core)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password or url.path not in ('','/'):
        raise ValueError('Example supports only the loopback core')
    token=os.environ.get('YANXU_AGENT_TOKEN')
    if not token:raise ValueError('Set the project credential in YANXU_AGENT_TOKEN; never put it in a reply file')
    def core_api(path,body=None):
        req=urllib.request.Request(args.core.rstrip('/')+path,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            detail=json.loads(error.read());raise ValueError(str(error.code)+': '+detail.get('error','Request denied')) from None
    def api(path,body=None):return core_api('/api/agent/'+path,body)
    capability=core_api('/healthz').get('capabilities') or {}
    contracts=capability.get('contracts') or {}
    if capability.get('product')!='yanxu' or contracts.get('ecosystem')!=2 or contracts.get('external_reply')!=1:
        raise ValueError('Core contracts are incompatible; no project context or materials were requested')
    api('context') # Strict protocol handshake; no model call.
    requests=[r for r in api('ecosystem')['requests']
              if r.get('mode')=='review' and r.get('reply_tool')=='project.reply_review']
    if not args.reply:
        print(json.dumps({'requests':requests,'boundary':'Requests only; no execution or reply performed'},ensure_ascii=False,indent=2));return
    request=next((r for r in requests if r['room_id']==args.room),None)
    if not request:raise ValueError('Selected granted request is no longer available')
    if args.reply.stat().st_size>180000:raise ValueError('Reply file too large')
    output=json.loads(args.reply.read_text(encoding='utf-8'))
    body={k:request[k] for k in ('room_id','participant_id','run_id')};body['output']=output
    print(json.dumps(api('discussion/reply',body),ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:print(str(error),file=sys.stderr);raise SystemExit(1)
