# -*- coding: utf-8 -*-
"""MPEG-TS 轻量解析：同步/PAT/PMT/SDT（频道名）/编码类型/H.264 SPS 分辨率。
原生加组验证替代 ffmpeg，实现单文件绿色化。
"""

CODEC_MAP = {
    0x01: 'mpeg1video', 0x02: 'mpeg2video', 0x10: 'mpeg4video',
    0x1B: 'h264', 0x24: 'hevc',
    0x03: 'mp2', 0x04: 'mp2', 0x0F: 'aac', 0x11: 'aac',
    0x81: 'ac3', 0x87: 'eac3',
}
VIDEO_TYPES = {0x01, 0x02, 0x10, 0x1B, 0x24}
AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x81, 0x87}


def dvb_text(b):
    """DVB SI 文本解码：处理字符集前缀，中文常见 GB2312/UTF-8。"""
    if not b:
        return ''
    if b[0] < 0x20:
        if b[0] == 0x10 and len(b) >= 3:
            b = b[3:]
        else:
            b = b[1:]
    for enc in ('utf-8', 'gb18030', 'latin-1'):
        try:
            s = b.decode(enc)
            return s.replace('\x00', '').strip()
        except (UnicodeDecodeError, ValueError):
            continue
    return ''


class _BitReader:
    def __init__(self, data):
        self.d = data
        self.pos = 0

    def u(self, n):
        v = 0
        for _ in range(n):
            byte_i = self.pos >> 3
            if byte_i >= len(self.d):
                raise ValueError('bitstream end')
            v = (v << 1) | ((self.d[byte_i] >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 32:
                raise ValueError('bad ue')
        return (1 << zeros) - 1 + (self.u(zeros) if zeros else 0)

    def se(self):
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


def _skip_scaling(br, size):
    last, nxt = 8, 8
    for _ in range(size):
        if nxt != 0:
            nxt = (last + br.se() + 256) % 256
        if nxt != 0:
            last = nxt


def h264_resolution(sps_nal):
    """从 SPS NAL（含起始码后的 NAL 头）解析宽高；失败返回 None。"""
    try:
        rbsp = sps_nal.replace(b'\x00\x00\x03', b'\x00\x00')
        br = _BitReader(rbsp[1:])  # 跳过 NAL 头
        profile = br.u(8)
        br.u(8)  # constraint flags
        br.u(8)  # level_idc
        br.ue()  # sps id
        chroma = 1
        if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
            chroma = br.ue()
            if chroma == 3:
                br.u(1)
            br.ue()  # bit_depth_luma
            br.ue()  # bit_depth_chroma
            br.u(1)  # qpprime
            if br.u(1):  # seq_scaling_matrix_present
                for i in range(8 if chroma != 3 else 12):
                    if br.u(1):
                        _skip_scaling(br, 16 if i < 6 else 64)
        br.ue()  # log2_max_frame_num
        poc_type = br.ue()
        if poc_type == 0:
            br.ue()
        elif poc_type == 1:
            br.u(1)
            br.se()
            br.se()
            n = br.ue()
            for _ in range(n):
                br.se()
        br.ue()  # max_num_ref_frames
        br.u(1)  # gaps_allowed
        w = br.ue()
        h = br.ue()
        frame_mbs_only = br.u(1)
        if not frame_mbs_only:
            br.u(1)
        br.u(1)  # direct_8x8
        cl = cr = ct = cb = 0
        if br.u(1):  # cropping
            cl, cr, ct, cb = br.ue(), br.ue(), br.ue(), br.ue()
        # 裁剪单位：4:2:0 水平 2；垂直 = SubHeightC * (2 - frame_mbs_only)，隔行时为 4
        sub_w = 2 if chroma in (1, 2) else 1
        sub_h = 2 if chroma == 1 else 1
        crop_x = sub_w
        crop_y = sub_h * (2 - frame_mbs_only)
        width = (w + 1) * 16 - (cl + cr) * crop_x
        height = (2 - frame_mbs_only) * (h + 1) * 16 - (ct + cb) * crop_y
        if 16 <= width <= 8192 and 16 <= height <= 8192:
            return '%dx%d' % (width, height)
    except Exception:
        pass
    return None


class TSAnalyzer:
    """喂入 TS 字节流（可含 RTP 剥离后的数据），产出频道信息。"""

    def __init__(self):
        self.buf = bytearray()
        self.synced = False
        self.pat = {}            # program_number -> pmt_pid
        self.pmt_pids = set()
        self.streams = []        # (stream_type, pid)
        self.services = {}       # service_id -> {name, provider, type}
        self.program_number = None
        self._sec = {}           # pid -> bytearray
        self.video_pid = None
        self.video_codec = None
        self.audio_codec = None
        self.resolution = None
        self._vbuf = bytearray()
        self._vscan = 0
        self.ts_packets = 0

    # ---- 基础信息 ----
    @property
    def has_video(self):
        return self.video_codec is not None

    @property
    def has_audio(self):
        return self.audio_codec is not None

    @property
    def ready(self):
        return self.has_video or self.has_audio

    def service_name(self):
        if self.program_number and self.program_number in self.services:
            return self.services[self.program_number]['name']
        for s in self.services.values():
            if s['name']:
                return s['name']
        return ''

    # ---- 喂数据 ----
    def feed(self, data):
        self.buf.extend(data)
        if not self.synced:
            # 寻找连续 3 个 188 间隔的 0x47
            n = len(self.buf)
            i = 0
            while i + 376 < n:
                if self.buf[i] == 0x47 and self.buf[i + 188] == 0x47 and self.buf[i + 376] == 0x47:
                    del self.buf[:i]
                    self.synced = True
                    break
                i += 1
            if not self.synced:
                if len(self.buf) > 188 * 16:
                    del self.buf[:len(self.buf) - 188 * 8]
                return
        while len(self.buf) >= 188:
            pkt = bytes(self.buf[:188])
            del self.buf[:188]
            if pkt[0] != 0x47:
                self.synced = False
                return
            self._packet(pkt)

    def _packet(self, pkt):
        self.ts_packets += 1
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        pusi = bool(pkt[1] & 0x40)
        afc = (pkt[3] >> 4) & 3
        if not (afc & 1):
            return
        off = 4
        if afc & 2:
            off += 1 + pkt[4]
        if off >= 188:
            return
        payload = pkt[off:]
        if pid == 0 or pid == 0x11 or pid in self.pmt_pids:
            self._section(pid, pusi, payload)
        elif pid == self.video_pid and self.video_codec == 'h264' and not self.resolution:
            self._scan_sps(payload)

    # ---- PSI 段重组 ----
    def _section(self, pid, pusi, payload):
        if pusi:
            if not payload:
                return
            ptr = payload[0]
            data = payload[1 + ptr:]
            self._sec[pid] = bytearray(data)
        else:
            if pid not in self._sec:
                return
            self._sec[pid].extend(payload)
        buf = self._sec[pid]
        while len(buf) >= 3:
            if buf[0] == 0xFF:
                del buf[:]
                return
            slen = ((buf[1] & 0x0F) << 8) | buf[2]
            total = 3 + slen
            if slen < 5 or total > 4096:
                del buf[:]
                return
            if len(buf) < total:
                return
            sec = bytes(buf[:total])
            del buf[:total]
            self._dispatch(pid, sec)

    def _dispatch(self, pid, sec):
        tid = sec[0]
        slen = ((sec[1] & 0x0F) << 8) | sec[2]
        end = 3 + slen - 4  # 去 CRC
        if pid == 0 and tid == 0x00:
            i = 8
            while i + 4 <= end:
                prog = (sec[i] << 8) | sec[i + 1]
                p = ((sec[i + 2] & 0x1F) << 8) | sec[i + 3]
                if prog != 0 and p:
                    self.pat[prog] = p
                    self.pmt_pids.add(p)
                i += 4
        elif tid == 0x02 and pid in self.pmt_pids:
            self.program_number = (sec[8] << 8) | sec[9]
            pil = ((sec[10] & 0x0F) << 8) | sec[11]
            i = 12 + pil
            streams = []
            while i + 5 <= end:
                st = sec[i]
                ep = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2]
                eil = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
                streams.append((st, ep))
                i += 5 + eil
            if streams:
                self.streams = streams
                for st, ep in streams:
                    if st in VIDEO_TYPES and self.video_pid is None:
                        self.video_pid = ep
                        self.video_codec = CODEC_MAP.get(st, 'video(0x%02x)' % st)
                    elif st in AUDIO_TYPES and self.audio_codec is None:
                        self.audio_codec = CODEC_MAP.get(st, 'audio(0x%02x)' % st)
                    elif st == 0x06 and self.audio_codec is None:
                        self.audio_codec = 'private(0x06)'
        elif tid in (0x42, 0x46) and pid == 0x11:
            i = 11
            while i + 5 <= end:
                sid = (sec[i] << 8) | sec[i + 1]
                dll = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
                j = i + 5
                stop = min(j + dll, end)
                name, provider, stype = '', '', None
                while j + 2 <= stop:
                    tag, ln = sec[j], sec[j + 1]
                    val = sec[j + 2:j + 2 + ln]
                    if tag == 0x48 and len(val) >= 2:
                        stype = val[0]
                        pl = val[1]
                        provider = dvb_text(val[2:2 + pl])
                        k = 2 + pl
                        if k < len(val):
                            sl = val[k]
                            name = dvb_text(val[k + 1:k + 1 + sl])
                    j += 2 + ln
                if sid:
                    old = self.services.get(sid, {})
                    self.services[sid] = {
                        'name': name or old.get('name', ''),
                        'provider': provider or old.get('provider', ''),
                        'type': stype if stype is not None else old.get('type'),
                    }
                i += 5 + dll

    # ---- H.264 SPS 扫描 ----
    def _scan_sps(self, payload):
        self._vscan += len(payload)
        if self._vscan > 3_000_000:
            return
        self._vbuf.extend(payload)
        # 找起始码，提取完整 NAL
        while True:
            i = self._vbuf.find(b'\x00\x00\x01')
            if i < 0:
                if len(self._vbuf) > 65536:
                    del self._vbuf[:len(self._vbuf) - 4]
                return
            j = self._vbuf.find(b'\x00\x00\x01', i + 3)
            if j < 0:
                if i > 0:
                    del self._vbuf[:i]
                if len(self._vbuf) > 262144:
                    del self._vbuf[:len(self._vbuf) - 65536]
                return
            nal = bytes(self._vbuf[i + 3:j])
            del self._vbuf[:j]
            if nal and (nal[0] & 0x1F) == 7 and len(nal) > 4:
                self.resolution = h264_resolution(nal)
                if self.resolution:
                    self._vbuf.clear()
                    return


def strip_rtp(payload):
    """UDP 载荷可能是 RTP 封装（0x80 开头）或裸 TS（0x47）。返回 TS 字节或 None。"""
    if not payload:
        return None
    if payload[0] == 0x47:
        return payload
    if (payload[0] & 0xC0) == 0x80 and len(payload) >= 12:
        cc = payload[0] & 0x0F
        off = 12 + cc * 4
        if (payload[1] & 0x10):  # 扩展头
            if len(payload) < off + 4:
                return None
            ext_len = int.from_bytes(payload[off + 2:off + 4], 'big')
            off += 4 + ext_len * 4
        if off < len(payload) and payload[off] == 0x47:
            return payload[off:]
    return None
