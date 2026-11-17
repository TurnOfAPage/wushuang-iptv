/**
 * MPEG-TS 轻量解析（tsutil.py 的 ArkTS 移植）：
 * 同步/PAT/PMT/SDT（频道名）/编码类型/H.264 SPS 分辨率。
 * 与 Windows/Linux 版同一套解析逻辑，自测用例语义一致。
 */
import { util } from '@kit.ArkTS';

const VIDEO_TYPES: number[] = [0x01, 0x02, 0x10, 0x1B, 0x24];
const AUDIO_TYPES: number[] = [0x03, 0x04, 0x0F, 0x11, 0x81, 0x87];

function codecName(st: number): string {
  switch (st) {
    case 0x01: return 'mpeg1video';
    case 0x02: return 'mpeg2video';
    case 0x10: return 'mpeg4video';
    case 0x1B: return 'h264';
    case 0x24: return 'hevc';
    case 0x03: return 'mp2';
    case 0x04: return 'mp2';
    case 0x0F: return 'aac';
    case 0x11: return 'aac';
    case 0x81: return 'ac3';
    case 0x87: return 'eac3';
    default: return '';
  }
}

/** DVB SI 文本解码：处理字符集前缀，中文常见 GB2312/UTF-8。 */
export function dvbText(b: number[]): string {
  if (b.length === 0) {
    return '';
  }
  let start = 0;
  if (b[0] < 0x20) {
    if (b[0] === 0x10 && b.length >= 3) {
      start = 3;
    } else {
      start = 1;
    }
  }
  const data = new Uint8Array(b.slice(start));
  const encs: string[] = ['utf-8', 'gb18030', 'iso-8859-1'];
  for (let k = 0; k < encs.length; k++) {
    try {
      const dec = util.TextDecoder.create(encs[k], { fatal: true });
      const s = dec.decodeToString(data);
      return s.replace(/\u0000/g, '').trim();
    } catch (e) {
      continue;
    }
  }
  return '';
}

class BitReader {
  private d: number[];
  private pos: number = 0;

  constructor(d: number[]) {
    this.d = d;
  }

  u(n: number): number {
    let v = 0;
    for (let i = 0; i < n; i++) {
      const byteI = this.pos >> 3;
      if (byteI >= this.d.length) {
        throw new Error('bitstream end');
      }
      v = (v << 1) | ((this.d[byteI] >> (7 - (this.pos & 7))) & 1);
      this.pos += 1;
    }
    return v;
  }

  ue(): number {
    let zeros = 0;
    while (this.u(1) === 0) {
      zeros += 1;
      if (zeros > 32) {
        throw new Error('bad ue');
      }
    }
    return (1 << zeros) - 1 + (zeros > 0 ? this.u(zeros) : 0);
  }

  se(): number {
    const k = this.ue();
    return (k % 2 === 1) ? (k + 1) / 2 : -(k / 2);
  }
}

function skipScaling(br: BitReader, size: number): void {
  let last = 8;
  let next = 8;
  for (let i = 0; i < size; i++) {
    if (next !== 0) {
      next = (last + br.se() + 256) % 256;
    }
    if (next !== 0) {
      last = next;
    }
  }
}

const HIGH_PROFILES: number[] = [100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135];

/** 从 SPS NAL（含 NAL 头）解析宽高；失败返回 ''。 */
export function h264Resolution(spsNal: number[]): string {
  try {
    // 去 emulation prevention（00 00 03 → 00 00）
    const rbsp: number[] = [];
    for (let i = 0; i < spsNal.length; i++) {
      if (i + 2 < spsNal.length && spsNal[i] === 0 && spsNal[i + 1] === 0 && spsNal[i + 2] === 3) {
        rbsp.push(0);
        rbsp.push(0);
        i += 2;
      } else {
        rbsp.push(spsNal[i]);
      }
    }
    const br = new BitReader(rbsp.slice(1)); // 跳过 NAL 头
    const profile = br.u(8);
    br.u(8); // constraint flags
    br.u(8); // level_idc
    br.ue(); // sps id
    let chroma = 1;
    if (HIGH_PROFILES.includes(profile)) {
      chroma = br.ue();
      if (chroma === 3) {
        br.u(1);
      }
      br.ue(); // bit_depth_luma
      br.ue(); // bit_depth_chroma
      br.u(1); // qpprime
      if (br.u(1) === 1) { // seq_scaling_matrix_present
        const cnt = (chroma !== 3) ? 8 : 12;
        for (let i = 0; i < cnt; i++) {
          if (br.u(1) === 1) {
            skipScaling(br, i < 6 ? 16 : 64);
          }
        }
      }
    }
    br.ue(); // log2_max_frame_num
    const pocType = br.ue();
    if (pocType === 0) {
      br.ue();
    } else if (pocType === 1) {
      br.u(1);
      br.se();
      br.se();
      const n = br.ue();
      for (let i = 0; i < n; i++) {
        br.se();
      }
    }
    br.ue(); // max_num_ref_frames
    br.u(1); // gaps_allowed
    const w = br.ue();
    const h = br.ue();
    const frameMbsOnly = br.u(1);
    if (frameMbsOnly === 0) {
      br.u(1);
    }
    br.u(1); // direct_8x8
    let cl = 0;
    let cr = 0;
    let ct = 0;
    let cb = 0;
    if (br.u(1) === 1) { // cropping
      cl = br.ue();
      cr = br.ue();
      ct = br.ue();
      cb = br.ue();
    }
    const subW = (chroma === 1 || chroma === 2) ? 2 : 1;
    const subH = (chroma === 1) ? 2 : 1;
    const cropX = subW;
    const cropY = subH * (2 - frameMbsOnly);
    const width = (w + 1) * 16 - (cl + cr) * cropX;
    const height = (2 - frameMbsOnly) * (h + 1) * 16 - (ct + cb) * cropY;
    if (width >= 16 && width <= 8192 && height >= 16 && height <= 8192) {
      return width + 'x' + height;
    }
  } catch (e) {
    // 解析失败按无分辨率处理
  }
  return '';
}

class ServiceInfo {
  name: string = '';
  provider: string = '';
  type: number = -1;
}

function findStartCode(buf: number[], from: number): number {
  for (let i = from; i + 2 < buf.length; i++) {
    if (buf[i] === 0 && buf[i + 1] === 0 && buf[i + 2] === 1) {
      return i;
    }
  }
  return -1;
}

/** 喂入 TS 字节流（RTP 剥离后），产出频道信息。 */
export class TSAnalyzer {
  private buf: number[] = [];
  private synced: boolean = false;
  private pmtPids: Set<number> = new Set();
  private services: Map<number, ServiceInfo> = new Map();
  private programNumber: number = 0;
  private sec: Map<number, number[]> = new Map();
  private vbuf: number[] = [];
  private vscan: number = 0;
  videoPid: number = -1;
  videoCodec: string = '';
  audioCodec: string = '';
  resolution: string = '';
  tsPackets: number = 0;

  get ready(): boolean {
    return this.videoCodec !== '' || this.audioCodec !== '';
  }

  serviceName(): string {
    if (this.programNumber !== 0 && this.services.has(this.programNumber)) {
      const s = this.services.get(this.programNumber);
      if (s !== undefined && s.name !== '') {
        return s.name;
      }
    }
    const it = this.services.values();
    let r = it.next();
    while (!r.done) {
      if (r.value.name !== '') {
        return r.value.name;
      }
      r = it.next();
    }
    return '';
  }

  feed(data: Uint8Array): void {
    for (let i = 0; i < data.length; i++) {
      this.buf.push(data[i]);
    }
    if (!this.synced) {
      // 寻找连续 3 个 188 间隔的 0x47
      const n = this.buf.length;
      let i = 0;
      while (i + 376 < n) {
        if (this.buf[i] === 0x47 && this.buf[i + 188] === 0x47 && this.buf[i + 376] === 0x47) {
          this.buf.splice(0, i);
          this.synced = true;
          break;
        }
        i += 1;
      }
      if (!this.synced) {
        if (this.buf.length > 188 * 16) {
          this.buf.splice(0, this.buf.length - 188 * 8);
        }
        return;
      }
    }
    while (this.buf.length >= 188) {
      const pkt = this.buf.splice(0, 188);
      if (pkt[0] !== 0x47) {
        this.synced = false;
        return;
      }
      this.packet(pkt);
    }
  }

  private packet(pkt: number[]): void {
    this.tsPackets += 1;
    const pid = ((pkt[1] & 0x1F) << 8) | pkt[2];
    const pusi = (pkt[1] & 0x40) !== 0;
    const afc = (pkt[3] >> 4) & 3;
    if ((afc & 1) === 0) {
      return;
    }
    let off = 4;
    if ((afc & 2) !== 0) {
      off += 1 + pkt[4];
    }
    if (off >= 188) {
      return;
    }
    const payload = pkt.slice(off);
    if (pid === 0 || pid === 0x11 || this.pmtPids.has(pid)) {
      this.section(pid, pusi, payload);
    } else if (pid === this.videoPid && this.videoCodec === 'h264' && this.resolution === '') {
      this.scanSps(payload);
    }
  }

  private section(pid: number, pusi: boolean, payload: number[]): void {
    if (pusi) {
      if (payload.length === 0) {
        return;
      }
      const ptr = payload[0];
      this.sec.set(pid, payload.slice(1 + ptr));
    } else {
      const cur = this.sec.get(pid);
      if (cur === undefined) {
        return;
      }
      for (let i = 0; i < payload.length; i++) {
        cur.push(payload[i]);
      }
    }
    const buf = this.sec.get(pid);
    if (buf === undefined) {
      return;
    }
    while (buf.length >= 3) {
      if (buf[0] === 0xFF) {
        buf.splice(0, buf.length);
        return;
      }
      const slen = ((buf[1] & 0x0F) << 8) | buf[2];
      const total = 3 + slen;
      if (slen < 5 || total > 4096) {
        buf.splice(0, buf.length);
        return;
      }
      if (buf.length < total) {
        return;
      }
      const sec = buf.splice(0, total);
      this.dispatch(pid, sec);
    }
  }

  private dispatch(pid: number, sec: number[]): void {
    const tid = sec[0];
    const slen = ((sec[1] & 0x0F) << 8) | sec[2];
    const end = 3 + slen - 4; // 去 CRC
    if (pid === 0 && tid === 0x00) {
      // PAT
      let i = 8;
      while (i + 4 <= end) {
        const prog = (sec[i] << 8) | sec[i + 1];
        const p = ((sec[i + 2] & 0x1F) << 8) | sec[i + 3];
        if (prog !== 0 && p !== 0) {
          this.pmtPids.add(p);
        }
        i += 4;
      }
    } else if (tid === 0x02 && this.pmtPids.has(pid)) {
      // PMT
      this.programNumber = (sec[8] << 8) | sec[9];
      const pil = ((sec[10] & 0x0F) << 8) | sec[11];
      let i = 12 + pil;
      while (i + 5 <= end) {
        const st = sec[i];
        const ep = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2];
        const eil = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4];
        if (VIDEO_TYPES.includes(st) && this.videoPid === -1) {
          this.videoPid = ep;
          const cn = codecName(st);
          this.videoCodec = cn !== '' ? cn : 'video(0x' + st.toString(16) + ')';
        } else if (AUDIO_TYPES.includes(st) && this.audioCodec === '') {
          const cn = codecName(st);
          this.audioCodec = cn !== '' ? cn : 'audio(0x' + st.toString(16) + ')';
        } else if (st === 0x06 && this.audioCodec === '') {
          this.audioCodec = 'private(0x06)';
        }
        i += 5 + eil;
      }
    } else if ((tid === 0x42 || tid === 0x46) && pid === 0x11) {
      // SDT
      let i = 11;
      while (i + 5 <= end) {
        const sid = (sec[i] << 8) | sec[i + 1];
        const dll = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4];
        let j = i + 5;
        const stop = Math.min(j + dll, end);
        let name = '';
        let provider = '';
        let stype = -1;
        while (j + 2 <= stop) {
          const tag = sec[j];
          const ln = sec[j + 1];
          const val = sec.slice(j + 2, j + 2 + ln);
          if (tag === 0x48 && val.length >= 2) {
            stype = val[0];
            const pl = val[1];
            provider = dvbText(val.slice(2, 2 + pl));
            const k = 2 + pl;
            if (k < val.length) {
              const sl = val[k];
              name = dvbText(val.slice(k + 1, k + 1 + sl));
            }
          }
          j += 2 + ln;
        }
        if (sid !== 0) {
          const old = this.services.get(sid);
          const si = new ServiceInfo();
          si.name = name !== '' ? name : (old !== undefined ? old.name : '');
          si.provider = provider !== '' ? provider : (old !== undefined ? old.provider : '');
          si.type = stype !== -1 ? stype : (old !== undefined ? old.type : -1);
          this.services.set(sid, si);
        }
        i += 5 + dll;
      }
    }
  }

  private scanSps(payload: number[]): void {
    this.vscan += payload.length;
    if (this.vscan > 3000000) {
      return;
    }
    for (let i = 0; i < payload.length; i++) {
      this.vbuf.push(payload[i]);
    }
    while (true) {
      const i = findStartCode(this.vbuf, 0);
      if (i < 0) {
        if (this.vbuf.length > 65536) {
          this.vbuf.splice(0, this.vbuf.length - 4);
        }
        return;
      }
      const j = findStartCode(this.vbuf, i + 3);
      if (j < 0) {
        if (i > 0) {
          this.vbuf.splice(0, i);
        }
        if (this.vbuf.length > 262144) {
          this.vbuf.splice(0, this.vbuf.length - 65536);
        }
        return;
      }
      const nal = this.vbuf.slice(i + 3, j);
      this.vbuf.splice(0, j);
      if (nal.length > 4 && (nal[0] & 0x1F) === 7) {
        this.resolution = h264Resolution(nal);
        if (this.resolution !== '') {
          this.vbuf = [];
          return;
        }
      }
    }
  }
}

/** UDP 载荷可能是 RTP 封装（0x80 开头）或裸 TS（0x47）。返回 TS 字节或 null。 */
export function stripRtp(payload: Uint8Array): Uint8Array | null {
  if (payload.length === 0) {
    return null;
  }
  if (payload[0] === 0x47) {
    return payload;
  }
  if ((payload[0] & 0xC0) === 0x80 && payload.length >= 12) {
    const cc = payload[0] & 0x0F;
    let off = 12 + cc * 4;
    if ((payload[1] & 0x10) !== 0) { // 扩展头
      if (payload.length < off + 4) {
        return null;
      }
      const extLen = (payload[off + 2] << 8) | payload[off + 3];
      off += 4 + extLen * 4;
    }
    if (off < payload.length && payload[off] === 0x47) {
      return payload.subarray(off);
    }
  }
  return null;
}
