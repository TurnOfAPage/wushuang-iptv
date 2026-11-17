# -*- coding: utf-8 -*-
"""无双IPTV抓源工具 · headless CLI（供 AI 工具 / 脚本命令行调用，v2.1 新增）

调用方式：
  WushuangIPTV-CLI.exe <子命令> [参数]          （Windows 控制台版，推荐 AI 工具使用）
  ./WushuangIPTV-CLI <子命令> [参数]            （Linux/macOS 控制台版）
  无双IPTV抓源工具.exe cli <子命令> [参数]   （GUI 版兼容入口，无控制台，须用 --out 取结果）
  python main.py cli <子命令> [参数]        （源码方式，全平台）

输出协议（对 AI 友好）：
  · stdout 只输出一个 JSON 结果文档（UTF-8）；
  · stderr 输出 JSON Lines 进度/日志，不污染 stdout；
  · --out FILE 把结果 JSON 原子写入文件（GUI 版 exe 无控制台时的取结果方式）；
  · 退出码：0=成功  1=运行失败  2=参数错误  3=需要管理员权限。

频道文件贯穿全流程：load/capture/analyze/verify 的结果 JSON 内含 channels 数组，
可直接作为下一步 verify / m3u / proxy 的 --channels 输入（也兼容 .m3u 与裸数组 JSON）。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture
import channeldb
import m3u
import naspush
import netutil
import proxy
import refupdate
import verify
from appinfo import APP_NAME, APP_VER, APP_VER_DISPLAY, BETA_NOTE


class AdminRequired(Exception):
    def __init__(self, msg, hint=''):
        super().__init__(msg)
        self.hint = hint


# ---------------- 输出协议 ----------------

def log(event, **kw):
    """stderr JSON Lines 进度（stdout 保持只有一个最终 JSON）。"""
    if sys.stderr is None:
        return
    rec = {'event': event, 'time': time.strftime('%H:%M:%S')}
    rec.update(kw)
    try:
        sys.stderr.write(json.dumps(rec, ensure_ascii=False) + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def result(command, ok=True, **payload):
    d = {'ok': ok, 'tool': APP_NAME, 'version': APP_VER_DISPLAY, 'command': command}
    if BETA_NOTE:
        d['beta_note'] = BETA_NOTE
    d.update(payload)
    return d


def _write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)


def emit(obj, out_path=None):
    if out_path:
        d = os.path.dirname(os.path.abspath(out_path))
        if d:
            os.makedirs(d, exist_ok=True)
        _write_json(out_path, obj)
    if sys.stdout is not None:
        try:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
            sys.stdout.flush()
        except Exception:
            pass


# ---------------- 频道文件读写 ----------------

def read_channels(path):
    """接受：本工具结果 JSON（含 channels）/ 裸数组 JSON / .m3u/.m3u8。"""
    if path.lower().endswith(('.m3u', '.m3u8')):
        return m3u.read_m3u(path)
    with open(path, encoding='utf-8-sig') as f:
        d = json.load(f)
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get('channels'), list):
        return d['channels']
    raise ValueError('无法识别的频道文件（需要含 channels 的 JSON、裸数组 JSON 或 m3u）: %s' % path)


def resolve_region(prov, carrier):
    """省份/运营商支持中文或拼音（zhejiang/telecom）。"""
    prov = channeldb.PROV.get(prov, prov)
    carrier = channeldb.CARRIER.get(carrier, carrier)
    provs = channeldb.provinces()
    if prov not in provs:
        raise ValueError('未知省份 %r，可选: %s' % (prov, '、'.join(provs)))
    cs = [c for _, c, _ in channeldb.carriers(prov)]
    if carrier not in cs:
        raise ValueError('%s 没有运营商 %r，可选: %s' % (prov, carrier, '、'.join(cs)))
    return prov, carrier


def flows_to_channels(r):
    """抓包分析结果 → 频道候选（与 GUI「加入频道列表」同一套规则：
    跳过噪声流；参考库自动命名；仅 IGMP 加组无流的按主流端口推测）。"""
    real = [f for f in r['flows'] if not f['noise']]
    common_port = 5140
    if real:
        ports = {}
        for f in real:
            ports[f['port']] = ports.get(f['port'], 0) + f['pkts']
        common_port = max(ports, key=ports.get)
    chans, seen = [], set()

    def add(g, p, source):
        if (g, p) in seen:
            return
        seen.add((g, p))
        ref = channeldb.lookup(g, p)
        chans.append({'name': ref['name'] if ref else '未知频道(%s)' % g,
                      'group': g, 'port': p,
                      'cat': (ref.get('cat') if ref else '') or '未分类',
                      'ok': False, 'video': None, 'audio': None, 'res': None,
                      'sdt_name': '', 'source': source,
                      'ref_ok': ref.get('ok') if ref else None})

    for f in real:
        add(f['group'], f['port'], 'cap')
    flow_groups = {f['group'] for f in r['flows']}
    for g in r['joins']:
        if g not in flow_groups and not g.startswith('224.0.0.'):
            add(g, common_port, 'cap-igmp')
    return chans, common_port


def _analyze_to_result(command, path):
    if path.lower().endswith('.etl'):
        if not netutil.IS_WIN:
            return result(command, ok=False,
                          error='etl 是 Windows pktmon 抓包产物，请在 Windows 上分析，或提供 pcap/pcapng 文件')
        pm = capture.Pktmon(os.path.dirname(os.path.abspath(path)))
        pm.etl = path
        pm.pcap = path + '.pcap'
        ok, p = pm.convert()
        if not ok:
            return result(command, ok=False, error=p)
        path = p
    log('analyze_start', file=path)
    r = capture.analyze(path, progress_cb=lambda n: log('analyze_progress', packets=n))
    chans, common_port = flows_to_channels(r)
    payload = {'channels': chans, 'stats': r['stats'],
               'flows': r['flows'], 'joins': r['joins'],
               'igmp_only_port_guess': common_port}
    if r.get('stb'):
        payload['stb'] = r['stb']
        payload['privacy_note'] = 'stb 含机顶盒账号信息，仅限本机使用，分享结果前请脱敏'
    return result(command, **payload)


# ---------------- 子命令 ----------------

def cmd_info(args):
    ifaces = netutil.list_interfaces()
    backend, backend_path = netutil.capture_backend()
    return result('info',
                  admin=netutil.is_admin(),
                  platform=sys.platform,
                  pktmon=netutil.pktmon_path(),
                  capture_backend=backend,
                  capture_backend_path=backend_path,
                  app_dir=channeldb.app_dir(),
                  interfaces=ifaces,
                  suggested_multicast_iface=netutil.pick_multicast_iface(ifaces),
                  suggested_udpxy_host=netutil.lan_ip_for_udpxy(ifaces),
                  refdb=channeldb.db_info(),
                  commands=['info', 'ifaces', 'refdb info|carriers|update|import',
                            'load', 'verify', 'capture', 'analyze', 'm3u',
                            'proxy', 'push'])


def cmd_ifaces(args):
    ifaces = netutil.list_interfaces()
    return result('ifaces', interfaces=ifaces,
                  suggested_multicast_iface=netutil.pick_multicast_iface(ifaces),
                  suggested_udpxy_host=netutil.lan_ip_for_udpxy(ifaces))


def cmd_refdb(args):
    if args.action == 'info':
        return result('refdb info', refdb=channeldb.db_info(),
                      provinces=channeldb.provinces())
    if args.action == 'carriers':
        if not args.province:
            raise ValueError('refdb carriers 需要 --province')
        prov = channeldb.PROV.get(args.province, args.province)
        cs = [{'carrier': c, 'label': lbl, 'channels': n}
              for lbl, c, n in channeldb.carriers(prov)]
        if not cs:
            raise ValueError('未知省份 %r，可选: %s' % (prov, '、'.join(channeldb.provinces())))
        return result('refdb carriers', province=prov, carriers=cs)
    if args.action == 'update':
        log('refdb_update_start')
        ok, msg = refupdate.fetch_online(
            progress_cb=lambda d, t, txt: log('refdb_update_progress', done=d, total=t, file=txt))
        return result('refdb update', ok=ok, message=msg, refdb=channeldb.db_info())
    if args.action == 'import':
        if not args.file:
            raise ValueError('refdb import 需要 --file')
        msg = refupdate.import_file(args.file)
        return result('refdb import', message=msg, refdb=channeldb.db_info())
    raise ValueError('未知 refdb 动作: %s' % args.action)


def cmd_load(args):
    prov, carrier = resolve_region(args.province, args.carrier)
    chans = channeldb.channels_for(prov, carrier)
    return result('load', province=prov, carrier=carrier,
                  count=len(chans), channels=chans,
                  note='参考库只是候选，ok 均为 false，请用 verify 实测')


def cmd_verify(args):
    if args.channels:
        chans = read_channels(args.channels)
    elif args.group:
        if not args.port:
            raise ValueError('--group 需要同时指定 --port')
        ref = channeldb.lookup(args.group, args.port)
        chans = [{'name': ref['name'] if ref else '', 'group': args.group, 'port': args.port,
                  'cat': (ref.get('cat') if ref else '') or '未分类',
                  'ok': False, 'video': None, 'audio': None, 'res': None,
                  'sdt_name': '', 'source': 'manual'}]
    elif args.province and args.carrier:
        prov, carrier = resolve_region(args.province, args.carrier)
        chans = channeldb.channels_for(prov, carrier)
    else:
        raise ValueError('频道来源三选一：--channels FILE | --province P --carrier C | --group G --port P')
    if not chans:
        raise ValueError('频道列表为空')
    if args.limit and args.limit > 0:
        chans = chans[:args.limit]
    iface = args.iface or netutil.pick_multicast_iface(netutil.list_interfaces())
    if not iface:
        raise ValueError('未找到可用网卡，请用 --iface 指定组播网卡 IP（有线口，连接 IPTV 网络/桥接后的局域网）')
    log('verify_start', total=len(chans), iface=iface,
        timeout=args.timeout, concurrency=args.concurrency)

    def progress(done, total, ch, r):
        channeldb.apply_verify_result(ch, r)
        ch['error'] = r.get('error', '')
        ch['bytes'] = r.get('bytes', 0)
        log('verify_progress', done=done, total=total,
            group=ch['group'], port=ch['port'], ok=r['ok'])

    verify.verify_batch(chans, iface, concurrency=args.concurrency, timeout=args.timeout,
                        progress_cb=progress)
    ok_n = sum(1 for c in chans if c.get('ok'))
    return result('verify', iface=iface, total=len(chans), ok_count=ok_n,
                  failed_count=len(chans) - ok_n, channels=chans)


def cmd_capture(args):
    if netutil.IS_WIN:
        admin_msg = '抓包需要管理员权限（pktmon）'
        admin_hint = '在管理员 PowerShell/cmd 中运行本命令；verify/m3u/refdb 等其它子命令不需要管理员'
        missing_msg = '未找到 pktmon（需要 Windows 10 1809+ / Windows 11）'
    else:
        admin_msg = '抓包需要 root 权限（tcpdump）'
        admin_hint = '用 sudo 运行本命令；verify/m3u/refdb 等其它子命令不需要 root'
        missing_msg = '未找到 tcpdump（Linux: sudo apt install tcpdump；macOS 系统自带）'
    if not netutil.is_admin():
        raise AdminRequired(admin_msg, hint=admin_hint)
    workdir = args.workdir or os.path.join(channeldb.app_dir(), 'cap_temp')
    pm = capture.get_engine(workdir, iface=getattr(args, 'iface', None))
    if not pm.available():
        return result('capture', ok=False, error=missing_msg)
    ok, msg = pm.start()
    if not ok:
        return result('capture', ok=False, error=msg)
    log('capture_started', seconds=args.seconds, workdir=workdir)
    try:
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            time.sleep(min(5, max(0.1, deadline - time.time())))
            log('capture_progress', remaining=round(max(0, deadline - time.time())))
    except KeyboardInterrupt:
        pm.stop()
        pm.cleanup(keep_pcap=False)
        raise
    ok, msg = pm.stop()
    if not ok:
        return result('capture', ok=False, error=msg)
    ok, pcap = pm.convert()
    if not ok:
        return result('capture', ok=False, error=pcap)
    res = _analyze_to_result('capture', pcap)
    if args.keep_pcap:
        res['pcap'] = pcap
    pm.cleanup(keep_pcap=args.keep_pcap)
    return res


def cmd_analyze(args):
    if not os.path.exists(args.pcap):
        raise ValueError('抓包文件不存在: %s' % args.pcap)
    return _analyze_to_result('analyze', args.pcap)


def cmd_m3u(args):
    chans = read_channels(args.channels)
    if not chans:
        raise ValueError('频道列表为空')
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    name = args.name or 'iptv.m3u'
    host = args.host
    if not host:
        # 主格式即使是 udp，配对的 http 版也需要主机地址（与 GUI 默认行为一致）
        host = netutil.lan_ip_for_udpxy(netutil.list_interfaces())
    p = dict(fmt=args.fmt, udpxy_host=host or '', udpxy_port=args.port,
             logo_base=args.logo_base or '', only_ok=not args.all)
    path = os.path.join(outdir, name)
    merged = False
    if not args.no_merge and os.path.exists(path):
        try:
            old = m3u.read_m3u(path)
            chans = m3u.merge_channels(old, chans)
            merged = True
        except Exception:
            pass
    files = []
    n = m3u.write_m3u(path, chans, **p)
    files.append({'path': os.path.abspath(path), 'fmt': args.fmt, 'channels': n})
    if not args.no_pair:
        base, ext = os.path.splitext(name)
        if args.fmt == 'udpxy':
            p2, path2 = dict(p, fmt='udp'), os.path.join(outdir, base + '-udp' + ext)
        else:
            p2, path2 = dict(p, fmt='udpxy'), os.path.join(outdir, base + '-http' + ext)
        n2 = m3u.write_m3u(path2, chans, **p2)
        files.append({'path': os.path.abspath(path2), 'fmt': p2['fmt'], 'channels': n2})
    return result('m3u', files=files, merged=merged, only_ok=not args.all,
                  total_channels=len(chans))


def cmd_proxy(args):
    iface = args.iface or netutil.pick_multicast_iface(netutil.list_interfaces())
    if not iface:
        raise ValueError('未找到可用网卡，请用 --iface 指定组播网卡 IP')
    chan_path = args.channels

    def channels_cb():
        if not chan_path:
            return []
        try:
            return read_channels(chan_path)
        except Exception:
            return []

    srv = proxy.ProxyServer(iface, args.port, channels_cb)
    ok, msg = srv.start()
    if not ok:
        return result('proxy', ok=False, error=msg)
    base = 'http://%s:%d' % (iface, args.port)
    emit(result('proxy', running=True, message=msg, iface=iface, port=args.port,
                urls={'status': base + '/status',
                      'playlist_http': base + '/playlist.m3u',
                      'playlist_udp': base + '/raw.m3u',
                      'stream': base + '/udp/<组播地址>:<端口>'},
                note='服务在前台持续运行，Ctrl+C 停止；仅限局域网，禁止映射公网'), args.out)
    log('proxy_running', port=args.port, iface=iface)
    try:
        while srv.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    log('proxy_stopped')
    return None  # 启动 JSON 已输出，停止时不再重复输出


def cmd_push(args):
    if not args.files:
        raise ValueError('push 需要 --files')
    results = naspush.push_many(args.files, args.method, args.target,
                                args.user or '', args.password or '')
    pushed = [{'file': p, 'dest': d} for p, d in results if not str(d).startswith('失败')]
    failed = [{'file': p, 'error': d} for p, d in results if str(d).startswith('失败')]
    return result('push', ok=not failed, pushed=pushed, failed=failed)


# ---------------- 参数解析 ----------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog='wushuang-iptv',
        description='%s v%s · headless CLI（stdout=单个JSON结果, stderr=JSONL进度, '
                    '退出码 0成功/1失败/2参数错误/3需管理员）%s' % (APP_NAME, APP_VER_DISPLAY,
                                                                  (' ' + BETA_NOTE) if BETA_NOTE else ''))
    sub = ap.add_subparsers(dest='command', required=True)

    def common(p):
        p.add_argument('--out', metavar='FILE', help='结果 JSON 同时写入文件（GUI版exe无控制台时必需）')

    p = sub.add_parser('info', help='环境总览：管理员/抓包后端/网卡/参考库/建议网卡')
    common(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser('ifaces', help='列出网卡与建议的组播网卡')
    common(p)
    p.set_defaults(func=cmd_ifaces)

    p = sub.add_parser('refdb', help='全国参考库：info/carriers/update/import')
    p.add_argument('action', choices=['info', 'carriers', 'update', 'import'])
    p.add_argument('--province', help='carriers 动作必填，中文或拼音')
    p.add_argument('--file', help='import 动作必填：refdb.json(.gz) 路径')
    common(p)
    p.set_defaults(func=cmd_refdb)

    p = sub.add_parser('load', help='按省份+运营商载入参考库频道（候选，未实测）')
    p.add_argument('--province', required=True, help='省份，中文或拼音，如 浙江/zhejiang')
    p.add_argument('--carrier', required=True, help='运营商：电信/联通/移动/广电 或 telecom/unicom/mobile/broadent')
    common(p)
    p.set_defaults(func=cmd_load)

    p = sub.add_parser('verify', help='真实加组收流验证频道（自动命名/编码/分辨率）')
    p.add_argument('--channels', help='频道文件：load/capture/analyze 的结果 JSON 或 m3u')
    p.add_argument('--province', help='直接验证某省参考库（与 --carrier 连用）')
    p.add_argument('--carrier', help='运营商')
    p.add_argument('--group', help='只验证单个组播地址（与 --port 连用）')
    p.add_argument('--port', type=int, help='组播端口')
    p.add_argument('--iface', help='组播网卡 IP（缺省自动选有线口）')
    p.add_argument('--timeout', type=float, default=5.0, help='单频道收流超时秒数，默认5')
    p.add_argument('--concurrency', type=int, default=4, help='并发数，默认4')
    p.add_argument('--limit', type=int, default=0, help='只验证前 N 个频道（调试用）')
    common(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('capture', help='pktmon/tcpdump 抓包并分析出频道候选（Windows 需管理员，Linux/macOS 需 sudo）')
    p.add_argument('--seconds', type=int, default=90, help='抓包时长秒数，默认90；期间请让机顶盒换台')
    p.add_argument('--workdir', help='抓包临时目录，默认 程序目录/cap_temp')
    p.add_argument('--iface', help='抓包网卡（Linux/macOS：设备名或 IP；缺省 Linux=any，macOS=建议有线口）')
    p.add_argument('--keep-pcap', action='store_true', help='分析后保留 pcap 文件')
    common(p)
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser('analyze', help='分析已有抓包文件（pcap/pcapng/etl，不需管理员）')
    p.add_argument('--pcap', required=True, help='抓包文件路径')
    common(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser('m3u', help='生成/更新 M3U 播放列表（udp 主用 + http 配对）')
    p.add_argument('--channels', required=True, help='频道文件（verify 结果 JSON 或 m3u）')
    p.add_argument('--outdir', required=True, help='输出目录')
    p.add_argument('--name', default='iptv.m3u', help='文件名，默认 iptv.m3u')
    p.add_argument('--fmt', choices=['udp', 'rtp', 'udpxy'], default='udp', help='主格式，默认 udp')
    p.add_argument('--host', help='udpxy 主机 IP（缺省自动取本机局域网 IP）')
    p.add_argument('--port', type=int, default=9999, help='udpxy 端口，默认9999')
    p.add_argument('--logo-base', help='台标 URL 前缀（可选）')
    p.add_argument('--all', action='store_true', help='连未验证/不可用频道一起导出（默认只导出可用）')
    p.add_argument('--no-merge', action='store_true', help='不与目录中已有文件合并')
    p.add_argument('--no-pair', action='store_true', help='不生成配对格式文件')
    common(p)
    p.set_defaults(func=cmd_m3u)

    p = sub.add_parser('proxy', help='前台运行组播→HTTP转发服务（udpxy 等价，Ctrl+C 停止）')
    p.add_argument('--port', type=int, default=9999, help='监听端口，默认9999')
    p.add_argument('--iface', help='组播网卡 IP（缺省自动选有线口）')
    p.add_argument('--channels', help='频道文件，用于 /playlist.m3u（可省略）')
    common(p)
    p.set_defaults(func=cmd_proxy)

    p = sub.add_parser('push', help='推送播放列表文件到 NAS（SMB/WebDAV）')
    p.add_argument('--files', nargs='+', required=True, help='要推送的本地文件')
    p.add_argument('--method', choices=['smb', 'webdav', 'local'], default='smb')
    p.add_argument('--target', required=True, help='SMB 共享/映射盘路径 或 WebDAV 目录 URL')
    p.add_argument('--user', help='账号（可选）')
    p.add_argument('--password', help='密码（可选）')
    common(p)
    p.set_defaults(func=cmd_push)

    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    noconsole = sys.stdout is None  # GUI 版 exe（--noconsole）里 stdout/stderr 为 None
    if noconsole:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    out = getattr(args, 'out', None)
    if out is None and noconsole:
        out = os.path.join(os.getcwd(), 'cli-result.json')
    try:
        res = args.func(args)
        if res is None:  # proxy：启动 JSON 已输出
            return 0
        code = 0 if res.get('ok') else 1
    except AdminRequired as e:
        res = result(args.command, ok=False, error=str(e), hint=e.hint, need_admin=True)
        code = 3
    except KeyboardInterrupt:
        res = result(args.command, ok=False, error='已取消（Ctrl+C）')
        code = 1
    except Exception as e:
        res = result(args.command, ok=False, error='%s: %s' % (type(e).__name__, e))
        code = 1
    emit(res, out)
    return code


if __name__ == '__main__':
    sys.exit(main())
