# 无双IPTV录像工具 · NAS Docker 部署

> ⚠ **本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。传播录制文件会导致版权风险，该风险与本软件无关。**
> 已在 Synology DS918+（DSM 7 / Docker 24 / Compose v2.20）真机部署实测通过（2026-11-24）：
> 真流录制、局域网点播、预约/跨进程取消/重启恢复、EPG 与按节目名预约全链路验证。
> 纯 Python 标准库的「直播转发 + 预约录像 + 录像点播」常驻服务，面向 NAS 7×24。
> 与 `iptv-wan`（19999，公网鉴权转发）**互不影响、可共存**；本服务**仅限局域网，禁止映射公网**。
> 零第三方依赖；容器内不需要管理员（host 网络下 root 仅用于 IGMP raw socket 续期，不可用自动回退）。

## 0. 前提（与 wan 相同，已部署过 wan 的机器一般都满足）

1. NAS 有线口接入 IPTV 专网/桥接网络（本机 `IPTV_IFACE`，示例 192.168.1.100）。
2. **开机任务必须保留**：控制面板 → 任务计划 → 开机触发 → root：
   `sysctl -w net.ipv4.conf.all.force_igmp_version=2`（及 default/eth0）。
   强制 IGMPv2 是加组收流前提；Docker host 网络共享宿主机内核参数，**容器依赖该任务**。
3. 频道文件：主工具 `verify` 产物（如 `zj-telecom-verified.m3u`）放在 `/volume1/iptv/`。
4. 录像目录：`/volume1/iptv/rec/`（自动创建；建议独立子目录）。
5. **时区一致**：compose/Dockerfile 默认 `TZ=Asia/Shanghai`（alpine 默认 UTC，会与本地预约时间差 8 小时）。
   NAS/宿主机若是其他时区，改 `.env` 的 `TZ` 保持一致；`docker exec` 的管理命令自动读容器内 `IPTV_*` 环境变量。

## 1. 部署 A：Container Manager 项目（推荐，与 wan 同流程）

1. 把本目录（含 `src/`、`recorder/` 代码子目录，由 `build_docker.ps1|.sh` 打包生成
   `dist/docker-recorder/`）上传到 NAS，如 `/volume1/iptv/docker-recorder/`。
2. `cp .env.example .env`，按实际改 `IPTV_IFACE`/目录/配额。
3. Container Manager → 项目 → 新增 → 路径选该目录 → 创建并启动。
   - `network_mode: host` 必须（bridge 收不到 LAN 组播）。
   - 首次构建拉 `python:3.12-alpine`；拉不动用部署 B（离线镜像）。
   - **docker.io 镜像源失效兜底**（实测有效）：`docker pull public.ecr.aws/docker/library/python:3.12-alpine`
     然后 `docker tag public.ecr.aws/docker/library/python:3.12-alpine python:3.12-alpine` 再构建；
     或 `docker build --build-arg BASE=python:3.12-slim .`（Dockerfile 支持 BASE 参数，slim 同样零依赖可跑）。
4. 日志出现 `proxy_running` 即成功；healthcheck 每 30s 自检 `/status`。

## 2. 部署 B：离线镜像导入（NAS 拉不动 Docker Hub 时）

开发机已构建并导出镜像：`dist/iptv-recorder-1.0.0.tar`（`docker save` 产物）。

```bash
# SSH 到 NAS（管理员）
sudo docker load -i /volume1/iptv/iptv-recorder-1.0.0.tar
cd /volume1/iptv/docker-recorder
sudo docker compose up -d        # compose 里 image: iptv-recorder:1.0.0 已存在则不再构建
```

（Container Manager 界面也可：映像 → 新增 → 从文件导入 tar，再用本项目 compose 启动。）

## 3. 部署 C：免 Docker（root 计划任务，与 wan 部署 B 同理）

任务计划 → 开机触发 → root：

```bash
/var/packages/python314/target/bin/python3 \
  /volume1/iptv/docker-recorder/recorder/rec_cli.py proxy \
  --channels /volume1/iptv/zj-telecom-verified.m3u \
  --record-dir /volume1/iptv/rec --iface 192.168.1.100 --port 9999
```

（Python 路径按实际套件调整；任何 Python 3.10+ 均可。代码热更新：覆盖文件+重跑任务。）

## 4. 播放地址（局域网）

```
Web 管理页: http://192.168.1.100:9999/          ← 浏览器开始/停止录制、预约、删除、更新节目单
             顶部「状态与设置」：容量上限(默认100G)/GB小时备注/保存文件夹(须挂载卷内)
直播列表: http://192.168.1.100:9999/playlist.m3u
录像列表: http://192.168.1.100:9999/recordings.m3u   ← VLC/Kodi/TiviMate 点播拖动
状态页:   http://192.168.1.100:9999/status
```

## 5. 录像管理（SSH 或 Container Manager 终端）

```bash
# 即时录 90 分钟
sudo docker exec iptv-recorder python rec_cli.py record start \
    --channels /data/zj-telecom-verified.m3u --name CCTV5 --minutes 90 --record-dir /rec
# 节目单更新（主动联网）+ 预约
sudo docker exec iptv-recorder python rec_cli.py epg update \
    --channels /data/zj-telecom-verified.m3u --record-dir /rec
sudo docker exec iptv-recorder python rec_cli.py record add \
    --name CCTV5 --start 2026-11-24T19:30 --end 2026-11-24T21:30 --record-dir /rec
sudo docker exec iptv-recorder python rec_cli.py record list --record-dir /rec
```

注意：`docker exec` 的即时录与容器主进程是**两个进程**，并发上限通过 /rec 索引文件跨进程协调（默认 2 路）。
预约计划写入 /rec/records.json 后由主进程到点执行，无需 exec 常驻。

## 6. 验证清单

- [ ] `curl http://127.0.0.1:9999/status` 出 iface/port/recordings 字段
- [ ] 浏览器开 `http://127.0.0.1:9999/` 出管理页；点「录制」→「正在录制」出现进度 →「停止」→ 录像表出条目
- [ ] `curl http://127.0.0.1:9999/recordings.m3u` 出 `#EXTM3U`
- [ ] 即时录 1 分钟：`record start --seconds 60` → bytes>0、gaps=0 → /rec/ts/ 出文件
- [ ] 播放器打开录像列表能播、能拖；`/vod/<id>` Range 请求返回 206
- [ ] 重启容器：未完成计划恢复（续录或标 missed）
- [ ] 与 iptv-wan 共存：19999 公网鉴权转发不受影响

## 7. 维护

| 事项 | 操作 |
|---|---|
| 代码更新 | 覆盖上传 `src/`、`recorder/` → 重启容器（代码已挂载，无需重建镜像） |
| 频道更新 | 覆盖 `/volume1/iptv/` 下 m3u/json（proxy 每次请求实时读取） |
| 改配置 | 改 `.env` → `docker compose up -d` 重建容器 |
| 清录像 | 配额自动 LRU；或 `record delete --id <rid>` |
| 停服务 | 停容器/停用任务；`docker stop` 发 SIGTERM → 优雅收尾（在录录像标 partial 落盘），wan 转发不受影响 |

## 8. 安全

- 本服务**无鉴权，仅限局域网**；禁止把 9999 映射到公网（远程观看需求走 iptv-wan 的 token 模型）。
- 录像目录可能含个人观看内容，注意 NAS 共享权限。
- 不接触机顶盒账号；EPG 更新仅命令显式触发。
