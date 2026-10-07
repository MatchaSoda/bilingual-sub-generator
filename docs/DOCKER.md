# Docker 一键部署

> 面向「拿到仓库、想在自己电脑上跑起来」的人。日常运维看 [`RUNBOOK.md`](./RUNBOOK.md)。

## 1. 三步跑起来

```bash
git clone <仓库地址> && cd bilingual-sub-generator
./docker-start.sh          # 第一次会构建镜像 + 进入设置向导
# 打开 http://localhost:8501
```

前提：装好 [Docker Desktop](https://docs.docker.com/get-docker/)（Windows / macOS）或 Docker Engine + compose 插件（Linux）。
Windows 在 **WSL 终端或 Git Bash** 里运行脚本。macOS 上要长期开着跑（当服务器用）推荐 [OrbStack](https://orbstack.dev)，
同一份 compose 直接能用，空闲内存会还给系统；装法和坑见 §4。

设置向导会依次带你完成这些事，每一步都当场联网验证：

| 步骤 | 你需要准备 | 向导会做什么 |
|---|---|---|
| 0 环境自检 | 无 | 检查 ffmpeg、CJK 字体、Chromium、yt-dlp、biliup 是否在镜像里 |
| 1 网络 | 知道代理软件的端口（或确认能直连） | 先试直连，通了默认直连；否则自动把 127.0.0.1 换成容器可达的地址，HTTP 和 SOCKS5 都试，用能通的 |
| 2 Gemini | 到 https://aistudio.google.com/apikey 申请 key | 逐个 key 真调一次接口，区分「key 错」和「地区不支持」 |
| 3 YouTube cookie | 无痕窗口登录 YouTube，用扩展导出 cookies.txt 放到 `userdata/` | 去 CRLF、查 LOGIN_INFO、用生产同款参数实测一个视频能否拿到 ≥720p |
| 4 自动搬运（可选） | B 站账号手机 App 扫码 | `biliup login`；问答式生成 `config.json`（频道、关键词、排除词、分区、扫描间隔）；问「新账号全新开始，还是带 history 继续」决定 `backfill.mode`（RUNBOOK §4） |
| 5 模型 | 无 | 预下载 Whisper 模型（约 1.6 GB），先走代理、不通换直连，中断可续传；启动脚本每次也会确认它在 |

跑完向导，`./docker-start.sh` 会启动 `web`（始终）和 `mover`（仅当开启了自动搬运）。

## 2. 目录与文件

```
userdata/            ← 你的全部数据，git 忽略，备份这个目录就够
  .env               Gemini key / 代理 / 开关       （模板 docker/env.example；Web 界面填的 key 也写在这）
  cookies.txt        YouTube cookie
  cookies.json       B 站登录信息                    （Web「自动搬运」页扫码登录写的也是它，旧的备份成 .bak-<时间>）
  config.json        搬运频道与规则                  （模板 automation/config.json.example；Web「自动搬运」页可改，上一版留在 config.json.bak-last）
  history.json       已处理视频 id
  state.json         起点水位（首次启动时间，backfill.mode=since_first_start 时才有）
  uploads.jsonl      投稿记录：BV 号、YouTube ID、成品文件名、来源（自动 / Web / 补投）
  jobs/              Web「生成并投稿」的任务和日志，只留最近 200 个
  runtime/           mover 的心跳、最近动态、日志副本、锁（运行期文件，删了也只是丢掉最近动态）
  data/              生成好的双语视频 + 封面
data/downloads/      下载与中间产物缓存（会很大，可定期清）
docker volume whisper-models   Whisper 模型缓存
```

容器内路径分别是 `/app/userdata`、`/app/data`、`/models`。代码通过两个环境变量找到用户数据：
`AUTOMATION_STATE_DIR=/app/userdata`（mover.py 的 config / history / cookies.json / 产出）和
`YT_COOKIES_FILE=/app/userdata/cookies.txt`（settings.py 与 mover.py 的 YouTube cookie）。
不设这两个变量时行为和裸机部署完全一样。

## 3. 常用命令

日常操作多数在 Web（http://localhost:8501）的「自动搬运」页完成：看状态和日志、改频道 / 规则 / 处理参数、暂停、立即扫描、
B 站扫码登录、「生成并投稿」单个链接。下表是命令行的部分。

| 想做什么 | 命令 |
|---|---|
| 启动 / 重启 | `./docker-start.sh` |
| 改配置（换 cookie、改代理、加频道） | `./docker-start.sh setup` |
| 不交互地体检当前配置 | `./docker-start.sh check` |
| 确保 Whisper 模型已下载（启动时自动做） | `./docker-start.sh model`，试其他模型：`./docker-start.sh model --model small` |
| 看日志 | `./docker-start.sh logs`，只看搬运：`./docker-start.sh logs mover` |
| 停止 | `./docker-start.sh stop` |
| yt-dlp 过期 / 更新代码 | `./docker-start.sh update` |
| 进容器排查 | `./docker-start.sh shell` |
| 迁移：导出 / 导入用户数据 | `./docker-start.sh export`、`./docker-start.sh import <包>`（§3.5，裸机用 `scripts/migrate.sh`） |
| 补投单个视频 | Web「制作任务」选「生成并投稿 B 站」；mover 没在跑时 `docker compose run --rm setup bash -c "cd automation && ../venv/bin/python3 backfill.py <url>"` |

手改了 `userdata/.env` 后重新执行 `./docker-start.sh`（它跑的是 `docker compose up -d`，配置变了会自动
重建容器）。**`docker compose restart` 不行**——env_file 只在容器创建时读，restart 不重建，容器里还是旧值（09-19 实测）。
Gemini key 也可以在 Web 界面「系统设置」里填，后端会写到 `userdata/.env` 并立即对新任务生效，不用重启。
手改 `userdata/config.json` 不用重启，下一轮扫描生效（同裸机）。Web 上改配置也一样；页面打开之后有人手改过文件，Web 保存会被拒绝
（不会把手改的内容覆盖掉），刷新后再改。

## 3.5 迁移到另一台机器（裸机 / Docker 互通）

`scripts/migrate.sh` 不依赖 Docker，四个方向都能用：裸机→裸机、裸机→Docker、Docker→裸机、Docker→Docker。
`./docker-start.sh export` / `import` 就是它加上 `--from docker` / `--to docker`。

```bash
# 旧机器（先停自动搬运，见下）
scripts/migrate.sh export                    # 生成 bilingual-sub-userdata-<日期>.tar.gz
# 新机器
git clone <仓库> && cd bilingual-sub-generator
scripts/migrate.sh import <那个 .tar.gz>     # 自动判断这台是裸机还是 Docker；判断不对就加 --to bare / --to docker
# Docker：./docker-start.sh   裸机：venv/bin/python3 scripts/setup_wizard.py --check
```

带走的就这 7 个文件，包里统一按 `userdata/` 的结构放（所以老版本 `docker-start.sh export` 打的包也能导）：

| 文件 | 裸机位置 | Docker 位置 |
|---|---|---|
| `.env`（key、代理） | 仓库根 | `userdata/` |
| `cookies.txt`（YouTube） | 仓库根 | `userdata/` |
| `cookies.json`（B 站登录）、`config.json`、`history.json`、`state.json`、`uploads.jsonl`（投稿记录） | `automation/` | `userdata/` |

不带：生成的视频（`automation/data`、`userdata/data`）、`data/downloads` 缓存、Whisper 模型（新机器重新下载）。

脚本会自动处理、或者会拦下来的情况：

- **代理主机名。** 导入到 Docker 时，代理变量里的 `127.0.0.1` 会换成 `host.docker.internal`；导入到裸机时反过来换。
  端口和协议保持旧机器的设置，新机器不一样的话，体检会报出来，再用向导第 1 步改。`NO_PROXY` 不会被改。
- **两边别同时投稿。** 导入到 Docker 时会把 `ENABLE_AUTOMATION` 置 0；裸机导入不会碰 systemd。
  旧机器还在跑时导出会给警告：之后处理的视频不在包里的 history，新机器会再投一遍。所以要先停旧机器
  （裸机 `sudo systemctl disable --now bili-mover`，Docker `./docker-start.sh stop`），再导出。
- **不覆盖已有数据。** 目标机器上已有 key / cookie / history 时，导入会拒绝；加 `--force` 才覆盖，原文件备份成 `.bak-<时间>`。
  同一台机器上裸机和 Docker 两份数据都有时，导出要用 `--from` 指明导哪份。
- **包里有登录凭据**（权限 600），传完删掉。

## 4. 已知限制与坑

- **代理软件必须允许局域网连接。** 容器通过 `host.docker.internal` 访问宿主机，Linux 上这是网桥地址，
  代理只监听 127.0.0.1 就连不上。Docker Desktop 大多能直接通，但打开「Allow LAN」最省事。
  （macOS Docker Desktop + Clash Verge 7897 实测：不开 Allow LAN 也能通。）
- **宿主机 DNS 被污染时，构建会在第一步就超时。** 症状是
  `failed to fetch anonymous token: Get "https://auth.docker.io/token?...": dial tcp 162.125.x.x:443: i/o timeout`
  ——`auth.docker.io` 被解析到了 Dropbox 的网段（宿主机 DNS 是 114.114.114.114 之类时常见）。
  处理：先手工 `docker pull` 两个基础镜像（`node:20-bookworm-slim`、`python:3.12-slim-bookworm`），
  多试几次总能拉下来，之后 build 就只用本地缓存。Dockerfile 已去掉 `# syntax=docker/dockerfile:1`
  指令，否则 BuildKit 每次 build 都要去远端解析这个 frontend 镜像，撞上同一个超时。
- **迁移时把 `history.json` 一起带过来，或者把 `config.json` 的 `backfill.mode` 设成 `since_first_start`。**
  两样都没有，第一轮起就会把频道最近 `playlist_items` 个（example 是 300）视频全部重新投一遍（RUNBOOK §4「起点水位」）。
- **Hugging Face 走代理可能卡死在收尾。** 镜像里已关掉 xet 协议（`HF_HUB_DISABLE_XET=1`），启动前的模型检查
  会先代理后直连。任务日志若停在 `Loading Whisper model` 十几分钟不动，看 RUNBOOK §5.9。
- **YouTube cookie 不是可选项。** 生产用的 `mweb` 客户端没有登录 cookie 时，YouTube 直接返回
  `Sign in to confirm you're not a bot`——日本直连和经代理都一样（09-19 实测）。所以向导第 3 步的
  cookie 必须给，否则 Web 界面能开但提交任务必失败。
- **镜像约 3 GB。** Python 依赖（ctranslate2 / onnxruntime）、Chromium、Noto CJK 字体各占一大块。
  Chromium 是 yt-dlp 取 PO Token 必需的（RUNBOOK §5.3），去掉它画质会掉到 360p。
- **x86_64 和 arm64 都可以原生跑。** 早先以为 `biliup` 没有 arm64 wheel，实际 PyPI 上 1.1.29 就有
  `manylinux_2_28_aarch64`。2026-09-19 在 Apple Silicon（M 系列，Docker Desktop）上原生构建通过，
  容器内 `biliup --version` 正常，不需要 `platform: linux/amd64`。首次构建约 12 分钟（apt 5 分钟、pip 4 分钟）。
  x86_64 侧同日用 `docker buildx build --platform linux/amd64` 在 Mac 上交叉构建通过（QEMU 下约 11 分钟），
  镜像内 `uname -m` 为 x86_64，biliup / deno / yt-dlp / ffmpeg / Noto CJK 均可用；真实 x86 服务器上的运行还没测。
- **转写是纯 CPU。** large-v3-turbo 处理 10 分钟视频约需 5–15 分钟，取决于核数。GPU 版需要换
  CUDA 基础镜像并把 `transcription_engine.py` 的 device 改成 cuda，目前没做。
- **磁盘占用由 mover 定期清理。** `data/downloads` 和 `userdata/data` 里超过 `config.json` 的 `cleanup.keep_days`
  （缺省 7）天的文件每轮自动删掉，Web 界面的成品保留，规则见 RUNBOOK §4「定期清理」。只用 Web 界面、
  没开自动搬运时不会清理；这时磁盘紧张，删 `data/downloads` 里的 .mp4 / .wav 即可，缓存删了会重算。
- **容器以谁的身份运行**由 `PUID`/`PGID` 决定，`docker-start.sh` 按情形自动填，目的是让 `userdata/`、`data/`
  里生成的文件属主是操作这台机器的人：

  | 情形 | 结果 |
  |---|---|
  | 普通用户运行脚本 | 自己的 uid/gid（macOS 是 501，Linux 通常 1000） |
  | `sudo ./docker-start.sh` | 取 `SUDO_UID`/`SUDO_GID`，文件仍归你而不是 root |
  | root 登录的服务器 | root，文件归 root |
  | Windows（Git Bash） | 不传，按 root 跑；Windows 的 bind mount 不讲属主 |
  | 想自己指定 | `PUID=1000 PGID=1000 ./docker-start.sh`；`PUID= ./docker-start.sh` 强制 root |

  不经脚本直接 `docker compose up` 时这两个变量为空 = root 运行；Linux 上事后 `sudo chown -R $USER userdata data` 一次即可。
  非 root 下 Chromium 靠 `/etc/chromium.d/no-sandbox` 里的 `--no-sandbox` 启动（Docker 默认 seccomp 不给用户命名空间）。
  裸机部署（README 方式 B）不涉及这些，文件本来就是你的。
- **资源。** 镜像 3 GB + 模型 1.6 GB + 每个视频的中间产物几十 MB；内存高峰约 2 GB（large-v3-turbo int8）。
  给 Docker 至少 4 GB 内存、10 GB 磁盘。容器日志已限制在 5×20 MB 轮转，PID 1 是 tini（`init: true`）负责回收
  每个任务留下的 chromium 僵尸进程。
- **yt-dlp 会过期。** YouTube 改接口时运行 `./docker-start.sh update`：拉代码、`build --pull`，并传一个新的
  `YTDLP_REFRESH`，让 Dockerfile 里单独升级 yt-dlp 的那一层重跑（其余层走缓存，半分钟左右）。
  以前只有 `--pull`：基础镜像没变时装依赖那层命中缓存，yt-dlp 根本不会升级（10-07 实测）。
- **macOS 用 OrbStack（10-07 生产机 Mac mini 实测）。** `brew install --cask orbstack` 之后如果没在图形界面里走完
  首次引导，`docker` 不在 PATH 里，`docker compose` 也认不出来。把 `/Applications/OrbStack.app/Contents/MacOS/xbin/`
  下的 `docker` 链进 PATH（例如 `/opt/homebrew/bin`），`docker-compose`、`docker-buildx` 链进 `~/.docker/cli-plugins/` 即可。
  `orbctl config set app.start_at_login true` 让它随登录启动，容器靠 `restart: unless-stopped` 跟着恢复。
  **别随手 `docker builder prune`**：清掉构建缓存后下一次 build 会把装依赖那层整个重下一遍。
- **中国大陆网络（10-07 Mac mini 实测，Clash Verge 混合端口 7897）。**
  - OrbStack 默认 `network_proxy: auto`，跟随 macOS 系统代理：拉镜像走它；容器里没设代理的流量也会被它透明地转给系统代理，
    **但域名在本地解析**，`www.youtube.com` 被污染成 Facebook 的 IP，所以容器「直连」YouTube 不通。
    `userdata/.env` 仍要写 `http://host.docker.internal:7897`。
  - 构建不用额外传代理参数，apt / pip / npm 都通，只是慢：首次构建约 37 分钟（apt 18、pip 16、npm 7）。
  - `GEMINI_PROXY` 留空。那条 socks5 + 本地解析的绕行到了 Clash 只剩 IP，会被按 IP 规则分到地区不支持的出口，
    探测 `direct-v4` 0/6、`default` 6/6（RUNBOOK §5.5）。
  - B 站域名在 `NO_PROXY` 里，`api.bilibili.com/x/web-interface/zone` 显示出口是国内，上传不绕路。
  - 模型下载经代理会中途断开（`peer closed connection without sending complete message body`，每次几百 MB），
    靠 `.incomplete` 续传，再跑一次 `./docker-start.sh model` 接着下就行。

## 5. 这套部署对运行中裸机服务的影响

`backend/config/settings.py` 不再内置 `127.0.0.1:10808` 代理默认值，改为完全读环境变量；
`GEMINI_PROXY` 也从「自动由 HTTPS_PROXY 推导」改为「显式设置才启用」。裸机部署要在仓库根
`.env` 里显式写：

```
HTTP_PROXY=http://127.0.0.1:10808
HTTPS_PROXY=http://127.0.0.1:10808
GEMINI_PROXY=socks5://127.0.0.1:10808
```

本机已补上。`mover.py` 新增 `AUTOMATION_STATE_DIR` / `YT_COOKIES_FILE` 两个环境变量，不设时路径不变。
