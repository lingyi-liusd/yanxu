"""Private extraction child. Input is bytes on stdin; output is bounded JSON."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

LIMIT = 2 * 1024 * 1024
STREAM_LIMIT = 4 * 1024 * 1024
WHEELS = {
    'pypdf-6.19.0-py3-none-any.whl':'7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14',
    'typing_extensions-4.15.0-py3-none-any.whl':'f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548'}


class DocumentError(ValueError):
    """Only fixed, product-owned messages may cross the child boundary."""


def pdf_library():
    for name, expected in WHEELS.items():
        path = Path(__file__).parent / 'vendor' / name
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise DocumentError('随包PDF依赖缺失或校验不符')
        sys.path.insert(0, str(path))
    import pypdf
    return pypdf


class Text:
    def __init__(self):
        self.parts, self.units, self.size = [], [], 0

    def add(self, label, value):
        if not value.strip():
            return
        content = '\n[' + label + ']\n' + value + '\n'
        amount = len(content.encode('utf-8'))
        if self.size + amount > LIMIT or len(self.units) >= 2000:
            raise DocumentError('文档文字超过2MB或2000段限制；请拆分')
        self.units.append({'label':label,'start':self.size,'end':self.size + amount})
        self.parts.append(content); self.size += amount

    def finish(self, metadata):
        if not self.parts:
            raise DocumentError('没有可提取文字；扫描件需要OCR，未标为已读')
        metadata['units'] = self.units
        return {'ok':True,'text':''.join(self.parts),'metadata':metadata}


def extract_pdf(raw):
    if not raw.startswith(b'%PDF-'):
        raise DocumentError('不是有效PDF文件')
    pdf = pdf_library()
    config = pdf.Configuration(maximum_declared_stream_length=STREAM_LIMIT,
        array_based_stream_maximum_output_length=STREAM_LIMIT,
        zlib_maximum_output_length=STREAM_LIMIT, lzw_maximum_output_length=STREAM_LIMIT,
        run_length_maximum_output_length=STREAM_LIMIT, jbig2_maximum_output_length=STREAM_LIMIT,
        image_maximum_buffer_size=STREAM_LIMIT, page_tree_maximum_entries=200,
        page_tree_maximum_depth=30, xform_maximum_invocations_per_extraction=300,
        jbig2dec_binary=None)
    text, gaps = Text(), []
    with pdf.apply_configuration(config):
        reader = pdf.PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise DocumentError('加密PDF未读取；请使用获授权的未加密副本')
        if len(reader.pages) > 100:
            raise DocumentError('PDF超过100页；请拆分后再授权')
        pages = len(reader.pages)
        for index, page in enumerate(reader.pages):
            value = page.extract_text() or ''
            if not value.strip():
                gaps.append('Page ' + str(index + 1) + ' 无文字层（可能是空白或扫描页）')
            else:
                contents = page.get_contents()
                operators = {op for _, op in contents.operations} if contents is not None else set()
                # XObjects alone miss inline images and vector drawing. A
                # successful text extraction never proves these visual objects.
                if (page.get('/Resources') and page['/Resources'].get_object().get('/XObject')
                        or operators & {b'INLINE IMAGE', b'Do', b'S', b's', b'f', b'F',
                                        b'f*', b'B', b'B*', b'b', b'b*', b'sh'}):
                    gaps.append('Page ' + str(index + 1) + ' 含图片或图形，未解释视觉内容')
                if page.get('/Annots'):
                    gaps.append('Page ' + str(index + 1) + ' 含批注或表单，未解释对象内容')
            text.add('Page ' + str(index + 1), value)
    return text.finish({'format':'pdf','complete':not gaps,'gaps':gaps,
        'pages':pages,'scope':'仅PDF文字层；不做OCR，不解析图表语义、公式或阅读顺序正确性'})


def extract_docx(raw):
    text, gaps = Text(), []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 2000 or sum(m.file_size for m in members) > 8 * LIMIT:
            raise DocumentError('DOCX压缩内容超过安全范围')
        names = [m.filename for m in members]
        if len(set(names)) != len(names):
            raise DocumentError('DOCX存在重复条目，拒绝歧义内容')
        for member in members:
            name = member.filename
            if name.startswith('/') or '\\' in name or '..' in name.split('/') or member.flag_bits & 1:
                raise DocumentError('DOCX路径或加密内容不安全')
            if member.file_size > 200 * max(1,member.compress_size):
                raise DocumentError('DOCX压缩比超过安全范围')
            if name.lower().endswith('vbaproject.bin'):
                raise DocumentError('宏文档不读取')
        if 'word/document.xml' not in names or '[Content_Types].xml' not in names:
            raise DocumentError('不是有效DOCX文档；旧doc格式不支持')
        parts = ['word/document.xml'] + sorted(n for n in names if re.fullmatch(
            r'word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml', n))
        namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        for part in parts:
            if archive.getinfo(part).file_size > LIMIT:
                raise DocumentError('DOCX XML超过安全范围')
            content = archive.read(part)
            # No-BOM UTF-16 is ASCII-decodable but still contains NUL bytes;
            # ElementTree would auto-detect it and bypass our UTF-8 DTD scan.
            if b'\x00' in content:
                raise DocumentError('DOCX XML编码不是UTF-8；未处理')
            try:
                xml=content.decode('utf-8-sig')
            except UnicodeError:
                raise DocumentError('DOCX XML编码不是UTF-8；未处理') from None
            if len(content) > LIMIT or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
                raise DocumentError('DOCX XML含实体声明或超过安全范围')
            document = ET.fromstring(xml)
            tags = {node.tag.rsplit('}',1)[-1] for node in document.iter()}
            omitted = sorted(tags & {'drawing','pict','object','oMath','oMathPara','del','ins',
                                    'commentRangeStart','altChunk','fldSimple','fldChar','instrText',
                                    'subDoc','contentPart','AlternateContent','sdt'})
            if omitted:
                gaps.append(part + ' 未解析对象：' + ', '.join(omitted))
            for index, paragraph in enumerate(document.iter(namespace + 'p'), 1):
                tokens = []
                for node in paragraph.iter():
                    if node.tag == namespace + 't': tokens.append(node.text or '')
                    elif node.tag == namespace + 'tab': tokens.append('\t')
                    elif node.tag in (namespace + 'br',namespace + 'cr'): tokens.append('\n')
                text.add(part + ' · Paragraph ' + str(index), ''.join(tokens))
        if any(n.startswith('word/embeddings/') or n.startswith('word/media/') for n in names):
            gaps.append('图片、嵌入对象未读取；外部链接不会打开')
    return text.finish({'format':'docx','complete':not gaps,'gaps':gaps,'parts':parts,
        'scope':'正文与表格段落、页眉页脚和脚注尾注文字；不执行Office，不打开外部链接，不解释修订、批注、布局、图形或公式'})


def restrict_child():
    # Defense in depth, not an OS sandbox. Only runtime/vendor imports may open
    # files. Document paths and secrets never reach this process.
    roots = [Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve(),
             (Path(__file__).parent / 'vendor').resolve()]
    def guard(event, args):
        if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn'):
            raise PermissionError('文档解析禁止网络和工具执行')
        if event == 'open' and isinstance(args[0], (str,bytes,os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1], args[2]
            if ((isinstance(mode,str) and any(c in mode for c in 'wa+'))
                    or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
                    or not any(path == root or root in path.parents for root in roots)):
                raise PermissionError('文档解析禁止访问其他文件')
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (8,8))
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * LIMIT,8 * LIMIT))
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,512 * 1024 * 1024))
    sys.addaudithook(guard)


if __name__ == '__main__':
    try:
        restrict_child()
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT: raise DocumentError('文档超过2MB')
        result = extract_pdf(raw) if sys.argv[1] == '.pdf' else extract_docx(raw) if sys.argv[1] == '.docx' else None
        if result is None: raise DocumentError('文档格式不支持')
    except Exception as exc:
        # Do not print parser exception messages that may include private text.
        result = {'ok':False,'error':str(exc) if isinstance(exc,DocumentError) else '文档结构损坏或解析受限；未处理'}
    sys.stdout.write(json.dumps(result,ensure_ascii=False,separators=(',',':')))
