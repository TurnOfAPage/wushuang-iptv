# AGENTS.md — 给 AI 工具的操作指南

本仓库是「无双IPTV抓源工具」的源码。**AI 工具（Claude Code / DSH / Cursor / Manus 等）可以通过 CLI 无界面操作本软件的全部核心功能**：载入参考库 → 实测验证频道 → 生成 M3U → 转发/推送 NAS。

## 方式一：直接用发布二进制（推荐，无需 Python）

从 [Releases](../../releases) 下载 `WushuangIPTV-CLI.exe`（Windows）或 `WushuangIPTV-CLI`（Linux/macOS，控制台版，不强制管理员），然后：

```bash
WushuangIPTV-CLI.exe info                                            # 第一步：环境总览（网卡/参考库/建议网卡）
WushuangIPTV-CLI.exe verify --province 浙江 --carrier 电信 --out verified.json   # 载入参考库并真实加组验证
WushuangIPTV-CLI.exe m3u --channels verified.json --outdir ./out     # 生成 udp + http 双版播放列表
# Linux/macOS 把 WushuangIPTV-CLI.exe 换成 ./WushuangIPTV-CLI 即可，参数完全一致
```

**输出协议**：stdout 只有一个 JSON 结果（`ok/tool/version/command/...`）；stderr 是 JSON Lines 进度；退出码 `0`成功 `1`失败 `2`参数错误 `3`需管理员；`--out FILE` 把结果写入文件。

**频道文件贯穿全流程**：`load/capture/analyze/verify` 的结果 JSON 内含 `channels` 数组，直接作为下一步 `verify/m3u/proxy` 的 `--channels` 输入；也接受 `.m3u` 文件。

完整子命令与参数：[CLI使用说明.md](docs/CLI使用说明.md)；Linux/macOS 差异：[跨平台说明.md](docs/跨平台说明.md)。

## 方式二：从源码运行（Python 3.10+，核心零第三方依赖，全平台）

```bash
python src/main.py cli info          # Linux/macOS 用 python3
python src/main.py cli verify --province zhejiang --carrier telecom --out verified.json
python src/main.py cli m3u --channels verified.json --outdir ./out
python src/main.py --selftest        # 自测（合成数据，无需网络/管理员，48 项）
python src/e2e_posix.py              # Linux/macOS 回环端到端冒烟（无需 IPTV 网络/root）
```

## 子命令速查

| 命令 | 作用 | 需要管理员 |
|---|---|---|
| `info` / `ifaces` | 环境/网卡总览，含建议的组播网卡 | 否 |
| `refdb info\|carriers\|update\|import` | 全国参考库（31省×4运营商） | 否 |
| `load --province P --carrier C` | 载入候选频道（未实测） | 否 |
| `verify` | 真实加组收流验证，自动命名/编码/分辨率 | 否 |
| `sweep --range 233.50.200.0/22` | 组播全段扫频，发现参考库外频道 | 否 |
| `capture --seconds 90` | pktmon/tcpdump 抓包并分析出频道候选 | **是**（Win 管理员 / Linux·macOS sudo） |
| `analyze --pcap FILE` | 分析已有抓包（pcap/pcapng/etl） | 否 |
| `m3u --channels F --outdir D` | 生成/合并 udp+http 播放列表 | 否 |
| `proxy --port 9999` | 组播→HTTP 转发服务（前台长驻） | 否 |
| `push --files ... --method smb\|webdav` | 推送播放列表到 NAS | 否 |

## 约束与注意（AI 必读）

- **平台**：Windows 10 1809+ / Windows 11（pktmon 内置，v2.2.0 正式版）、Linux / macOS（tcpdump，**v2.1 测试版，未做真机测试，仅供参考**）、鸿蒙PC 精简版（`harmony/` ArkTS 工程，测试版，无抓包）。详见 [跨平台说明.md](docs/跨平台说明.md) 与 [harmony/README.md](harmony/README.md)。
- **网络前提**：验证频道需要有线网卡接入 IPTV 专网（搭线/桥接/路由器 IPTV 口，见 docs/使用说明.md）；`info` 的 `suggested_multicast_iface` 是建议网卡，可用 `--iface` 覆盖。WSL2 默认 NAT 收不到物理局域网组播，需镜像网络模式或真机。
- **防火墙**：新 exe 首次运行可能弹 Windows 防火墙提示，需用户点「允许访问」，否则收不到组播流（表现为 verify 全部 `ok=false` 且 `bytes=0`）；macOS 应用防火墙同理点「允许」。
- **参考库只是候选**：各地运营商随时调整组播地址，一切以 `verify` 实测为准。
- **隐私**：软件不后台联网、不上传数据（仅 `refdb update` 主动联网）；`capture/analyze` 结果中的 `stb` 字段含机顶盒账号，**切勿外传或写入公开文件**。
- **安全**：转发服务仅限局域网，禁止映射公网。
- **长任务**：`capture` 默认 90 秒、`verify` 全量可能数分钟、`proxy` 前台长驻——请放后台任务并解析 stderr 进度。

## 修改源码的约定

- 核心模块：`capture.py`（抓包：Pktmon/Tcpdump 双引擎 + `get_engine` 平台工厂）/ `netutil.py`（平台层：管理员/网卡枚举/后端探测）/ `verify.py`（验证）/ `tsutil.py`（TS 解析）/ `m3u.py` / `channeldb.py`（参考库）/ `proxy.py`（转发）/ `naspush.py` / `cli.py`（命令行）/ `main.py`（GUI）。
- GUI 与 CLI 共用核心模块与命名规则（`channeldb.apply_verify_result`），改一处两边生效。
- 版本号在 `src/appinfo.py` 统一维护。
- 改动后必须跑 `python src/main.py --selftest`（48 项）；GUI 冒烟：`python src/main.py --smoke`；Linux/macOS 另跑 `python3 src/e2e_posix.py`。
- 构建：Windows `src/build.ps1`（GUI）/ `src/build_cli.ps1`（CLI）；Linux/macOS `src/build.sh` / `src/build_cli.sh`；CI `.github/workflows/build.yml`。产物在 `dist/`。
