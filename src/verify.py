# -*- coding: utf-8 -*-
"""原生组播加组验证（不依赖 ffmpeg）：IGMP 加组 → 收流 → TS 解析出频道名/编码/分辨率。
经验：组播免鉴权；169.254.x 地址也能加组；网卡硬件过滤意味着必须真正加组才能收流。
"""
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from tsutil import TSAnalyzer, strip_rtp


def verify_channel(group, port, iface_ip, timeout=5.0, min_bytes=200_000):
    """验证单个组播频道。返回 dict(ok, video, audio, res, sdt_name, bytes, pkts, error)。"""
    res = {'ok': False, 'video': None, 'audio': None, 'res': None,
           'sdt_name': '', 'bytes': 0, 'pkts': 0, 'error': ''}
    s = None
    mreq = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', port))
        mreq = struct.pack('4s4s', socket.inet_aton(group), socket.inet_aton(iface_ip))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
        s.settimeout(0.5)
        ana = TSAnalyzer()
        deadline = time.time() + timeout
        rtp_mode = None
        while time.time() < deadline:
            try:
                data, _ = s.recvfrom(65535)
            except socket.timeout:
                if ana.ready and res['bytes'] >= min_bytes // 4:
                    break
                continue
            res['pkts'] += 1
            res['bytes'] += len(data)
            ts = strip_rtp(data)
            if ts:
                ana.feed(ts)
            if ana.ready and res['bytes'] >= min_bytes:
                # 再等一会 SDT（频道名）与 SPS（分辨率），最多 2.5s
                extra = time.time() + 2.5
                while time.time() < extra:
                    want_name = not ana.service_name()
                    want_res = ana.video_codec == 'h264' and not ana.resolution
                    if not want_name and not want_res:
                        break
                    try:
                        data, _ = s.recvfrom(65535)
                    except socket.timeout:
                        continue
                    res['pkts'] += 1
                    res['bytes'] += len(data)
                    t2 = strip_rtp(data)
                    if t2:
                        ana.feed(t2)
                break
        res['ok'] = ana.ready
        res['video'] = ana.video_codec
        res['audio'] = ana.audio_codec
        res['res'] = ana.resolution
        res['sdt_name'] = ana.service_name()
        if not res['ok'] and res['bytes'] == 0:
            res['error'] = '未收到数据（组播未到达此网卡/频道停播）'
        elif not res['ok']:
            res['error'] = '收到数据但无法解析出音视频流'
    except Exception as e:
        res['error'] = str(e)
    finally:
        if s is not None:
            if mreq is not None:
                try:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                except OSError:
                    pass
            s.close()
    return res


def verify_batch(channels, iface_ip, concurrency=4, timeout=5.0,
                 progress_cb=None, stop_event=None):
    """并发验证一组频道；progress_cb(done, total, channel, result) 在工作线程调用。"""
    stop_event = stop_event or threading.Event()
    total = len(channels)
    done = 0
    lock = threading.Lock()

    def work(ch):
        nonlocal done
        if stop_event.is_set():
            return
        r = verify_channel(ch['group'], ch['port'], iface_ip, timeout=timeout)
        with lock:
            done += 1
            if progress_cb:
                progress_cb(done, total, ch, r)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        list(ex.map(work, channels))
    return done
