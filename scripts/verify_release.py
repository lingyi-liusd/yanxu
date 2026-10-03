"""Dependency-free source regression entry. Does not invoke a real model."""
from pathlib import Path
import subprocess
import sys
import os

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    compile_js = "const fs=require('fs');let n=0;for(const b of fs.readFileSync('index.html','utf8').matchAll(/<script\\b[^>]*>([\\s\\S]*?)<\\/script>/g)){new Function(b[1]);n++;}if(!n)throw Error('No script blocks');console.log('Compiled script blocks:',n);"
    commands = [['node', '-e', compile_js],
                [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py']]
    commands += [['node', str(p)] for p in sorted((ROOT/'tests').glob('test_ui_*.cjs'))]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env)
        if result.returncode:
            return result.returncode
    print('Source regression passed; native/real-model/Windows/long-run gates remain separate.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
