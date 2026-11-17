# 无双IPTV抓源工具 · 鸿蒙精简版（HarmonyOS NEXT）

> ## ⚠️ 测试版声明
> **v2.1.0 测试版：未做真机测试，仅供参考。**
> 已完成：ArkTS 全部核心代码 + hvigor 构建通过（API 22 SDK，产物 `entry-default-unsigned.hap`）。
> 未完成：签名、模拟器/真机安装运行、真实 IPTV 网络实测。

## 一、功能范围（与 Windows/Linux 版对齐的精简版）

| 功能 | 状态 | 说明 |
|---|---|---|
| 全国参考库载入 | ✅ | 31省×运营商；**在线更新**（与 Windows 版同一镜像策略）；也可构建期注入 |
| 组播加组实测验证 | ✅ | `MulticastSocket`（API 11+，仅 INTERNET 普通权限）；TS 解析/自动命名/编码/分辨率与 Python 版同一套逻辑 |
| M3U 生成导出 | ✅ | udp/rtp/udpxy 三格式，系统保存对话框导出 |
| 组播→HTTP 转发 | ✅ | `TCPSocketServer` 实现的 udpxy 等价服务（/status /playlist.m3u /raw.m3u /udp/组:端口） |
| 抓包发现频道 | ❌ | **鸿蒙第三方应用无原始抓包权限（系统限制，无法实现）** |
| 接线向导 | ❌ | 精简版不含，接线方法见主仓库《使用说明.md》 |

设备类型：`2in1`（鸿蒙PC，主目标）/ `phone` / `tablet`。最低 API 12，目标 API 22。

## 二、运行方法（DevEco Studio）

1. 用 **DevEco Studio** 打开本目录（`harmony/`）。
2. 首次打开会同步工程；如提示 SDK 版本，按本机 SDK 确认即可。
3. **签名**：登录华为账号 → `File > Project Structure > Signing Configs` → 勾选
   `Automatically generate signature`（调试证书自动生成）。
4. 运行：
   - **模拟器**：Device Manager 里已有的 Mate 80 等镜像可直接运行（功能验证用；
     模拟器 NAT 网络收不到物理局域网 IPTV 组播，真实收流需真机）。
   - **真机（鸿蒙PC/手机）**：开发者模式 + USB 调试，直接 Run。
5. 使用：① 频道验证页先点「**在线更新参考库**」（首次必需，仓库不捆绑社区数据）→
   选省份+运营商 → 载入参考库 → 选网卡 → 验证全部；
   ② M3U 页生成导出；③ 转发页启动 HTTP 转发（仅限局域网）。

**网络前提**（与 Windows 版相同）：设备有线口需接入 IPTV 专网（搭线/桥接/路由器 IPTV 口），
组播才能到达；验证不需要 root/管理员。

## 三、命令行构建（不签名）

```bat
python prepare_refdb.py   :: 可选：抓取社区数据注入 rawfile（不注入也能用，应用内在线更新）
build_hap.bat
```

需要本机装有 DevEco Studio（脚本自动使用其 node/jbr/hvigor/SDK）。
产物：`entry\build\default\outputs\default\entry-default-unsigned.hap`。
未签名 HAP 不能安装，仅用于 CI/存档；安装请走 DevEco 自动签名。

**数据政策**：与主仓库一致，出于许可证考虑**不捆绑**社区参考数据
（`rawfile/refdb.json` 已 gitignore）；应用运行时按需下载（仅用户点更新时联网）。

## 四、工程结构

```
harmony/
├── build-profile.json5          # 产品/SDK 配置（target 6.0.2(22)，compatible 5.0.0(12)）
├── build_hap.bat                # 命令行构建脚本
├── AppScope/                    # 应用级配置与图标
└── entry/src/main/
    ├── module.json5             # 权限：INTERNET + GET_NETWORK_INFO（均普通权限）
    ├── ets/
    │   ├── entryability/EntryAbility.ets
    │   ├── pages/Index.ets      # 四 Tab 主界面
    │   ├── model/Channel.ets    # 频道/验证结果/网卡数据模型
    │   └── core/
    │       ├── TS.ets           # tsutil.py 移植：PAT/PMT/SDT/SPS 解析
    │       ├── RefDb.ets        # channeldb.py+refupdate.py 移植：参考库+在线更新+命名规则
    │       ├── Net.ets          # netutil.py 移植：网卡枚举/选口策略
    │       ├── Verify.ets       # verify.py 移植：MulticastSocket 加组验证
    │       ├── M3U.ets          # m3u.py 移植：生成+导出
    │       └── Proxy.ets        # proxy.py 移植：TCPSocketServer HTTP 转发
    └── resources/rawfile/refdb.json   # 参考库（构建期注入，gitignore，不入库）
```

## 五、已知限制与待验证项

- **未真机测试**：`MulticastSocket` 加组收流、指定网卡（bind 到网卡 IP）、`TCPSocketServer`
  转发性能，均需在真实鸿蒙PC + IPTV 网络验证。API 签名已按本机 SDK（API 22）d.ts 逐一核对。
- 模拟器只能验证 UI/参考库/M3U 逻辑，收不到物理局域网组播。
- 参考库更新：应用内「在线更新参考库」（镜像策略与 Windows 版一致）；
  也可 `python prepare_refdb.py` 构建期注入最新数据。
- 转发服务仅限局域网，禁止映射公网；应用退到后台可能被系统挂起，7×24 转发请用 NAS/路由器方案。

## 六、隐私与安全

与主版本一致：不后台联网、不上传数据；参考库仅含公开组播地址与频道名；
不含机顶盒账号类信息（抓包功能本身不存在）。
