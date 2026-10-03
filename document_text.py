"""Opt-in, bounded document text extraction from already-authorized bytes.

The child receives bytes, never a user path. No OCR, network, Office automation,
or embedded-content execution. Process isolation is not an OS security sandbox.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

DOCUMENT_TYPES = {'.pdf', '.docx'}
PARSER_VERSION = 'document-text-v2/pypdf-6.19.0'
MAX_INPUT = 2 * 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
MAX_REPLY = 8 * 1024 * 1024
TIMEOUT = 12


def extract(raw, suffix):
    if suffix not in DOCUMENT_TYPES or len(raw) > MAX_INPUT:
        raise ValueError('文档格式不支持或超过2MB')
    environment = {k:v for k,v in os.environ.items() if k in
                   ('SYSTEMROOT','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','PATH')}
    # Ordinary files avoid blocked pipe writes; temporary content is private and
    # removed on close. No production state, credentials or file path is passed.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
        source.write(raw); source.seek(0)
        try:
            proc = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                str(Path(__file__).with_name('document_worker.py')), suffix],
                stdin=source, stdout=output, stderr=subprocess.DEVNULL,
                env=environment, timeout=TIMEOUT, close_fds=True)
        except subprocess.TimeoutExpired:
            raise ValueError('文档解析超时；保留未处理，不自动重试') from None
        if proc.returncode != 0:
            raise ValueError('文档解析失败或达到资源限制；未处理')
        if output.tell() > MAX_REPLY:
            raise ValueError('文档解析结果超过安全范围；未处理')
        output.seek(0)
        try:
            result = json.load(output)
        except (ValueError, UnicodeError):
            raise ValueError('文档解析结果无效；未处理') from None
    if not result.get('ok'):
        raise ValueError(result.get('error', '文档无法提取文字'))
    text = result.get('text')
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_TEXT:
        raise ValueError('文档没有可用文字或提取范围过大；未处理')
    metadata = result['metadata']
    metadata.update(parser_version=PARSER_VERSION, text_basis='extracted_utf8',
                    text_sha256='sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest())
    return text.encode('utf-8'), metadata
