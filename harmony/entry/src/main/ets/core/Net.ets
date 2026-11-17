/**
 * 网卡枚举与选口策略（netutil.py 的 HarmonyOS 移植）。
 * 通过 @ohos.net.connection 获取各网络的接口名/IPv4/承载类型/网关。
 */
import { connection } from '@kit.NetworkKit';
import { IfaceInfo } from '../model/Channel';

export async function listIfaces(): Promise<IfaceInfo[]> {
  const out: IfaceInfo[] = [];
  try {
    const nets = await connection.getAllNets();
    for (let i = 0; i < nets.length; i++) {
      try {
        const net = nets[i];
        const props = await connection.getConnectionProperties(net);
        const caps = await connection.getNetCapabilities(net);
        let ipv4 = '';
        for (let j = 0; j < props.linkAddresses.length; j++) {
          const la = props.linkAddresses[j];
          if (la.address.family === 1 && la.address.address !== '127.0.0.1' && ipv4 === '') {
            ipv4 = la.address.address;
          }
        }
        if (ipv4 === '') {
          continue;
        }
        let kind = 'other';
        if (caps.bearerTypes.includes(connection.NetBearType.BEARER_WIFI)) {
          kind = 'wifi';
        } else if (caps.bearerTypes.includes(connection.NetBearType.BEARER_ETHERNET)) {
          kind = 'wired';
        }
        let gw = '';
        for (let j = 0; j < props.routes.length; j++) {
          const rt = props.routes[j];
          if (rt.hasGateway && rt.gateway.family === 1 && rt.gateway.address !== '') {
            gw = rt.gateway.address;
            break;
          }
        }
        const info = new IfaceInfo();
        info.name = props.interfaceName;
        info.ipv4 = ipv4;
        info.kind = kind;
        info.gateway = gw;
        out.push(info);
      } catch (e) {
        continue;
      }
    }
  } catch (e) {
    // 无网络权限或无网络时返回空列表
  }
  return out;
}

/** 组播验证优先有线口（与 Windows/Linux 版策略一致）。 */
export function pickMulticastIface(ifaces: IfaceInfo[]): string {
  const wired: IfaceInfo[] = ifaces.filter((i: IfaceInfo): boolean => i.kind === 'wired' && i.ipv4 !== '');
  if (wired.length > 0) {
    wired.sort((a: IfaceInfo, b: IfaceInfo): number => (a.gateway !== '' ? 0 : 1) - (b.gateway !== '' ? 0 : 1));
    return wired[0].ipv4;
  }
  const other: IfaceInfo[] = ifaces.filter((i: IfaceInfo): boolean => i.ipv4 !== '' && i.kind !== 'wifi');
  if (other.length > 0) {
    return other[0].ipv4;
  }
  const wifi: IfaceInfo[] = ifaces.filter((i: IfaceInfo): boolean => i.ipv4 !== '');
  return wifi.length > 0 ? wifi[0].ipv4 : '';
}

/** HTTP 转发版 M3U 里填的地址：有网关的口优先。 */
export function lanIpForUdpxy(ifaces: IfaceInfo[]): string {
  const cands: IfaceInfo[] = ifaces.filter((i: IfaceInfo): boolean => i.ipv4 !== '' && i.gateway !== '');
  if (cands.length > 0) {
    cands.sort((a: IfaceInfo, b: IfaceInfo): number => (a.kind === 'wifi' ? 0 : 1) - (b.kind === 'wifi' ? 0 : 1));
    return cands[0].ipv4;
  }
  const all: IfaceInfo[] = ifaces.filter((i: IfaceInfo): boolean => i.ipv4 !== '');
  return all.length > 0 ? all[0].ipv4 : '192.168.1.100';
}
