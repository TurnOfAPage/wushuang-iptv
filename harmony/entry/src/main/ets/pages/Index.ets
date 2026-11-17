/**
 * 无双IPTV 鸿蒙精简版 · 主界面
 * ① 频道验证（参考库载入 + 组播实测）② M3U 生成 ③ HTTP 转发 ④ 关于
 * 测试版：未做真机测试，仅供参考。无抓包功能（鸿蒙第三方应用无原始抓包权限）。
 */
import { common } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { Channel, VerifyResult, IfaceInfo, CarrierInfo } from '../model/Channel';
import { loadRefDb, updateRefDb, provinces, carriers, channelsFor, dbInfo, applyVerifyResult } from '../core/RefDb';
import { listIfaces, pickMulticastIface, lanIpForUdpxy } from '../core/Net';
import { verifyBatch, StopToken } from '../core/Verify';
import { buildM3U, saveTextFile } from '../core/M3U';
import { ProxyServer } from '../core/Proxy';

const ACCENT = '#2563EB';
const OKC = '#16A34A';
const BADC = '#DC2626';
const SUB = '#64748B';
const BG = '#F2F5FA';

@Entry
@Component
struct Index {
  @State tabIdx: number = 0;
  @State provs: string[] = [];
  @State provIdx: number = 0;
  @State carrierList: CarrierInfo[] = [];
  @State carrierIdx: number = 0;
  @State channels: Channel[] = [];
  @State ifaces: IfaceInfo[] = [];
  @State ifaceIdx: number = 0;
  @State verifying: boolean = false;
  @State updating: boolean = false;
  @State progress: string = '';
  @State dbText: string = '参考库加载中…';
  @State fmtIdx: number = 0;
  @State host: string = '';
  @State proxyPort: string = '9999';
  @State m3uPort: string = '9999';
  @State proxyRunning: boolean = false;
  @State proxyMsg: string = '未运行';
  @State proxyActive: string = '';
  @State m3uMsg: string = '';
  @State manualGroup: string = '';
  @State manualPort: string = '5140';
  private stop: StopToken = new StopToken();
  private proxy: ProxyServer | null = null;
  private timerId: number = -1;
  private ctx: common.UIAbilityContext | null = null;

  aboutToAppear(): void {
    this.ctx = getContext(this) as common.UIAbilityContext;
    this.init();
  }

  aboutToDisappear(): void {
    if (this.timerId >= 0) {
      clearInterval(this.timerId);
      this.timerId = -1;
    }
    if (this.proxy !== null) {
      this.proxy.stop();
      this.proxy = null;
    }
    this.stop.stopped = true;
  }

  async init(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      await loadRefDb(this.ctx);
      this.provs = provinces();
      this.dbText = dbInfo();
      const zi = this.provs.indexOf('浙江');
      this.provIdx = zi >= 0 ? zi : 0;
      this.refreshCarriers();
    } catch (e) {
      this.dbText = '参考库加载失败: ' + JSON.stringify(e);
    }
    await this.refreshIfaces();
  }

  async refreshIfaces(): Promise<void> {
    this.ifaces = await listIfaces();
    const ip = pickMulticastIface(this.ifaces);
    let idx = 0;
    for (let i = 0; i < this.ifaces.length; i++) {
      if (this.ifaces[i].ipv4 === ip) {
        idx = i;
        break;
      }
    }
    this.ifaceIdx = idx;
    if (this.host === '') {
      this.host = lanIpForUdpxy(this.ifaces);
    }
  }

  refreshCarriers(): void {
    if (this.provs.length === 0) {
      return;
    }
    this.carrierList = carriers(this.provs[this.provIdx]);
    this.carrierIdx = 0;
  }

  toast(msg: string): void {
    promptAction.showToast({ message: msg, duration: 2500 });
  }

  async doUpdateRefDb(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    this.updating = true;
    try {
      await updateRefDb(this.ctx, (done: number, total: number) => {
        this.dbText = '正在更新参考库 ' + done.toString() + '/' + total.toString() + ' …';
      });
      this.provs = provinces();
      const zi = this.provs.indexOf('浙江');
      this.provIdx = zi >= 0 ? zi : 0;
      this.refreshCarriers();
      this.dbText = dbInfo();
      this.toast('参考库更新完成');
    } catch (e) {
      this.dbText = dbInfo();
      this.toast('更新失败: ' + JSON.stringify(e));
    }
    this.updating = false;
  }

  loadChannels(): void {
    if (this.provs.length === 0 || this.carrierList.length === 0) {
      this.toast('参考库未就绪');
      return;
    }
    const prov = this.provs[this.provIdx];
    const carrier = this.carrierList[this.carrierIdx].carrier;
    this.channels = channelsFor(prov, carrier);
    this.progress = '已载入 ' + prov + carrier + ' ' + this.channels.length.toString() + ' 个候选（未实测）';
  }

  addManual(): void {
    const g = this.manualGroup.trim();
    const p = parseInt(this.manualPort);
    if (!/^\d+\.\d+\.\d+\.\d+$/.test(g) || isNaN(p) || p <= 0 || p > 65535) {
      this.toast('请输入正确的组播地址与端口');
      return;
    }
    const first = parseInt(g.split('.')[0]);
    if (first < 224 || first > 239) {
      this.toast('组播地址应为 224~239 段');
      return;
    }
    const ch = new Channel();
    ch.name = '手动(' + g + ')';
    ch.group = g;
    ch.port = p;
    ch.source = 'manual';
    this.channels = [...this.channels, ch];
    this.manualGroup = '';
  }

  async doVerify(): Promise<void> {
    if (this.channels.length === 0) {
      this.toast('请先载入频道');
      return;
    }
    if (this.ifaces.length === 0) {
      this.toast('无可用网卡');
      return;
    }
    const iface = this.ifaces[this.ifaceIdx].ipv4;
    this.verifying = true;
    this.stop = new StopToken();
    const stop = this.stop;
    await verifyBatch(this.channels, iface, 4, 5000,
      (done: number, total: number, ch: Channel, r: VerifyResult) => {
        applyVerifyResult(ch, r);
        ch.bytes = r.bytes;
        ch.error = r.error;
        this.progress = done.toString() + '/' + total.toString() + ' ' + ch.name + (r.ok ? ' ✓' : ' ✗');
        this.channels = [...this.channels];
      }, stop);
    this.verifying = false;
    let okN = 0;
    for (let i = 0; i < this.channels.length; i++) {
      if (this.channels[i].ok) {
        okN += 1;
      }
    }
    this.progress = '完成：' + okN.toString() + '/' + this.channels.length.toString() + ' 可用';
  }

  async doSaveM3U(): Promise<void> {
    const fmts: string[] = ['udp', 'rtp', 'udpxy'];
    const fmt = fmts[this.fmtIdx];
    let okN = 0;
    for (let i = 0; i < this.channels.length; i++) {
      if (this.channels[i].ok) {
        okN += 1;
      }
    }
    if (okN === 0) {
      this.toast('没有验证可用的频道（先验证，或勾选导出全部）');
      return;
    }
    const port = parseInt(this.m3uPort);
    const content = buildM3U(this.channels, fmt, this.host, isNaN(port) ? 9999 : port, true);
    try {
      const uri = await saveTextFile('iptv-' + fmt + '.m3u', content);
      this.m3uMsg = uri !== '' ? '已保存 ' + okN.toString() + ' 个频道 → ' + uri : '已取消';
    } catch (e) {
      this.m3uMsg = '保存失败: ' + JSON.stringify(e);
    }
  }

  async toggleProxy(): Promise<void> {
    if (this.proxyRunning) {
      if (this.proxy !== null) {
        await this.proxy.stop();
        this.proxy = null;
      }
      if (this.timerId >= 0) {
        clearInterval(this.timerId);
        this.timerId = -1;
      }
      this.proxyRunning = false;
      this.proxyMsg = '已停止';
      this.proxyActive = '';
      return;
    }
    if (this.ifaces.length === 0) {
      this.toast('无可用网卡');
      return;
    }
    const port = parseInt(this.proxyPort);
    if (isNaN(port) || port <= 0 || port > 65535) {
      this.toast('端口不正确');
      return;
    }
    const iface = this.ifaces[this.ifaceIdx].ipv4;
    const p = new ProxyServer(iface, port, (): Channel[] => this.channels);
    try {
      const msg = await p.start();
      this.proxy = p;
      this.proxyRunning = true;
      this.proxyMsg = msg;
      this.timerId = setInterval(() => {
        if (this.proxy === null) {
          return;
        }
        let s = '';
        this.proxy.active.forEach((v: number, k: string) => {
          s += k + ' 观看数 ' + v.toString() + '\n';
        });
        this.proxyActive = s !== '' ? s : '（无活跃流）';
      }, 2000);
    } catch (e) {
      this.proxyMsg = '启动失败: ' + JSON.stringify(e);
    }
  }

  @Builder
  verifyTab() {
    Column({ space: 8 }) {
      Row({ space: 8 }) {
        Text(this.dbText).fontSize(12).fontColor(SUB).layoutWeight(1)
        Button(this.updating ? '更新中…' : '在线更新参考库')
          .fontSize(12)
          .enabled(!this.updating)
          .onClick(() => {
            this.doUpdateRefDb();
          })
      }.width('100%')
      Row({ space: 8 }) {
        Select(this.provs.map((p: string): SelectOption => {
          return { value: p } as SelectOption;
        }))
          .selected(this.provIdx)
          .value(this.provs.length > 0 ? this.provs[this.provIdx] : '省份')
          .onSelect((index: number) => {
            this.provIdx = index;
            this.refreshCarriers();
          })
          .layoutWeight(1)
        Select(this.carrierList.map((c: CarrierInfo): SelectOption => {
          return { value: c.label + ' ' + c.count.toString() } as SelectOption;
        }))
          .selected(this.carrierIdx)
          .value(this.carrierList.length > 0 ? this.carrierList[this.carrierIdx].label : '运营商')
          .onSelect((index: number) => {
            this.carrierIdx = index;
          })
          .layoutWeight(1)
        Button('载入参考库')
          .backgroundColor(ACCENT)
          .onClick(() => {
            this.loadChannels();
          })
      }.width('100%')

      Row({ space: 8 }) {
        Select(this.ifaces.map((i: IfaceInfo): SelectOption => {
          return { value: i.name + ' ' + i.ipv4 + (i.kind === 'wifi' ? ' (WiFi)' : ' (有线)') } as SelectOption;
        }))
          .selected(this.ifaceIdx)
          .value(this.ifaces.length > 0 ? this.ifaces[this.ifaceIdx].ipv4 : '无网卡')
          .onSelect((index: number) => {
            this.ifaceIdx = index;
          })
          .layoutWeight(1)
        Button('刷新网卡')
          .onClick(() => {
            this.refreshIfaces();
          })
      }.width('100%')

      Row({ space: 8 }) {
        Button(this.verifying ? '验证中…' : '验证全部')
          .backgroundColor(ACCENT)
          .enabled(!this.verifying)
          .onClick(() => {
            this.doVerify();
          })
        Button('停止')
          .enabled(this.verifying)
          .onClick(() => {
            this.stop.stopped = true;
          })
        Text(this.progress).fontSize(12).fontColor(SUB).layoutWeight(1)
      }.width('100%')

      Row({ space: 8 }) {
        TextInput({ text: this.manualGroup, placeholder: '手动添加：组播地址 如 233.50.201.118' })
          .onChange((v: string) => {
            this.manualGroup = v;
          })
          .layoutWeight(2)
        TextInput({ text: this.manualPort, placeholder: '端口' })
          .onChange((v: string) => {
            this.manualPort = v;
          })
          .layoutWeight(1)
        Button('添加')
          .onClick(() => {
            this.addManual();
          })
      }.width('100%')

      List({ space: 4 }) {
        ForEach(this.channels, (ch: Channel) => {
          ListItem() {
            Row({ space: 8 }) {
              Column({ space: 2 }) {
                Text(ch.name).fontSize(14).fontWeight(FontWeight.Medium)
                Text(ch.group + ':' + ch.port.toString() +
                  (ch.res !== '' ? ' · ' + ch.res : '') +
                  (ch.video !== '' ? ' · ' + ch.video : ''))
                  .fontSize(11).fontColor(SUB)
              }.alignItems(HorizontalAlign.Start).layoutWeight(1)

              Text(ch.ok ? '可用' : (ch.tested ? '不可用' : '未测'))
                .fontSize(12)
                .fontColor(ch.ok ? OKC : (ch.tested ? BADC : SUB))
            }.width('100%').padding(8)
            .backgroundColor(Color.White)
            .borderRadius(8)
          }
        }, (ch: Channel): string => ch.group + ':' + ch.port.toString() + ':' +
          (ch.ok ? '1' : '0') + ':' + ch.name)
      }
      .layoutWeight(1)
      .width('100%')
    }
    .padding(12)
    .width('100%')
    .height('100%')
  }

  @Builder
  m3uTab() {
    Column({ space: 12 }) {
      Text('生成播放列表（只导出验证可用的频道）').fontSize(14).fontWeight(FontWeight.Medium)
      Row({ space: 8 }) {
        Text('格式').fontSize(13)
        Select([
          { value: 'udp（组播直连）' } as SelectOption,
          { value: 'rtp' } as SelectOption,
          { value: 'udpxy（HTTP 转发）' } as SelectOption
        ])
          .selected(this.fmtIdx)
          .value(['udp（组播直连）', 'rtp', 'udpxy（HTTP 转发）'][this.fmtIdx])
          .onSelect((index: number) => {
            this.fmtIdx = index;
          })
          .layoutWeight(1)
      }.width('100%')

      Row({ space: 8 }) {
        Text('转发主机').fontSize(13)
        TextInput({ text: this.host, placeholder: '本机局域网 IP' })
          .onChange((v: string) => {
            this.host = v;
          })
          .layoutWeight(2)
        TextInput({ text: this.m3uPort, placeholder: '端口' })
          .onChange((v: string) => {
            this.m3uPort = v;
          })
          .layoutWeight(1)
      }.width('100%')

      Button('生成并保存 M3U…')
        .backgroundColor(ACCENT)
        .width('100%')
        .onClick(() => {
          this.doSaveM3U();
        })
      Text(this.m3uMsg).fontSize(12).fontColor(SUB).width('100%')
      Text('udp 版给支持组播的设备（电视/盒子/VLC）；udpxy 版配合「转发」页或路由器 udpxy 使用。')
        .fontSize(12).fontColor(SUB)
    }
    .padding(12)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  proxyTab() {
    Column({ space: 12 }) {
      Text('组播 → HTTP 单播转发（udpxy 等价）').fontSize(14).fontWeight(FontWeight.Medium)
      Row({ space: 8 }) {
        Text('端口').fontSize(13)
        TextInput({ text: this.proxyPort, placeholder: '9999' })
          .onChange((v: string) => {
            this.proxyPort = v;
          })
          .layoutWeight(1)
        Button(this.proxyRunning ? '停止转发' : '启动转发')
          .backgroundColor(this.proxyRunning ? BADC : ACCENT)
          .onClick(() => {
            this.toggleProxy();
          })
      }.width('100%')

      Text(this.proxyMsg).fontSize(12).fontColor(SUB).width('100%')
      if (this.proxyRunning && this.ifaces.length > 0) {
        Column({ space: 4 }) {
          Text('播放列表（HTTP）: http://' + this.ifaces[this.ifaceIdx].ipv4 + ':' + this.proxyPort + '/playlist.m3u')
            .fontSize(12).copyOption(CopyOptions.LocalDevice)
          Text('单频道: http://' + this.ifaces[this.ifaceIdx].ipv4 + ':' + this.proxyPort + '/udp/<组播地址>:<端口>')
            .fontSize(12).copyOption(CopyOptions.LocalDevice)
          Text('状态: http://' + this.ifaces[this.ifaceIdx].ipv4 + ':' + this.proxyPort + '/status')
            .fontSize(12).copyOption(CopyOptions.LocalDevice)
        }.alignItems(HorizontalAlign.Start).width('100%')
      }
      Text(this.proxyActive).fontSize(12).fontColor(SUB).width('100%')
      Text('⚠ 仅限局域网使用，禁止映射公网。转发依赖本机开机；7×24 需求请用 NAS/路由器方案。')
        .fontSize(12).fontColor('#D97706')
    }
    .padding(12)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  aboutTab() {
    Column({ space: 12 }) {
      Text('无双IPTV抓源工具 · 鸿蒙精简版').fontSize(18).fontWeight(FontWeight.Bold)
      Text('v2.1.0 测试版（HarmonyOS）').fontSize(13).fontColor(SUB)
      Text('⚠ 测试版声明：未做真机测试，仅供参考。').fontSize(13).fontColor(BADC)
      Divider()
      Text('功能：全国 31 省参考库载入 → 组播加组实测验证（自动命名/编码/分辨率）→ M3U 生成 → HTTP 转发。')
        .fontSize(13)
      Text('与 Windows/Linux 版同一套 TS 解析与命名规则；参考库为同一份社区数据（xisohi/CHINA-IPTV）。')
        .fontSize(13)
      Text('限制：鸿蒙第三方应用无原始抓包权限，本版不含「抓包发现频道」，请用参考库 + 实测验证。')
        .fontSize(13).fontColor('#D97706')
      Text('网络前提：设备需接入 IPTV 专网/已桥接的局域网（有线口），组播才能到达。')
        .fontSize(13)
      Divider()
      Text('作者：B站-锤无双 · QQ群 170621740').fontSize(13)
      Text('教程：https://www.bilibili.com/video/BV17SWk6VEPZ/').fontSize(12).copyOption(CopyOptions.LocalDevice)
      Text('仓库：https://github.com/chuiziyao/wushuang-iptv').fontSize(12).copyOption(CopyOptions.LocalDevice)
      Text('隐私：不后台联网、不上传数据；参考库仅含公开组播地址。').fontSize(12).fontColor(SUB)
    }
    .padding(16)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Column() {
      Tabs({ barPosition: BarPosition.Start, index: this.tabIdx }) {
        TabContent() {
          this.verifyTab()
        }.tabBar('① 频道验证')

        TabContent() {
          this.m3uTab()
        }.tabBar('② M3U')

        TabContent() {
          this.proxyTab()
        }.tabBar('③ 转发')

        TabContent() {
          this.aboutTab()
        }.tabBar('④ 关于')
      }
      .barMode(BarMode.Fixed)
      .layoutWeight(1)
      .onChange((index: number) => {
        this.tabIdx = index;
      })
    }
    .width('100%')
    .height('100%')
    .backgroundColor(BG)
  }
}
