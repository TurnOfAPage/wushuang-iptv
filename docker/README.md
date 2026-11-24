# NAS Docker 鉴权转发（iptv-wan）· 部署说明

> 纯 Python 标准库的组播→HTTP 转发，面向**个人远程观看**（placeshifting 自用）的加固实现。
> 与工具内置 `proxy`（仅限局域网、禁止公网映射）不同，本服务靠**强制鉴权**兜底后才可经路由器映射公网；
> 是否开放公网由部署者知情选择，请自行确认运营商套餐条款允许个人远程观看、勿二次分发。

## 0. 安全模型

| 措施 | 说明 |
|---|---|
| 强制 token | 所有请求（含播放列表）必须带 token；恒定时间比较；无/错 token → 403 |
| 路径式 token | `/t/<token>/playlist.m3u`、`/t/<token>/udp/<group>:<port>`；客户端重连丢 query 也不掉鉴权；`?token=` 查询式兼容 |
| 失败封禁 | 同 IP 连续 8 次鉴权失败 → 封 10 分钟 |
| 频道白名单 | 只转发播放列表里存在的组播地址，其余 404（不能当开放组播代理） |
| 并发上限 | 默认 8 路（`IPTV_MAX_TOTAL`），保护家庭上行；超出 503 |
| 无管理端点 | 不暴露 restart/诊断类接口；`/status` 也要 token |
| 只读挂载 | 频道目录与脚本均 ro 挂载 |
| IGMP 续期 | 每 60s 补发 IGMPv2 report（`IPTV_REFRESH_SECS`），防无查询器网络加组老化断流；raw socket 需 root（容器默认），不可用自动回退 re-add |
| 剥 RTP 头 | 兼容 RTP 封装与裸 UDP-TS 两种运营商流 |

**token 即密码**：播放列表 URL 内含 token，不要外传该 URL。建议配合 HTTPS（见第 5 节）。

## 1. 准备

1. NAS 共享目录（示例 `/volume1/iptv`）放：
   - `iptv.m3u`：**组播版**播放列表（`udp://@<group>:<port>`，可由本工具 `m3u` 子命令生成）；
   - `wan/iptv_wan_proxy.py`：本目录脚本。
2. `cp .env.example .env`，填随机 token 与 NAS 有线网口 IP。
3. **tv 开机任务（必须保留/新建）**：控制面板 → 任务计划 → 开机触发 → root：

   ```bash
   sysctl -w net.ipv4.conf.all.force_igmp_version=2
   sysctl -w net.ipv4.conf.default.force_igmp_version=2
   sysctl -w net.ipv4.conf.eth0.force_igmp_version=2   # 双网口再补 eth1
   ```

   强制 IGMPv2 是加组收流前提；**Docker host 网络共享宿主机内核参数，容器依赖该任务**。
   清理旧任务时勿删；缺失则新建并立即运行一次（sysctl 即时生效）。

## 2. 部署 A：Docker（Container Manager，推荐）

1. 把本目录（含 `.env`）上传到 NAS，如 `/volume1/iptv/wan/`。
2. Container Manager → 项目 → 新增 → 路径选该目录 → 创建并启动。
   - `network_mode: host` 必须（bridge 收不到 LAN 组播）。
   - 首次构建拉 `python:3.12-alpine`；拉不动用部署 B。
3. 日志出现 `iptv-wan-proxy on 0.0.0.0:19999 ... auth=on` 即成功；healthcheck 每 30s 自检。

## 3. 部署 B：免 Docker（root 计划任务）

任务计划 → 开机触发 → root → 运行命令（路径按实际修改）：

```bash
export IPTV_TOKEN='<你的随机token>'
export IPTV_IFACE='<NAS有线IP>'
export IPTV_PORT='19999'
export IPTV_M3U='/volume1/iptv/iptv.m3u'
export IPTV_MAX_TOTAL='8'
/var/packages/python314/target/bin/python3 /volume1/iptv/wan/iptv_wan_proxy.py
```

（Python 路径按 NAS 实际套件调整；任何 Python 3.8+ 均可，零第三方依赖。）

## 4. 路由器映射 + 播放地址

1. 路由器只映射 **TCP 19999 → NAS:19999** 一条；DDNS（如 ddns-go）维持域名解析。
2. 播放列表（外网内网通吃，流地址自动跟随请求 Host）：

   ```
   http://<DDNS域名或NAS_IP>:19999/t/<token>/playlist.m3u
   ```

3. 外网验证时手机关 WiFi 用蜂窝网络；局域网可继续用内置免鉴权 `proxy`（9999）互不影响。

## 5. 建议加 HTTPS

DSM 控制面板 → 登录门户 → 反向代理：`https://<域名>:19999` → `localhost:19999`；
证书用 Let's Encrypt。之后播放地址改 `https://` 前缀。不做 HTTPS 也能用，但 token 明文过公网有被嗅探的理论风险。

## 6. 验证清单

- [ ] `curl 'http://127.0.0.1:19999/t/<token>/playlist.m3u'` 出全部频道
- [ ] 无/错 token → 403；白名单外地址 → 404
- [ ] 局域网播放器打开列表能播；外网（蜂窝）能播
- [ ] 并发超上限 → 503；`/status?token=` 或路径式 `/t/<token>/status` 看活跃流

## 7. 维护

| 事项 | 操作 |
|---|---|
| 频道更新 | 覆盖 `iptv.m3u`（服务按 mtime 热重载，无需重启） |
| 脚本更新 | 覆盖 `wan/iptv_wan_proxy.py` → 重启容器/任务（脚本已挂载，无需重建镜像） |
| 换 token | 改 `.env`/任务环境变量 → 重启；播放 URL 同步换 |
| 停服务 | 停容器/停用任务；局域网内置 proxy 不受影响 |

## 8. 与 Tvheadend 的关系

看直播不需要 Tvheadend（多一层订阅/扫描反而引入并发与卡顿问题）；EPG/录像/海报墙需求再启用 Tvheadend，
并让其 IPTV 网络指向本服务或内置 proxy 的 HTTP 列表、限制最大输入流数避免扫描打满转发。
轻量「预约录像+局域网点播」需求可直接用独立产品**无双IPTV录像工具**（仓库 `recorder/`，
`WushuangIPTV-Recorder-CLI proxy --record-dir ...` 一个常驻服务搞定，零第三方依赖、不需管理员），
重度 DVR（海报墙/系列录制）仍推荐 Tvheadend。
