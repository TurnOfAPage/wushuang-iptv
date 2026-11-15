# 更新说明

## v2.1.0（2026-11-15）

### 🆕 CLI 命令行模式 —— 可被 AI 工具直接调用

- 新增 **`无双IPTV-CLI.exe`**（控制台版，**不强制管理员**）与 `src/cli.py`、`src/cli_entry.py`。
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
