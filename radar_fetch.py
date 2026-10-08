"""Bounded public-source reader. No browser cookies, proxies, local files or models."""
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import source_extractors
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES = 1024 * 1024
MAX_TEXT = 120000


def source_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        raise ValueError('请输入有效的公开网页地址')
    try:
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            raise ValueError()
        if u.port and u.port not in (80, 443):
            raise ValueError()
        host = u.hostname.encode('idna').decode('ascii')
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            if re.fullmatch(r'[0-9a-fA-F:.]+', host) or host.lower() in ('localhost',):
                raise ValueError()
        if '.' not in host:
            raise ValueError()
        netloc = ('[' + host + ']') if ':' in host else host
        if u.port:
            netloc += ':' + str(u.port)
        return urlunsplit((u.scheme, netloc, u.path or '/', u.query, ''))
    except (ValueError, UnicodeError):
        raise ValueError('雷达仅接受公开 HTTP/HTTPS 来源，不接受本机、内网或含凭据的地址')


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr', 'section'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li', 'section'):
            self.parts.append('\n')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def fetch_source(value):
    url = source_url(value)
    for _ in range(4):
        u = urlsplit(url)
        port = u.port or (443 if u.scheme == 'https' else 80)
        answers = socket.getaddrinfo(u.hostname, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(row[4][0] for row in answers))
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError('来源解析到了非公开地址，未读取')
        # Connect to the validated IP once; DNS cannot change between validation and connection.
        connection = http.client.HTTPConnection(u.hostname, port, timeout=12)
        raw_socket = socket.create_connection((addresses[0], port), timeout=12)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=u.hostname) if u.scheme == 'https' else raw_socket
            connection.request('GET', urlunsplit(('', '', u.path or '/', u.query, '')),
                               headers={'User-Agent': 'Yanxu-Radar/0.1', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('来源重定向缺少目标地址')
                url = source_url(urljoin(url, location))
                continue
            if response.status != 200:
                raise ValueError('来源返回 HTTP ' + str(response.status))
            if response.getheader('Content-Encoding', 'identity') not in ('identity', ''):
                raise ValueError('来源使用暂不支持的压缩格式')
            media = response.getheader('Content-Type', '').lower()
            if not any(part in media for part in ('text/', 'json', 'xml')):
                raise ValueError('首版支持网页、文本、RSS/XML 和 JSON，尚不读取该格式')
            content = response.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError('来源超过 1MB 上限，未截断保存')
            charset = re.search(r'charset=["\']?([\w-]+)', media)
            try:
                text = content.decode(charset.group(1) if charset else 'utf-8')
            except (LookupError, UnicodeError):
                raise ValueError('来源编码无法完整解析，未保存为完整快照')
            structured = source_extractors.extract(text, media)
            if structured:
                text = source_extractors.comparable(structured)
            elif 'html' in media:
                parser = Text()
                parser.feed(text)
                text = ''.join(parser.parts)
            text = '\n'.join(line for line in (re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()) if line)
            if not text:
                raise ValueError('来源没有可比较的文字，未覆盖旧快照')
            if len(text) > MAX_TEXT:
                raise ValueError('来源文字超过首版上限，未截断保存')
            return {'url': url, 'text': text, 'hash': hashlib.sha256(text.encode()).hexdigest(), 'bytes': len(content), 'structured': structured}
        finally:
            connection.close()
            raw_socket.close()
    raise ValueError('来源重定向次数超过上限')
