# 无双IPTV抓源工具 · CLI 命令行调用说明（v2.1 新增）

> 本文档面向 **AI 工具 / 自动化脚本**，也适合喜欢命令行的用户。
> 作者：锤无双 · [B站教程](https://www.bilibili.com/video/BV17SWk6VEPZ/) · QQ群：170621740
> 开源仓库：https://github.com/chuiziyao/wushuang-iptv

## 一、两种调用方式

| 方式 | 命令形式 | 说明 |
|---|---|---|
| **CLI 版（推荐）** | `无双IPTV-CLI.exe <子命令> [参数]` | 控制台程序，stdout 直接输出 JSON；**不强制管理员**（仅 capture 需要） |
| GUI 版兼容入口 | `无双IPTV抓源工具.exe cli <子命令> [参数]` | 无控制台，stdout 不可用，**必须用 `--out 文件` 取结果**（缺省写入当前目录 `cli-result.json`）；启动会弹 UAC |
| 源码方式 | `python src\main.py cli <子命令> [参数]` | 需要 Python 3.10+，无第三方依赖 |

AI 工具（Claude Code / DSH / Cursor / Manus 等）拿到 `无双IPTV-CLI.exe` 后即可直接命令行操作全流程，无需点击 GUI。

## 二、输出协议（对 AI 友好）

- **stdout 只有一个 JSON 结果文档**（UTF-8），结构固定：
  ```json
  { "ok": true, "tool": "无双IPTV抓源工具", "version": "2.1.0", "command": "verify", ... }
  ```
  失败时 `ok=false`，附 `error`（和可能的 `hint`）。
- **stderr 是 JSON Lines 进度日志**（`{"event":"verify_progress","done":3,"total":202,...}`），不污染 stdout，可忽略或用于展示进度。
- `--out FILE`：结果 JSON 同时原子写入文件（先写 .tmp 再替换）。
- **退出码**：`0`=成功 · `1`=运行失败 · `2`=参数错误 · `3`=需要管理员权限。
- **频道文件贯穿全流程**：`load / capture / analyze / verify` 的结果 JSON 内含 `channels` 数组，可直接作为下一步 `verify / m3u / proxy` 的 `--channels` 输入；也兼容 `.m3u` 文件和裸数组 JSON。

## 三、子命令参考

### info — 环境总览（AI 建议的第一步）
```
无双IPTV-CLI.exe info
```
返回：是否管理员、pktmon 路径、网卡列表（名称/IP/有线无线）、**建议的组播网卡** `suggested_multicast_iface`、**建议的 udpxy 主机** `suggested_udpxy_host`、参考库概况。

### ifaces — 网卡列表
```
无双IPTV-CLI.exe ifaces
```

### refdb — 全国参考库（31省 × 电信/联通/移动/广电）
```
无双IPTV-CLI.exe refdb info                          # 库概况 + 省份列表
无双IPTV-CLI.exe refdb carriers --province 浙江       # 该省运营商与频道数
无双IPTV-CLI.exe refdb update                        # 在线更新（仅此时联网）
无双IPTV-CLI.exe refdb import --file refdb.json      # 离线导入
```

### load — 载入某省某运营商频道（候选，未实测）
```
无双IPTV-CLI.exe load --province 浙江 --carrier 电信 --out channels.json
```
省份/运营商支持中文或拼音（`zhejiang` / `telecom`）。运营商：电信/联通/移动/广电。

### verify — 真实加组收流验证（核心功能，不需管理员）
```
无双IPTV-CLI.exe verify --channels channels.json --out verified.json
无双IPTV-CLI.exe verify --province 浙江 --carrier 电信 --out verified.json   # 载入+验证一步完成
无双IPTV-CLI.exe verify --group 233.50.201.118 --port 5140                  # 只验证单个频道
```
| 参数 | 默认 | 说明 |
|---|---|---|
| `--iface IP` | 自动选有线口 | 组播网卡：搭线阶段选有线口(169.254.x 也可)，已桥接选有线口(192.168.x) |
| `--timeout 秒` | 5 | 单频道收流超时 |
| `--concurrency N` | 4 | 并发验证数 |
| `--limit N` | 全部 | 只验证前 N 个（调试用） |

结果含每频道 `ok/video/audio/res/sdt_name`，实测成功自动规范化命名（CCTV-1 HD → CCTV1）。

### capture — pktmon 抓包并分析（需管理员）
```
无双IPTV-CLI.exe capture --seconds 90 --out channels.json
```
非管理员运行返回退出码 3 + JSON 错误提示。抓包期间请让机顶盒开机并逐个换台（每频道停 3~5 秒）。`--keep-pcap` 保留抓包文件；`--workdir` 指定临时目录。结果含频道候选 + 流统计 + 机顶盒信息（**含账号，分享前脱敏**）。

### analyze — 分析已有抓包文件（不需管理员）
```
无双IPTV-CLI.exe analyze --pcap cap.pcap --out channels.json
```
支持 pcap / pcapng / etl（pktmon 产物）。

### m3u — 生成/更新播放列表
```
无双IPTV-CLI.exe m3u --channels verified.json --outdir D:\iptv
```
默认生成 `iptv.m3u`（udp 组播直连）+ `iptv-http.m3u`（udpxy 转发配对版），只导出验证可用频道，自动与目录中已有文件合并。
| 参数 | 默认 | 说明 |
|---|---|---|
| `--name` | iptv.m3u | 文件名 |
| `--fmt udp\|rtp\|udpxy` | udp | 主格式 |
| `--host IP` | 自动取本机局域网 IP | udpxy 主机 |
| `--port N` | 9999 | udpxy 端口 |
| `--all` | 关 | 连未验证/不可用频道一起导出 |
| `--no-merge` / `--no-pair` | 关 | 不合并已有文件 / 不生成配对版 |
| `--logo-base URL` | 空 | 台标 URL 前缀 |

### proxy — 组播→HTTP 转发服务（前台长驻，udpxy 等价）
```
无双IPTV-CLI.exe proxy --port 9999 --channels verified.json
```
启动即输出含 URL 的 JSON，然后前台持续运行（AI 工具请放后台任务），Ctrl+C 停止。
端点：`/status` 状态 · `/playlist.m3u` HTTP 版列表 · `/raw.m3u` udp 版列表 · `/udp/<组>:<端口>` 单频道转发。
**仅限局域网，禁止映射公网。**

### push — 推送播放列表到 NAS
```
无双IPTV-CLI.exe push --files iptv.m3u iptv-http.m3u --method smb --target \\192.168.1.84\共享\iptv
无双IPTV-CLI.exe push --files iptv.m3u --method webdav --target http://192.168.1.84:5005/iptv --user u --password p
```

## 四、AI 工具典型工作流

**场景 B（已桥接，机顶盒退役）——全自动，无需管理员：**
```
无双IPTV-CLI.exe info
无双IPTV-CLI.exe verify --province 浙江 --carrier 电信 --out verified.json
无双IPTV-CLI.exe m3u --channels verified.json --outdir D:\iptv
无双IPTV-CLI.exe push --files D:\iptv\iptv.m3u D:\iptv\iptv-http.m3u --method webdav --target http://NAS:5005/iptv
```

**场景 A（首次抓源）——capture 一步需管理员终端：**
```
无双IPTV-CLI.exe capture --seconds 90 --out channels.json     # 管理员终端；期间机顶盒换台
无双IPTV-CLI.exe verify --channels channels.json --out verified.json
无双IPTV-CLI.exe m3u --channels verified.json --outdir D:\iptv
```

**7×24 转发（本机或 NAS 已有 udpxy/Tvheadend 则跳过 proxy）：**
```
无双IPTV-CLI.exe proxy --port 9999 --channels verified.json   # 后台运行
```

## 五、注意事项

- **首次运行可能弹出 Windows 防火墙提示，请点「允许访问」**（验证频道/转发服务需要接收组播流；点了「取消」会生成阻止规则，需在「Windows Defender 防火墙 → 允许应用通过防火墙」中改为允许）。
- 验证/生成 M3U/参考库操作**不需要管理员**；只有 `capture`（pktmon）需要。
- 参考库只是候选，各地运营商随时可能调整组播地址，**一切以本机 verify 实测为准**。
- 软件不后台联网、不上传数据；仅 `refdb update` 主动联网下载公开频道列表。
- `capture/analyze` 结果中的 `stb` 字段含机顶盒账号，仅本机使用，分享前请脱敏。
- 转发服务仅限局域网。
- 硬件接线方法（傻瓜交换机搭线/桥接/路由器 IPTV 口）见《使用说明.md》与 B 站视频教程。
