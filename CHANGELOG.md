# 更新说明

## 无双IPTV录像工具 v1.0.0（2026-11-23，独立新产品）

> **独立发行**：录像功能做成单独产品（`recorder/` 目录，独立版本号），与主工具共享 `src/` 核心模块；
> 主工具「无双IPTV抓源工具」v2.2.1 功能与行为**零改动**，不需要录像的用户无需安装本工具。
> 决策背景：用户呼声最高的「回看」经技术评估——运营商真回看需克隆机顶盒鉴权、逐省适配、隐私/合规风险大，**搁置**；
> 改做本地录像（DVR）：把免鉴权收到的组播直播流录下来事后点播，常开设备+预约覆盖「错过直播补看」核心诉求。
> **只能录开始之后的内容，不能回溯过去**（宣传口径务必注明）。

### 🆕 录像核心（src/record.py · epg.py，GUI/CLI 共用）

- **即时录**：`record start` 前台录制（时长精确，不吃预约余量），Ctrl+C 优雅收尾；剥 RTP、IGMP 60s 续期、断流 6s 自动重加组续录。
- **预约录像**：手动时间段 或 公共 XMLTV 节目单点选（epg.pw/51zmt/自定义 URL，**仅用户主动更新**）；提前 60s/延后 120s 余量防提前/拖堂；同频道重叠拒绝。
- **重启恢复**：计划/索引原子落盘；在录续录剩余时段（分段并入同一索引），过期计划标 missed 或 `--missed remainder` 续录。
- **磁盘治理**：启动预检+录制中周期检查（余量 < max(2GiB, 10分钟×码率) 优雅停止）；配额 LRU 自动清理（绝不删进行中/待录）；单文件超 4GiB/2h 自动分段。
- **索引自愈**：recordings.json 损坏时从 ts/ 文件名重建基础索引。
- 全程**不需要管理员/root**（IGMP raw socket 不可用自动回退 drop/re-add，与 proxy 一致）。

### 🆕 录像点播（proxy.py 向后兼容扩展 + m3u.py）

- `ProxyServer(record_mgr=...)` 可选参数：`/vod/<rid>`（Range 206/416/HEAD、多分段虚拟拼接、边录边看、rid 白名单防路径穿越）、`/recordings.m3u`（真实时长 VOD 列表）、`/recordings.json`、`/status` 扩展。
- **缺省不传 record_mgr 时行为与旧版完全一致**（主工具零影响，selftest 回归通过）。

### 🆕 独立 CLI + GUI（recorder/）

- CLI `WushuangIPTV-Recorder-CLI`：info / record start|list|add|cancel|delete / epg update|show|map / proxy（常驻=转发+调度+点播）；输出协议与主工具一致（stdout 单 JSON、stderr JSONL、退出码 0/1/2、--out）。
- GUI `无双IPTV录像工具.exe`：① 频道与录制（导入主工具 verified.json/M3U/参考库自验证、⏺录制选中）② 录像管理（EPG 更新、预约对话框手动/节目点选、配额条、删除/停止/复制点播地址）③ 常驻服务 ④ 帮助。
- NAS 7×24：`proxy --channels verified.json --record-dir /volume1/iptv/rec` 一条命令；群晖 force_igmp_version=2 开机任务依赖见 docker/README.md。
- 构建脚本 recorder/build*.ps1|.sh；产物 dist/ 下两个 exe（单文件、零第三方依赖、内嵌参考库）。

### 🐳 NAS Docker 部署包（2026-11-24 补充）

- `recorder/docker/`：Dockerfile（python:3.12-alpine，零第三方依赖）+ compose（**host 网络**、频道目录只读挂载、录像目录读写挂载、**代码热更新挂载**——与 iptv-wan 同模式，更新=上传文件+重启）+ `.env.example` + 部署 README（Container Manager 项目 / 离线镜像导入 / 免 Docker 计划任务三路线）。
- `recorder/build_docker.ps1|.sh`：打包自包含上传目录 `dist/docker-recorder/`；本机 Docker 可用时构建 `iptv-recorder:1.0.0` 并 `docker save` 导出 `dist/iptv-recorder-1.0.0.tar`（NAS 拉不动 Docker Hub 时离线导入）。
- 与 iptv-wan（19999 公网鉴权）共存互不影响；本服务 9999 **仅限局域网，禁止映射公网**；依赖既有 `force_igmp_version=2` 开机任务。
- 容器级实测修复三处：**TZ 默认 Asia/Shanghai**（alpine 默认 UTC 会使预约偏移 8 小时）、entrypoint.sh（无参=常驻 proxy / 有参透传 CLI，`docker run <镜像> info` 可用）、**SIGTERM 优雅收尾**（docker stop 时在录录像标 partial 落盘）；`docker exec` 管理命令自动读容器 `IPTV_*` 环境变量；docker.io 镜像源失效时 ECR 公共镜像兜底（实测有效）。
- 容器冒烟通过：/status、/recordings.m3u、跨进程预约拾取（exec add → 主进程到点启动）、docker stop 优雅收尾索引落盘。
- **NAS 真机部署实测通过**（Synology DS918+ / DSM 7 / Docker 24 + Compose v2.20）：上传部署包 + 离线镜像 load + compose 启动，与 iptv-wan 共存；真流实录 10s≈10MB 零断流；局域网 /recordings.m3u + /vod 206 点播可解码 h264「CCTV-1 HD」；预约拾取、跨进程取消、重启恢复、EPG 直更（70 频道映射）与按节目名预约全过。
- 真机过程修复：busybox ifconfig 解析（alpine 容器网卡枚举：`inet addr:`、UP 独立行、`Link encap` 头、docker 桥过滤、网关回退解析）；跨进程 recordings.json 热重载与 cancel 信号（tick 合并不再覆盖磁盘 canceled）；**EPG 内置源更新**（epg.pw 旧 `/api/epg.xml` 已 404 → 实测 `/xmltv/epg_CN.xml.gz` 可用，旧源保留兜底）。
- **内置 Web 管理页**（`src/webui.py`，2026-11-24）：浏览器 `http://<服务IP>:9999/` 开始/停止录制、手动/按节目预约、取消、删除/播放录像、更新节目单、实时进度与配额；纯标准库内嵌单页（零外部资源/零新增依赖），JSON API `/api/state|programs|record/start|record/stop|schedule/add|schedule/cancel|recording/delete|epg/update`；仅 `record_mgr` 启用时生效，主工具 `/` 仍返回 status JSON（零变化）；selftest 54/54；NAS 真机页面+API 真流录停实测通过。
- **Web 设置区与布局改版 + Windows GUI 同款设置**（2026-11-24 二轮）：页面区块顺序改为 **状态与设置 → 预约录像 → 录像 → 频道与录制**；顶部设置区含**容量上限（全链路默认 20→100G）**、**GB/小时备注**（实测均值+经验值：标清 1~2/高清 3~4/4K 15~22）、**保存文件夹选择**；设置持久化 `base_dir/settings.json`（`record.save_settings`，Docker 下锚定挂载根，重启自动读取），换文件夹即时重建管理器（在录时拒绝）；播放兼容备注加 **KmPlayer**；Windows GUI ②页顶部同款「状态与设置」区（配额/目录/浏览/应用/备注）；selftest **61/61**；NAS 真机顺序/设置 API/100G 持久化实测通过。
- **Windows 版改文件夹版（onedir）+ 默认录像目录=系统下载文件夹**（2026-11-24 三轮，用户报障）：单文件 exe 启动报「Could not create temporary directory!」根因＝**火绒等安全软件拦截未签名 exe 向系统临时目录解包**（实测作者旧单文件 exe 同报、改 TMP 到 D 盘即好；签名进程 python/cmd 不受影响）→ Windows 构建改 `--onedir`（无解包动作天然免疫），产物 `dist/无双IPTV录像工具/`、`dist/WushuangIPTV-Recorder-CLI/` + 同名 `-win.zip`；**默认录像目录改为系统「下载」文件夹/无双IPTV录像**（Windows 经 SHGetKnownFolderPath 取真实 Downloads 含 OneDrive 重定向；`record.default_record_dir`），Web/GUI/CLI `--record-dir` 均可自定义；selftest 62/62。
- **版权显著声明 + 保护目录拒绝写入修复 + 帮助页去按钮**（2026-11-24 四轮）：全界面显著声明「**本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。传播录制文件会导致版权风险，该风险与本软件无关**」（GUI 窗口底部常驻红字＋帮助页首节、Web 页头红色横幅、CLI 结果 copyright_note、各文档首行）；修复「点确定不录制」静默失败：根因＝火绒文档/勒索防护拒绝未信任 exe 写 Downloads（PermissionError WinError5 被 noconsole 吞掉）→ `record.dir_writable` 启动探测自动回退可写目录并提示、手动录制/改目录拒绝写入显式弹窗、RecordManager 建目录拒绝时带指引报错；帮助页移除「打开视频教程/开源仓库」按钮。
- **Windows 发行包改「信任进程链入口 + 签名 Python 运行时」**（2026-11-24 五轮，用户硬要求：杀软开着也要能录、默认必须下载文件夹）：实测火绒按**进程链+安装路径**信任（未签名 exe 的子进程即使签名也被拒；复制/嵌入式 python 离开安装路径也被拒）→ Windows 不再发行 exe 入口，改 **纯 ASCII 的 `无双IPTV录像工具.vbs` / `WushuangIPTV-Recorder-CLI.bat`**（wscript/cmd → py/已安装 Python 全信任链；无安装 Python 回退 bundled 官方签名运行时+tkinter overlay）；`recorder/build_win.ps1` 组装；**本机带火绒实测：默认下载目录真流录制 4s=4.35MB 零断流、GUI 冒烟通过**；入口脚本纯 ASCII（WSH/cmd 按 ANSI 解析，UTF-8 中文注释吞行曾致双击报错，已修）。
- 滚动时移/HLS 仍属 P3 另行设计；Docker 集成之「部署」部分至此落地。

### ✅ 验证

- 独立自测 **42/42**（合成 TS/假 socket/假时钟/XMLTV + HTTP Range 回环 + 主工具兼容对照）；GUI smoke 通过。
- **真实网络端到端通过**（浙江电信 CCTV1 233.50.201.118:5140）：实录 5s=4.9MB 零断流 → 常驻服务 → /recordings.m3u → /vod 206 Range → TS 解析 h264/mp2「CCTV-1 HD」；CLI exe 与 GUI exe 构建并验证（exe 首 run 需点防火墙「允许」，与主工具一致）。
- 主工具回归：selftest 47/48（唯一失败为**预先存在**的外部 refdb.json 数据问题「CCTV1 实测可用」，与本次改动无关）、GUI smoke 通过。
- 设计文档：docs/录像功能设计.md（P1+P2 已实现；P3 滚动时移/HLS/Docker 集成另行设计）。

## v2.2.1（2026-11-20 夜）

### 🐛 验证/扫频默认并发下调（防假失败）

- 实测发现：部分光猫对**burst 加组限速**——8 并发复测 313 台误报 121 台「无流」，2 并发复测同批 **121/121 全活**。
- `verify` / `sweep` 默认并发 4/8 → **2**；help 与文档注明「高并发易假失败，失败频道请低并发复核」。
- 频道精简流程建议：高并发快扫发现 → 低并发复核判死 → 同名去重留最优（分辨率/码率）→ 剔 4K/HEVC 与无台名流。

### 📱 无双电视 APK v1.2（apk/ 目录同步更新）

- 默认直播源策略调整：**发行版不再内置任何私人播放地址**（空默认，首次运行引导设置），避免私人 NAS 地址/token 随公开包分发；个人设备定制构建可固化自家 NAS 转发地址（含 token 的构建仅限本机推送安装，不入库）。
- 安卓投影仪经局域网推送口（POST /upload, field file1）安装验证通过；versionName 1.2 / versionCode 3。

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
