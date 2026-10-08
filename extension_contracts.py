"""Small versioned extension contracts, no extension code execution."""
import hashlib
import json
from radar_fetch import source_url


def bounded(value,label,maximum):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise ValueError(label+'为空或过长')
    return value.strip()


def source_pack(value):
    if not isinstance(value,dict) or set(value)!={'schema_version','name','question','sources'} or value.get('schema_version')!='yanxu.source-pack.v1':
        raise ValueError('来源包版本或字段不兼容；只支持 yanxu.source-pack.v1')
    name=bounded(value['name'],'来源包名称',100);question=bounded(value['question'],'关注问题',1000)
    sources=value['sources']
    if not isinstance(sources,list) or not 1<=len(sources)<=6:raise ValueError('来源包需要 1–6 个明确来源')
    result=[];seen=set()
    for source in sources:
        if not isinstance(source,dict) or set(source)!={'name','url','keywords','interval_minutes'}:raise ValueError('来源字段不符合契约')
        url=source_url(source['url'])
        if url in seen:raise ValueError('来源包有重复地址')
        seen.add(url);interval=source['interval_minutes'];keywords=source['keywords']
        if type(interval) is not int or not 15<=interval<=1440:raise ValueError('检查间隔必须在 15–1440 分钟之间')
        if not isinstance(keywords,list) or len(keywords)>12:raise ValueError('每个来源最多 12 个关键词')
        result.append({'name':bounded(source['name'],'来源名称',100),'url':url,'keywords':[bounded(k,'关键词',80) for k in keywords],'interval_minutes':interval})
    return {'schema_version':value['schema_version'],'name':name,'question':question,'sources':result}


def pack_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
