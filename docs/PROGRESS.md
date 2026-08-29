# 当前进展 (PROGRESS)

> 每次改动后更新这里。下一个接手的人 / AI 只看这个文件判断现状。
> 最后更新：2026-08-29

---

## 现在的状态

自动搬运服务 `bili-mover` 在线运行，**端到端已跑通**：20:21 有一条视频完整走完
下载 → 转写 → 翻译 → 压制 → B 站投稿并成功。今天共修复四处故障。

积压：约 29 条视频待补投，已从 `history.json` 中移除，服务每轮取 3 条自动重试，无需人工干预。

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

翻译和标题翻译频繁报 400 `User location is not supported for the API use`，靠重试硬扛
过去（标题一次要退避 17 秒），偶发耗尽 6 次重试导致整条流水线失败。

排查过程绕了两次弯，都记在 [RUNBOOK §5.5](./RUNBOOK.md#55-gemini-返回-400-user-location-is-not-supported-for-the-api-use)：

1. 先用「成功的慢、失败的快」推断有两条路径——**推理是错的**，400 不做模型推理天然就快，
   那个延迟差是推理耗时不是网络跳数。
2. 再推断是 WARP 的 IPv6 被封、建议强制 v4——**结论也是反的**。用户改成 ForceIPv4 后
   成功率从 55% 掉到 0%，反而证明被封的是 WARP 的 **IPv4** 段。

最终实测清楚：WARP IPv4 全拒（0/16），WARP IPv6 可用，而 **VPS 原生 IPv4 出口 17/17 全过**。
所以 WARP 在这个场景里是问题本身，不是解法。

修复：`backend/utils/gemini_transport.py` 让**重试在两条路径间轮换**——偶数次尝试走
`direct-v4`（切 `socks5://` 本地解析 + 钉死 IPv4，绕开服务端域名分流落到直连出站），
奇数次走 `default`（原有 WARP 分流）。作用域限制在 Gemini 调用内。

之所以不直接把 WARP 摘掉：用户指出当初加 WARP 正是因为 VPS 原生 IP 被 Google 封过。
两边的封禁态势都在变，押注任何单条路径都会在某天翻车，所以做成轮换。

验证：直连路径用真实负载连测 15/15（累计 32/32），真实 translator 类零重试通过；
故障注入把 `direct-v4` 指向死端口后，`default` 成功兜住。环境变量与 `getaddrinfo` 正确还原。

---

## 已知问题

### ~~#1 B 站投稿失败~~（已修复，待线上验证）

`client error (Connect)`，倒在上传 CDN 连接上。

**第一次归因错了**：当时以为是 `subprocess.run()` 继承了 systemd 的 `HTTPS_PROXY`，
而 10808 是 SOCKS5 端口。用户指出「之前投稿一直正常」后复测，发现那组
「直连 200 / 代理失败」的对比是噪音——同一 URL 稍后测直连也是 0/5。代理无关。

**真实原因**：B 站上传 CDN 连通性本身在波动，且 biliup 选中了一条**探测超时**的线路
（日志里 `cost` = `u128::MAX` 哨兵值），而同批另外 4 条线都探通了（`tx` 最快 433ms）。
biliup 内部的 reqwest 重试只在同一条死线上退避，所以必然失败。

**修复**：`upload_to_bilibili()` 增加进程级重试（默认 3 次 / 间隔 60s），每次都是全新
biliup 进程会重新探测选线；同时支持在 `config.json` 的 `upload.line` 钉死线路。
已用故障注入的假 biliup 验证过三种路径（中途成功 / 耗尽重试 / `--line` 透传）。

**已线上验证**：20:21:02 投稿成功（首次尝试即通过，重试逻辑未被触发）。

### #2 两个待决策的小项

- `6NGQ9mXQ-54`（石川·富山大雨解説）当初是命中**描述**里的 `害` 被跳过的。现在 exclude 不再作用于描述，这条会被正常处理。如果不想要，需要手工加回 history。
- `config.json` 的 `exclude` 里仍保留 `"every"`，现在只影响标题。日テレ的目标视频标题基本是日文，影响很小，但如果它当初就是误加的，删掉更干净。

### #3 技术债

- `subtitle_translator.py` 仍在用已废弃的 `google.generativeai` 包，每次运行都打 `FutureWarning`，官方已停止维护，应迁移到 `google.genai`。
- `automation/` 下堆了一批日志和备份文件（`*.log.*`、`history.json.bak-*`、`cookies.txt.bak-*`），未纳入 git 忽略规则，`git status` 一直是脏的。

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
