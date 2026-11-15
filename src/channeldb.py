# -*- coding: utf-8 -*-
"""全国 IPTV 组播参考库。
数据：社区开源仓库 xisohi/CHINA-IPTV（31省×电信/联通/移动/广电，每日更新）+ 浙江电信实测校验。
加载顺序：程序目录外部 refdb.json(.gz)（在线更新/手动导入产物）→ 内嵌 refdb.json.gz。
仅含组播地址与频道名等公开信息，不含任何账号/个人数据。
"""
import gzip
import json
import os
import re
import sys
import time

PROV = {
    'anhui': '安徽', 'beijing': '北京', 'chongqing': '重庆', 'fujian': '福建',
    'gansu': '甘肃', 'guangdong': '广东', 'guangxi': '广西', 'guizhou': '贵州',
    'hainan': '海南', 'hebei': '河北', 'heilongjiang': '黑龙江', 'henan': '河南',
    'hubei': '湖北', 'hunan': '湖南', 'jiangsu': '江苏', 'jiangxi': '江西',
    'jilin': '吉林', 'liaoning': '辽宁', 'neimenggu': '内蒙古', 'ningxia': '宁夏',
    'qinghai': '青海', 'shaanxi': '陕西', 'shandong': '山东', 'shanghai': '上海',
    'shanxi': '山西', 'sichuan': '四川', 'tianjin': '天津', 'xinjiang': '新疆',
    'xizang': '西藏', 'yunnan': '云南', 'zhejiang': '浙江',
}
CARRIER = {'telecom': '电信', 'unicom': '联通', 'mobile': '移动', 'broadent': '广电'}
URL_RE = re.compile(r'(?:udp|rtp)://@?(\d+\.\d+\.\d+\.\d+):(\d+)')


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _embedded_path():
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'refdb.json.gz')


_DB = None
_DB_ORIGIN = '内置'
_INDEX = None


def _load_file(path):
    if path.endswith('.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def db():
    global _DB, _DB_ORIGIN, _INDEX
    if _DB is not None:
        return _DB
    for name in ('refdb.json', 'refdb.json.gz'):
        p = os.path.join(app_dir(), name)
        if os.path.exists(p):
            try:
                d = _load_file(p)
                if d.get('format') == 'wushuang-iptv-refdb' and d.get('regions'):
                    _DB, _DB_ORIGIN = d, '外部更新'
                    break
            except (OSError, ValueError, gzip.BadGzipFile):
                continue
    if _DB is None:
        try:
            _DB = _load_file(_embedded_path())
            _DB_ORIGIN = '内置'
        except (OSError, ValueError):
            _DB = {'format': 'wushuang-iptv-refdb', 'version': 1, 'updated': '',
                   'sources': [], 'files': [], 'regions': []}
            _DB_ORIGIN = '空'
    _INDEX = {}
    for r in _DB.get('regions', []):
        for c in r.get('channels', []):
            k = (c['group'], c['port'])
            old = _INDEX.get(k)
            # 实测可用的优先，其次先到
            if old is None or (c.get('ok') and not old.get('ok')):
                _INDEX[k] = dict(c, province=r['province'], carrier=r['carrier'])
    return _DB


def reload_db():
    global _DB, _INDEX
    _DB = None
    _INDEX = None
    return db()


def db_info():
    d = db()
    n = sum(len(r.get('channels', [])) for r in d.get('regions', []))
    provs = {r['province'] for r in d.get('regions', [])}
    return {'updated': d.get('updated', '?'), 'origin': _DB_ORIGIN,
            'regions': len(d.get('regions', [])), 'channels': n, 'provinces': len(provs)}


def provinces():
    seen = []
    for r in db().get('regions', []):
        if r['province'] not in seen:
            seen.append(r['province'])
    return sorted(seen)


def carriers(province):
    out = []
    for r in db().get('regions', []):
        if r['province'] == province:
            label = r['carrier'] + (('（%s）' % r['note']) if r.get('note') else '')
            out.append((label, r['carrier'], len(r.get('channels', []))))
    return out


def channels_for(province, carrier):
    out = []
    for r in db().get('regions', []):
        if r['province'] == province and r['carrier'] == carrier:
            for c in r.get('channels', []):
                out.append({'name': c['name'], 'group': c['group'], 'port': c['port'],
                            'cat': c.get('cat') or '其他频道', 'ok': False,
                            'video': None, 'audio': None, 'res': None, 'sdt_name': '',
                            'source': 'ref', 'ref_ok': c.get('ok'),
                            'ref_video': c.get('video'), 'ref_res': c.get('res')})
    return out


def lookup(group, port):
    db()
    return _INDEX.get((group, port))


def normalize_name(name):
    """SDT/参考名规范化：CCTV-1综合 → CCTV1 等。"""
    if not name:
        return ''
    s = name.strip()
    m = re.match(r'^CCTV[-\s]?(\d+)\s*[\u4e00-\u9fff]*$', s, re.I)
    if m:
        return 'CCTV' + m.group(1)
    m = re.match(r'^CCTV[-\s]?(\d+)\s*\+', s, re.I)
    if m:
        return 'CCTV%s+' % m.group(1)
    s = re.sub(r'[\s\u3000]+', '', s)
    return s


def guess_category(name, sdt_type=None):
    n = (name or '').upper()
    if '4K' in n or '超高清' in n:
        return '4K超高清'
    if 'CCTV' in n or '央视' in n or 'CGTN' in n:
        return '央视'
    if '卫视' in n:
        return '卫视'
    if '广播' in n or '之声' in n or '调频' in n:
        return '广播频道'
    if '购物' in n:
        return '电视购物'
    if sdt_type in (0x02, 0x0A, 0x12):
        return '广播频道'
    return '其他频道'


def apply_verify_result(ch, r):
    """把 verify.verify_channel 的结果写回频道 dict（GUI 与 CLI 共用同一套命名规则）。
    实测成功且拿到 SDT 名时自动命名；参考库已有名字/用户改过的名字不覆盖。"""
    ch['ok'] = r['ok']
    ch['tested'] = True
    ch['video'] = r['video']
    ch['audio'] = r['audio']
    ch['res'] = r['res']
    ch['sdt_name'] = r['sdt_name']
    if r['ok'] and r['sdt_name'] and not ch.get('user_named'):
        nm = normalize_name(r['sdt_name'])
        ref = lookup(ch['group'], ch['port'])
        if not ref:
            ch['name'] = nm
            if not ch.get('user_catted'):
                ch['cat'] = guess_category(nm)
    return ch


def guess_cat(name, genre):
    n = (name or '').upper()
    g = genre or ''
    if '4K' in n or '超高清' in n or '4K' in g:
        return '4K超高清'
    if 'CCTV' in n or '央视' in g or 'CGTN' in n:
        return '央视'
    if '卫视' in n or '卫视' in g:
        return '卫视'
    if '广播' in n or '之声' in n or '调频' in n or '广播' in g:
        return '广播频道'
    if '购物' in n:
        return '电视购物'
    if '地方' in g:
        return '地方'
    return '其他频道'


def parse_txt(data):
    """解析 DIYP txt（分类,#genre# / 频道名,url），只收组播地址。"""
    if isinstance(data, bytes):
        data = data.decode('utf-8', 'replace')
    out = []
    genre = ''
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith('#genre#'):
            genre = line.split(',')[0].strip()
            continue
        if ',' not in line:
            continue
        name, url = line.split(',', 1)
        name = name.strip()
        m = URL_RE.search(url)
        if not m or not name:
            continue
        g, p = m.group(1), int(m.group(2))
        if not (224 <= int(g.split('.')[0]) <= 239):
            continue
        out.append({'name': name, 'group': g, 'port': p, 'cat': guess_cat(name, genre)})
    return out


def build_db(file_texts, updated=None):
    """file_texts: {仓库路径 'Multicast/<prov>/<carrier>.txt': 文本} → 参考库 dict"""
    regions = []
    files = []
    for path in sorted(file_texts):
        m = re.match(r'Multicast/([^/]+)/([^/]+)\.txt$', path)
        if not m:
            continue
        prov_py, fn = m.group(1), m.group(2)
        if prov_py not in PROV:
            continue
        base = re.sub(r'[（(].*?[)）]', '', fn).strip()
        carrier = CARRIER.get(base)
        if not carrier:
            continue
        chans = parse_txt(file_texts[path])
        if not chans:
            continue
        seen = {}
        for c in chans:
            seen.setdefault((c['group'], c['port']), c)
        regions.append({'province': PROV[prov_py], 'carrier': carrier,
                        'note': '备用' if fn != base else '',
                        'channels': list(seen.values())})
        files.append(path)
    return {'format': 'wushuang-iptv-refdb', 'version': 1,
            'updated': updated or time.strftime('%Y-%m-%d'),
            'sources': ['xisohi/CHINA-IPTV（GitHub 社区维护）'],
            'files': files, 'regions': regions}


def save_external(d):
    path = os.path.join(app_dir(), 'refdb.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)
    return path
