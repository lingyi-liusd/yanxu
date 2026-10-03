"""Offline installation test: synthetic records only, no login/model/global config."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'app'))
import launcher
import source_bridge


def package_identity(root):
    value = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in value['files'].items():
        path = root / name
        if (not path.resolve().is_relative_to(root.resolve()) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise RuntimeError('安装测试文件已改变：' + name)
    return {'release': value['release'], 'platform': value['platform'],
            'files_sha256': hashlib.sha256(json.dumps(value['files'], sort_keys=True,
                separators=(',', ':')).encode()).hexdigest()}


def document_probe(python, env, flags, extract_documents=True):
    # Imports must resolve inside this package even if the host has pypdf or an
    # older Research Desk installed. Only synthetic in-memory documents are read.
    probe = '''import importlib, io, json, pathlib, sys, zipfile
app=pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0,str(app))
for name in ('pypdf-6.19.0-py3-none-any.whl','typing_extensions-4.15.0-py3-none-any.whl'):
    wheel=app/'vendor'/name
    if not wheel.is_file(): raise RuntimeError('Missing bundled document wheel: '+name)
    sys.path.insert(0,str(wheel))
modules={name:importlib.import_module(name) for name in ('pypdf','typing_extensions','document_text','document_worker')}
for name,module in modules.items():
    if not pathlib.Path(module.__file__).resolve().is_relative_to(app):
        raise RuntimeError('Document import escaped packaged code: '+name)
if modules['pypdf'].__version__!='6.19.0': raise RuntimeError('Unexpected pypdf version')
result={'pypdf':modules['pypdf'].__version__,'modules':list(modules),'extraction':'NOT_RUN_FIXTURE'}
if sys.argv[2]=='extract':
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=modules['pypdf'].PdfWriter()
    page=writer.add_blank_page(width=200,height=200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 10 100 Td (SYNTHETIC_PDF_INSTALL_CHECK) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(content)
    pdf=io.BytesIO();writer.write(pdf)
    docx=io.BytesIO()
    with zipfile.ZipFile(docx,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SYNTHETIC_DOCX_INSTALL_CHECK</w:t></w:r></w:p></w:body></w:document>')
    for raw,suffix,marker in ((pdf.getvalue(),'.pdf',b'SYNTHETIC_PDF_INSTALL_CHECK'),(docx.getvalue(),'.docx',b'SYNTHETIC_DOCX_INSTALL_CHECK')):
        text,metadata=modules['document_text'].extract(raw,suffix)
        if marker not in text or metadata.get('format')!=suffix[1:]:
            raise RuntimeError('Bundled document extraction failed: '+suffix)
    try: modules['document_text'].extract(b'invalid synthetic PDF','.pdf')
    except ValueError: pass
    else: raise RuntimeError('Invalid synthetic PDF accepted')
    result['extraction']='SYNTHETIC_PDF_DOCX_AND_INVALID_PDF_PASS'
print(json.dumps(result))
'''
    result = subprocess.run([str(python), '-X', 'utf8', '-c', probe, str(ROOT / 'app'),
                             'extract' if extract_documents else 'fixture-import-only'],
                            env=env, check=True, capture_output=True, text=True,
                            encoding='utf-8', timeout=50, **flags)
    return json.loads(result.stdout)


def run():
    suffix = '.exe' if os.name == 'nt' else ''
    node = ROOT / 'runtime/node' / ('node'+suffix)
    codex = ROOT / 'runtime/codex/bin' / ('codex'+suffix)
    python = Path(sys.executable)
    if python.name == 'pythonw.exe':
        python = python.with_name('python.exe')
    report = {'kind':'offline-installation-test', 'model_calls':0, 'user_sources_read':False,
              'platform':sys.platform, 'python':sys.version.split()[0], 'checks':[],
              'package':package_identity(ROOT)}
    with tempfile.TemporaryDirectory(prefix='yanxu-install-test-') as directory:
        root = Path(directory).resolve()
        env = os.environ.copy()
        env.update(RESEARCH_DESK_DATA_DIR=directory, OPEN_BROWSER='0', CODEX_HOME=str(root/'isolated-codex'),
                   RESEARCH_DESK_SOURCE_CODEX_HOME=str(root/'synthetic-sessions'),
                   RESEARCH_DESK_CODEX_BIN=str(codex), RESEARCH_DESK_NODE_BIN=str(node),
                   RESEARCH_DESK_RELEASE=report['package']['release'],
                   PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        for name in ('RESEARCH_DESK_AGENT_TOKEN', 'RESEARCH_DESK_BASE_URL', 'RESEARCH_FOCUS_API_URL',
                     'RESEARCH_FOCUS_API_KEY', 'RESEARCH_FOCUS_MODEL'):
            env.pop(name, None)
        (root/'isolated-codex').mkdir()
        flags = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        report['document_runtime'] = document_probe(python, env, flags)
        report['checks'].append('bundled-document-modules-pinned-wheels-synthetic-pdf-docx')
        for name, command in [('node', [str(node), '--version']), ('codex', [str(codex), '--version'])]:
            result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8',
                                    timeout=30, check=True, **flags)
            report[name] = result.stdout.strip()
        help_text = subprocess.check_output([str(codex), 'exec', '--help'], env=env, text=True,
                                             encoding='utf-8', timeout=30, **flags)
        for flag in ('--ignore-user-config', '--ignore-rules', '--ephemeral', '--output-schema'):
            if flag not in help_text:
                raise RuntimeError('CLI缺少隔离所需选项：'+flag)
        report['checks'].append('bundled-runtimes-and-isolation-flags')
        probe = '''import sys
sys.path.insert(0,sys.argv[1])
import agent_connection
client=agent_connection.RPC(sys.argv[2],sys.argv[3],agent_connection.profile())
try:
    client.call('initialize',{'clientInfo':{'name':'yanxu_offline_protocol_test','version':'1'}})
    client.send({'method':'initialized'})
    agent_connection.verify_profile(client.call('config/read',{'includeLayers':False}).get('config',{}))
    account=client.call('account/read',{'refreshToken':False})
    if account.get('account'):
        raise RuntimeError('隔离安装测试不应继承用户登录')
finally:
    client.close()
'''
        subprocess.run([str(python),'-X','utf8','-c',probe,str(ROOT/'app'),str(codex),str(root)],
                       env=env,check=True,capture_output=True,timeout=40,**flags)
        report['checks'].append('bundled-app-server-handshake-isolated-profile-no-login-no-turn')
        sample = root/'synthetic.md'
        sample.write_text('仅安装测试，无真实资料',encoding='utf-8')
        if source_bridge.secure_read(sample,root,1024) != sample.read_bytes():
            raise RuntimeError('安全文件读取失败')
        try:
            source_bridge.secure_read(root.parent/'outside.md',root,1024)
        except (OSError,ValueError):
            pass
        else:
            raise RuntimeError('文件范围保护失败')
        report['checks'].append('secure-file-read-and-escape-rejection')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        env['PORT']=str(port)
        url='http://127.0.0.1:'+str(port)+'/'
        args=[str(python),'-X','utf8',str(ROOT/'app/launcher.py'),'--no-open']
        pid=None
        try:
            children=[subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**flags) for _ in range(2)]
            for child in children:
                output,error=child.communicate(timeout=30)
                if child.returncode:
                    raise RuntimeError('并发启动失败：'+error.decode('utf-8',errors='replace'))
            current=launcher.health(url)
            if not current:
                raise RuntimeError('安装测试服务没有启动')
            pid=current['pid']
            token=(root/'api-token').read_text().strip()
            request=urllib.request.Request(url+'api/state',headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(request,timeout=5) as response:
                state=json.load(response)
            if state['projects'] or state['tasks']:
                raise RuntimeError('全新启动不应携带项目数据')
            report['checks'].append('fresh-empty-state-and-concurrent-single-instance')
            request=urllib.request.Request(url+'api/agent-connection',headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(request,timeout=5) as response:
                connection=json.load(response)
            if connection.get('enabled') or connection.get('configured'):
                raise RuntimeError('全新安装不应继承常驻连接授权')
            report['checks'].append('persistent-connection-default-off')
            try:
                urllib.request.urlopen(url+'api/state',timeout=5)
            except urllib.error.HTTPError as error:
                if error.code != 401:
                    raise
            else:
                raise RuntimeError('API缺少鉴权')
            report['checks'].append('unauthenticated-state-denied')
            env['RESEARCH_DESK_BASE_URL']=url.rstrip('/')
            messages='\n'.join(json.dumps(m) for m in [
                {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'installation-test','version':'1'}}},
                {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}])+'\n'
            result=subprocess.run([str(node),str(ROOT/'app/mcp-server.js')],input=messages,
                                  env=env,text=True,capture_output=True,encoding='utf-8',timeout=15,**flags)
            replies=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            if result.returncode or not any(r.get('id')==2 and r.get('result',{}).get('tools') for r in replies):
                raise RuntimeError('内置MCP启动失败')
            report['checks'].append('bundled-node-mcp-initialize-and-tools-list')
            subprocess.run(args,env=env,capture_output=True,check=True,timeout=10,**flags)
            if launcher.health(url)['pid'] != pid:
                raise RuntimeError('重复启动产生多实例')
        finally:
            if pid is None:
                current=launcher.health(url)
                if current: pid=current['pid']
            if pid:
                if os.name=='nt':
                    subprocess.run(['taskkill.exe','/PID',str(pid),'/F'],capture_output=True,**flags)
                else:
                    os.kill(pid,signal.SIGTERM)
                import time
                for _ in range(40):
                    if not launcher.health(url):break
                    time.sleep(.1)
    if package_identity(ROOT) != report['package']:
        raise RuntimeError('安装测试期间代码或运行库变化；回执无效')
    report['checks'].append('exact-package-files-unchanged-through-test')
    report['status']='PASS'
    return report


if __name__=='__main__':
    try:
        value=run()
    except Exception as error:
        value={'status':'FAIL','error':str(error),'model_calls':0}
    output=json.dumps(value,ensure_ascii=False,indent=2)
    if '--report' in sys.argv:
        destination=Path(sys.argv[sys.argv.index('--report')+1])
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(output,encoding='utf-8')
    else:
        print(output)
    sys.exit(0 if value['status']=='PASS' else 1)
