/**
 * M3U 播放列表生成与导出（m3u.py 的 ArkTS 精简移植）。
 * 导出用系统 DocumentViewPicker，用户自选保存位置。
 */
import { picker } from '@kit.CoreFileKit';
import { fileIo } from '@kit.CoreFileKit';
import { Channel } from '../model/Channel';

export function buildM3U(channels: Channel[], fmt: string, host: string, port: number,
  onlyOk: boolean): string {
  const lines: string[] = ['#EXTM3U'];
  for (let i = 0; i < channels.length; i++) {
    const ch = channels[i];
    if (onlyOk && !ch.ok) {
      continue;
    }
    const name = ch.name !== '' ? ch.name : ch.group + ':' + ch.port.toString();
    const cat = ch.cat !== '' ? ch.cat : '未分类';
    lines.push('#EXTINF:-1 tvg-name="' + name + '" group-title="' + cat + '",' + name);
    if (fmt === 'udpxy') {
      lines.push('http://' + host + ':' + port.toString() + '/udp/' + ch.group + ':' + ch.port.toString());
    } else if (fmt === 'rtp') {
      lines.push('rtp://' + ch.group + ':' + ch.port.toString());
    } else {
      lines.push('udp://@' + ch.group + ':' + ch.port.toString());
    }
  }
  return lines.join('\n') + '\n';
}

/** 通过系统保存对话框导出文本文件，返回保存的 URI（取消返回 ''）。 */
export async function saveTextFile(fileName: string, content: string): Promise<string> {
  const saver = new picker.DocumentViewPicker();
  const opts = new picker.DocumentSaveOptions();
  opts.newFileNames = [fileName];
  const uris = await saver.save(opts);
  if (uris.length === 0) {
    return '';
  }
  const file = fileIo.openSync(uris[0], fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE);
  fileIo.writeSync(file.fd, content);
  fileIo.closeSync(file);
  return uris[0];
}
