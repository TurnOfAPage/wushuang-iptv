# -*- coding: utf-8 -*-
"""本地录像（DVR）核心：Recorder 单频道组播录制 + RecordManager 调度/持久化/配额。
独立产品「无双IPTV录像工具」与主工具共用本模块；零第三方依赖；不需要管理员
（IGMP 续期 raw socket 不可用时自动回退 drop/re-add，与 proxy 一致）。
设计文档：docs/录像功能设计.md

目录布局（record_dir 为唯一需要 NAS 挂载的目录）：
  records.json      预约计划（含历史状态）
  recordings.json   录像索引（进行中 + 已完成）
  epg.xml.gz/.json  EPG 缓存（epg.py 维护）
  ts/<rid>.ts       录像文件（超 4GiB/2h 自动分段 _p2.ts ...）
"""
import glob
import json
import os
import re
import shutil
import socket
import struct
import threading
import time
import uuid
from datetime import datetime, timedelta

from tsutil import TSAnalyzer, strip_rtp
from channeldb import normalize_name
from proxy import _refresh_loop
import netutil


def default_record_dir():
    """默认录像目录：系统「下载」文件夹/无双IPTV录像（用户可在 Web/GUI/CLI 自定义）。
    Windows 用 SHGetKnownFolderPath 取真实 Downloads（含 OneDrive 重定向），其余平台 ~/Downloads。"""
    base = None
    if netutil.IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                            ('Data3', wintypes.WORD), ('Data4', ctypes.c_byte * 8)]

            # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
            guid = _GUID(0x374DE290, 0x123F, 0x4565,
                         (ctypes.c_byte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(p)) == 0:
                base = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
        except Exception:
            base = None
    if not base:
        base = os.path.join(os.path.expanduser('~'), 'Downloads')
    return os.path.join(base, '无双IPTV录像')

PART_MAX_BYTES = 4 * 1024 ** 3      # 单分段上限 4GiB（FAT32/老 NAS 兼容）
PART_MAX_SECONDS = 7200             # 单分段上限 2 小时
RECV_TIMEOUT = 6.0                  # 收流超时 → 判断流并重加组
FLUSH_INTERVAL = 5.0
DISK_CHECK_INTERVAL = 30.0
DISK_MIN_FREE = 2 * 1024 ** 3       # 磁盘剩余低于 max(2GiB, 10分钟×码率) 优雅停止
ISO_FMT = '%Y-%m-%dT%H:%M:%S'

COPYRIGHT_NOTE = ('本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。'
                  '传播录制文件会导致版权风险，该风险与本软件无关。')


def dir_writable(path):
    """探测目录可建可写（火绒/控制文件夹访问可能拒绝未信任程序写下载/文档等保护目录）。"""
    try:
        os.makedirs(os.path.join(path, 'ts'), exist_ok=True)
        probe = os.path.join(path, '.w_probe')
        with open(probe, 'w') as f:
            f.write('x')
        os.remove(probe)
        return True
    except OSError:
        return False


def _iso(dt):
    return dt.strftime(ISO_FMT)


def _parse(s):
    return datetime.fromisoformat(s)


def safe_name(name):
    """频道名 → 文件系统安全短名（索引损坏时也能从文件名认出频道）。"""
    s = normalize_name(name or '') or 'channel'
    s = re.sub(r'[\\/:*?"<>|\s]+', '_', s).strip('._')
    return s[:40] or 'channel'


def _atomic_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, path)


def _load_json(path, default):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class Recorder:
    """单频道录制器：加组收流 → 剥 RTP → 写 TS。run() 阻塞，在独立线程调用。

    测试钩子：sock_factory（注入假 socket，跳过加组/IGMP 续期）、
    disk_usage_fn（注入磁盘余量）、now_fn（注入时钟）、part_max_*（分段阈值）。
    """

    def __init__(self, channel, iface_ip, out_path, stop_evt=None, progress_cb=None,
                 sock_factory=None, disk_usage_fn=None, now_fn=None, end_time=None,
                 part_max_bytes=PART_MAX_BYTES, part_max_seconds=PART_MAX_SECONDS,
                 start_part=1, prior_bytes=0):
        self.channel = channel
        self.iface_ip = iface_ip
        self.out_path = out_path
        self.stop_evt = stop_evt or threading.Event()
        self.progress_cb = progress_cb
        self.sock_factory = sock_factory
        self.disk_usage_fn = disk_usage_fn or shutil.disk_usage
        self.now_fn = now_fn or datetime.now
        self.end_time = end_time
        self.part_max_bytes = part_max_bytes
        self.part_max_seconds = part_max_seconds
        self.start_part = start_part
        self.stats = {'bytes': 0, 'pkts': 0, 'duration': 0.0, 'gaps': 0,
                      'parts': [], 'error': ''}
        self._prior_bytes = prior_bytes
        self._thread = None

    # ---- 对外 ----
    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self.stop_evt.set()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    # ---- 内部 ----
    def _emit(self, event, **kw):
        if self.progress_cb:
            try:
                self.progress_cb(event, name=self.channel.get('name', ''),
                                 group=self.channel.get('group', ''),
                                 port=self.channel.get('port', 0), **kw)
            except Exception:
                pass

    def _make_socket(self):
        g, p = self.channel['group'], int(self.channel['port'])
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', p))
        mreq = struct.pack('4s4s', socket.inet_aton(g), socket.inet_aton(self.iface_ip))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.iface_ip))
        s.settimeout(RECV_TIMEOUT)
        return s, mreq

    def _part_path(self, idx):
        if idx <= 1:
            return self.out_path
        base, ext = os.path.splitext(self.out_path)
        return '%s_p%d%s' % (base, idx, ext)

    def _open_part(self, idx):
        p = self._part_path(idx)
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        return open(p, 'ab' if idx < self.start_part else 'wb'), p

    def _disk_ok(self, elapsed):
        try:
            free = self.disk_usage_fn(os.path.dirname(os.path.abspath(self.out_path))).free
        except OSError:
            return True
        bps = (self.stats['bytes'] / elapsed) if elapsed > 10 else 4_000_000 / 8
        return free >= max(DISK_MIN_FREE, 600 * bps)

    def run(self):
        s = None
        mreq = None
        refresh_stop = None
        f = None
        part_idx = self.start_part
        part_bytes = 0
        t0 = self.now_fn()
        mono0 = time.monotonic()
        last_flush = last_disk = last_progress = mono0
        part_start = mono0
        ana = TSAnalyzer()
        wait_pat = True
        self._emit('record_start', rid=os.path.basename(self.out_path))
        try:
            if self.sock_factory is not None:
                s = self.sock_factory()
            else:
                s, mreq = self._make_socket()
                refresh_stop = threading.Event()
                threading.Thread(target=_refresh_loop,
                                 args=(self.channel['group'], self.iface_ip,
                                       refresh_stop, s, mreq), daemon=True).start()
            f, part_path = self._open_part(part_idx)
            if not self._disk_ok(0):
                self.stats['error'] = 'disk_full'
                self._emit('record_error', error='disk_full')
            while not self.stop_evt.is_set() and not self.stats['error']:
                if self.end_time is not None and self.now_fn() >= self.end_time:
                    break
                try:
                    data, _ = s.recvfrom(65535)
                except socket.timeout:
                    self.stats['gaps'] += 1
                    self._emit('record_gap', gaps=self.stats['gaps'])
                    if mreq is not None:
                        try:
                            s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                        except OSError:
                            pass
                    continue
                ts = strip_rtp(data)
                if not ts:
                    continue
                if wait_pat:
                    ana.feed(ts)
                    if ana.ready or time.monotonic() - mono0 > 2.0:
                        wait_pat = False
                f.write(ts)
                self.stats['bytes'] += len(ts)
                self.stats['pkts'] += 1
                part_bytes += len(ts)
                now_mono = time.monotonic()
                if now_mono - last_flush >= FLUSH_INTERVAL:
                    f.flush()
                    last_flush = now_mono
                if now_mono - last_progress >= FLUSH_INTERVAL:
                    last_progress = now_mono
                    self._emit('record_progress', bytes=self.stats['bytes'],
                               duration=round((self.now_fn() - t0).total_seconds()),
                               gaps=self.stats['gaps'])
                if now_mono - last_disk >= DISK_CHECK_INTERVAL:
                    last_disk = now_mono
                    if not self._disk_ok(now_mono - mono0):
                        self.stats['error'] = 'disk_full'
                        self._emit('record_error', error='disk_full')
                        break
                if (part_bytes >= self.part_max_bytes
                        or now_mono - part_start >= self.part_max_seconds):
                    f.close()
                    self.stats['parts'].append({'file': part_path, 'bytes': part_bytes})
                    part_idx += 1
                    part_bytes = 0
                    part_start = now_mono
                    f, part_path = self._open_part(part_idx)
        except Exception as e:
            self.stats['error'] = '%s: %s' % (type(e).__name__, e)
            self._emit('record_error', error=self.stats['error'])
        finally:
            try:
                if f is not None and not f.closed:
                    f.flush()
                    f.close()
                    self.stats['parts'].append({'file': part_path, 'bytes': part_bytes})
            except OSError:
                pass
            if refresh_stop is not None:
                refresh_stop.set()
            if s is not None:
                if mreq is not None:
                    try:
                        s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                    except OSError:
                        pass
                try:
                    s.close()
                except OSError:
                    pass
            self.stats['duration'] = round((self.now_fn() - t0).total_seconds(), 1)
            self.stats['ended_early'] = bool(
                self.end_time is not None and self.now_fn() < self.end_time
                and not self.stats['error'])
            self._emit('record_stopped', bytes=self.stats['bytes'],
                       duration=self.stats['duration'], gaps=self.stats['gaps'],
                       error=self.stats['error'])


class RecordManager:
    """预约调度 + 录制管理 + 持久化 + 配额。GUI/CLI/proxy 共用。

    scheduler=False 时不做定时调度（CLI 即时录 / GUI 手动录场景），
    但 record_now/add_schedule/持久化/配额照常可用。
    测试钩子：now_fn（假时钟）、sock_factory（假 socket，透传 Recorder）。
    """

    def __init__(self, record_dir, iface_ip, channels_cb=None, quota_gb=100,
                 pad_before=60, pad_after=120, max_concurrent=2, missed_policy='skip',
                 now_fn=None, progress_cb=None, scheduler=True, sock_factory=None,
                 part_max_bytes=PART_MAX_BYTES, part_max_seconds=PART_MAX_SECONDS):
        # base_dir = 启动配置目录（settings.json 锚点，Docker 下即挂载根）；
        # record_dir = 生效录像目录（可被 settings.json 里的用户选择覆盖）
        self.base_dir = os.path.abspath(record_dir)
        settings = _load_json(os.path.join(self.base_dir, 'settings.json'), {})
        self.record_dir = os.path.abspath(settings.get('record_dir') or self.base_dir)
        if settings.get('quota_gb') is not None:
            quota_gb = settings['quota_gb']
        self.iface_ip = iface_ip
        self.channels_cb = channels_cb or (lambda: [])
        self.quota_gb = quota_gb
        self.pad_before = pad_before
        self.pad_after = pad_after
        self.max_concurrent = max_concurrent
        self.missed_policy = missed_policy
        self.now_fn = now_fn or datetime.now
        self.progress_cb = progress_cb
        self.scheduler = scheduler
        self.sock_factory = sock_factory
        self.part_max_bytes = part_max_bytes
        self.part_max_seconds = part_max_seconds
        try:
            os.makedirs(os.path.join(self.record_dir, 'ts'), exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                '%s —— 该目录被安全软件保护（火绒文档/勒索防护或 Windows 控制文件夹访问），'
                '拒绝未信任程序写入。请在安全软件中信任本程序，或改用其它文件夹。' % e)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._active = {}          # sid -> {'recorder', 'rid', 'thread'}
        self._sched_mtime = 0
        self.schedules = _load_json(self._sched_path(), [])
        self.recordings = _load_json(self._rec_path(), None)
        if self.recordings is None:
            self.recordings = self._rebuild_index()
            self._save_recordings()
        self._track_mtime()
        try:
            self._rec_mtime = os.path.getmtime(self._rec_path())
        except OSError:
            self._rec_mtime = 0

    # ---- 路径/持久化 ----
    def _sched_path(self):
        return os.path.join(self.record_dir, 'records.json')

    def _rec_path(self):
        return os.path.join(self.record_dir, 'recordings.json')

    def _ts_path(self, rid):
        return os.path.join(self.record_dir, 'ts', rid + '.ts')

    def _track_mtime(self):
        try:
            self._sched_mtime = os.path.getmtime(self._sched_path())
        except OSError:
            self._sched_mtime = 0

    def _save_schedules(self):
        _atomic_json(self._sched_path(), self.schedules)
        self._track_mtime()

    def _save_recordings(self):
        _atomic_json(self._rec_path(), self.recordings)
        try:
            self._rec_mtime = os.path.getmtime(self._rec_path())
        except OSError:
            self._rec_mtime = 0

    def _refresh_recordings(self):
        """热重载其它进程（如 docker exec / CLI 即时录）写入的索引；
        本进程在录条目保留内存实时统计，不被磁盘旧值覆盖。"""
        try:
            mt = os.path.getmtime(self._rec_path())
        except OSError:
            mt = 0
        if mt == self._rec_mtime:
            return
        disk = _load_json(self._rec_path(), [])
        own_ids = {a['rid'] for a in self._active.values()}
        own = {r['id']: r for r in self.recordings if r['id'] in own_ids}
        merged = [own.get(r['id'], r) for r in disk]
        for rid, r in own.items():
            if not any(x['id'] == rid for x in merged):
                merged.append(r)
        self.recordings = merged
        self._rec_mtime = mt

    def _rebuild_index(self):
        """索引缺失/损坏时从 ts/ 文件名重建基础索引（降级可用）。"""
        out = {}
        for p in sorted(glob.glob(os.path.join(self.record_dir, 'ts', '*.ts'))):
            base = os.path.basename(p)[:-3]
            rid = re.sub(r'_p\d+$', '', base)
            e = out.setdefault(rid, {'id': rid, 'name': '', 'epg_title': '',
                                     'group': '', 'port': 0, 'start': '', 'end': '',
                                     'duration': 0, 'bytes': 0, 'parts': [],
                                     'status': 'done', 'gaps': 0, 'error': ''})
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            e['parts'].append({'file': os.path.relpath(p, self.record_dir), 'bytes': sz})
            e['bytes'] += sz
            m = re.match(r'r(\d{8}_\d{6})_(.+)$', rid)
            if m:
                e['name'] = m.group(2)
                if not e['start']:
                    try:
                        e['start'] = _iso(datetime.strptime(m.group(1), '%Y%m%d_%H%M%S'))
                    except ValueError:
                        pass
        return list(out.values())

    def _emit(self, event, **kw):
        if self.progress_cb:
            try:
                self.progress_cb(event, **kw)
            except Exception:
                pass

    # ---- 查询 ----
    def get_recording(self, rid):
        with self._lock:
            self._refresh_recordings()
            for r in self.recordings:
                if r['id'] == rid:
                    return dict(r)
        return None

    def list_recordings(self):
        with self._lock:
            self._refresh_recordings()
            self._refresh_active_stats()
            return [dict(r) for r in self.recordings]

    def list_schedules(self):
        with self._lock:
            return [dict(s) for s in self.schedules]

    def _refresh_active_stats(self):
        for sid, a in self._active.items():
            st = a['recorder'].stats
            for r in self.recordings:
                if r['id'] == a['rid']:
                    r['bytes'] = st['bytes'] + r.get('_prior_bytes', 0)
                    r['gaps'] = st['gaps'] + r.get('_prior_gaps', 0)
                    r['duration'] = round((self.now_fn() - _parse(r['start'])).total_seconds())
                    break

    def status(self):
        with self._lock:
            self._refresh_recordings()
            self._refresh_active_stats()
            now = self.now_fn()
            active = []
            for sid, a in self._active.items():
                r = self.get_recording(a['rid']) or {}
                active.append({'sid': sid, 'rid': a['rid'],
                               'name': r.get('name', ''), 'bytes': r.get('bytes', 0),
                               'duration': r.get('duration', 0), 'gaps': r.get('gaps', 0)})
            pending = [s for s in self.schedules if s['status'] == 'pending']
            soon = [s for s in pending
                    if _parse(s['start']) <= now + timedelta(hours=24)]
            used = sum(r['bytes'] for r in self.recordings if r['status'] != 'recording')
            return {'record_dir': self.record_dir, 'iface': self.iface_ip,
                    'active': active, 'pending': len(pending), 'pending_24h': len(soon),
                    'recordings': len(self.recordings),
                    'quota_used_gb': round(used / 1024 ** 3, 2), 'quota_gb': self.quota_gb}

    # ---- 预约 ----
    def add_schedule(self, ch, start, end, source='manual', epg_title='',
                     pad_before=None, pad_after=None):
        if isinstance(start, str):
            start = _parse(start)
        if isinstance(end, str):
            end = _parse(end)
        if end <= start:
            raise ValueError('结束时间必须晚于开始时间')
        with self._lock:
            for s in self.schedules:
                if s['status'] not in ('pending', 'recording'):
                    continue
                if (s['channel']['group'], s['channel']['port']) != (ch['group'], ch['port']):
                    continue
                if start < _parse(s['end']) + timedelta(seconds=self.pad_after) and \
                        end > _parse(s['start']) - timedelta(seconds=self.pad_before):
                    raise ValueError('与已有计划冲突: %s %s~%s' % (
                        s['channel'].get('name', ''), s['start'], s['end']))
            sch = {'id': uuid.uuid4().hex[:8],
                   'channel': {'name': ch.get('name', ''), 'group': ch['group'],
                               'port': int(ch['port'])},
                   'start': _iso(start), 'end': _iso(end),
                   'source': source, 'epg_title': epg_title,
                   'pad_before': self.pad_before if pad_before is None else pad_before,
                   'pad_after': self.pad_after if pad_after is None else pad_after,
                   'status': 'pending', 'rid': '', 'error': '',
                   'created': _iso(self.now_fn())}
            self.schedules.append(sch)
            self._save_schedules()
            return dict(sch)

    def cancel(self, sid):
        with self._lock:
            for s in self.schedules:
                if s['id'] != sid:
                    continue
                if s['status'] == 'pending':
                    s['status'] = 'canceled'
                    self._save_schedules()
                    return True
                if s['status'] == 'recording':
                    s['status'] = 'canceled'
                    self._save_schedules()
                    if sid in self._active:
                        self._active[sid]['recorder'].stop()
                    # 跨进程：拥有该录制的进程 tick 读到 canceled 后自行停止收尾
                    return True
                raise ValueError('计划状态 %s 不可取消' % s['status'])
        raise ValueError('未找到计划: %s' % sid)

    def record_now(self, ch, seconds=None, end=None):
        now = self.now_fn()
        if end is None:
            if not seconds or seconds <= 0:
                raise ValueError('需要 seconds 或 end')
            end = now + timedelta(seconds=seconds)
        elif isinstance(end, str):
            end = _parse(end)
        sch = self.add_schedule(ch, now, end, source='manual', pad_before=0, pad_after=0)
        self._launch(sch['id'], ignore_pad=True)
        with self._lock:
            cur = next(s for s in self.schedules if s['id'] == sch['id'])
            return dict(cur)

    def delete_recording(self, rid):
        with self._lock:
            self._refresh_recordings()
            for r in self.recordings:
                if r['id'] == rid and r['status'] == 'recording':
                    raise ValueError('该录像正在录制中，请先停止再删除')
            for a in self._active.values():
                if a['rid'] == rid:
                    raise ValueError('该录像正在录制中，请先停止再删除')
            rec = None
            for r in self.recordings:
                if r['id'] == rid:
                    rec = r
                    break
            if rec is None:
                raise ValueError('未找到录像: %s' % rid)
            for part in rec.get('parts', []):
                p = os.path.join(self.record_dir, part['file'])
                try:
                    os.remove(p)
                except OSError:
                    pass
            self.recordings.remove(rec)
            self._save_recordings()
            return True

    # ---- 调度 ----
    def start(self):
        with self._lock:
            self._recover()
        if self.scheduler:
            self._stop.clear()
            self._thread = threading.Thread(target=self._tick_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            actives = list(self._active.items())
        for sid, a in actives:
            a['recorder'].stop()
        for sid, a in actives:
            a['recorder'].join(timeout=8)
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self.poll()  # scheduler=False 时也要收尾，保证索引落盘

    def _recover(self):
        """重启恢复：recording 续录剩余时段；过期 pending 按 missed_policy。"""
        now = self.now_fn()
        for r in self.recordings:
            if r['status'] != 'recording':
                continue
            sch = next((s for s in self.schedules if s.get('rid') == r['id']), None)
            if sch and now < _parse(sch['end']) + timedelta(
                    seconds=sch.get('pad_after', self.pad_after)):
                parts = self._parts_from_disk(r['id'])
                r['parts'] = parts
                r['_prior_bytes'] = sum(p['bytes'] for p in parts)
                r['_prior_gaps'] = r.get('gaps', 0)
                self._start_recorder(sch, r, start_part=len(parts) + 1)
            else:
                parts = self._parts_from_disk(r['id'])
                r['parts'] = parts
                r['bytes'] = sum(p['bytes'] for p in parts)
                r['status'] = 'partial'
                r['end'] = _iso(now)
                if sch:
                    sch['status'] = 'done'
        for s in self.schedules:
            if s['status'] != 'pending':
                continue
            end_pad = _parse(s['end']) + timedelta(seconds=s.get('pad_after', self.pad_after))
            if now >= end_pad:
                s['status'] = 'missed'
                self._emit('schedule_missed', sid=s['id'], name=s['channel'].get('name', ''))
            elif self.missed_policy == 'remainder' and now > _parse(s['start']):
                try:
                    self._launch(s['id'], ignore_pad=True)
                except ValueError:
                    pass
        self._save_schedules()
        self._save_recordings()

    def _parts_from_disk(self, rid):
        parts = []
        for p in sorted(glob.glob(os.path.join(self.record_dir, 'ts', rid + '*.ts'))):
            base = os.path.basename(p)[:-3]
            if base != rid and not re.match(re.escape(rid) + r'_p\d+$', base):
                continue
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            parts.append({'file': os.path.relpath(p, self.record_dir), 'bytes': sz})
        return parts

    def _external_recording_count(self):
        """其它进程（如 CLI 即时录）在同一目录的在录路数。"""
        own = {a['rid'] for a in self._active.values()}
        data = _load_json(self._rec_path(), [])
        return sum(1 for r in data if r.get('status') == 'recording' and r.get('id') not in own)

    def _launch(self, sid, ignore_pad=False):
        with self._lock:
            sch = next((s for s in self.schedules if s['id'] == sid), None)
            if sch is None or sch['status'] != 'pending':
                raise ValueError('计划不存在或状态不可启动: %s' % sid)
            if len(self._active) + self._external_recording_count() >= self.max_concurrent:
                raise ValueError('并发录制已达上限(%d)，请等待其它录制结束或调大上限'
                                 % self.max_concurrent)
            now = self.now_fn()
            rid = 'r%s_%s' % (now.strftime('%Y%m%d_%H%M%S'),
                              safe_name(sch['channel'].get('name', '')))
            n = 2
            while os.path.exists(self._ts_path(rid)):
                rid = 'r%s_%s_%d' % (now.strftime('%Y%m%d_%H%M%S'),
                                     safe_name(sch['channel'].get('name', '')), n)
                n += 1
            rec = {'id': rid, 'name': sch['channel'].get('name', ''),
                   'epg_title': sch.get('epg_title', ''),
                   'group': sch['channel']['group'], 'port': sch['channel']['port'],
                   'start': _iso(now), 'end': '', 'duration': 0, 'bytes': 0,
                   'parts': [], 'status': 'recording', 'gaps': 0, 'error': ''}
            self.recordings.append(rec)
            sch['status'] = 'recording'
            sch['rid'] = rid
            self._start_recorder(sch, rec, start_part=1)
            self._save_schedules()
            self._save_recordings()
            self._emit('schedule_started', sid=sid, rid=rid,
                       name=sch['channel'].get('name', ''))
            return rid

    def _start_recorder(self, sch, rec, start_part):
        stop_evt = threading.Event()
        end_time = _parse(sch['end']) + timedelta(
            seconds=sch.get('pad_after', self.pad_after))

        def cb(event, **kw):
            self._emit(event, rid=rec['id'], sid=sch['id'], **kw)

        recorder = Recorder(sch['channel'], self.iface_ip, self._ts_path(rec['id']),
                            stop_evt=stop_evt, progress_cb=cb,
                            sock_factory=self.sock_factory, now_fn=self.now_fn,
                            end_time=end_time, part_max_bytes=self.part_max_bytes,
                            part_max_seconds=self.part_max_seconds,
                            start_part=start_part,
                            prior_bytes=rec.get('_prior_bytes', 0))
        th = recorder.start()
        self._active[sch['id']] = {'recorder': recorder, 'rid': rec['id'], 'thread': th}

    def _finalize(self, sid):
        with self._lock:
            a = self._active.pop(sid, None)
            if a is None:
                return
            st = a['recorder'].stats
            rec = next((r for r in self.recordings if r['id'] == a['rid']), None)
            sch = next((s for s in self.schedules if s['id'] == sid), None)
            if rec is not None:
                parts = []
                for p in st['parts']:
                    try:
                        sz = os.path.getsize(p['file'])
                    except OSError:
                        sz = p['bytes']
                    parts.append({'file': os.path.relpath(p['file'], self.record_dir),
                                  'bytes': sz})
                if rec.get('_prior_bytes'):
                    parts = self._parts_from_disk(rec['id'])
                rec['parts'] = parts
                rec['bytes'] = sum(p['bytes'] for p in parts)
                rec['gaps'] = st['gaps'] + rec.get('_prior_gaps', 0)
                rec['end'] = _iso(self.now_fn())
                try:
                    rec['duration'] = round((self.now_fn() - _parse(rec['start'])).total_seconds())
                except ValueError:
                    rec['duration'] = st['duration']
                rec.pop('_prior_bytes', None)
                rec.pop('_prior_gaps', None)
                canceled = sch is not None and sch['status'] == 'canceled'
                if st['error']:
                    rec['status'] = 'error'
                    rec['error'] = st['error']
                elif canceled or st.get('ended_early'):
                    rec['status'] = 'partial'
                else:
                    rec['status'] = 'done'
            if sch is not None and sch['status'] == 'recording':
                sch['status'] = 'error' if st['error'] else 'done'
                sch['error'] = st['error']
            self._save_schedules()
            self._save_recordings()
            self._cleanup_quota()
            self._emit('record_done', rid=a['rid'], sid=sid,
                       status=rec['status'] if rec else 'error',
                       bytes=rec['bytes'] if rec else 0,
                       error=st['error'])

    def _cleanup_quota(self):
        if not self.quota_gb or self.quota_gb <= 0:
            return
        limit = self.quota_gb * 1024 ** 3
        done = sorted((r for r in self.recordings if r['status'] in ('done', 'partial', 'error')),
                      key=lambda r: r.get('end') or r.get('start') or '')
        total = sum(r['bytes'] for r in done)
        for r in done:
            if total <= limit:
                break
            for part in r.get('parts', []):
                try:
                    os.remove(os.path.join(self.record_dir, part['file']))
                except OSError:
                    pass
            total -= r['bytes']
            self.recordings.remove(r)
            self._emit('quota_cleaned', rid=r['id'], name=r.get('name', ''))
        self._save_recordings()

    def poll(self):
        """scheduler=False 时由宿主循环周期调用：收尾已结束的录制线程。"""
        for sid, a in list(self._active.items()):
            if not a['thread'].is_alive():
                self._finalize(sid)

    def cleanup_quota(self):
        """GUI「立即清理」：按配额 LRU 清理已完成录像。"""
        with self._lock:
            self._cleanup_quota()

    def save_settings(self, quota_gb=None, record_dir=None):
        """用户设置持久化（Web 设置区 / GUI 设置区共用），锚定 base_dir/settings.json。
        quota 立即生效；record_dir 由调用方重建管理器生效（重启后自动读取）。"""
        p = os.path.join(self.base_dir, 'settings.json')
        s = _load_json(p, {})
        if quota_gb is not None:
            s['quota_gb'] = quota_gb
            with self._lock:
                self.quota_gb = quota_gb
        if record_dir is not None:
            s['record_dir'] = os.path.abspath(record_dir)
        _atomic_json(p, s)

    def prune_schedules(self):
        """GUI「清理历史」：移除已结束的计划（保留 pending/recording）。"""
        with self._lock:
            self.schedules = [s for s in self.schedules
                              if s['status'] in ('pending', 'recording')]
            self._save_schedules()

    def _tick_loop(self):
        while not self._stop.wait(1.0):
            try:
                self._tick()
            except Exception as e:
                self._emit('scheduler_error', error=str(e))

    def _tick(self):
        now = self.now_fn()
        with self._lock:
            # 外部进程新增的计划（record add 写文件）：mtime 变化则重载
            try:
                mt = os.path.getmtime(self._sched_path())
            except OSError:
                mt = 0
            if mt != self._sched_mtime:
                disk = _load_json(self._sched_path(), [])
                active_ids = set(self._active)
                merged = []
                for s in disk:
                    if s['id'] in active_ids:
                        mine = next(x for x in self.schedules if x['id'] == s['id'])
                        # 磁盘上的 canceled 是跨进程取消信号，必须接受；其余以本进程内存为准
                        if s['status'] != 'canceled':
                            s['status'] = mine['status']
                            s['rid'] = mine['rid']
                    merged.append(s)
                self.schedules = merged
                self._track_mtime()
            for s in self.schedules:
                if s['status'] != 'pending':
                    continue
                start_pad = _parse(s['start']) - timedelta(
                    seconds=s.get('pad_before', self.pad_before))
                end_pad = _parse(s['end']) + timedelta(
                    seconds=s.get('pad_after', self.pad_after))
                if now >= end_pad:
                    s['status'] = 'missed'
                    self._save_schedules()
                    self._emit('schedule_missed', sid=s['id'],
                               name=s['channel'].get('name', ''))
                elif now >= start_pad:
                    try:
                        self._launch(s['id'])
                    except ValueError:
                        pass  # 并发满，下一秒重试
            for sid, a in list(self._active.items()):
                sch = next((s for s in self.schedules if s['id'] == sid), None)
                if sch and sch['status'] == 'canceled':
                    a['recorder'].stop()
                elif sch and now >= _parse(sch['end']) + timedelta(
                        seconds=sch.get('pad_after', self.pad_after)):
                    a['recorder'].stop()
        # 收尾已结束的录制线程
        self.poll()
