import json, os, pathlib, signal, socket, subprocess, sys, tempfile, unittest, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
class LauncherCase(unittest.TestCase):
 def test_concurrent_launches_survive_launcher_exit_and_reuse_one_service(self):
  with tempfile.TemporaryDirectory(prefix='desk-launcher-') as data:
   sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
   env=os.environ.copy();env.update(RESEARCH_DESK_DATA_DIR=data,PORT=str(port));env.pop('OPEN_BROWSER',None)
   args=[sys.executable,str(ROOT/'launcher.py'),'--no-open']
   children=[subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
   server_pid=None
   try:
    for p in children:
     out,err=p.communicate(timeout=12);self.assertEqual(p.returncode,0,(out,err))
    url='http://127.0.0.1:'+str(port)+'/'
    with urllib.request.urlopen(url,timeout=3) as r:self.assertEqual(r.status,200)
    token=(pathlib.Path(data)/'api-token').read_text().strip()
    req=urllib.request.Request(url+'api/state',headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,timeout=3) as r:self.assertEqual(json.loads(r.read())['projects'],[])
    raw=subprocess.check_output(['/usr/sbin/lsof','-t','-iTCP:'+str(port),'-sTCP:LISTEN'],text=True)
    pids=raw.split();self.assertEqual(len(pids),1);server_pid=int(pids[0])
    repeat=subprocess.run(args,env=env,capture_output=True,text=True,timeout=5);self.assertEqual(repeat.returncode,0)
    self.assertEqual(raw,subprocess.check_output(['/usr/sbin/lsof','-t','-iTCP:'+str(port),'-sTCP:LISTEN'],text=True))
   finally:
    if server_pid is None:
     try:server_pid=int(subprocess.check_output(['/usr/sbin/lsof','-t','-iTCP:'+str(port),'-sTCP:LISTEN'],text=True).strip())
     except (ValueError,subprocess.CalledProcessError):pass
    if server_pid:os.kill(server_pid,signal.SIGTERM)
