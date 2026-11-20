# 更新说明

## v2.2.1（2026-11-20 夜）

### 🐛 验证/扫频默认并发下调（防假失败）

- 实测发现：部分光猫对**burst 加组限速**——8 并发复测 313 台误报 121 台「无流」，2 并发复测同批 **121/121 全活**。
- `verify` / `sweep` 默认并发 4/8 → **2**；help 与文档注明「高并发易假失败，失败频道请低并发复核」。
- 频道精简流程建议：高并发快扫发现 → 低并发复核判死 → 同名去重留最优（分辨率/码率）→ 剔 4K/HEVC 与无台名流。

## v2.2.0（2026-11-20）

### 🆕 sweep 组播全段扫频

- 新增 `sweep` 子命令：CIDR / 起止 / 单地址范围（逗号多段）逐个**真实加组收流**，发现参考库未收录的频道（试看/轮播/地方台/运营商改址后普查）；SDT 台名自动命名；单段上限 65536、自动排除 224.0.0.x 协议噪声。
- 结果 JSON 与 verify 同构，贯穿 `m3u` / `proxy` 全链路；不需管理员。
- 实测：某省电信 `233.50.200.0/22` + `231.10.23.0/24` 共 1280 地址 → **313 个有流频道，其中 132 个参考库未收录**。

### 🐛 转发服务两项实测修复

- **剥 RTP 头**：部分运营商 IPTV 组播为 RTP 封装（12B 头 + 1316B TS），原 proxy 直转脏流致播放器马赛克/疯狂缓冲；现 `strip_rtp` 剥头并兼容裸 UDP-TS。
- **IGMP 周期续期**：光猫/交换机不发 IGMP 查询的网络里，内核加组约 4 分钟在设备侧老化断流；proxy 每 60s 补发 IGMPv2 membership report（raw socket，需管理员/root；不可用时自动回退流 socket drop/re-add）。

### 🧭 抓包空结果诊断提示

- `capture` 0 候选时结果附 `hint`：IGMP snooping 定向转发场景（机顶盒能正常看但被动抓包不可见，新光猫常见）指引改走 `verify` / `sweep` 主动加组路线；使用说明同步补充该场景与「无查询器老化」「RTP 封装」原理条目。

### 📱 无双电视 APK v1.1（apk/ 目录同步更新）

- 直播缓冲抗抖动调优：`min-frames` 2→75、`max-buffer-size` 4MB→8MB —— WiFi 瞬时抖动时「正在连接」遮罩不再反复弹跳；代价起播多 1~2 秒换稳定。
- 电视端（Android 4.3 / API 18 真机）安装与播放验证通过；同签名覆盖安装不丢设置；TV/Phone 双包 versionName 1.1 / versionCode 2。

### 🐳 NAS Docker 鉴权转发（新增 docker/ 目录）

- 面向「个人远程观看」的加固版组播→HTTP 转发（纯标准库）：强制 token（路径式 `/t/<token>/...` 与 query 双兼容，客户端重连丢 query 不掉鉴权）、频道白名单、并发上限、鉴权失败封禁、IGMP 续期、容器 healthcheck。
- host 网络（组播加组必需）+ 频道目录只读挂载 + **脚本挂载**（更新 = 上传文件 + 重启容器，无需重建镜像）。
- 群晖部署说明含 **tv 开机任务依赖**：`sysctl force_igmp_version=2` 为加组收流前提，Docker host 网络共享宿主机内核参数，**该任务必须保留**；另附免 Docker 的 root 计划任务兜底与路由器单端口映射指引。
- 安全口径不变：内置 `proxy` 仍仅限局域网、禁止公网映射；`docker/` 为知情选择下的鉴权例外，token 即密码、播放列表 URL 勿外传。

### ✅ 验证

- selftest **48/48**、GUI smoke 通过；`sweep` 真网小范围 3/3 命中并自动命名；电视真机 v1.1 起播/长播截屏验证干净无遮罩。

## v2.1.0-beta · Linux/macOS 移植测试版（2026-11-17）

> **版本口径**：Windows 版保持 **v2.1.0** 不变（本次无 Windows 功能改动）；
> Linux/macOS 为 **v2.1 测试版**，**未做真机测试，仅供参考**（Linux 已在 WSL Ubuntu 22.04 完成功能验证，macOS 仅代码路径与 CI 覆盖）。

### 🆕 跨平台：Linux / macOS 原生支持（CLI + GUI，测试版）

- **同一套核心代码跑三个平台**：组播验证 / TS 解析 / M3U / HTTP 转发 / 参考库 / NAS 推送全平台共用；Windows 版行为完全不变。
- 新增平台适配层 `netutil.py`：管理员/root 检测、网卡枚举（Windows ipconfig / Linux ip·ifconfig / macOS ifconfig·networksetup）、抓包后端探测。
- 抓包双引擎：Windows 保持内置 **pktmon**；Linux/macOS 新增 **tcpdump** 引擎（`capture.get_engine` 平台工厂），支持 `-i any` 的 LINUX_SLL/SLL2 链路类型解析；`capture` 新增 `--iface` 参数。
- GUI 跨平台：字体按系统自动选择与回退（雅黑/苹方/Noto Sans CJK）、Windows DPI 逻辑仅 Win 生效、POSIX 窗口图标、无头 Linux 上 CLI/selftest 不依赖 tkinter。
- NAS 推送：Linux/macOS 支持已挂载目录与 `smb://` URL（系统 smbclient）；WebDAV 不变。
- CLI 协议向后兼容：`info` 新增 `platform` / `capture_backend` / `capture_backend_path` 字段，原字段保留；退出码语义不变（3=需管理员/root）；POSIX 上 `version` 显示 `2.1.0-beta` 并附 `beta_note` 测试版声明。
- 构建：新增 `src/build_cli.sh` / `src/build.sh`（PyInstaller 单文件）与 GitHub Actions 四平台矩阵（linux-x64 / macos-x64 / macos-arm64 / windows-x64）。
- 文档：新增 [跨平台说明.md](跨平台说明.md)；AGENTS.md / CLI使用说明.md 同步更新。

### ✅ 验证

- 自测扩充到 **48/48**（新增平台层 7 项 + SLL/SLL2 解析 4 项），Windows 与 WSL Ubuntu 22.04 双平台全绿。
- Linux 回环端到端（`src/e2e_posix.py`）：真实加组收流 → h264/mp2/SDT 命名/1080p → HTTP 转发 200KB → M3U，全部通过。
- Linux root 下 tcpdump 真实抓包（SLL2）发现组播流；CLI 全链路（非 root 拦截退出码 3 → capture → verify → m3u）通过。
- WSL 内 PyInstaller 打包 CLI/GUI 二进制并运行通过；GUI 冒烟（WSLg）通过。
- macOS 与 Linux 共用 POSIX 分支，CI 构建 + selftest 覆盖；真实 IPTV 收流待 Mac 实测。

### 🆕 鸿蒙PC 精简版（HarmonyOS NEXT，测试版）

- 新增 `harmony/` ArkTS 工程（DevEco Studio 6 / API 22，设备类型 2in1/phone/tablet）：
  全国参考库载入、`MulticastSocket` 组播加组验证（TS 解析/自动命名与 Python 版同一套逻辑）、
  M3U 生成导出、`TCPSocketServer` HTTP 转发（udpxy 等价）。
- hvigor 命令行构建通过，产物 `entry-default-unsigned.hap`；**未签名、未真机测试，仅供参考**。
- 系统限制：鸿蒙第三方应用无原始抓包权限，精简版不含抓包发现频道。
- 运行：DevEco Studio 打开工程 → 登录华为账号自动签名 → 模拟器/真机；详见 [harmony/README.md](harmony/README.md)。

### ⚠️ 注意

- **Linux/macOS 为测试版：未做真机测试，仅供参考**。真实 IPTV 环境验证前请勿用于生产。
- Linux/macOS 抓包需 **sudo**（verify/m3u/proxy 等不需要）；Linux 抓包需安装 tcpdump，GUI 需 python3-tk。
- macOS 未签名产物首次打开需右键→打开；正式分发建议签名+公证。
- 鸿蒙PC（HarmonyOS NEXT）不运行 Python/ELF，且第三方应用无抓包权限——精简版（验证+M3U+转发）待真机技术验证后另行立项。

## v2.1.0（2026-11-15）

### 🆕 CLI 命令行模式 —— 可被 AI 工具直接调用

- 新增 **`WushuangIPTV-CLI.exe`**（控制台版，**不强制管理员**）与 `src/cli.py`、`src/cli_entry.py`。
- 10 个子命令覆盖全流程：`info / ifaces / refdb / load / verify / capture / analyze / m3u / proxy / push`。
- **AI 友好输出协议**：stdout 只输出一个 JSON 结果文档；stderr 输出 JSON Lines 进度；退出码 `0`成功 / `1`失败 / `2`参数错误 / `3`需管理员；`--out` 原子写入结果文件。
- 频道 JSON 贯穿 `load → verify → m3u → proxy/push` 全链路（也兼容 `.m3u` 输入）；省份/运营商支持中文或拼音。
- **仅 `capture`（pktmon 抓包）需要管理员**，验证/生成 M3U/参考库等操作全部免管理员。
- GUI 版 exe 兼容入口：`无双IPTV抓源工具.exe cli <子命令>`（无控制台，须用 `--out` 取结果）。
- 新增构建脚本 `src/build_cli.ps1`；完整调用文档见 [docs/CLI使用说明.md](docs/CLI使用说明.md)，AI 工具入口见 [AGENTS.md](AGENTS.md)。

### 🐛 修复：4K 高分屏字体过小

- 根因：`tk scaling` 硬编码 1.25，叠加系统 DPI 感知后，4K + 200% 缩放下字体物理尺寸只有预期的一半。
- 现按系统真实 DPI（`GetDpiForSystem`）自适应：字体（磅值）随 `tk scaling` 放大，窗口/行高/列宽/内边距/拓扑图等像素尺寸同比缩放。
- **96 DPI（1080p 100%）下界面与 v2.0 完全一致**，无观感变化。

### 🔧 其他改进

- 版本号集中到 `src/appinfo.py` 统一维护（GUI/CLI 共用）。
- GUI 与 CLI 共用频道验证命名规则（`channeldb.apply_verify_result`），行为一致。
- CLI 单频道验证自动预填参考库名称；验证结果附 `error` / `bytes` 诊断字段。
- 构建脚本加 UTF-8 BOM，修复 Windows PowerShell 5.1 下中文脚本解析乱码。
- 文档修正：源码获取方式指向本仓库（发布包不含 `src`）。

### ✅ 验证

- 自测 37/37 通过；GUI 冒烟测试通过；2x DPI 模拟测试通过。
- 真实环境实测：组播频道验证（CCTV1，h264/1080p/SDT 自动命名）、360MB 抓包分析、组播→HTTP 转发（3 秒 3.39MB）均通过。
- 两个 exe 全链路实测通过；错误路径（非管理员抓包→退出码 3、非法省份→1、参数错误→2）正确。

### ⚠️ 升级注意

- 新 exe 首次运行若弹出 **Windows 防火墙提示，请点「允许访问」**（接收组播流需要；点「取消」会生成阻止规则，需在防火墙设置中改为允许）。
- 配置 `WushuangIPTV.json` 与频道列表自动保留，直接替换 exe 即可。

## v2.0.0

- 首个公开版本：接线向导 / pktmon 抓包分析 / 原生组播验证（不依赖 ffmpeg）/ 全国 31 省参考库 / M3U 生成与合并 / 一键推送 NAS / 内置 HTTP 转发服务。
- 配套无双电视 APK（电视版 + 手机版）。
