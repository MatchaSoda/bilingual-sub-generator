# 当前进展 (PROGRESS)

> 每次改动后更新这里。下一个接手的人 / AI 只看这个文件判断现状。
> 最后更新：2026-10-07

---

## 现在的状态

**10-07 生产已迁到 Mac mini（Docker + OrbStack），web 和 mover 两个容器在跑**；旧 WSL 机的 `bili-mover` 已停（用户确认）。
**新机器的第一次真实投稿 05:55 成功**（`BV1WJpN65EEH`）。在那之前 mover 在 Docker 里撞上一个只有 Docker 才有的
跨挂载点 rename bug，已修（`fb4eba5`，RUNBOOK §5.10）。
新机器上 `GEMINI_PROXY` 已清空，Gemini 只走 `default`（`direct-v4` 在这里 0/6，见下）。
10-03 那三个失败循环的修复随新镜像一起生效了。

## 2026-10-07（傍晚）：Web 和自动搬运合成一个产品

用户原本打算把「网页上输入链接」和「自动搬运」做成两个项目，现在要合在一起：自动搬运要有自己的页面、能改全部配置；
网页上识别的链接要能直接投稿；其他部分也要融合。设计和取舍写在 `document.md` §4.3，运维语义在 RUNBOOK §9。

### 架构：Web 是控制台，mover 是唯一的投稿执行者

两个容器不互相调用，只读写 userdata 下的共享文件（`backend/utils/automation_store.py`）。投稿任务写进 `jobs/`，由 mover 和频道扫描
在同一个进程里串行执行。没选「Web 进程自己投稿」，原因有三：

- 不会两边同时压视频（CPU）。
- 不会把同一个视频投两次：扫描时跳过有 Web 任务的视频，history 仍然只有 mover 写。
- 任务在文件里，Web 重启不丢。

代价是 mover 没在跑时任务只能排队，页面上会明确提示。

### 做了什么

- **「自动搬运」页**（`frontend/app/components/automation/`），六个标签：
  - 概览：在线状态、当前在处理哪个视频的哪一步、下一轮时间、上一轮统计、24 小时投稿 / 失败 / 跳过原因。
    还有「立即扫描」「暂停 / 恢复」、投稿队列、B 站账号、最近动态。
  - 频道、扫描规则、处理与投稿：三页配置。草稿 + 保存，带版本号防覆盖手改，上一版留在 `config.json.bak-last`。
  - 投稿记录、日志。
- **生成并投稿**：「制作任务」页切模式，只收 YouTube 单视频链接，分区 / 标签 / 标题可按次覆盖，可以连续提交排队。
  遥测页显示排队位置、阶段进度和 BV 号；排队时可以取消，失败可以重试。
  - 视频在 `uploads.jsonl` 里有记录：确认一次才提交。
  - 在 history 里但不知道是不是被过滤的：同样确认一次。
  - history 里有「跳过」动态的：直接放行。mover 把扫到的每个视频都记进 history，不这样区分的话，监控频道的视频每个都会弹确认。
- **mover**：
  - 休眠时每 3 秒看一次队列和「立即扫描」的触发文件；处理视频的间隙也会插空跑 Web 任务。
  - `config.json` 的 `paused` 只暂停扫描，Web 投稿照常处理。
  - 心跳线程每 5 秒写 `runtime/status.json`。判定和结果写 `runtime/events.jsonl`。
  - 输出另存 `runtime/mover.log`，带时间戳，5 MB 轮转。
  - 投稿成功写 `uploads.jsonl`（BV 号从 biliup 打印的接口返回里取）。
  - 每轮开头把磁盘 history 并进内存。
  - 重启时把还在跑的任务标成失败、不自动重跑，避免重复投稿。
  - `process_and_upload` 拆成 `build_cli_command` + `publish_video`（返回失败在哪一步、原因、BV 号），backfill.py 也走它。
  - B 站标题 / 简介改成模板，缺省值和原来逐字相同。
  - 所有「没写时」的缺省值都从 `automation_store.DEFAULTS` 取。
- **融合的其他部分**：
  - 视觉实验室加「设为投稿样式」，写进 `processing.style`，mover 把它转成 entry_cli 的样式参数。
  - 处理与投稿页可以一键导入「系统设置 / 视觉实验室」的当前设置。
  - 两种任务共用分阶段进度条，阶段表在 `backend/utils/pipeline_stages.py`。TODO 的「分阶段进度条」随之完成。
  - 侧边栏显示自动搬运状态。
  - Gemini key 改成先读 `.env` 文件。以前 mover 容器的环境变量是创建时注入的，Web 上换了 key，mover 要重建才用得上。
- **B 站扫码登录搬到 Web**：用 biliup 自带的 stream_gears，但放在子进程里。原因：直接在 Web 进程里等扫码，整个服务卡死（RUNBOOK §5.11）。
  登录成功才替换 `cookies.json`，旧的备份；返回里没有 SESSDATA 就不覆盖。
- `scripts/migrate.sh` 迁移时带上 `uploads.jsonl`；`runtime/`、`jobs/` 不带。
- 顺带修正 RUNBOOK §2 的 Docker 扫码命令：原来 `cd /app/automation`，登录信息写进容器里，一退出就丢了。

### 验证

- 单元测试 96 → 198，新增 `test_automation_store.py`、`test_mover_publish.py`、`test_automation_api.py`：
  - 假 entry_cli、假 biliup 走完整投稿链路，biliup 参数逐个比对。
  - 扫描跳过 Web 任务正在处理的视频。
  - 唤醒、任务中断、配置冲突。
  - 扫码 helper 的成功 / 坏数据 / 过期 / 取消。
  - 回归：等扫码时主线程照常跑。
- `next build` 编译和类型检查通过。
- 隔离的开发环境：8502 端口，生产镜像挂 worktree 代码，userdata / data 用副本，biliup 换成假脚本，生产容器没动。
  在内置浏览器里实测：
  - 「生成并投稿」`T3VwdAhbbQg`（71 秒新闻）：提交后 2 秒内被 mover 认领，61 秒走完下载 → 转写 → 翻译 → 压制 → 投稿。
    - 遥测页显示「投稿成功：【双语字幕】【白银周】交通状况如何？台风是否有影响 · BV1DEVTEST00」。
    - `uploads.jsonl`、history、动态都写上了；成品改名成中文标题。
    - 传给 biliup 的参数（标题、简介、分区、标签、封面、`--line tx`）和旧代码一致。
  - 页面上加排除词并保存：`config.json` 改对了，`.bak-last` 是上一版。
  - 恢复扫描 → 立即扫描：几秒内开始，列出 300 个、新视频 3 个，全部按排除词跳过。
    概览的「上一轮」和跳过原因分布都对，再暂停。
  - 视觉实验室把主字幕字号调到 95 →「设为投稿样式」：`processing.style` 写入，按钮变成「与投稿样式一致」。
  - 扫码登录：
    - 第一次实测把整个 Web 卡死，查到 GIL 的问题，改成子进程（§5.11）。
    - 改完二维码 0.25 秒返回，等扫码期间别的接口 6 ms 响应。
    - 用浏览器的 BarcodeDetector 解码页面上的二维码，得到 B 站 TV 登录链接。关弹窗后 helper 进程退出。
  - 任务跑到下载阶段时重启 mover：任务标成失败，原因是「服务重启，先确认 B 站没有这条稿件再重试」，没有自动重跑。
  - 账号卡片用真实 cookies.json 调 nav 接口（只读）：用户「抹茶搬运」，到期 2027-01-03。

### 没验证 / 待办

- **真机扫码没测**（要用户的手机）：没确认 `login_by_qrcode` 的返回原样存成 `cookies.json` 后 biliup 能用。
  biliup 自己的 Web 就是这么存的。代码只在返回里有 SESSDATA 时才替换文件，旧的有备份。
  建议用户找个时间扫一次，然后看下一次投稿成功。
- **第一次真实投稿走新代码**要等下一个命中的视频，看日志里 `✅ B 站投稿成功! BV…` 和投稿记录页。
- **局域网里谁都能用这个页面**：Web 没有登录，OrbStack 把 8501 开到了局域网。以前最多泄露 Gemini key；
  现在能改搬运配置、能往 B 站投稿、能把 B 站账号换成扫码人的账号。家庭网络里风险不大，要不要加访问密码需要用户决定。
- 媒体库显示「已投稿 / BV 号」：数据都在 `uploads.jsonl`（含成品文件名和 `origin`），媒体库那边按「来源 + 文件名」就能对上。
  按分工由做媒体库的会话来做。注意 Web 投稿的成品也在 userdata/data，媒体库按目录会标成「自动搬运」，要区分就看 `origin=manual`。
- `uploads.jsonl` 从这次上线才开始记。更早的投稿可以用 `biliup list` + `show` 从简介里的原视频链接反查补齐，记在 TODO。

## 2026-10-07（下午）：媒体文件定期清理

每个投稿的视频在本地留约 370 MB（原视频、`.wav`、成品），代码从来不删。最近 5 天 B 站投了 60 条，平均每天约 12 条，
多的时候一天约 20 条。算下来每天 4–7 GB，Mac mini 剩 120 GB，三四周就会写满。

- `mover.py` 每轮开头调用 `cleanup_old_media`，删 `data/downloads` 和产出目录里超过 `cleanup.keep_days`
  天的文件。缺省 7 天，0 表示关闭；Web 界面的成品（`data/downloads/*_bilingual.*`）不删。规则见 RUNBOOK §4「定期清理」。
- 判断新旧用 `max(mtime, ctime)`。实测 yt-dlp 抽音频会让 `.wav` 继承源视频的 mtime（重跑后 mtime 05:45、ctime 05:51）；
  在 OrbStack 的 bind mount 上把 mtime 改到两年前，ctime 仍是当前时间。yt-dlp 默认 `--no-mtime`，下载文件本身不会被改时间。
- `config.json.example` 和生产的 `userdata/config.json` 都加了 `"cleanup": {"keep_days": 7}`。
- 新增 `test_mover_cleanup.py`（10 个），全套 92/92。容器里对真实 bind mount 实测：当下 0 删、改了 mtime 的 `.wav` 留下；
  假设过了 8 天，删 3 个，Web 成品保留；生产目录当下 0 删。部署后首轮正常。

## 2026-10-07（下午）：媒体库显示自动搬运的成品，加筛选和排序

用户要求自动搬运的视频也出现在 Web 界面的媒体库里，并能筛选、排序。以前 `/api/library` 只列
`data/downloads/*_bilingual.mp4`（Web 任务的成品），mover 的产出在 `userdata/data`，界面上看不到。

- 后端：
  - `backend/utils/library.py` 把两个目录一起列出来，每条带 `source`（`web` / `auto`），以及 `size_bytes`、`mtime` 两个原始数值。
  - `settings.AUTOMATION_OUTPUT_DIR` 和 mover 的 `OUTPUT_DIR` 是同一个目录，静态挂载在 `/api/outputs`。
  - `DELETE /api/library/{name}?source=` 按来源删成品和同名的 `.jpg` / `.ass`。文件名必须是该目录下的 `*_bilingual.mp4`，否则 404。
  - `DELETE /api/library?source=`（缺省 `web`）不再顺带删掉 downloads 里所有 `.ass` / `.jpg`。那些是别的视频的缓存和封面，交给定期清理。
- 前端 `LibraryPanel`：
  - 来源筛选「全部 / 手动制作 / 自动搬运」，带数量。
  - 标题搜索。
  - 排序：最新、最早、最大、最小、名称。来源和排序存在 localStorage。
  - 封面左上角显示来源标签。
  - 「Clear Hub」改为逐个删除当前筛选、搜索后看得到的视频。
  - 下载按钮加了 `download`。媒体 URL 统一转义 `#` / `?`。
- 验证：
  - `test_library.py` 4 个，全套 96/96，`next build` 编译和类型检查通过。
  - 在内置浏览器里实测：
    - 列出两条（自动搬运 153 MB、手动 29 MB）。
    - 「自动搬运」筛选剩 1 条，搜「白银」剩手动那条。
    - 按「文件最小」排序后顺序反过来；刷新页面后排序还在。
    - 自动搬运的视频从 `/api/outputs/` 播放：readyState 4，1920x1080，337 秒，Range 请求返回 206。
  - 删除接口：用名字带 `#` 的临时文件实测，`source=web` 返回 404，`source=auto` 返回 200，视频和封面都删掉了。

## 2026-10-07：生产迁到 Mac mini（Docker + OrbStack）

机器：Apple M6（2 超大核 + 4 性能核 + 6 能效核）/ 16 GB / macOS 27，中国大陆网络，代理是 Clash Verge 7897。
用户还拿它当桌面用（UU 远程）。选 Docker 而不是 macOS 裸机，原因有三：

- `yt-dlp-getpot-wpc` 1.1.2 源码里写死了 `headless=False`，裸机每次下载都会在桌面弹出一个 Chrome。
- Docker 路线 09-19 已在 Apple Silicon 上验证过，裸机文档只覆盖 Linux。
- faster-whisper 在 Mac 上没有 Metal 后端，裸机也只能用 CPU。

运行时选 OrbStack 而不是 Docker Desktop：同一份 compose，空闲内存会还给 macOS。

### 做了什么

- OrbStack 2.2.3（`brew install --cask orbstack`）。图形引导没走，手工把 docker CLI 和 compose / buildx 插件链上
  （DOCKER.md §4），设了 `app.start_at_login=true`。
- 导入用户带来的包（`.env`、cookies.txt、B 站 cookies.json、config.json、history 8908 条），然后改 `userdata/.env`：
  - 代理 `10808` 改成 `http://host.docker.internal:7897`
  - `GEMINI_PROXY` 清空
  - 补上 `NO_PROXY`（B 站域名）
  - `TZ=Asia/Shanghai`
  - config.json 没动（无 `backfill` 段，按老账号 `all` 模式带 history 继续）。
- 首次构建约 37 分钟（apt 18、pip 16、npm 7 分钟），网速 0.5–1 MB/s。Whisper 模型 45 分钟，经代理断了 3 次，靠续传下完。
- 体检 6/6。Gemini 两条路径各打 6 次：`direct-v4` 0/6（`location is not supported`），`default` 6/6。
  原因是 socks5 + 本地解析到了 Clash 只剩 IP，被按 IP 规则分到了不支持的出口。所以清空 `GEMINI_PROXY`。
- 端到端（Web API，`T3VwdAhbbQg`，71 秒新闻）：**55 秒出片**（09-19 MacBook Air 约 1.5 分钟）。
  - 下载 399+251，经代理 3.9 MB/s。
  - 转写，翻译 16 段。标题译为「【白银周】交通状况如何？台风是否有影响」。
  - 成片 1920x1080 h264，70.7 秒。抽 12 秒、47.8 秒两帧：日文主字幕、振假名、中文副字幕三层都正常，Noto CJK 无豆腐块。
- 防重投：包里的 history 最后写入是 10-06 23:24。用 `biliup list` + `biliup show` 核对 B 站最近 10 条投稿
  （最新 10-06 21:21）的原视频 ID，全在 history 里，所以不用再导一次。用户确认旧机 mover 已停后才开 `ENABLE_AUTOMATION=1`。
- B 站上传：`api.bilibili.com/x/web-interface/zone` 显示容器出口是国内（北京联通）；`tx` 线路从这里解析只有 1 个节点，证书有效。
- 顺带修了 `./docker-start.sh update` 不会真的升级 yt-dlp（`ab35422`，DOCKER.md §4 有说明）。
- mover 03:47 到 05:17 的四轮：每轮列出 300 个视频，全在 history 里，直接休眠。符合预期，频道最新的几条旧机停之前已经处理过。
- **05:4x 第一个新视频 `lTelR_g9adE` 失败**：压制完成后 entry_cli 把封面从 `data/downloads` rename 到
  `userdata/data`，报 `[Errno 18] Invalid cross-device link`，`CLI 失败 (Code 1)`。原因是 Docker 里这两个目录分属两个 bind mount，
  而 rename 不能跨文件系统。裸机上它们在同一块盘，Web 界面的产出又在 downloads 里，所以以前从没撞上过。
  09-19 的 Docker 验证没跑过 mover，今天的端到端也是走 Web。
  不修的话每轮都会重压一遍再失败（§5.6）。修复是改用 `shutil.move`（`fb4eba5`）。
  用旧镜像 + `--output /app/userdata/data/...` 复现出同样的 EXDEV；新镜像同一条命令 exit 0。82/82。
- 重建容器后 mover 立刻重试 `lTelR_g9adE`，**05:55 投稿成功**，`BV1WJpN65EEH` 审核中，history 8909 条：
  - 转写、翻译走缓存，5 分 37 秒的 1080p 视频压制 73 秒，产出 160 MB。（之前按 .wav 大小估成约 8.5 分钟，是错的；
    媒体库播放器读出来时长是 337 秒。）
  - 上传 2 分 13 秒（`tx` 线路，国内直连）。

### 观察到、还没处理的

- 体检时出现 7 次 `[pot:wpc] Timed out waiting for WebPoClient to be available in browser`，但同一次实测最后拿到了 1080p；
  单独 `yt-dlp -v` 21 秒拿到 gvs token，端到端任务里也没出现。疑似浏览器冷启动加上经代理加载 YouTube 太慢，先观察
  mover 日志里的出现频率。
- **`/api/config` 会把明文 Gemini key 返回给任何能访问 8501 的客户端**，而 OrbStack 默认把端口开到局域网
  （`docker.expose_ports_to_lan: true`）。以前在 WSL 上也是 `0.0.0.0`，不是这次引入的，但现在机器在家庭局域网里长期开着。
- 我在做缓存实验时跑了 `docker builder prune`，把项目的构建缓存也清了，导致下一次 build 重下了 pip 那层（多花约 13 分钟）。已写进 DOCKER.md / CLAUDE.md：别 prune。

- 投稿后 8 小时（05:55–13:52）复查：16 轮扫描全部正常，1 个处理，跳过 19 个（关键字不匹配 11、排除词 8），拉描述失败 0。
  按 RUNBOOK §8 第四步把 11 个「关键字不匹配」的简介逐个实测：10 个简介完整、都不含 `#newsevery`。
  剩下的 `aUVCfAfHSBE` 简介是 `NA`，原因是日テレ删掉了它（`Video unavailable`），重发成 `lgfY7r3MYyM`，后者也不含 `#newsevery`。
  所以白天产出少是正常的：旧机最近 10 条投稿都在 19:12–21:21 之间，`#newsevery` 的视频主要在晚间节目前后上传。

### 机器设置（用户已改，10-07 下午复查）

- `pmset`：`sleep 0`、`autorestart 1`。
- 「自动安装 macOS 更新」已关；用户把「安全响应和系统文件」（`CriticalUpdateInstall` / `ConfigDataInstall`）也一起关了。
- 远程登录（SSH）已开，sshd 在监听 22 端口。FileVault 仍开着，重启后可以用 SSH 远程解锁。
  **没实测过**：SSH 解锁后会不会自动进入图形会话、OrbStack 能不能随之起来。

### 待办

- 找个方便的时间重启一次，验证「SSH 解锁 FileVault → 用户会话 → OrbStack → 容器」整条链路。
- 旧 WSL 机保持 `disable`，新机器稳定跑几天后再决定是否清理。

## 2026-10-07：迁移脚本支持裸机 / Docker 互迁

用户准备把生产从这台 WSL 裸机迁到另一台电脑，迁过去用裸机还是 Docker 都要能用。原来的 `./docker-start.sh export`
只打包 `userdata/`（裸机上这个目录是空的），而且脚本开头就要求 docker 在运行，所以裸机上根本走不到导出。

- 新增 `scripts/migrate.sh export|import`，不依赖 Docker。包格式仍然是 `userdata/` 结构，兼容旧包；
  导入时自动判断目标部署方式（userdata 已有数据 → Docker，有 venv/ → 裸机，都没有 → Docker），也可以用 `--to` 指定。
  代理主机名在 `127.0.0.1` 和 `host.docker.internal` 之间自动换；目标机器已有数据时拒绝覆盖（`--force` 覆盖并备份）。
- `docker-start.sh export/import` 改为调用这个脚本，并且挪到 docker 检查之前执行。
- 用法见 DOCKER.md §3.5，测试在 `backend/tests/test_migrate.py`。

**迁移待办：** ~~新机器跑通 → 旧机 `sudo systemctl disable --now bili-mover` → 再导出一次 → 导入 → 新机开自动搬运。~~
已完成，见上一节（没有再导出一次，因为 B 站投稿记录核对过 history 无缺口）。

## 2026-10-03 这次做了什么：三个失败循环

起因是「日志又有报错」。日志 3 天里 128 次 `CLI 失败`，但按视频 ID 一数只有两个视频
（方法见 [RUNBOOK §5.6](./RUNBOOK.md#56-同一个视频每轮都失败)）：

- **`urcgQPQulSs` × 113：文件名超 255 字节。** 长日文标题 + `.f399.mp4.part` = 263 字节。
  所有标题来源的文件名统一截到 200 字节，标题翻译改用元数据里的完整标题。§5.7
- **`R3HNFKr1OKM` × 16：`Translation count mismatch`，缺尾部编号。** 不是截断，是模型在批次
  中间合并相邻两行导致后面全部错位；温度 0 下 5/5 复现，重试无效。现在数量不对就对半拆批。§5.8
  （这个视频 10-02 碰巧过了一次，已投稿）
- **Gemini `direct-v4` 路径自 09-29 起 100% 被拒**，每次重试有一半白费。现在被拒的路径在本进程内
  不再使用。§5.5

### 本次的提交

```
a55ea39 backend: cap title-derived filenames at 200 bytes to avoid ENAMETOOLONG
f55f879 automation: byte-cap the output filename passed to entry_cli --output
186ba3b backend: split a translation batch in half when the model drops lines
9b20049 backend: stop using a Gemini route for the run once it is location-blocked
```

### 已知问题 / 待办

- **字幕可能静默错位一行。** 复现 §5.8 时发现：半批（50 行）数量对上了，但第 43–48 行的译文各
  错了一行，到 49 行又对齐（模型一处合并、一处拆分，正负抵消）。数量校验抓不到。可能的方向：
  让模型同时回显原文首尾几个字做对齐校验，或者缩小默认批次。需要先量一下发生率再决定。
- **确定性失败会无限重试**（失败不写 history）。这次两个视频分别空转了 113 和 16 轮。
  可以考虑在 mover 里给连续失败计数、超过 N 次就跳过并告警。
- `direct-v4` 出口被拒要在代理服务端处理（§5.5 的方法）；代码侧已经不受影响，不急。
- 2026-09-19 的 Docker 待办见下。

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
处置见 RUNBOOK §5.9（`local_files_only` 优先、`HF_HUB_DISABLE_XET=1`、启动前 `--download-model`、缓存判断看 `model.bin`）。

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
