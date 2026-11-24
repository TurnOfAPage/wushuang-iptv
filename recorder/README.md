# 无双IPTV录像工具（独立产品）

> **把 IPTV 直播录下来，事后随时看。** 独立于主工具「无双IPTV抓源工具」发行——
> 不需要录像的用户无需安装本工具；主工具功能与体积不受任何影响。
> **版权与免责声明**：本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。
> 传播录制文件会导致版权风险，该风险与本软件无关。
> 版本：v1.0.0（Windows 正式版；Linux/macOS 测试版，未做真机测试）
> 作者：B站-锤无双 · QQ群 170621740 · [开源仓库](https://github.com/chuiziyao/wushuang-iptv)

## 这是什么 / 不是什么

- ✅ **本地录像（DVR）**：把已经免鉴权收到的组播直播流存成 TS 文件，局域网内点播拖动。
  即时录、按节目单（EPG）预约录、重启自动恢复、磁盘配额自动清理。
- ✅ **一个常驻服务全搞定**：直播转发（udpxy 等价）+ 预约调度 + 录像点播，NAS 上一条命令。
- ✅ **内置 Web 管理页**：浏览器开 `http://<服务IP>:9999/` 即可开始/停止录制、添加/取消预约、
  删除/播放录像、更新节目单（纯标准库内嵌单页，零外部资源；NAS Docker 场景的主界面）。
  顶部「状态与设置」：容量上限（默认 **100G**，超限自动清最旧）、GB/小时备注、保存文件夹选择；
  区块顺序：状态设置 → 预约 → 录像 → 频道。Windows GUI ②页有同款设置区。
- ❌ **不是运营商回看**：不能回溯「开始录制之前」的过去内容（真回看需要机顶盒鉴权克隆，
  逐省适配且涉隐私/合规风险，经评估不做）。常开设备 + 预约录像覆盖「错过直播补看」的核心诉求。
- ❌ 不做 MP4 转码（零第三方依赖，TS 全平台可播；VLC/Kodi/PotPlayer/TiviMate 拖动良好）。

## 与主工具的关系

```
无双IPTV抓源工具（主工具）          无双IPTV录像工具（本产品）
  抓包/验证/生成 verified.json  ──→  导入频道文件 → 录制/预约/点播
  共享核心：src/record.py · epg.py · proxy.py · verify.py · tsutil.py · channeldb.py
```

- 录像文件默认存 **系统「下载」文件夹/无双IPTV录像**（Web 设置区/GUI 设置区/CLI `--record-dir` 可自定义）。
  Windows 发行包经签名 python 子进程写盘，火绒/控制文件夹访问下默认下载目录仍可写；
  若个别环境仍拒绝写入：GUI 启动自动回退可写目录并提示，手动录制拒绝写入会**显式弹窗**（不再静默失败）。
- 频道来源：主工具 `verify` 结果 JSON / 任意 M3U / 内置全国参考库（本产品也可自行验证）。
- 录像/预约/转发**全部不需要管理员/root**（IGMP 续期自动回退 drop/re-add）。
- 网络前提与主工具相同：有线网卡接入 IPTV 专网（搭线/桥接/路由器 IPTV 口）。

## 快速开始

### Windows 桌面（GUI）

双击 `无双IPTV录像工具\无双IPTV录像工具.bat`（或已装 Python 时双击 `无双IPTV录像工具.pyw`，无黑窗）；
CLI 用同目录 `recorder_cli.bat`。发行包 `无双IPTV录像工具-win.zip`（**下载后先右键 zip→属性→解除锁定再解压**，消除安全警告）。
包内 = 官方签名 Python 运行时（python\，无安装 Python 时的回退）+ 应用脚本（app\）+ **纯 ASCII 入口脚本**：
进程链 wscript/cmd → py 启动器/已安装 Python **全程受杀软信任** → **开着火绒也能录、默认下载文件夹可写**（本机实测）。
（未签名 exe 无论单文件/文件夹都会被火绒按「进程链+安装路径」拦截解包与保护目录写入，故 Windows 不再发行 exe 入口；
入口脚本必须保持纯 ASCII——WSH/cmd 按 ANSI 解析，UTF-8 中文注释会吞行导致脚本报错。）
1. **① 频道与录制**：导入主工具 verified.json（或「载入参考库」→「验证全部」）→
   选组播网卡 → 选中频道 → **⏺ 录制选中** → 设定时长。
2. **② 录像管理**：「🔄 更新节目单」→「＋ 新增预约」按节目点选（或手动时间段）。
3. **③ 常驻服务**：启动后得到直播列表 + 录像列表地址，复制到 VLC/Kodi/TiviMate。
   预约录像需本服务保持运行。

### NAS / 软路由 7×24（CLI，推荐）

```bash
# 常驻服务：直播转发 + 预约调度 + 录像点播（放后台/计划任务/Docker host 网络）
WushuangIPTV-Recorder-CLI proxy --channels verified.json --record-dir /volume1/iptv/rec

# 即时录 90 分钟
WushuangIPTV-Recorder-CLI record start --channels verified.json --name CCTV5 --minutes 90 \
    --record-dir /volume1/iptv/rec

# 节目单 + 预约（明晚 19:30~21:30 的 CCTV5）
WushuangIPTV-Recorder-CLI epg update --channels verified.json --record-dir /volume1/iptv/rec
WushuangIPTV-Recorder-CLI record add --name CCTV5 --start 2026-11-24T19:30 --end 2026-11-24T21:30 \
    --record-dir /volume1/iptv/rec
WushuangIPTV-Recorder-CLI record add --name CCTV5 --title "英超" --record-dir /volume1/iptv/rec

# 播放（局域网）
#   直播: http://<NAS_IP>:9999/playlist.m3u
#   录像: http://<NAS_IP>:9999/recordings.m3u   （VLC/Kodi/TiviMate 点播拖动）
```

群晖注意：需保留开机任务 `sysctl -w net.ipv4.conf.all.force_igmp_version=2`（见主仓库
[docker/README.md](../build/gh-push/docker/README.md)）；Docker 部署必须 host 网络。
**Docker 部署包**：`recorder/docker/`（Dockerfile/compose/.env.example/README），
`recorder/build_docker.ps1|.sh` 一键打包 `dist/docker-recorder/` 上传目录，本机 Docker 可用时
另构建并导出离线镜像 `dist/iptv-recorder-1.0.0.tar`（NAS 拉不动 Docker Hub 时 `docker load` 导入）。
详见 [docker/README.md](docker/README.md)。
完整命令参考：[CLI使用说明.md](CLI使用说明.md)；GUI 图文说明：[使用说明.md](使用说明.md)。

## 可靠性设计

| 场景 | 行为 |
|---|---|
| 光猫无 IGMP 查询器（加组老化断流） | 60s 周期续期（复用主工具实测方案），非管理员自动回退 |
| 录制中流中断 | 6s 超时自动重加组续录同一文件，断流计数可查 |
| 进程/设备重启 | 计划落盘恢复：在录续录剩余时段；过期计划标 missed 或续录（`--missed remainder`） |
| 磁盘将满 | 启动预检 + 录制中周期检查，优雅停止不写坏文件 |
| 配额超限 | 按结束时间 LRU 清理已完成录像（**绝不删进行中/待录**） |
| 单文件过大 | 超 4GiB/2h 自动分段，点播端虚拟拼接，播放器无感 |
| 索引损坏 | 从 ts/ 文件名重建基础索引 |

## 目录结构（record_dir，NAS 只需挂载这一个目录）

```
rec/
  records.json      预约计划        recordings.json  录像索引
  epg.xml.gz/.json  节目单缓存      ts/<rid>.ts      录像文件（_p2.ts 分段）
```

## 隐私与安全

- 不接触任何机顶盒账号/鉴权信息；不上传任何数据。
- EPG 更新是唯一联网点，**仅用户主动触发**（GUI「启动时自动更新」为显式勾选，默认关）。
- 所有服务仅限局域网，**禁止映射公网**；录像仅供个人观看。

## 开发 / 构建 / 测试

```bash
python recorder/rec_main.py cli info        # 源码运行 CLI（全平台）
python recorder/rec_main.py                 # 源码运行 GUI
python recorder/selftest_rec.py             # 独立自测 42 项（合成数据，无网络/无管理员）
python recorder/rec_main.py --smoke         # GUI 冒烟
python recorder/e2e_rec.py --iface <IP> --group 233.50.201.118 --port 5140
                                            # 真实网络端到端（需能收到组播，可选）
# 构建（产物在 dist/）
recorder/build_cli.ps1 / build.ps1          # Windows
recorder/build_cli.sh  / build.sh           # Linux/macOS
recorder/build_docker.ps1 / build_docker.sh # NAS Docker 部署包 + 离线镜像 tar
```

设计文档：[docs/录像功能设计.md](../docs/录像功能设计.md)。
主工具回归不受影响：`python src/main.py --selftest` 与 `--smoke` 照常。
