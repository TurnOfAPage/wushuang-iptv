/**
 * 全国 IPTV 组播参考库（channeldb.py + refupdate.py 的 ArkTS 移植，精简版）。
 * 加载顺序：应用沙箱 refdb.json（在线更新产物）→ 构建期内嵌 rawfile/refdb.json（可能不存在）。
 * 仓库出于许可证考虑不捆绑社区数据：首次使用请点「在线更新参考库」，
 * 或构建前运行 harmony/prepare_refdb.py 注入。
 * 仅含组播地址与频道名等公开信息，不含任何账号/个人数据。
 */
import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { fileIo } from '@kit.CoreFileKit';
import { http } from '@kit.NetworkKit';
import { Channel, CarrierInfo, VerifyResult } from '../model/Channel';

interface RefChannel {
  name: string;
  group: string;
  port: number;
  cat?: string;
  ok?: boolean;
  video?: string;
  res?: string;
}

interface RefRegion {
  province: string;
  carrier: string;
  note?: string;
  channels: RefChannel[];
}

interface RefDbData {
  format?: string;
  updated?: string;
  regions?: RefRegion[];
}

interface IndexEntry {
  ch: RefChannel;
  province: string;
  carrier: string;
}

const PROV: Map<string, string> = new Map([
  ['anhui', '安徽'], ['beijing', '北京'], ['chongqing', '重庆'], ['fujian', '福建'],
  ['gansu', '甘肃'], ['guangdong', '广东'], ['guangxi', '广西'], ['guizhou', '贵州'],
  ['hainan', '海南'], ['hebei', '河北'], ['heilongjiang', '黑龙江'], ['henan', '河南'],
  ['hubei', '湖北'], ['hunan', '湖南'], ['jiangsu', '江苏'], ['jiangxi', '江西'],
  ['jilin', '吉林'], ['liaoning', '辽宁'], ['neimenggu', '内蒙古'], ['ningxia', '宁夏'],
  ['qinghai', '青海'], ['shaanxi', '陕西'], ['shandong', '山东'], ['shanghai', '上海'],
  ['shanxi', '山西'], ['sichuan', '四川'], ['tianjin', '天津'], ['xinjiang', '新疆'],
  ['xizang', '西藏'], ['yunnan', '云南'], ['zhejiang', '浙江']
]);

const CARRIER: Map<string, string> = new Map([
  ['telecom', '电信'], ['unicom', '联通'], ['mobile', '移动'], ['broadent', '广电']
]);

const MIRRORS: string[] = [
  'https://ghproxy.net/https://raw.githubusercontent.com/',
  'https://gh-proxy.com/https://raw.githubusercontent.com/',
  'https://ghfast.top/https://raw.githubusercontent.com/',
  'https://raw.githubusercontent.com/'
];

let dbCache: RefDbData | null = null;
let indexCache: Map<string, IndexEntry> = new Map();
let dbUpdated: string = '';
let dbOrigin: string = '空';

function dbFilePath(ctx: common.UIAbilityContext): string {
  return ctx.filesDir + '/refdb.json';
}

function buildIndex(d: RefDbData): void {
  indexCache = new Map();
  const regions = d.regions !== undefined ? d.regions : [];
  for (let ri = 0; ri < regions.length; ri++) {
    const r = regions[ri];
    for (let ci = 0; ci < r.channels.length; ci++) {
      const c = r.channels[ci];
      const k = c.group + ':' + c.port.toString();
      const old = indexCache.get(k);
      // 实测可用的优先，其次先到（与 Python 版一致）
      if (old === undefined || (c.ok === true && old.ch.ok !== true)) {
        const e: IndexEntry = { ch: c, province: r.province, carrier: r.carrier };
        indexCache.set(k, e);
      }
    }
  }
}

export async function loadRefDb(ctx: common.UIAbilityContext): Promise<void> {
  if (dbCache !== null) {
    return;
  }
  let text = '';
  // 1) 沙箱内在线更新产物
  try {
    const p = dbFilePath(ctx);
    if (fileIo.accessSync(p)) {
      const stat = fileIo.statSync(p);
      const buf = new ArrayBuffer(stat.size);
      const f = fileIo.openSync(p, fileIo.OpenMode.READ_ONLY);
      fileIo.readSync(f.fd, buf);
      fileIo.closeSync(f);
      text = util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buf));
      dbOrigin = '在线更新';
    }
  } catch (e) {
    text = '';
  }
  // 2) 构建期内嵌 rawfile（prepare_refdb.py 注入；仓库不捆绑数据，可能不存在）
  if (text === '') {
    try {
      const raw = await ctx.resourceManager.getRawFileContent('refdb.json');
      text = util.TextDecoder.create('utf-8').decodeToString(raw);
      dbOrigin = '内置';
    } catch (e) {
      text = '';
    }
  }
  if (text === '') {
    dbCache = { regions: [] } as RefDbData;
    dbUpdated = '';
    dbOrigin = '空';
    indexCache = new Map();
    return;
  }
  const d = JSON.parse(text) as RefDbData;
  dbCache = d;
  dbUpdated = d.updated !== undefined ? d.updated : '';
  buildIndex(d);
}

/** 在线更新参考库（用户主动触发；镜像策略与 Windows 版 refupdate.py 一致）。 */
export async function updateRefDb(ctx: common.UIAbilityContext,
  onProgress: (done: number, total: number) => void): Promise<string> {
  const files: string[] = [];
  PROV.forEach((cn: string, py: string) => {
    CARRIER.forEach((cn2: string, en: string) => {
      files.push('Multicast/' + py + '/' + en + '.txt');
    });
  });
  const texts: Map<string, string> = new Map();
  let done = 0;
  for (let mi = 0; mi < MIRRORS.length; mi++) {
    const missing: string[] = files.filter((f: string): boolean => !texts.has(f));
    if (missing.length === 0) {
      break;
    }
    const base = MIRRORS[mi] + 'xisohi/CHINA-IPTV/main/';
    let idx = 0;
    const worker = async (): Promise<void> => {
      while (true) {
        const i = idx;
        idx += 1;
        if (i >= missing.length) {
          return;
        }
        const path = missing[i];
        try {
          const req = http.createHttp();
          const resp = await req.request(base + path, {
            method: http.RequestMethod.GET,
            expectDataType: http.HttpDataType.STRING,
            connectTimeout: 10000,
            readTimeout: 20000
          });
          req.destroy();
          if (resp.responseCode === 200) {
            const s = resp.result as string;
            if (s.includes(',')) {
              texts.set(path, s);
            }
          }
        } catch (e) {
          // 单文件失败：换下一镜像重试
        }
        done += 1;
        onProgress(done, files.length);
      }
    };
    const ws: Promise<void>[] = [];
    for (let k = 0; k < 8; k++) {
      ws.push(worker());
    }
    await Promise.all(ws);
    // 31省×3主流运营商≈93 个文件拿到九成即成功（广电列表部分地区缺失属正常）
    if (texts.size >= 84) {
      break;
    }
  }
  if (texts.size === 0) {
    throw new Error('所有更新源均不可达，请检查网络后重试');
  }
  const d = buildDbFromTexts(texts);
  const json = JSON.stringify(d);
  const p = dbFilePath(ctx);
  const f = fileIo.openSync(p, fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
  fileIo.writeSync(f.fd, json);
  fileIo.closeSync(f);
  dbCache = null;
  await loadRefDb(ctx);
  return dbInfo();
}

function guessCat(name: string, genre: string): string {
  const n = name.toUpperCase();
  if (n.includes('4K') || n.includes('超高清') || genre.includes('4K')) {
    return '4K超高清';
  }
  if (n.includes('CCTV') || n.includes('央视') || genre.includes('央视') || n.includes('CGTN')) {
    return '央视';
  }
  if (n.includes('卫视') || genre.includes('卫视')) {
    return '卫视';
  }
  if (n.includes('广播') || n.includes('之声') || n.includes('调频') || genre.includes('广播')) {
    return '广播频道';
  }
  if (n.includes('购物')) {
    return '电视购物';
  }
  if (genre.includes('地方')) {
    return '地方';
  }
  return '其他频道';
}

interface ParsedChannel {
  name: string;
  group: string;
  port: number;
  cat: string;
}

/** 解析 DIYP txt（分类,#genre# / 频道名,url），只收组播地址。 */
function parseTxt(data: string): ParsedChannel[] {
  const out: ParsedChannel[] = [];
  let genre = '';
  const lines = data.split('\n');
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li].trim();
    if (line === '') {
      continue;
    }
    if (line.endsWith('#genre#')) {
      genre = line.split(',')[0].trim();
      continue;
    }
    const ci = line.indexOf(',');
    if (ci < 0) {
      continue;
    }
    const name = line.substring(0, ci).trim();
    const url = line.substring(ci + 1);
    const m = /(?:udp|rtp):\/\/@?(\d+\.\d+\.\d+\.\d+):(\d+)/.exec(url);
    if (m === null || name === '') {
      continue;
    }
    const g = m[1];
    const p = parseInt(m[2]);
    const first = parseInt(g.split('.')[0]);
    if (first < 224 || first > 239) {
      continue;
    }
    const pc: ParsedChannel = { name: name, group: g, port: p, cat: guessCat(name, genre) };
    out.push(pc);
  }
  return out;
}

function buildDbFromTexts(texts: Map<string, string>): RefDbData {
  const regions: RefRegion[] = [];
  const keys: string[] = Array.from(texts.keys());
  keys.sort();
  for (let ki = 0; ki < keys.length; ki++) {
    const path = keys[ki];
    const m = /^Multicast\/([^/]+)\/([^/]+)\.txt$/.exec(path);
    if (m === null) {
      continue;
    }
    const provPy = m[1];
    const fn = m[2];
    const prov = PROV.get(provPy);
    if (prov === undefined) {
      continue;
    }
    const base = fn.replace(/[（(].*?[)）]/g, '').trim();
    const carrier = CARRIER.get(base);
    if (carrier === undefined) {
      continue;
    }
    const chans = parseTxt(texts.get(path) as string);
    if (chans.length === 0) {
      continue;
    }
    const seen: Map<string, RefChannel> = new Map();
    for (let ci = 0; ci < chans.length; ci++) {
      const c = chans[ci];
      const k = c.group + ':' + c.port.toString();
      if (!seen.has(k)) {
        const rc: RefChannel = { name: c.name, group: c.group, port: c.port, cat: c.cat };
        seen.set(k, rc);
      }
    }
    const region: RefRegion = {
      province: prov,
      carrier: carrier,
      note: fn !== base ? '备用' : '',
      channels: Array.from(seen.values())
    };
    regions.push(region);
  }
  const now = new Date();
  const updated = now.getFullYear().toString() + '-' +
    (now.getMonth() + 1).toString().padStart(2, '0') + '-' +
    now.getDate().toString().padStart(2, '0');
  const d: RefDbData = { format: 'wushuang-iptv-refdb', updated: updated, regions: regions };
  return d;
}

export function dbInfo(): string {
  if (dbCache === null) {
    return '参考库未加载';
  }
  const regions = dbCache.regions !== undefined ? dbCache.regions : [];
  if (regions.length === 0) {
    return '参考库为空，请点「在线更新参考库」';
  }
  let n = 0;
  const provSet: Set<string> = new Set();
  for (let i = 0; i < regions.length; i++) {
    n += regions[i].channels.length;
    provSet.add(regions[i].province);
  }
  return '参考库 ' + dbUpdated + '（' + dbOrigin + '） · ' + provSet.size.toString() + ' 省 · ' +
    regions.length.toString() + ' 列表 · ' + n.toString() + ' 频道';
}

export function provinces(): string[] {
  if (dbCache === null) {
    return [];
  }
  const seen: Set<string> = new Set();
  const regions = dbCache.regions !== undefined ? dbCache.regions : [];
  for (let i = 0; i < regions.length; i++) {
    seen.add(regions[i].province);
  }
  const out: string[] = Array.from(seen);
  out.sort();
  return out;
}

export function carriers(province: string): CarrierInfo[] {
  const out: CarrierInfo[] = [];
  if (dbCache === null) {
    return out;
  }
  const regions = dbCache.regions !== undefined ? dbCache.regions : [];
  for (let i = 0; i < regions.length; i++) {
    const r = regions[i];
    if (r.province === province) {
      const info = new CarrierInfo();
      info.carrier = r.carrier;
      info.label = r.carrier + ((r.note !== undefined && r.note !== '') ? '（' + r.note + '）' : '');
      info.count = r.channels.length;
      out.push(info);
    }
  }
  return out;
}

export function channelsFor(province: string, carrier: string): Channel[] {
  const out: Channel[] = [];
  if (dbCache === null) {
    return out;
  }
  const regions = dbCache.regions !== undefined ? dbCache.regions : [];
  for (let i = 0; i < regions.length; i++) {
    const r = regions[i];
    if (r.province === province && r.carrier === carrier) {
      for (let j = 0; j < r.channels.length; j++) {
        const c = r.channels[j];
        const ch = new Channel();
        ch.name = c.name;
        ch.group = c.group;
        ch.port = c.port;
        ch.cat = (c.cat !== undefined && c.cat !== '') ? c.cat : '其他频道';
        ch.source = 'ref';
        ch.refOk = c.ok === true;
        out.push(ch);
      }
    }
  }
  return out;
}

export function lookup(group: string, port: number): IndexEntry | undefined {
  return indexCache.get(group + ':' + port.toString());
}

/** SDT/参考名规范化：CCTV-1综合 → CCTV1 等（与 Python 版同一套规则）。 */
export function normalizeName(name: string): string {
  if (name === '') {
    return '';
  }
  let s = name.trim();
  let m = /^CCTV[-\s]?(\d+)\s*[\u4e00-\u9fff]*$/i.exec(s);
  if (m !== null) {
    return 'CCTV' + m[1];
  }
  m = /^CCTV[-\s]?(\d+)\s*\+/i.exec(s);
  if (m !== null) {
    return 'CCTV' + m[1] + '+';
  }
  s = s.replace(/[\s\u3000]+/g, '');
  return s;
}

export function guessCategory(name: string, sdtType: number): string {
  const n = name.toUpperCase();
  if (n.includes('4K') || n.includes('超高清')) {
    return '4K超高清';
  }
  if (n.includes('CCTV') || n.includes('央视') || n.includes('CGTN')) {
    return '央视';
  }
  if (n.includes('卫视')) {
    return '卫视';
  }
  if (n.includes('广播') || n.includes('之声') || n.includes('调频')) {
    return '广播频道';
  }
  if (n.includes('购物')) {
    return '电视购物';
  }
  if (sdtType === 0x02 || sdtType === 0x0A || sdtType === 0x12) {
    return '广播频道';
  }
  return '其他频道';
}

/** 验证结果写回频道（与 GUI/CLI 共用同一套命名规则）。 */
export function applyVerifyResult(ch: Channel, r: VerifyResult): void {
  ch.ok = r.ok;
  ch.tested = true;
  ch.video = r.video;
  ch.audio = r.audio;
  ch.res = r.res;
  ch.sdtName = r.sdtName;
  if (r.ok && r.sdtName !== '' && !ch.userNamed) {
    const nm = normalizeName(r.sdtName);
    const ref = lookup(ch.group, ch.port);
    if (ref === undefined) {
      ch.name = nm;
      ch.cat = guessCategory(nm, -1);
    }
  }
}
