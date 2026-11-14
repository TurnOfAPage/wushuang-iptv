# -*- coding: utf-8 -*-
"""构建全国参考库 refdb.json.gz：
- 数据源 xisohi/CHINA-IPTV（GitHub 每日自动更新，31省×电信/联通/移动/广电）
- 浙江电信叠加实测校验结果（可用性/编码/分辨率）
- 仅保留组播地址（224-239段），不含任何单播账号类信息
"""
import gzip
import io
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NAT = os.path.join(HERE, '..', 'ref', 'national')
VERIFY = os.path.join(HERE, '..', 'verify_results.json')

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


def parse_txt(path):
    """DIYP txt: 分类,#genre# / 频道名, url"""
    out = []
    genre = ''
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
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
            first = int(g.split('.')[0])
            if not (224 <= first <= 239):
                continue
            out.append({'name': name, 'group': g, 'port': p, 'cat': guess_cat(name, genre)})
    return out


def main():
    # 浙江实测校验表
    verified = {}
    try:
        for r in json.load(open(VERIFY, encoding='utf-8')):
            verified[(r['group'], r['port'])] = r
    except (OSError, ValueError):
        pass

    regions = []
    files_meta = []
    total = 0
    for prov in sorted(os.listdir(NAT)):
        pdir = os.path.join(NAT, prov)
        if not os.path.isdir(pdir) or prov not in PROV:
            continue
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith('.txt'):
                continue
            base = re.sub(r'[（(].*?[)）]', '', fn[:-4]).strip()
            carrier = CARRIER.get(base)
            if not carrier:
                continue
            path = os.path.join(pdir, fn)
            chans = parse_txt(path)
            if not chans:
                continue  # 空占位文件
            # 去重
            seen = {}
            for c in chans:
                seen.setdefault((c['group'], c['port']), c)
            chans = list(seen.values())
            note = '备用' if fn != base + '.txt' else ''
            # 浙江电信：叠加实测结果
            if prov == 'zhejiang' and carrier == '电信':
                for c in chans:
                    v = verified.get((c['group'], c['port']))
                    if v:
                        c['name'] = v['name']
                        c['cat'] = v['cat']
                        c['ok'] = v['ok']
                        c['video'] = v.get('video')
                        c['res'] = v.get('res')
                have = {(c['group'], c['port']) for c in chans}
                for k, v in verified.items():
                    if k not in have:
                        chans.append({'name': v['name'], 'group': k[0], 'port': k[1],
                                      'cat': v['cat'], 'ok': v['ok'],
                                      'video': v.get('video'), 'res': v.get('res')})
            regions.append({'province': PROV[prov], 'carrier': carrier, 'note': note,
                            'channels': chans})
            files_meta.append('Multicast/%s/%s' % (prov, fn))
            total += len(chans)

    db = {
        'format': 'wushuang-iptv-refdb',
        'version': 1,
        'updated': time.strftime('%Y-%m-%d'),
        'sources': ['xisohi/CHINA-IPTV（GitHub 社区维护，每日更新）', '浙江电信频道实测校验'],
        'files': files_meta,
        'regions': regions,
    }
    raw = json.dumps(db, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    gz = gzip.compress(raw, 9)
    out = os.path.join(HERE, 'refdb.json.gz')
    with open(out, 'wb') as f:
        f.write(gz)
    provs = sorted({r['province'] for r in regions})
    print('regions=%d channels=%d raw=%dKB gz=%dKB' % (len(regions), total, len(raw) // 1024, len(gz) // 1024))
    print('provinces(%d): %s' % (len(provs), ' '.join(provs)))
    for r in regions:
        if r['province'] in ('浙江', '广东', '北京'):
            okc = sum(1 for c in r['channels'] if c.get('ok'))
            print('  %s%s: %d 频道 (实测可用 %d)' % (r['province'], r['carrier'], len(r['channels']), okc))


if __name__ == '__main__':
    main()
