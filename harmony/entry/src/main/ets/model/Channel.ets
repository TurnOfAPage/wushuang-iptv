/**
 * 共享数据模型（与 Windows/Linux 版频道字段语义一致）。
 */

export class Channel {
  name: string = '';
  group: string = '';
  port: number = 0;
  cat: string = '其他频道';
  ok: boolean = false;
  tested: boolean = false;
  video: string = '';
  audio: string = '';
  res: string = '';
  sdtName: string = '';
  source: string = 'ref';
  refOk: boolean = false;
  userNamed: boolean = false;
  bytes: number = 0;
  error: string = '';
}

export class VerifyResult {
  ok: boolean = false;
  video: string = '';
  audio: string = '';
  res: string = '';
  sdtName: string = '';
  bytes: number = 0;
  pkts: number = 0;
  error: string = '';
}

export class IfaceInfo {
  name: string = '';
  ipv4: string = '';
  kind: string = 'other'; // wired | wifi | other
  gateway: string = '';
}

export class CarrierInfo {
  label: string = '';
  carrier: string = '';
  count: number = 0;
}
