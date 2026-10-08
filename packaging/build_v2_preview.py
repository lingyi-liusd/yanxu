"""Build one unified preview from verified owned beta runtimes; no downloads.

Original packages and installed apps are never changed. All runtime receipts are
fresh; source/UI tests and real-model/user acceptance remain separate.
"""
import argparse
import json
from pathlib import Path
import shutil
import finalize_beta as finalizer

VERSION='2026.10.05-v2.preview.8'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mac-runtime',type=Path,required=True,help='Owned beta.16 .app')
    parser.add_argument('--windows-runtime',type=Path,required=True,help='Owned unpacked beta.16 Windows folder')
    parser.add_argument('--work',type=Path,required=True,help='Fresh staging directory')
    parser.add_argument('--output',type=Path,required=True,help='Fresh unified preview deliverable directory')
    args=parser.parse_args();build=finalizer.build
    if args.work.exists() or args.output.exists():raise RuntimeError('Staging and output must be fresh')
    mac=args.mac_runtime.resolve();windows=args.windows_runtime.resolve()
    roots=[mac/'Contents/Resources',windows];manifests=[]
    for root,platform in zip(roots,('macos-arm64','windows-x64')):
        value=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if value.get('release')!='2026.10.03-beta.16' or value.get('platform')!=platform or value.get('contains_user_data') is not False:
            raise RuntimeError('Need the owned beta.16 package without user data')
        build.package_identity(root);manifests.append(value)
    if manifests[0]['dependencies']!=manifests[1]['dependencies']:raise RuntimeError('Runtime provenance differs between packages')
    args.work.mkdir(parents=True)
    seed=args.work/'seed';seed.mkdir()
    finalizer.clone_owned_build(mac,seed/'研序测试版.app')
    finalizer.clone_owned_build(windows,seed/'研序测试版-Windows-x64')
    # This is a new private staging copy; original public receipts remain intact.
    for root in (seed/'研序测试版.app/Contents/Resources',seed/'研序测试版-Windows-x64'):
        value=json.loads((root/'manifest.json').read_text());value['private_beta']=True
        (root/'manifest.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
    build.PREVIOUS_VERSION='2026.10.03-beta.16';build.VERSION=VERSION
    build.GUIDE_PATH='packaging/V2-PREVIEW-README.md';build.PREVIEW_DATA_NAME='ResearchDeskV2Preview'
    build.BUNDLE_IDENTIFIER='local.yanxu.researchdesk.v2preview'
    copy_code=build.copy_code
    def fresh_code(root):
        # finalize() has already verified and cloned the owned runtime seed.
        # Its public documentation extras are replaced only in this new copy.
        app=root/'app'
        if app.is_symlink():raise RuntimeError('Unsafe staged app directory')
        if app.exists():shutil.rmtree(app)
        return copy_code(root)
    build.copy_code=fresh_code
    receipt=finalizer.finalize(args.output,seed,manifests[0]['dependencies'])
    receipt['product']='yanxu';receipt['distribution']='unified';receipt['runtime_origin']='owned-public-beta.16'
    (args.output/'打包验收.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
