/**
 * 原生组播加组验证（verify.py 的 ArkTS 移植）：
 * MulticastSocket 加组 → 收流 → TS 解析出频道名/编码/分辨率。
 * 仅需 ohos.permission.INTERNET（普通权限），不需要 root。
 */
import { socket } from '@kit.NetworkKit';
import { TSAnalyzer, stripRtp } from './TS';
import { Channel, VerifyResult } from '../model/Channel';

function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void) => {
    setTimeout(resolve, ms);
  });
}

export class StopToken {
  stopped: boolean = false;
}

export async function verifyChannel(group: string, port: number, ifaceIp: string,
  timeoutMs: number = 5000, minBytes: number = 200000): Promise<VerifyResult> {
  const res = new VerifyResult();
  let ms: socket.MulticastSocket | null = null;
  let joined = false;
  try {
    ms = socket.constructMulticastSocketInstance();
    // bind 到指定网卡 IP 即选择组播出口网卡（等价 IP_MULTICAST_IF）
    await ms.bind({ address: ifaceIp !== '' ? ifaceIp : '0.0.0.0', port: port, family: 1 });
    await ms.addMembership({ address: group, port: port, family: 1 });
    joined = true;
    const ana = new TSAnalyzer();
    ms.on('message', (info: socket.SocketMessageInfo) => {
      const data = new Uint8Array(info.message);
      res.pkts += 1;
      res.bytes += data.length;
      const ts = stripRtp(data);
      if (ts !== null) {
        ana.feed(ts);
      }
    });
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await sleep(100);
      if (ana.ready && res.bytes >= minBytes) {
        // 再等一会 SDT（频道名）与 SPS（分辨率），最多 2.5s
        const extra = Date.now() + 2500;
        while (Date.now() < extra) {
          const wantName = ana.serviceName() === '';
          const wantRes = ana.videoCodec === 'h264' && ana.resolution === '';
          if (!wantName && !wantRes) {
            break;
          }
          await sleep(100);
        }
        break;
      }
    }
    res.ok = ana.ready;
    res.video = ana.videoCodec;
    res.audio = ana.audioCodec;
    res.res = ana.resolution;
    res.sdtName = ana.serviceName();
    if (!res.ok && res.bytes === 0) {
      res.error = '未收到数据（组播未到达此网卡/频道停播）';
    } else if (!res.ok) {
      res.error = '收到数据但无法解析出音视频流';
    }
  } catch (e) {
    res.error = 'socket错误: ' + JSON.stringify(e);
  } finally {
    if (ms !== null) {
      if (joined) {
        try {
          await ms.dropMembership({ address: group, port: port, family: 1 });
        } catch (e) {
          // 忽略退组失败
        }
      }
      try {
        ms.off('message');
      } catch (e) {
        // 忽略
      }
      try {
        await ms.close();
      } catch (e) {
        // 忽略
      }
    }
  }
  return res;
}

export async function verifyBatch(channels: Channel[], ifaceIp: string, concurrency: number,
  timeoutMs: number, onProgress: (done: number, total: number, ch: Channel, r: VerifyResult) => void,
  stop: StopToken): Promise<number> {
  let done = 0;
  let idx = 0;
  const total = channels.length;
  const worker = async (): Promise<void> => {
    while (true) {
      if (stop.stopped) {
        return;
      }
      const i = idx;
      idx += 1;
      if (i >= total) {
        return;
      }
      const ch = channels[i];
      const r = await verifyChannel(ch.group, ch.port, ifaceIp, timeoutMs);
      done += 1;
      onProgress(done, total, ch, r);
    }
  };
  const workers: Promise<void>[] = [];
  const n = Math.max(1, concurrency);
  for (let k = 0; k < n; k++) {
    workers.push(worker());
  }
  await Promise.all(workers);
  return done;
}
