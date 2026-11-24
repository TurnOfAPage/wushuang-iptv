# 无双IPTV录像工具 · CLI 使用说明

> ⚠ **本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。传播录制文件会导致版权风险，该风险与本软件无关。**
> 独立产品 CLI：`WushuangIPTV-Recorder-CLI.exe`（Windows）/ `WushuangIPTV-Recorder-CLI`（Linux/macOS）。
> 源码方式：`python recorder/rec_main.py cli <子命令>`（全平台）；GUI 版 exe 也支持 `cli` 入口（无控制台，须 `--out` 取结果）。
> **所有命令都不需要管理员/root。** 输出协议与主工具 CLI 完全一致：
> stdout 单个 JSON 结果（`ok/tool/version/command/...`）；stderr JSON Lines 进度；
> 退出码 `0`成功 `1`失败 `2`参数错误；`--out FILE` 原子写入结果文件。

## 命令总览

| 命令 | 作用 |
|---|---|
| `info` | 环境总览：网卡/建议组播口/缺省录像目录 |
| `record start` | 前台即时录制（Ctrl+C 优雅停止并收尾） |
| `record list` | 预约计划 + 录像索引 + 状态 |
| `record add` | 添加预约（手动时间段 或 EPG 节目关键词） |
| `record cancel --id SID` | 取消预约（在录的会停止并收尾为 partial） |
| `record delete --id RID` | 删除录像文件与索引（在录的拒绝删除） |
| `epg update` | 主动更新节目单（唯一联网点，用户显式触发） |
| `epg show --name X` | 查某频道节目单 |
| `epg map --channels F` | 频道↔EPG 映射报告 |
| `proxy` | 前台常驻：直播转发 + 预约调度 + 录像点播 |

公共参数：`--record-dir DIR`（缺省 **系统下载文件夹/无双IPTV录像**）、`--out FILE`。
Windows 入口：`无双IPTV录像工具\WushuangIPTV-Recorder-CLI.bat`（py 启动器→已安装 Python 信任链；
无安装 Python 时回退 bundled 运行时）；Linux/macOS 仍为单文件 `WushuangIPTV-Recorder-CLI`。
频道来源三选一（与主工具 verify 一致）：`--channels FILE`（verify 结果 JSON/裸数组/m3u）+ `--name 频道名`，
或 `--group G --port P` 直给组播地址（免频道文件）。`--name` 按 `normalize_name` 归一匹配（CCTV-5体育 → CCTV5）。

## record start · 即时录

```bash
WushuangIPTV-Recorder-CLI.exe record start --channels verified.json --name CCTV5 --minutes 90
WushuangIPTV-Recorder-CLI.exe record start --group 233.50.201.118 --port 5140 --seconds 30
WushuangIPTV-Recorder-CLI.exe record start --channels verified.json --name CCTV5 --until 21:30
```

| 参数 | 说明 |
|---|---|
| `--minutes N` | 录制分钟数，默认 60 |
| `--seconds N` | 录制秒数（优先于 --minutes） |
| `--until HH:MM` | 录到指定时刻（已过则次日） |
| `--iface IP` | 组播网卡（缺省自动选有线口） |
| `--quota-gb N` | 配额 GB，默认 100，0=不限 |
| `--max-concurrent N` | 并发路数上限，默认 2 |

**即时录时长精确**（不吃预约的提前/延后余量）。stderr 进度示例：

```json
{"event": "record_start", "time": "19:29:00", "name": "CCTV5", "rid": "r20261123_192900_CCTV5.ts"}
{"event": "record_progress", "time": "19:29:30", "bytes": 26214400, "duration": 30, "gaps": 0}
{"event": "record_gap", "time": "19:41:02", "gaps": 1}
```

结果 JSON：`recording`（id/name/start/end/duration/bytes/parts/status/gaps/error）+ `vod_url`。
`status`：`done` 完整 / `partial` 提前停止 / `error` 出错（如 disk_full）。
文件在 `<record-dir>/ts/<rid>.ts`，VLC/Kodi 直接可播；`vod_url` 需同目录 `proxy` 常驻。

## record add · 预约

```bash
# 手动时间段（ISO 本地时间）
WushuangIPTV-Recorder-CLI.exe record add --name CCTV5 --start 2026-11-24T19:30 --end 2026-11-24T21:30
# EPG 节目关键词（先 epg update；--date 限定日期）
WushuangIPTV-Recorder-CLI.exe record add --name CCTV5 --title "英超" --date 2026-11-24
```

- 预约自动加余量：提前 `--pad-before`（默认 60s）开录、延后 `--pad-after`（默认 120s）收尾，防节目提前/拖堂。
- 同频道时段重叠会拒绝。计划写入 `records.json`，**由常驻服务到点执行**
  （`proxy --record-dir 同目录`，或 GUI ③ 页服务）；服务没跑时计划保留，启动后恢复。
- `record list` 看计划与录像；`record cancel --id <计划ID>` 取消。

## epg · 节目单

```bash
WushuangIPTV-Recorder-CLI.exe epg update --channels verified.json          # 内置源逐个尝试
WushuangIPTV-Recorder-CLI.exe epg update --url https://example.com/e.xml   # 自定义 XMLTV
WushuangIPTV-Recorder-CLI.exe epg show --name CCTV5 --date 2026-11-24
WushuangIPTV-Recorder-CLI.exe epg map --channels verified.json             # 映射成功/失败清单
```

- 内置候选源：epg.pw / 51zmt.top / 112114.xyz（可用性随时间变化，失败自动换源；可 `--url` 自定义）。
- 不带 `--channels` 时只保留央视/卫视类频道节目（控制缓存体积）。
- 缓存：`epg.xml.gz`（原始）+ `epg.json`（映射后、未来 7 天）。映射失败的频道仍可手动时间段预约。
- **仅命令触发联网**，无后台自动更新。

## proxy · 常驻服务（NAS 推荐形态）

```bash
WushuangIPTV-Recorder-CLI proxy --channels verified.json --record-dir /volume1/iptv/rec --port 9999
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--port` | 9999 | 监听端口 |
| `--iface` | 自动选有线口 | 组播网卡 IP |
| `--channels` | 可省略 | 直播列表 /playlist.m3u 与预约名字解析 |
| `--record-dir` | 程序目录/recordings | 录像目录（状态文件也在内） |
| `--quota-gb` | 100 | 配额，0=不限 |
| `--pad-before/--pad-after` | 60/120 | 预约余量秒数 |
| `--max-concurrent` | 2 | 同时录制路数（光猫可能限速加组，勿贪多） |
| `--missed` | skip | 重启后错过计划：skip 标记 / remainder 续录剩余 |

端点：

| 路径 | 内容 |
|---|---|
| `/playlist.m3u` `/raw.m3u` | 直播列表（HTTP 版 / udp 版，同主工具） |
| `/udp/<组>:<端口>` | 直播转发 |
| `/recordings.m3u` | **录像点播列表**（真实时长，倒序） |
| `/recordings.json` | 录像索引 JSON |
| `/vod/<录像ID>` | 录像点播，支持 Range 拖动/HEAD/边录边看/多分段虚拟拼接 |
| `/status` | 活跃流 + 录制状态 + 待录计划 + 配额 |

启动 JSON 的 `urls` 含全部地址。服务前台长驻：放后台任务/计划任务/Docker（host 网络），
解析 stderr JSONL（`schedule_started/record_progress/record_done/quota_cleaned/...`）。
**仅限局域网，禁止映射公网。**

## NAS 部署示例（群晖，免 Docker）

任务计划 → 开机触发 → root（仅开机任务需要 root 设 sysctl，服务本身普通用户可跑）：

```bash
sysctl -w net.ipv4.conf.all.force_igmp_version=2   # 加组收流前提，必须保留
/var/packages/python314/target/bin/python3 /volume1/iptv/recorder/rec_main.py cli proxy \
    --channels /volume1/iptv/verified.json --record-dir /volume1/iptv/rec --port 9999
```

（Python 路径按实际套件调整；任何 Python 3.10+ 均可，零第三方依赖。Docker 方式见主仓库 docker/README.md，host 网络必须。）

## 与主工具 CLI 的衔接

```bash
WushuangIPTV-CLI.exe verify --province 浙江 --carrier 电信 --out verified.json   # 主工具实测
WushuangIPTV-Recorder-CLI.exe proxy --channels verified.json --record-dir ./rec  # 本产品录像+点播
```
