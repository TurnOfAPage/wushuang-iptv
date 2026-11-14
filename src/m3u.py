# -*- coding: utf-8 -*-
"""M3U 读写/合并/排序，支持 udp:// rtp:// 与 udpxy(HTTP) 三种格式。"""
import os
import re

CAT_ORDER = ['央视高清', '央视', '卫视高清', '卫视', '4K超高清', '地方高清', '地方',
             '国际标清', '影视剧场', '高清剧场', '广播频道', '电视购物', '付费',
             '游戏频道', '其他频道', '其他', '未分类']


def channel_url(ch, fmt='udp', udpxy_host='', udpxy_port=9999):
    g, p = ch['group'], ch['port']
    if fmt == 'rtp':
        return 'rtp://@%s:%d' % (g, p)
    if fmt == 'udpxy':
        return 'http://%s:%d/udp/%s:%d' % (udpxy_host, udpxy_port, g, p)
    return 'udp://@%s:%d' % (g, p)


def _nat_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


def sort_channels(channels):
    def key(ch):
        cat = ch.get('cat') or '未分类'
        ci = CAT_ORDER.index(cat) if cat in CAT_ORDER else len(CAT_ORDER)
        return (ci, _nat_key(ch.get('name') or ''), ch['group'], ch['port'])
    return sorted(channels, key=key)


def write_m3u(path, channels, fmt='udp', udpxy_host='', udpxy_port=9999,
              logo_base='', only_ok=True, header_extra=None):
    lines = ['#EXTM3U']
    if header_extra:
        lines.append(header_extra)
    n = 0
    for ch in sort_channels(channels):
        if only_ok and not ch.get('ok'):
            continue
        name = ch.get('name') or '%s:%d' % (ch['group'], ch['port'])
        cat = ch.get('cat') or '未分类'
        attrs = 'tvg-name="%s" group-title="%s"' % (name, cat)
        if ch.get('tvg_id'):
            attrs = 'tvg-id="%s" ' % ch['tvg_id'] + attrs
        if logo_base and ch.get('logo'):
            attrs += ' tvg-logo="%s/%s"' % (logo_base.rstrip('/'), ch['logo'])
        lines.append('#EXTINF:-1 %s,%s' % (attrs, name))
        lines.append(channel_url(ch, fmt, udpxy_host, udpxy_port))
        n += 1
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, path)
    return n


_URL_RE = re.compile(
    r'(?:udp|rtp)://@?(\d+\.\d+\.\d+\.\d+):(\d+)'
    r'|https?://[^/]+/(?:udp|rtp)/(\d+\.\d+\.\d+\.\d+):(\d+)')


def parse_url(url):
    m = _URL_RE.search(url)
    if not m:
        return None
    g = m.group(1) or m.group(3)
    p = int(m.group(2) or m.group(4))
    return g, p


def read_m3u(path):
    chans = []
    name, cat, logo, tvg_id = None, '', '', ''
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#EXTINF'):
                m = re.search(r'tvg-name="([^"]*)"', line)
                name = m.group(1) if m else line.split(',')[-1].strip()
                m = re.search(r'group-title="([^"]*)"', line)
                cat = m.group(1) if m else ''
                m = re.search(r'tvg-logo="([^"]*)"', line)
                logo = m.group(1) if m else ''
                m = re.search(r'tvg-id="([^"]*)"', line)
                tvg_id = m.group(1) if m else ''
            elif line and not line.startswith('#'):
                gp = parse_url(line)
                if gp:
                    chans.append({'name': name or '%s:%d' % gp, 'group': gp[0],
                                  'port': gp[1], 'cat': cat, 'ok': True,
                                  'logo': logo, 'tvg_id': tvg_id, 'source': 'import'})
                name, cat, logo, tvg_id = None, '', '', ''
    return chans


def merge_channels(old, new):
    """按 (group,port) 合并。原则：
    - 用户改过的名字/分类始终保留；
    - 已验证可用的频道不会被"未验证的候选"降级（载入参考库/导入时保护实测成果）；
    - 本轮新实测的结果（tested）优先；
    - 编码/分辨率/SDT 名取较新且非空者。
    """
    out = {(c['group'], c['port']): dict(c) for c in old}
    for c in new:
        k = (c['group'], c['port'])
        if k not in out:
            out[k] = dict(c)
            continue
        o = out[k]
        merged = dict(o)
        # 名字/分类：尊重用户自定义
        if c.get('name') and not o.get('user_named'):
            merged['name'] = c['name']
        if c.get('cat') and not o.get('user_catted'):
            merged['cat'] = c['cat']
        # 可用性：本轮实测优先；否则保留任一已验证结果，不被未验证候选覆盖
        if c.get('tested'):
            merged['ok'] = bool(c.get('ok'))
            merged['tested'] = True
        else:
            merged['ok'] = bool(o.get('ok') or c.get('ok'))
            merged['tested'] = bool(o.get('tested') or c.get('tested'))
        # 技术信息：取较新且非空者
        for x in ('video', 'audio', 'res', 'sdt_name', 'source'):
            if c.get(x):
                merged[x] = c[x]
        out[k] = merged
    return list(out.values())
