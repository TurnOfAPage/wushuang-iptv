# -*- coding: utf-8 -*-
"""公共 XMLTV 节目单（EPG）：拉取（仅用户主动触发，同 refdb update 模式）/
流式解析 / 频道映射 / 节目查询。录像预约的数据源；不碰运营商 EPG（需鉴权）。
缓存位于 record_dir：epg.xml.gz（原始）+ epg.json（映射后轻量缓存，未来 7 天）。
"""
import gzip
import io
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from channeldb import normalize_name

SOURCES = [
    # 2026-11 实测可用（epg.pw 旧 /api/epg.xml 已 404，改为 /xmltv/ 分国家路径）
    'https://epg.pw/xmltv/epg_CN.xml.gz',
    'https://epg.pw/xmltv/epg_CN.xml',
    'http://epg.51zmt.top:8000/e.xml',
    'https://epg.112114.xyz/pp.xml',
]
UA = {'User-Agent': 'wushuang-iptv-recorder'}
HORIZON_DAYS = 7
ISO_FMT = '%Y-%m-%dT%H:%M:%S'


def _iso(dt):
    return dt.strftime(ISO_FMT)


def norm(name):
    """EPG 与频道名双向归一：CCTV-1综合→CCTV1；湖南卫视高清→湖南卫视。"""
    s = normalize_name(name or '')
    s = re.sub(r'(高清|超高清|频道)$', '', s)
    return s


def fetch(url=None, progress_cb=None, timeout=30):
    """下载 XMLTV。返回 (source_url, xml_bytes)。逐个候选源尝试。"""
    urls = [url] if url else list(SOURCES)
    last = ''
    for u in urls:
        if progress_cb:
            progress_cb('epg_fetch', url=u)
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)
            if b'<tv' not in data[:4096]:
                raise ValueError('响应不是 XMLTV')
            return u, data
        except Exception as e:
            last = '%s: %s' % (u, e)
            if progress_cb:
                progress_cb('epg_source_failed', url=u, error=str(e))
    raise ValueError('所有 EPG 源均不可达（%s）。可用 --url 指定自定义 XMLTV 地址。' % last)


def _parse_time(s):
    """XMLTV 时间 'YYYYMMDDHHMMSS +0800' → 本地 naive datetime。"""
    s = (s or '').strip()
    if not s:
        return None
    try:
        if ' ' in s:
            dt = datetime.strptime(s, '%Y%m%d%H%M%S %z')
            return dt.astimezone().replace(tzinfo=None)
        return datetime.strptime(s[:14], '%Y%m%d%H%M%S')
    except ValueError:
        return None


def parse_xmltv(data):
    """流式解析（iterparse，防大文件爆内存）。
    返回 {'channels': {id: [display-name...]}, 'programmes': [(cid, start, stop, title, desc)]}。
    """
    channels = {}
    programmes = []
    ctx = ET.iterparse(io.BytesIO(data), events=('end',))
    for _, el in ctx:
        if el.tag == 'channel':
            cid = el.get('id', '')
            names = [n.text.strip() for n in el.findall('display-name') if n.text]
            if cid:
                channels[cid] = names
            el.clear()
        elif el.tag == 'programme':
            cid = el.get('channel', '')
            start = _parse_time(el.get('start'))
            stop = _parse_time(el.get('stop'))
            t = el.find('title')
            d = el.find('desc')
            if cid and start:
                programmes.append((cid, start, stop or start + timedelta(hours=1),
                                   (t.text or '').strip() if t is not None else '',
                                   (d.text or '').strip() if d is not None else ''))
            el.clear()
    return {'channels': channels, 'programmes': programmes}


def map_channels(channels, epg_channels):
    """工具频道列表 ↔ XMLTV 频道映射。返回 (mapped {归一名: cid}, unmapped [name...])。"""
    by_name = {}
    for cid, names in epg_channels.items():
        for n in names:
            k = norm(n)
            if k and k not in by_name:
                by_name[k] = cid
    mapped, unmapped = {}, []
    for ch in channels:
        name = ch.get('name', '')
        k = norm(name)
        cid = ch.get('tvg_id') if ch.get('tvg_id') in epg_channels else None
        if not cid:
            cid = by_name.get(k)
        if cid:
            mapped[k] = cid
        else:
            unmapped.append(name)
    return mapped, unmapped


def _default_filter(k):
    """未提供频道列表时的兜底过滤：只保留央视/卫视类频道，控制缓存体积。"""
    return bool(re.match(r'^(CCTV|CGTN)', k)) or k.endswith('卫视')


def update(record_dir, channels=None, url=None, progress_cb=None):
    """主动更新 EPG 缓存。返回结果 dict（ok/source/mapped/unmapped/programmes）。"""
    src, data = fetch(url, progress_cb)
    os.makedirs(record_dir, exist_ok=True)
    with open(os.path.join(record_dir, 'epg.xml.gz'), 'wb') as f:
        f.write(gzip.compress(data))
    if progress_cb:
        progress_cb('epg_parse', bytes=len(data))
    parsed = parse_xmltv(data)
    if channels:
        mapped, unmapped = map_channels(channels, parsed['channels'])
        keep = set(mapped.values())
        keys = {k: cid for k, cid in mapped.items()}
    else:
        keep = {cid for cid, names in parsed['channels'].items()
                if any(_default_filter(norm(n)) for n in names)}
        keys = {}
        for cid in keep:
            for n in parsed['channels'][cid]:
                k = norm(n)
                if _default_filter(k) and k not in keys:
                    keys[k] = cid
        unmapped = []
    now = datetime.now()
    horizon = now + timedelta(days=HORIZON_DAYS)
    out = {'updated': _iso(now), 'source': src, 'channels': {}}
    n = 0
    for cid, start, stop, title, desc in parsed['programmes']:
        if cid not in keep or start > horizon or stop < now - timedelta(days=1):
            continue
        k = next((kk for kk, vv in keys.items() if vv == cid), cid)
        lst = out['channels'].setdefault(k, [])
        lst.append({'title': title, 'start': _iso(start), 'stop': _iso(stop),
                    'desc': desc[:200]})
        n += 1
    for lst in out['channels'].values():
        lst.sort(key=lambda p: p['start'])
    tmp = os.path.join(record_dir, 'epg.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(record_dir, 'epg.json'))
    return {'ok': True, 'source': src, 'mapped': len(out['channels']),
            'unmapped': unmapped, 'programmes': n, 'updated': out['updated']}


def load(record_dir):
    try:
        with open(os.path.join(record_dir, 'epg.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def programs(record_dir, name):
    """某频道未来节目单（list of dict）；无缓存/未映射返回 []。"""
    d = load(record_dir)
    if not d:
        return []
    return d.get('channels', {}).get(norm(name), [])


def find_next(record_dir, name, title, date=None):
    """按节目名关键词查未来匹配节目（可选限定日期 YYYY-MM-DD）。返回节目 dict 或 None。"""
    now = datetime.now()
    for p in programs(record_dir, name):
        if title and title not in p.get('title', ''):
            continue
        try:
            start = datetime.fromisoformat(p['start'])
            stop = datetime.fromisoformat(p['stop'])
        except (ValueError, KeyError):
            continue
        if stop <= now:
            continue
        if date and start.strftime('%Y-%m-%d') != date:
            continue
        return p
    return None


def map_report(record_dir, channels):
    """映射报告：成功/失败清单（失败频道仍可手动时间段预约）。"""
    d = load(record_dir)
    if not d:
        return {'ok': False, 'error': '尚无 EPG 缓存，请先执行 epg update'}
    mapped, unmapped = [], []
    for ch in channels:
        k = norm(ch.get('name', ''))
        if k in d.get('channels', {}):
            mapped.append({'name': ch.get('name', ''), 'programs': len(d['channels'][k])})
        else:
            unmapped.append(ch.get('name', ''))
    return {'ok': True, 'updated': d.get('updated', ''), 'source': d.get('source', ''),
            'mapped': mapped, 'unmapped': unmapped}
