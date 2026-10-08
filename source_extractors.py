"""Versioned source adapter subset: RSS/Atom, JSON Feed and readable text.

No extra requests, tools or model calls. Source records remain unverified.
"""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

VERSION = 'yanxu.source-extractor.v1'
MAX_ITEMS = 120


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.hidden+=1
        if tag in ('p','br','li','div'):self.parts.append(' ')
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,value):
        if not self.hidden:self.parts.append(value)


def plain(value):
    parser=Plain();parser.feed(str(value or ''))
    return re.sub(r'\s+',' ',''.join(parser.parts)).strip()


def normalize(records,kind):
    if not isinstance(records,list) or not records or len(records)>MAX_ITEMS or kind not in ('rss','atom','json-feed'):
        raise ValueError('来源条目为空或超过 120 条，未静默截断')
    result=[];seen=set()
    for record in records:
        if not isinstance(record,dict):raise ValueError('来源条目不是对象')
        value={key:re.sub(r'\s+', ' ', str(record.get(key) or '')).strip() for key in ('id','title','url','date','summary')}
        if not value['id']:value['id']=hashlib.sha256((value['url']+'\n'+value['title']).encode()).hexdigest()
        if value['id'] in seen:raise ValueError('来源条目 ID 重复，无法可靠比较')
        seen.add(value['id'])
        if any(len(v)>16000 for v in value.values()):raise ValueError('来源单条材料过长，未静默截断')
        value['version']=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        result.append(value)
    result.sort(key=lambda r:r['id'])
    return {'schema_version':VERSION,'kind':kind,'items':result,'coverage':'仅解析本次返回的条目和列出的字段；未覆盖历史分页与链接正文'}


def extract(text,media):
    if 'json' in media:
        try:value=json.loads(text)
        except (ValueError,RecursionError) as error:raise ValueError('JSON 来源无法完整解析') from error
        if isinstance(value,dict) and isinstance(value.get('version'),str) and value['version'].startswith('https://jsonfeed.org/version/'):
            items=value.get('items')
            if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):raise ValueError('JSON Feed 条目格式不正确')
            return normalize([dict(id=r.get('id'),title=r.get('title'),url=r.get('url'),date=r.get('date_modified') or r.get('date_published'),summary=r.get('content_text') or plain(r.get('content_html')) or r.get('summary')) for r in items],'json-feed')
        return None  # Generic JSON retains the legacy whole-text reader.
    if 'xml' in media or '<rss' in text[:400] or '<feed' in text[:400]:
        if re.search(r'<!\s*(DOCTYPE|ENTITY)',text,re.I):raise ValueError('不读取含外部实体或 DTD 的来源')
        try:root=ET.fromstring(text)
        except ET.ParseError as error:raise ValueError('XML 来源无法完整解析') from error
        local=lambda tag:tag.rsplit('}',1)[-1]
        if local(root.tag) not in ('rss','feed','RDF'):return None
        entries=[element for element in root.iter() if local(element.tag) in ('item','entry')]
        rows=[]
        for entry in entries:
            def field(*names):
                return next((''.join(e.itertext()).strip() for e in entry if local(e.tag) in names),'')
            link=next((e.get('href') for e in entry if local(e.tag)=='link' and e.get('rel','alternate')=='alternate' and e.get('href')),None) or field('link')
            rows.append(dict(id=field('guid','id'),title=plain(field('title')),url=link,date=field('updated','pubDate','published'),summary=plain(field('description','summary','content'))))
        return normalize(rows,'atom' if local(root.tag)=='feed' else 'rss')
    return None


def comparable(structured):
    return '\n'.join('\n'.join(key+': '+item[key] for key in ('id','title','date','url','summary')) for item in structured['items'])


def changes(before,after):
    if not before or not after or before.get('kind')!=after.get('kind'):return None
    old={r['id']:r for r in before['items']};new={r['id']:r for r in after['items']}
    return {'added':[new[i] for i in sorted(new.keys()-old.keys())],
            'updated':[new[i] for i in sorted(new.keys()&old.keys()) if new[i]['version']!=old[i]['version']],
            'removed':[old[i] for i in sorted(old.keys()-new.keys())],
            'coverage':after['coverage'],'schema_version':VERSION}
