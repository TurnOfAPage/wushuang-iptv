/**
 * 组播 → HTTP 单播转发服务（proxy.py 的 ArkTS 移植，udpxy 等价）。
 * TCPSocketServer 监听；/status /playlist.m3u /raw.m3u /udp/<组>:<端口>。
 * 仅限局域网使用，禁止映射公网。
 */
import { socket } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { Channel } from '../model/Channel';
import { buildM3U } from './M3U';

export class ProxyServer {
  ifaceIp: string;
  port: number;
  running: boolean = false;
  active: Map<string, number> = new Map();
  private server: socket.TCPSocketServer | null = null;
  private channelsCb: () => Channel[];

  constructor(ifaceIp: string, port: number, channelsCb: () => Channel[]) {
    this.ifaceIp = ifaceIp;
    this.port = port;
    this.channelsCb = channelsCb;
  }

  async start(): Promise<string> {
    if (this.server !== null) {
      return '已在运行';
    }
    const srv = socket.constructTCPSocketServerInstance();
    srv.on('connect', (conn: socket.TCPSocketConnection) => {
      this.handleConn(conn);
    });
    await srv.listen({ address: '0.0.0.0', port: this.port, family: 1 });
    this.server = srv;
    this.running = true;
    return '转发服务已启动: 0.0.0.0:' + this.port.toString() + ' (组播网卡 ' + this.ifaceIp + ')';
  }

  async stop(): Promise<void> {
    this.running = false;
    if (this.server !== null) {
      try {
        this.server.off('connect');
      } catch (e) {
        // 忽略
      }
      try {
        await this.server.close();
      } catch (e) {
        // 忽略
      }
      this.server = null;
    }
    this.active.clear();
  }

  private handleConn(conn: socket.TCPSocketConnection): void {
    let buf = '';
    let handled = false;
    conn.on('message', (info: socket.SocketMessageInfo) => {
      if (handled) {
        return;
      }
      const dec = util.TextDecoder.create('utf-8');
      buf += dec.decodeToString(new Uint8Array(info.message));
      const idx = buf.indexOf('\r\n\r\n');
      if (idx < 0) {
        if (buf.length > 65536) {
          this.sendText(conn, 400, 'text/plain', 'bad request');
          handled = true;
        }
        return;
      }
      handled = true;
      const line = buf.substring(0, buf.indexOf('\r\n'));
      const parts = line.split(' ');
      if (parts.length < 2 || parts[0] !== 'GET') {
        this.sendText(conn, 400, 'text/plain', 'bad request');
        return;
      }
      this.route(conn, parts[1].split('?')[0]);
    });
    conn.on('error', () => {
      // 连接错误按关闭处理
    });
  }

  private route(conn: socket.TCPSocketConnection, path: string): void {
    if (path === '/' || path === '/status') {
      const act: Record<string, number> = {};
      this.active.forEach((v: number, k: string) => {
        act[k] = v;
      });
      const body = JSON.stringify({ iface: this.ifaceIp, port: this.port, active: act });
      this.sendText(conn, 200, 'application/json', body);
      return;
    }
    if (path === '/playlist.m3u' || path === '/http.m3u') {
      const body = buildM3U(this.channelsCb(), 'udpxy', this.ifaceIp, this.port, true);
      this.sendText(conn, 200, 'audio/x-mpegurl', body);
      return;
    }
    if (path === '/raw.m3u') {
      const body = buildM3U(this.channelsCb(), 'udp', '', 0, true);
      this.sendText(conn, 200, 'audio/x-mpegurl', body);
      return;
    }
    const parts = path.replace(/^\//, '').split('/');
    if (parts.length === 2 && (parts[0] === 'udp' || parts[0] === 'rtp')) {
      const gp = parts[1].split(':');
      if (gp.length === 2) {
        const g = gp[0];
        const p = parseInt(gp[1]);
        if (!isNaN(p) && /^\d+\.\d+\.\d+\.\d+$/.test(g)) {
          this.stream(conn, g, p);
          return;
        }
      }
    }
    this.sendText(conn, 404, 'text/plain', 'not found');
  }

  private sendText(conn: socket.TCPSocketConnection, code: number, ctype: string, body: string): void {
    const enc = new util.TextEncoder();
    const bodyBytes = enc.encodeInto(body);
    const reason = code === 200 ? 'OK' : (code === 400 ? 'Bad Request' : 'Not Found');
    const head = 'HTTP/1.1 ' + code.toString() + ' ' + reason + '\r\n' +
      'Content-Type: ' + ctype + '\r\n' +
      'Content-Length: ' + bodyBytes.length.toString() + '\r\n' +
      'Connection: close\r\n\r\n';
    const headBytes = enc.encodeInto(head);
    const all = new Uint8Array(headBytes.length + bodyBytes.length);
    all.set(headBytes, 0);
    all.set(bodyBytes, headBytes.length);
    conn.send({ data: all.buffer as ArrayBuffer }).then(() => {
      conn.close();
    }).catch(() => {
      try {
        conn.close();
      } catch (e) {
        // 忽略
      }
    });
  }

  private stream(conn: socket.TCPSocketConnection, group: string, port: number): void {
    const key = group + ':' + port.toString();
    const ms = socket.constructMulticastSocketInstance();
    let closed = false;
    const cleanup = (): void => {
      if (closed) {
        return;
      }
      closed = true;
      const n = this.active.get(key);
      if (n !== undefined) {
        if (n <= 1) {
          this.active.delete(key);
        } else {
          this.active.set(key, n - 1);
        }
      }
      ms.off('message');
      ms.dropMembership({ address: group, port: port, family: 1 }).catch(() => {
      });
      ms.close().catch(() => {
      });
    };
    ms.bind({ address: this.ifaceIp !== '' ? this.ifaceIp : '0.0.0.0', port: port, family: 1 })
      .then(() => ms.addMembership({ address: group, port: port, family: 1 }))
      .then(() => {
        const n = this.active.get(key);
        this.active.set(key, (n !== undefined ? n : 0) + 1);
        const head = 'HTTP/1.1 200 OK\r\nContent-Type: video/MP2T\r\n' +
          'Connection: close\r\nCache-Control: no-cache\r\n\r\n';
        const enc = new util.TextEncoder();
        conn.send({ data: enc.encodeInto(head).buffer as ArrayBuffer }).catch(() => {
          cleanup();
        });
        ms.on('message', (info: socket.SocketMessageInfo) => {
          if (closed) {
            return;
          }
          conn.send({ data: info.message }).catch(() => {
            cleanup();
            try {
              conn.close();
            } catch (e) {
              // 忽略
            }
          });
        });
        conn.on('close', () => {
          cleanup();
        });
      })
      .catch(() => {
        cleanup();
        this.sendText(conn, 500, 'text/plain', 'join failed');
      });
  }
}
