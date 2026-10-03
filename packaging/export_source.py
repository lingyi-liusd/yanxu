"""Explicit, public source snapshot; never exports Git or a user's profile."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import build_beta as build

ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md','AGENTS.md','AGENT-MANAGER.md','BETA-ACCEPTANCE.md',
        'BETA-PACKAGING.md','ARCHITECTURE-AUDIT.md','PROJECT-OS-MIGRATION.md',
        'PLUGIN.md','SECURITY.md','CONTRIBUTING.md','.gitignore',
        '.github/workflows/source-regression.yml','scripts/verify_release.py')


def export(destination):
    destination = Path(destination).absolute()
    archive = destination.with_suffix('.zip')
    if destination.exists() or archive.exists() or destination.is_symlink():
        raise ValueError('Refuse to overwrite an existing source snapshot')
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Export outside the source checkout')
    names = set(build.source_files()) | set(DOCS)
    names |= {'packaging/'+p.name for p in (ROOT/'packaging').iterdir()
              if p.suffix in ('.py','.swift','.md') and p.is_file()}
    names |= {'README.en.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'ROADMAP.md', 'CHANGELOG.md'}
    names |= {p.relative_to(ROOT).as_posix() for p in (ROOT/'docs').rglob('*') if p.is_file()}
    names |= {p.relative_to(ROOT).as_posix() for p in (ROOT/'examples').rglob('*') if p.is_file()}
    names |= {p.relative_to(ROOT).as_posix() for p in (ROOT/'.github').rglob('*') if p.is_file()}
    names |= {p.relative_to(ROOT).as_posix() for p in (ROOT/'scripts').glob('*.py') if p.is_file()}
    names |= {'tests/'+p.name for p in (ROOT/'tests').iterdir()
              if p.suffix in ('.py','.cjs') and p.is_file()}
    for name in names:
        source=ROOT/name
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError('Unsafe/missing source: '+name)
    destination.mkdir(parents=True)
    hashes={}
    for name in sorted(names):
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target)
        hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    manifest={'release':build.VERSION,'kind':'public-beta-source',
              'publish_authorized':True,'license_status':'MIT',
              'includes_user_data':False,'files':hashes,
              'acceptance':'Run scripts/verify_release.py from this exact snapshot; native and model gates separate.'}
    (destination/'SOURCE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for source in sorted(destination.rglob('*')):
            if source.is_file():z.write(source,str(Path(destination.name)/source.relative_to(destination)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip():raise ValueError('Archive CRC mismatch')
        for name,expected in hashes.items():
            if hashlib.sha256(z.read(destination.name+'/'+name)).hexdigest()!=expected:
                raise ValueError('Source/archive mismatch: '+name)
    print(json.dumps({'source':str(destination),'zip':str(archive),'files':len(hashes),
                      'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                      'license_status':manifest['license_status']},ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    export(parser.parse_args().output)
