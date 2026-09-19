# 当前进展 (PROGRESS)

> 每次改动后更新这里。下一个接手的人 / AI 只看这个文件判断现状。
> 最后更新：2026-09-19（下午，Docker 实测）

---

## 现在的状态

服务正常，**无待办故障**。09-19 加了 Docker 一键部署，同日下午在 Apple Silicon Mac 上完成首次真实构建与启动（见下）。

## 2026-09-19（下午）：Docker 首次真实构建（macOS / Apple Silicon）

在一台 M 系列 MacBook Air（Docker Desktop 29.8，arm64，Clash Verge 代理 7897）上从零克隆、构建、启动。

### 结果

- 镜像原生 arm64 构建成功，3.1 GB，首次约 12 分钟（apt 5 分钟，pip 4 分钟）。**`biliup` 1.1.29 有 aarch64 wheel**，
  文档里「只支持 x86_64」的说法是错的，已改 `docs/DOCKER.md` §4。
- `./docker-start.sh check`：ffmpeg / Noto Sans CJK / Chromium / yt-dlp / biliup 全部就位；
  `http://host.docker.internal:7897` 通（YouTube 204、Gemini 403 即可达）；模型预下载后显示已缓存。
- `docker compose up -d web`：`GET /` 200，`/api/config`、`/api/library` 正常，浏览器打开首页渲染无控制台报错。
- nodriver 在 entrypoint 起的 Xvfb 下能拉起 Chromium 并打开 youtube.com（`document.title == "YouTube"`），
  PROGRESS 上一条担心的「Chromium 在 Xvfb 下起不来」排除。
- 单元测试在容器里跑：51/51 通过（需要给 `GOOGLE_API_KEYS` 任意非空值，`config/keys.py` 导入期就校验）。

### 踩到并修掉的

- `# syntax=docker/dockerfile:1` 让 BuildKit 每次都去远端解析 frontend 镜像，宿主机 DNS（114.114.114.114）
  把 `auth.docker.io` 解析成 Dropbox 网段，60 秒超时后失败。Dockerfile 没用到任何需要外部 frontend 的语法，删掉该行。
- `./docker-start.sh check` 原来执行 `docker compose run --rm setup --check`，compose 的 `run` 会把后面的参数
  **整个替换** command，容器收到的 `$1` 是 `--check`，entrypoint 兜底分支 `exec --check` 直接报错。
  改成 `run --rm setup setup --check`，entrypoint 也加了 `--*)` 分支兜底。
- Web 界面「系统设置」的 `/api/config` 把 key 写到 `BASE_DIR/.env`，在容器里就是 `/app/.env`——不在挂载的
  `userdata/`，重建容器就丢。改为 `settings.ENV_FILE`（跟随 `AUTOMATION_STATE_DIR`）。顺带修了 POST 更新
  内存 key 管理器时用错属性名（`keys`/`current_index` → `active_api_keys`/`next_key_index`）。
- `docker compose restart` 不会重新读 `userdata/.env`（实测：改值后 restart，容器里还是旧值；`up -d` 会 Recreate）。
  DOCKER.md / env.example 里「改完 restart」的说法已改成重新 `./docker-start.sh`。

### 导入旧机配置后继续排查（同日下午，凭据到位）

用户导出的 `userdata/`（key、cookie 171 条含 LOGIN_INFO、B 站 cookies.json、config、7853 条 history）导入后：

- Gemini key 经 Clash 和直连都是 200。
- cookie 过了风控（不再 `not a bot`），但 `yt-dlp-getpot-wpc` 1.0.0 配镜像里的 nodriver 0.50.3 报
  `'NoneType' object has no attribute 'send'`，且每个 PO Token 请求重开一个 Chrome，35 个 Chromium 把宿主机 load 打到 38。
  升到 1.1.2（锁 nodriver==0.50.3）后 `Launching youtube.com in browser` / `Minting gvs PO Token` 正常。
- 之后仍只剩图片格式：`JS runtimes: none`。requirements 是裸 `yt-dlp`，没有 `yt-dlp-ejs`，镜像里也没有 JS 运行时。
  改成 `yt-dlp[default]` + PyPI 的 `deno` 二进制包，Dockerfile 把 `venv/bin` 加进 PATH。RUNBOOK §5.3 记了这两条。

### 新功能：automation 起点水位（`backfill.mode`）

用户提出：新账号 / 迁移时不想把频道 100 个存货全搬一遍，但停机恢复时又要能补齐「首次启动 → 现在」。
实现见 `mover.py` 的 `resolve_backfill_cutoff`，语义写在 RUNBOOK §4。要点：起点只在第一次启动时落盘到
`state.json`，重启不推后；`lookback_hours` 可随时改；发布时间用 `youtubetab:approximate_date` 从列表页换算，零额外请求。
`config.json.example` 默认 `since_first_start`，代码缺省 `all`（不影响正在跑的 WSL 服务）。向导第 4 步新增提问。
单测 13 个（`test_mover_backfill.py`），全套 64/64。

### 真实视频端到端（同日傍晚）

用 Web API 提交 `T3VwdAhbbQg`（日テレ 71 秒新闻）。第一次卡在 `Loading Whisper model` 17 分钟：模型 blob 已完整但仍是
`.incomplete`（我之前 `docker kill` 探测容器时把后台预下载一起杀了），hf_xet 经 Clash 收尾挂死；向导 `--check` 却报「已缓存」。
处置见 RUNBOOK §5.6（`local_files_only` 优先、`HF_HUB_DISABLE_XET=1`、启动前 `--download-model`、缓存判断看 `model.bin`）。

重提后全程约 1.5 分钟：下载 399+251（PO Token + deno 解 n 参数都走通）→ 转写 35 秒 → Gemini 翻译 16 段 3 秒 →
标题译为「【白银周】交通状况及台风影响」→ ffmpeg 压制 26 秒 → 1920x1080 h264 70.7 秒。抽帧确认主字幕 / 中文副字幕 /
振假名三层渲染正常，Noto Sans CJK 无豆腐块。

### 可迁移性 / 易用性收尾（同日晚）

用户明确这台 Mac 只是验证「能否换机器跑」，之后要迁到专用服务器，所以把这一路的摩擦点做掉：

- 容器按宿主机 uid 运行（`PUID`/`PGID` → entrypoint `setpriv` 降权，`/etc/chromium.d/no-sandbox` 让非 root 的 Chromium 能起）。
  实测 uid 501 下 check 6/6、PO Token 正常、产出文件宿主机属主 501。不设 PUID 仍是 root。
- compose 加 `init: true`（任务后 defunct 数 0）和日志轮转 5×20 MB。
- `./docker-start.sh` 检测到 userdata 齐全就先体检、通过直接启动，不再强制走向导；新增 `export` / `import`
  （导入自动关 ENABLE_AUTOMATION、删 .setup-done、拒绝覆盖已有配置除非 --force）。在干净的仓库副本里导入后 check 6/6。
- 向导第 1 步先探直连，通了默认直连。构建失败自动重试一次并给 DNS / 基础镜像的提示。
- 纠正：buildx 不会把 shell 的代理变量带进构建（实测），CLAUDE.md 之前那条建议已改。
- 用户提醒「权限不能一刀切，也要考虑裸机用户」：PUID 改为分情形推导（sudo 取 SUDO_UID、Windows 不传、root 登录就 root、
  `PUID=` 可强制 root、非数字兜底 root），裸机路径完全不涉及；README 方式 B 补齐 Chromium / Noto CJK / Xvfb 依赖和向导步骤。

### x86_64 构建验证

`docker buildx build --platform linux/amd64` 在这台 Mac 上交叉构建成功（QEMU，约 11 分钟）：pip 解析到
biliup / deno / ctranslate2 / onnxruntime / nodriver 的 x86_64 wheel，镜像内 `biliup --version`、`deno --version`、
`yt-dlp --version`、ffmpeg、10 个 Noto Sans CJK 字体族均正常。只验证了「能构建、二进制能跑」，没有在真实 x86 机器上跑流水线。

### 仍未验证（需要凭据）

- `biliup login` 在容器 tty 里的二维码显示未测（导入了旧机的 cookies.json，暂时不需要）。
- `mover` 在 Docker 里没有真正跑过一轮（`ENABLE_AUTOMATION=0`，等用户决定何时停旧机、开新机，避免双开投稿）。
- 起点水位只有单测和 flat-playlist 的时间戳实测，没有在真实一轮扫描里观察过日志。
- x86_64 只做了交叉构建 + 二进制冒烟，未在真实 x86 机器上跑过完整流水线（迁到新服务器时第一件事就是 `./docker-start.sh check`）。

## 2026-09-19 这次做了什么：Docker 一键部署 + 首次设置向导

目标是让别人在别的电脑上 `./docker-start.sh` 就能跑起来，代理 / key / cookie / 频道全部由向导引导填写并当场验证。

### 新增

- `Dockerfile`（node 阶段导出前端 → python:3.12-slim + ffmpeg + fonts-noto-cjk + chromium + xvfb，venv 在 `/app/venv`）
- `docker-compose.yml`：`web` / `mover`（profile `automation`）/ `setup`（profile `setup`）共用一个镜像
- `docker/entrypoint.sh`：起 Xvfb（PO Token 插件要非 headless Chrome）、按角色分发
- `docker-start.sh`：宿主机一键脚本（start / setup / check / logs / stop / update / shell）
- `scripts/setup_wizard.py`：交互向导，`--check` 为非交互体检。逻辑拆在 `backend/utils/setup_checks.py`，13 个单测
- `userdata/`：Docker 部署的全部用户数据目录（git 忽略）
- `docs/DOCKER.md`

### 改动（影响裸机部署，已在本机 `.env` 补齐）

- `settings.py`：代理不再默认 `127.0.0.1:10808`，纯环境变量；`GEMINI_PROXY` 显式设才启用；
  `YT_COOKIES_FILE` 可覆盖 cookie 路径；空 cookie 文件视为不存在
- `mover.py`：`AUTOMATION_STATE_DIR` 覆盖 config / history / cookies.json / 产出目录；biliup 的 cwd 跟着走
- `requirements.txt` 补上此前只装在本机 venv 的 `biliup`、`yt-dlp-getpot-wpc`、`PySocks`

### 验证

- `bash run_tests.sh` 51/51（新增 13 个 setup_checks 用例）
- `scripts/setup_wizard.py --check` 在本机裸机配置上 6/6 通过：YouTube 204、Gemini key 200、
  cookie 167 条含 LOGIN_INFO、yt-dlp 实测拿到 2160p、模型已缓存
- settings 改动后 `HTTP_PROXY / GEMINI_PROXY / route_for_attempt` 解析值与改前一致

### 未验证 / 待办

- ~~本机没有 Docker，镜像从未构建过。~~ 已于同日下午在 Apple Silicon Mac 上构建并启动，见上一节。
  `npm ci` 70 秒无卡顿（playwright 浏览器下载被跳过）、字体识别正常、nodriver 拉起 Chromium 正常、代理连通。
- ~~`biliup` 无 arm64 wheel~~（有，见上）；`biliup login` 在容器 tty 里的二维码显示未测。

## 2026-09-14 这次做了什么

起因是「日志有报错」+「有些投稿标题没翻译」。查下来是两个外部故障叠加，加一个代码 bug：

### ① Gemini 出口被拒（已解决，服务端）

两条出口路径先后都被 Gemini 以 400 `User location is not supported` 拒绝，字幕翻译耗尽重试
导致 `CLI 失败`，标题翻译失败则**照常投稿日文标题**。最终是在代理服务端把 Google 域名的出站
钉到探测干净的那个出口解决的。方法（怎么看出口、怎么探测两条路径）沉淀在 [RUNBOOK §5.5](./RUNBOOK.md#55-gemini-返回-400-user-location-is-not-supported-for-the-api-use)，
新增 `scripts/probe_gemini_routes.py`。具体哪个网段干净不记录，那是会变的。

### ② YouTube cookie 会话被作废（已解决）

`cookies are no longer valid` → `not a bot`，约 42% 失败。第一次重导出来的是同一个死会话，
毫无改善；在无痕窗口重新登录后导出才好，16/16。教训是两条：重导后先比对 `LOGIN_INFO`
是否真的换了；带着死 cookie 的成功率不能拿来比较别的变量。都写进了 RUNBOOK §2 / §5.2。

### ③ 标题里的 【】 标签没翻（已修，`998cbc9`）

prompt 让模型「像节目名就保留」，flash-lite 把普通新闻标签也保留了，约 19% 的标题开头是日文。
改成封闭白名单 + 假名残留检查 + 最多一次重问，标题重试次数 4 → 6 与字幕一致。
单测 11 个用例，真实标题回放 16/16 命中、白名单 0 误报，线上 6/6。

### 本次的提交

```
998cbc9 backend: pin the 【】 show-name whitelist and re-ask when a title keeps kana
c5fd20f backend: add a per-route Gemini reachability probe script
（+ 文档提交若干；排查过程中的两次误判及其推翻都记在 commit body 里，文档只留结论）
```

---

## 2026-08-29 这次做了什么

起因是「automation 最近两天没更新」。查下来是**三个独立的故障叠在一起**，逐层剥开的：

### ① 过滤规则死锁（已修复）

`config.json` 的 `exclude` 里有 `every`，而 `keyword` 是 `#newsevery`。由于判定顺序是先查排除词再查关键字，且排除词当时**也作用于描述**，导致每个真正该处理的视频都先被排除词干掉，匹配率恒为 0。服务表现完全正常，只是不再产出。

修复：`automation/mover.py` 删掉描述层的排除词检查，`exclude` 只对标题生效。语义说明见 [RUNBOOK §4](./RUNBOOK.md#4-过滤规则语义)。

停产区间：2026-08-27 18:52 ~ 08-29 19:23。

### ② history.json 误删复活（已解决，过程有教训）

被误跳过的 29 条视频已写入 history，需要移除才能重跑。第一次直接改磁盘文件后等待重启，结果运行中的进程中途醒来写了一次盘，把 29 条全部并集回来了。

原因是 `save_history()` 写盘前会先并集磁盘内容，运行中的进程内存才是权威。正确姿势（停服务 → 改 → 起服务）已写入 [RUNBOOK §3](./RUNBOOK.md#3-historyjson-语义改它之前必读)，并提供了 `scripts/prune_history.py`。

### ③ YouTube 下载被风控（已修复）

症状 `Sign in to confirm you're not a bot`，成功率约 33%，同一个视频时好时坏。

两个原因串在一起：

- `cookies.txt` 是残缺导出（16 条，无 `LOGIN_INFO`），残缺到让 yt-dlp 误判为未登录，于是放行了不支持 cookie 的 `tv_simply` 客户端，全靠裸奔过风控。
- 换上完整 cookie（471 条，含 `LOGIN_INFO`）后，yt-dlp 立刻跳过 `tv_simply`，转而报 `Requested format is not available`——只剩 storyboard 图片格式。

修复：`cookies.txt` 换成完整导出 + `media_downloader.py` 的 `player_client` 从 `tv_simply` 改为 `mweb`（唯一同时支持 cookies 和 GVS PO Token 的客户端）。客户端取舍矩阵见 [RUNBOOK §5.3](./RUNBOOK.md#53-requested-format-is-not-available--画质悄悄掉到-360p)。

验证：生产配置连测 5 次，5/5 成功，`399(1080p) + 251(audio)` 完整 DASH。线上 19:55 那轮也确认走通了下载 → 转写 → 翻译 → 压制全流程。

### ④ 文档化改造（本次）

新增 `CLAUDE.md` / `docs/RUNBOOK.md` / `docs/PROGRESS.md`，把上述运维经验从代码注释里搬出来，代码里只留一句指向 runbook 的锚点。

### ⑤ Gemini 地区封锁（已修复）

翻译和标题翻译频繁报 400 `User location is not supported for the API use`，靠重试硬扛，偶发
耗尽 6 次重试导致整条流水线失败。根因是出口 IP 段被 Gemini 拒绝，而哪段干净会随时间翻转。

排查绕了两次弯（拿响应延迟推断网络路径；对被封的 IP 族判断反了），教训记在 RUNBOOK §5.5。

修复：`backend/utils/gemini_transport.py` 让重试在两条出网路径间轮换，任一条活着流水线就能跑；
不押注单条路径，因为两边的封禁态势都在变。作用域限制在 Gemini 调用内。

验证：直连路径真实负载连测 32/32，故障注入把一条路径指向死端口后另一条成功兜住。

## 已知问题

### ~~#1 B 站投稿失败~~（已定位真因并修复）

`client error (Connect)`，倒在上传 CDN 上。**归因错了两次**，第三次才挖到底。

**第一次**：以为是 `subprocess.run()` 继承了 systemd 的 `HTTPS_PROXY`（10808 是 SOCKS5 端口）。
复测发现那组「直连成功/代理失败」的对比是噪音，同一 URL 稍后直连也是 0/5。代理无关。

**第二次**：以为是 biliup 选中了探测超时的线路（选线日志里 `cost` = `u128::MAX` 哨兵值）。
据此加了进程级重试，线上确实自愈过几次——但那只是掩盖症状。用户指出「不要只顾着写重试」
之后才继续往下挖。

**真因**：报错最内层写着，只是之前没翻到底——

```
╰─▶ invalid peer certificate: certificate expired:
    but certificate is not valid after 1783746060 (4263956 seconds ago)
```

**B 站 `bldsa` 线路上 14 个节点里有 7 个的 TLS 证书 2026-07-11 就过期了**，逐 IP 用
openssl 查证实。每次上传在节点间轮询，50% 概率撞上坏证书。biliup 内部的 5 次 reqwest
重试在同一条线上打转、必然失败；换新进程会重新解析，所以进程级重试约一半能救回来。
实测有一次连挂两次、第 3 次才过——按 12.5% 的三连挂概率，29 个视频跑一遍预期掉 3~4 个。

**修复**：`config.json` 的 `upload.line` 钉到 `tx`（6 个节点证书全部有效，且探测最快 433ms）。
进程级重试保留作兜底，正常不该再触发。复查各线路证书健康度的脚本见 RUNBOOK §5.4。

顺带记一条：`curl .../OK` 这种探测**不能用来判断线路好坏**，它每次只碰一个 IP，
测出来的成功率纯属随机——之前那组 `bldsa 1/5`、`3/3` 的矛盾数据就是这么来的。

### ~~#2 两个待决策的小项~~（已决策，不要再翻）

- `6NGQ9mXQ-54`（石川·富山大雨解説）当初是命中**描述**里的 `害` 被跳过的。现在 exclude 不再作用于描述，这条会被正常处理。如果不想要，需要手工加回 history。
- `config.json` 的 `exclude` 里的 `"every"` **是有意保留的，不要删。**
  它看起来和 keyword `#newsevery` 语义冲突（09-07 复查时又被当成 bug 查了一遍），
  实际作用是过滤掉标题带『every.特集』的生活 / 美食 / 街录类专题——那些视频描述里
  确实有 `#newsevery`，属于真实命中，但用户明确表示不要这类内容，只要普通新闻。
  所以这不是误加，是唯一能把「特集」和「普通新闻」分开的信号（两者描述都带同一个标签）。

### #3 技术债

- `subtitle_translator.py` 仍在用已废弃的 `google.generativeai` 包，每次运行都打 `FutureWarning`，官方已停止维护，应迁移到 `google.genai`。
- `automation/` 下堆了一批日志和备份文件（`*.log.*`、`history.json.bak-*`、`cookies.txt.bak-*`），未纳入 git 忽略规则，`git status` 一直是脏的。
- 排除词是裸子串匹配，会误伤：`死` 命中过「起死回生」（`wByz7sJm-Rk`），`害` 会命中
  「利害」这类无关词。09-07 复查时实测误伤率不高（9 条 `死` 命中里 1 条是成语），
  用户决定先不动。真要修就在 `mover.py` 查排除词前加一层无害短语白名单，改完要重启服务。

---

## 本次的提交

```
3cf09ed automation: stop applying exclude keywords to video descriptions
d6fce36 backend: switch yt-dlp to the mweb client so cookies and PO Token coexist
eecfc8f automation: retry bilibili submission in a fresh biliup process
（+ 本次文档提交）
```

`cookies.txt` 和 `automation/config.json` 已更新但被 git 忽略（含凭据），不在提交里。
换新机器/重装时记得单独恢复这两个文件。
