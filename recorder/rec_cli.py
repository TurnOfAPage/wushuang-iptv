# -*- coding: utf-8 -*-
"""无双IPTV录像工具 · headless CLI（独立产品，复用 src/ 核心模块；主工具不受影响）

调用方式：
  WushuangIPTV-Recorder-CLI.exe <子命令> [参数]     （Windows 控制台版）
  ./WushuangIPTV-Recorder-CLI <子命令> [参数]       （Linux/macOS，NAS/软路由）
  无双IPTV录像工具.exe cli <子命令> [参数]          （GUI 版兼容入口，须用 --out 取结果）
  python rec_main.py cli <子命令> [参数]            （源码方式，全平台）

输出协议（与主工具 CLI 一致，对 AI 友好）：
  · stdout 只输出一个 JSON 结果文档（UTF-8）；stderr 输出 JSON Lines 进度；
  · --out FILE 把结果 JSON 原子写入文件；退出码 0成功 1失败 2参数错误。
  · 录像/预约/转发均不需要管理员（IGMP 续期自动回退 drop/re-add）。

频道来源：主工具 verify 结果 JSON / 裸数组 JSON / .m3u（read_channels 全兼容）。
典型 NAS 部署：
  WushuangIPTV-Recorder-CLI proxy --channels verified.json --record-dir /volume1/iptv/rec
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import channeldb
import epg
import m3u
import netutil
import proxy
import record
from recinfo import REC_NAME, REC_VER_DISPLAY, BETA_NOTE


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return HERE


def default_record_dir():
    return record.default_record_dir()


# ---------------- 输出协议（与主工具 cli.py 同约定） ----------------

def log(event, **kw):
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
    d = {'ok': ok, 'tool': REC_NAME, 'version': REC_VER_DISPLAY, 'command': command}
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


# ---------------- 频道解析 ----------------

def read_channels(path):
    if path.lower().endswith(('.m3u', '.m3u8')):
        return m3u.read_m3u(path)
    with open(path, encoding='utf-8-sig') as f:
        d = json.load(f)
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get('channels'), list):
        return d['channels']
    raise ValueError('无法识别的频道文件（需要含 channels 的 JSON、裸数组 JSON 或 m3u）: %s' % path)


def resolve_channel(args, chans=None):
    """--group/--port 直给，或 --name 在频道列表内归一化匹配。"""
    if getattr(args, 'group', None):
        if not getattr(args, 'port', None):
            raise ValueError('--group 需要同时指定 --port')
        ref = channeldb.lookup(args.group, args.port)
        return {'name': (getattr(args, 'name', '') or
                         (ref['name'] if ref else '未知频道(%s)' % args.group)),
                'group': args.group, 'port': args.port,
                'cat': (ref.get('cat') if ref else '') or '未分类'}
    name = getattr(args, 'name', '')
    if not name:
        raise ValueError('需要 --name 频道名（配合 --channels），或 --group G --port P')
    if chans is None:
        chans = read_channels(args.channels) if getattr(args, 'channels', None) else []
    k = channeldb.normalize_name(name)
    exact = [c for c in chans if channeldb.normalize_name(c.get('name', '')) == k]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError('频道名 %r 匹配到多个: %s' % (
            name, '、'.join('%s(%s:%s)' % (c['name'], c['group'], c['port']) for c in exact)))
    part = [c for c in chans if k and k in channeldb.normalize_name(c.get('name', ''))]
    if len(part) == 1:
        return part[0]
    if not chans:
        raise ValueError('未提供频道列表（--channels FILE），无法按名字定位频道；'
                         '也可用 --group G --port P 直给组播地址')
    raise ValueError('未找到频道 %r（候选 %d 个，可用 record list --channels 查看）' % (name, len(chans)))


def _iface(args, required=True):
    iface = getattr(args, 'iface', None) or netutil.pick_multicast_iface(netutil.list_interfaces())
    if not iface:
        if required:
            raise ValueError('未找到可用网卡，请用 --iface 指定组播网卡 IP（有线口，连接 IPTV 网络/桥接后的局域网）')
        return '127.0.0.1'  # 仅查询/写计划类操作，不会真正收流
    return iface


def _opt(args, name, env, default, cast=str):
    """CLI 参数 > 容器环境变量（IPTV_*）> 缺省值。docker exec 的管理命令与主进程配置保持一致。"""
    v = getattr(args, name, None)
    if v is None:
        v = os.environ.get(env, default)
    return cast(v)


def _manager(args, scheduler=False, channels_cb=None, need_iface=True):
    return record.RecordManager(
        getattr(args, 'record_dir', None) or default_record_dir(),
        _iface(args, required=need_iface), channels_cb=channels_cb,
        quota_gb=_opt(args, 'quota_gb', 'IPTV_QUOTA_GB', 100, float),
        pad_before=_opt(args, 'pad_before', 'IPTV_PAD_BEFORE', 60, int),
        pad_after=_opt(args, 'pad_after', 'IPTV_PAD_AFTER', 120, int),
        max_concurrent=_opt(args, 'max_concurrent', 'IPTV_MAX_CONCURRENT', 2, int),
        missed_policy=_opt(args, 'missed', 'IPTV_MISSED', 'skip'),
        progress_cb=lambda ev, **kw: log(ev, **kw), scheduler=scheduler)


# ---------------- 子命令 ----------------

def cmd_info(args):
    ifaces = netutil.list_interfaces()
    return result('info', admin=netutil.is_admin(), platform=sys.platform,
                  admin_required=False,
                  note='录像/预约/转发均不需要管理员权限',
                  interfaces=ifaces,
                  suggested_multicast_iface=netutil.pick_multicast_iface(ifaces),
                  suggested_udpxy_host=netutil.lan_ip_for_udpxy(ifaces),
                  default_record_dir=default_record_dir(),
                  commands=['info', 'record start|list|add|cancel|delete',
                            'epg update|show|map', 'proxy'])


def cmd_record(args):
    rd = args.record_dir or default_record_dir()
    if args.action == 'start':
        chans = read_channels(args.channels) if args.channels else None
        ch = resolve_channel(args, chans)
        if args.until:
            try:
                t = datetime.strptime(args.until, '%H:%M')
            except ValueError:
                raise ValueError('--until 格式应为 HH:MM')
            now = datetime.now()
            end = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if end <= now:
                end += timedelta(days=1)
            seconds = (end - now).total_seconds()
        else:
            seconds = args.seconds or args.minutes * 60
        mgr = _manager(args, scheduler=False)
        log('record_prepare', name=ch.get('name', ''), group=ch['group'],
            port=ch['port'], seconds=int(seconds), record_dir=rd)
        sch = mgr.record_now(ch, seconds=seconds)
        try:
            while True:
                mgr.poll()
                st = mgr.status()
                if not st['active']:
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            mgr.stop()
        finally:
            mgr.stop()
        rec = mgr.get_recording(sch['rid'])
        ok = bool(rec) and rec['status'] in ('done', 'partial')
        lan = netutil.lan_ip_for_udpxy(netutil.list_interfaces())
        return result('record start', ok=ok, recording=rec,
                      vod_url='http://%s:9999/vod/%s' % (lan, sch['rid']),
                      copyright_note=record.COPYRIGHT_NOTE,
                      note='vod_url 需 proxy --record-dir 同目录常驻服务在运行；'
                           '文件可直接用 VLC/Kodi 打开',
                      error=(rec or {}).get('error', ''))
    if args.action == 'list':
        mgr = _manager(args, scheduler=False, need_iface=False)
        return result('record list', record_dir=rd,
                      schedules=mgr.list_schedules(),
                      recordings=mgr.list_recordings(), status=mgr.status())
    if args.action == 'add':
        chans = read_channels(args.channels) if args.channels else None
        ch = resolve_channel(args, chans)
        if args.start and args.end:
            start, end = args.start, args.end
            title = ''
            source = 'manual'
        elif args.title:
            p = epg.find_next(rd, ch.get('name', ''), args.title, args.date)
            if not p:
                raise ValueError('EPG 中未找到 %r 的匹配节目 %r%s。请先 epg update，'
                                 '或改用 --start/--end 手动预约' % (
                                     ch.get('name', ''), args.title,
                                     ('（日期 %s）' % args.date) if args.date else ''))
            start, end, title, source = p['start'], p['stop'], p['title'], 'epg'
        else:
            raise ValueError('预约需要 --start S --end E（ISO 本地时间），或 --title 关键词（配合 EPG）')
        mgr = _manager(args, scheduler=False, need_iface=False)
        sch = mgr.add_schedule(ch, start, end, source=source, epg_title=title)
        return result('record add', schedule=sch,
                      note='计划已写入 %s；需常驻服务（proxy --record-dir 同目录，或 GUI 录像服务）到点执行' % rd)
    if args.action == 'cancel':
        if not args.id:
            raise ValueError('record cancel 需要 --id 计划ID')
        mgr = _manager(args, scheduler=False, need_iface=False)
        mgr.cancel(args.id)
        return result('record cancel', id=args.id)
    if args.action == 'delete':
        if not args.id:
            raise ValueError('record delete 需要 --id 录像ID')
        mgr = _manager(args, scheduler=False, need_iface=False)
        mgr.delete_recording(args.id)
        return result('record delete', id=args.id)
    raise ValueError('未知 record 动作: %s' % args.action)


def cmd_epg(args):
    rd = args.record_dir or default_record_dir()
    if args.action == 'update':
        chans = read_channels(args.channels) if args.channels else None
        r = epg.update(rd, chans, url=args.url,
                       progress_cb=lambda ev, **kw: log(ev, **kw))
        return result('epg update', **r)
    if args.action == 'show':
        if not args.name:
            raise ValueError('epg show 需要 --name')
        ps = epg.programs(rd, args.name)
        if args.date:
            ps = [p for p in ps if p['start'].startswith(args.date)]
        return result('epg show', name=args.name, count=len(ps), programs=ps)
    if args.action == 'map':
        if not args.channels:
            raise ValueError('epg map 需要 --channels FILE')
        r = epg.map_report(rd, read_channels(args.channels))
        return result('epg map', **r)
    raise ValueError('未知 epg 动作: %s' % args.action)


def cmd_proxy(args):
    iface = _iface(args)
    rd = args.record_dir or default_record_dir()
    chan_path = args.channels

    def channels_cb():
        if not chan_path:
            return []
        try:
            return read_channels(chan_path)
        except Exception:
            return []

    mgr = _manager(args, scheduler=True, channels_cb=channels_cb)
    mgr.start()
    srv = proxy.ProxyServer(iface, args.port, channels_cb, record_mgr=mgr)
    ok, msg = srv.start()
    if not ok:
        mgr.stop()
        return result('proxy', ok=False, error=msg)
    base = 'http://%s:%d' % (iface, args.port)
    emit(result('proxy', running=True, message=msg, iface=iface, port=args.port,
                record_dir=rd,
                urls={'status': base + '/status',
                      'playlist_http': base + '/playlist.m3u',
                      'playlist_udp': base + '/raw.m3u',
                      'stream': base + '/udp/<组播地址>:<端口>',
                      'recordings_m3u': base + '/recordings.m3u',
                      'recordings_json': base + '/recordings.json',
                      'vod': base + '/vod/<录像ID>'},
                note='服务在前台持续运行（直播转发+预约录像+录像点播），Ctrl+C 停止；'
                     '仅限局域网，禁止映射公网',
                copyright_note=record.COPYRIGHT_NOTE), args.out)
    log('proxy_running', port=args.port, iface=iface, record_dir=rd)
    # docker stop / 服务管理器发 SIGTERM：转 KeyboardInterrupt 走优雅收尾（录像索引落盘）
    import signal

    def _term(*_):
        raise KeyboardInterrupt()

    try:
        signal.signal(signal.SIGTERM, _term)
    except (ValueError, OSError):
        pass
    try:
        while srv.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
        mgr.stop()
    log('proxy_stopped')
    return None


# ---------------- 参数解析 ----------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog='wushuang-iptv-recorder',
        description='%s v%s · headless CLI（stdout=单个JSON结果, stderr=JSONL进度, '
                    '退出码 0成功/1失败/2参数错误；不需要管理员）%s' % (
                        REC_NAME, REC_VER_DISPLAY, (' ' + BETA_NOTE) if BETA_NOTE else ''))
    sub = ap.add_subparsers(dest='command', required=True)

    def common(p):
        p.add_argument('--out', metavar='FILE', help='结果 JSON 同时写入文件')
        p.add_argument('--record-dir', help='录像目录（缺省 程序目录/recordings）')

    p = sub.add_parser('info', help='环境总览：网卡/建议组播口/缺省录像目录')
    common(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser('record', help='录像：start 即时录 / list / add 预约 / cancel / delete')
    p.add_argument('action', choices=['start', 'list', 'add', 'cancel', 'delete'])
    p.add_argument('--channels', help='频道文件（主工具 verify 结果 JSON 或 m3u）')
    p.add_argument('--name', help='频道名（归一化匹配）')
    p.add_argument('--group', help='组播地址（与 --port 连用，可免频道文件）')
    p.add_argument('--port', type=int, help='组播端口')
    p.add_argument('--minutes', type=int, default=60, help='start: 录制分钟数，默认60')
    p.add_argument('--seconds', type=int, help='start: 录制秒数（优先于 --minutes）')
    p.add_argument('--until', help='start: 录到 HH:MM（已过则次日）')
    p.add_argument('--start', help='add: 开始时间 ISO 本地，如 2026-11-23T19:30')
    p.add_argument('--end', help='add: 结束时间')
    p.add_argument('--title', help='add: EPG 节目名关键词（与 --start/--end 二选一）')
    p.add_argument('--date', help='add/show: 限定日期 YYYY-MM-DD')
    p.add_argument('--id', help='cancel: 计划ID / delete: 录像ID')
    p.add_argument('--iface', help='组播网卡 IP（缺省自动选有线口）')
    p.add_argument('--quota-gb', type=float, default=None, help='录像配额 GB，默认100（容器内读 IPTV_QUOTA_GB），0=不限')
    p.add_argument('--max-concurrent', type=int, default=None, help='同时录制路数上限，默认2（容器内读 IPTV_MAX_CONCURRENT）')
    common(p)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser('epg', help='节目单：update 主动更新 / show 查节目 / map 映射报告')
    p.add_argument('action', choices=['update', 'show', 'map'])
    p.add_argument('--url', help='update: 自定义 XMLTV 地址（缺省内置源逐个尝试）')
    p.add_argument('--channels', help='update/map: 频道文件（用于映射；缺省只保留央视/卫视）')
    p.add_argument('--name', help='show: 频道名')
    p.add_argument('--date', help='show: 限定日期 YYYY-MM-DD')
    common(p)
    p.set_defaults(func=cmd_epg)

    p = sub.add_parser('proxy', help='前台常驻：直播转发 + 预约录像调度 + 录像点播（Ctrl+C 停止）')
    p.add_argument('--port', type=int, default=9999, help='监听端口，默认9999')
    p.add_argument('--iface', help='组播网卡 IP（缺省自动选有线口）')
    p.add_argument('--channels', help='频道文件，用于 /playlist.m3u 与预约名字解析（可省略）')
    p.add_argument('--quota-gb', type=float, default=100, help='录像配额 GB，默认100，0=不限')
    p.add_argument('--pad-before', type=int, default=60, help='预约提前量秒数，默认60')
    p.add_argument('--pad-after', type=int, default=120, help='预约延后量秒数，默认120')
    p.add_argument('--max-concurrent', type=int, default=2, help='同时录制路数上限，默认2')
    p.add_argument('--missed', choices=['skip', 'remainder'], default='skip',
                   help='重启后错过计划：skip 标记错过 / remainder 续录剩余，默认 skip')
    common(p)
    p.set_defaults(func=cmd_proxy)

    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    noconsole = sys.stdout is None
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
        out = os.path.join(os.getcwd(), 'rec-cli-result.json')
    try:
        res = args.func(args)
        if res is None:
            return 0
        code = 0 if res.get('ok') else 1
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
