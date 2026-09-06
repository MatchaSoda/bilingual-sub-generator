# 运维手册 (RUNBOOK)

> 面向「服务出问题了怎么办」。架构说明看 [`document.md`](../document.md)，当前状态看 [`PROGRESS.md`](./PROGRESS.md)。

---

## 1. 服务概览

| 项 | 值 |
|---|---|
| systemd 单元 | `bili-mover.service`（`/etc/systemd/system/`，仓库内 `automation/bili-mover.service` 只是模板） |
| 进程 | `venv/bin/python3 mover.py`，工作目录 `automation/` |
| 循环周期 | `config.json` 的 `check_interval_seconds`（当前 1800s） |
| 每轮处理上限 | `max_uploads_per_cycle`（当前 3） |
| 日志 | `journalctl -u bili-mover` |

### 常用操作

```bash
systemctl status bili-mover                    # 只读，无需 sudo
journalctl -u bili-mover -n 100 --no-pager
journalctl -u bili-mover -f | grep -E "should process|投稿成功|投稿失败|CLI 失败"

# 需要密码，AI 不能直接跑，请用户在会话里执行：
! sudo systemctl restart bili-mover
```

### 什么时候需要重启

| 改动 | 需要重启？ |
|---|---|
| `automation/config.json` 的 `upload` 段 | ❌ **投稿时实时读盘**，改完立刻生效 |
| `automation/config.json` 其余部分 | ❌ 每轮循环开头读一次，**改动要下一轮才生效**（一轮最长 30 分钟） |
| `backend/**`（含 `media_downloader.py`） | ❌ 每个视频新起 `entry_cli.py` 子进程 |
| `cookies.txt` | ❌ 每次下载重新复制 |
| `automation/mover.py` | ✅ 代码常驻内存 |
| `automation/history.json` 手工改动 | ✅ 且有顺序要求，见 §3 |

---

## 2. 凭据与外部依赖

| 凭据 | 位置 | 用途 | 失效表现 |
|---|---|---|---|
| YouTube cookies | `cookies.txt`（仓库根，git 忽略） | yt-dlp 下载鉴权 | `Sign in to confirm you're not a bot` |
| B 站会话 | `automation/cookies.json` | biliup 投稿 | 投稿失败，日志提示重新 login |
| Gemini API Keys | `.env` 的 `GOOGLE_API_KEYS` | 翻译 / LLM 分段 | 翻译阶段报错 |

### 更新 YouTube cookies

导出要求 —— **必须是完整导出**，半残的 cookie 比没有更糟（见 §5.2）：

1. 浏览器开**无痕窗口** → 登录 YouTube
2. 用 cookie 导出扩展导出 **全部** cookie（Netscape 格式）
3. **立刻关掉无痕窗口**，不要再访问 YouTube（否则浏览器会轮换 token，把导出的那份作废）
4. 覆盖到仓库根 `cookies.txt`，去掉 Windows CRLF，权限设 600

```bash
cp cookies.txt cookies.txt.bak-$(date +%Y%m%d)
sed 's/\r$//' /mnt/c/Users/<user>/Downloads/cookies.txt > cookies.txt
chmod 600 cookies.txt
```

**校验是否合格**：

```bash
# .youtube.com 上必须有 LOGIN_INFO；一方认证组在 .google.com 上是正常的
grep -P '\tLOGIN_INFO\t' cookies.txt && echo "✅ 已登录态"
awk '!/^#/ && NF>=7 && $1 ~ /youtube\.com/ {print $6}' cookies.txt | sort -u
```

判定标准不是「有没有 SID/HSID」，而是 **yt-dlp 是否把它当登录态**。最终以 §6 的实测脚本为准。

### 更新 B 站会话

```bash
cd automation && ../venv/bin/biliup login    # 交互式，生成 cookies.json
```

---

## 3. `history.json` 语义（改它之前必读）

`automation/history.json` 是一个已处理视频 id 的 **JSON 数组**（当前约 6500 条）。一条 id 进了 history 就永远不会再被处理。

写入的地方：命中排除词、关键字不匹配、**投稿成功**。注意 —— **处理失败不写入**，所以失败的视频下一轮会自动重试，不需要人工干预。

### 致命陷阱：内存集合会覆盖磁盘

`mover.py` 的 `save_history()` 在写盘前会**先把磁盘内容并集进内存集合**（为了兼容 `backfill.py` 并发追加）。后果是：

> 只要 mover 进程还活着，它内存里的那份 history 就是权威。你在磁盘上删掉的 id，会在它下一次写盘时被原样并回来。

**曾经踩过**：2026-08-29 直接改磁盘后等着重启，结果运行中的进程在中途醒来写了一次盘，29 条删除全部复活，白做一轮。

### 正确的删除姿势

必须是 **停服务 → 改文件 → 起服务** 三步连成一个原子操作，中间不能有进程持有旧内存集合：

```bash
! sudo systemctl stop bili-mover && python3 scripts/prune_history.py <id...> && sudo systemctl start bili-mover
```

如果做不到停服务，退而求其次：确认进程正在休眠（日志最后一行是 `😴 等待 1800s`），算出下次醒来时间，在那之前完成删除 + 重启。删完务必核对 `已加载历史记录: N 条` 这行日志确认新进程读到的是清理后的数量。

---

## 4. 过滤规则语义

`automation/config.json` 每个频道：

- `keyword` —— **标题和描述都查**。标题没命中才去拉描述（每条约 10 秒，且是最容易触发 YouTube 风控的请求，所以放在最后）。
- `exclude` —— **只对标题生效**，命中即跳过并写入 history。

### 为什么 exclude 不能作用于描述

排除词一旦和 keyword 有**子串重叠**，就会形成死锁。真实案例：

```
keyword = "#newsevery"
exclude 含 "every"
```

判定顺序是「先查排除词、再查关键字」，而 `#newsevery` 本身就包含 `every`。于是**每一个真正该被处理的视频，都会先命中排除词被丢掉**，匹配率恒为 0。服务看起来一切正常（每轮扫 300 个视频、无报错），只是再也不产出——静默失效，最难发现的那种。

2026-08-27 到 08-29 停产两天就是这个原因。修复方式是把描述层的排除词检查整个删掉。

### `exclude` 里的 `every` 是有意保留的，不要删

现在 `exclude` 只作用于标题，所以 `every` 不再和 keyword 死锁，但它**仍在干活**：
日テレ的『every.特集』（美食 / 生活 / 街录类专题）描述里同样带 `#newsevery`，
靠描述无法和普通新闻区分，**标题里的 `every.特集` 是唯一的区分信号**。
用户明确只要普通新闻、不要这类专题，所以这条排除词是过滤器而非误配。

09-07 有人（AI）又把它当成 08-29 那个 bug 的残留查了一遍，实测拉了
`EwAI8HI54Ks` / `DfjuPKvutoc` 的描述确认确实含 `#newsevery`，才发现是有意为之。
**在动这个词之前先问用户要不要『every.特集』**，不要凭「语义冲突」自行判断。

### 排除词是裸子串匹配

不做词边界检查，所以 `死` 会命中「起死回生」、`害` 会命中「利害」。
实测误伤率不高（09-07 复查：9 条 `死` 命中里 1 条是成语 `wByz7sJm-Rk`），现状接受。

---

## 5. 故障处置

### 5.1 服务在跑但两天没有新投稿

不是崩溃，多半是过滤规则静默失效。按顺序排查：

```bash
# 1. 服务活着吗
systemctl status bili-mover
# 2. 有没有视频进入处理阶段
journalctl -u bili-mover --since "2 days ago" | grep -c "should process"
# 3. 如果是 0，看跳过原因的分布
journalctl -u bili-mover --since "2 days ago" | grep -oP '跳过 \(\K[^)]+' | sort | uniq -c | sort -rn
```

如果跳过原因集中在某一个排除词上，回去看 §4。

### 5.2 `Sign in to confirm you're not a bot`

**先确认是不是间歇性的**（同一个视频反复测，见 §6）。成功率 30~50% 说明是 cookie 问题，不是代码问题。

根因通常是 cookie 不完整。但要理解真正的机制 —— 不是「缺了几个 cookie 所以鉴权弱」，而是：

> cookie 残缺到让 yt-dlp **误判为未登录**，于是它放行了 `tv_simply` 客户端；而 `tv_simply` 根本不带 cookie 裸奔，全靠运气过风控，所以时好时坏。

按 §2 重新导出完整 cookie 即可。**但注意换完会引出 5.3 的问题。**

### 5.3 `Requested format is not available` / 画质悄悄掉到 360p

这两个症状都来自 yt-dlp 的 `player_client` 选择（`backend/engines/media_downloader.py`）。三条互相牵制的约束：

| 客户端 | 支持 cookies | 能拿 GVS PO Token | 结果 |
|---|---|---|---|
| `tv_simply` | ❌ | ✅ | 一旦 cookie 是真登录态，yt-dlp 打印 `Skipping client "tv_simply" since it does not support cookies`，只剩 storyboard 图片格式 |
| `web` | ✅ | ❌ | DASH 全被丢弃，静默退回 360p 的 itag 18 |
| **`mweb`** | ✅ | ✅ | **当前使用**，完整 DASH，1080p |

另外一条独立的坑：

> **千万不要加 `nocheckcertificate: True`。** `yt-dlp-getpot-wpc` 插件没有声明支持 `DISABLE_TLS_VERIFICATION`，一旦开启该选项，PO Token 框架会**静默跳过**这个 provider，于是拿不到 GVS PO Token，所有 DASH 格式被丢弃，或退回 `android_vr` 的无 token 直链（YouTube 只放行前 ~10MB 就 403）。全程零报错，唯一症状是画质掉到 360p。

PO Token 由 `yt-dlp-getpot-wpc` 插件提供，它会**真的拉起一个无头 Chrome**（日志里的 `Launching youtube.com in browser` / `successfully removed temp profile /tmp/uc_*`）。这是正常现象，不是异常。

### 5.4 B 站投稿失败 `client error (Connect)`

**根因：B 站部分上传节点的 TLS 证书过期了。** 不是网络抖动，也不是代理问题。

`client error (Connect)` 是表层错误，真正的原因埋在 biliup 报错的最内层：

```
├─▶ error sending request for url (https://upos-cs-upcdnbldsa.bilivideo.com/...)
├─▶ client error (Connect)
╰─▶ invalid peer certificate: certificate expired: verification time 1788010016 (UNIX),
    but certificate is not valid after 1783746060 (4263956 seconds ago)
```

**看报错一定要翻到最后一行**，前面几层都不说明问题。

2026-08-29 实测，`bldsa` 这条线解析出 14 个 IP，**其中 7 个的证书 2026-07-11 就过期了**：

| 线路 | 节点数 | 证书有效 | 证书过期 |
|---|---|---|---|
| `tx` | 6 | 6 | 0 |
| `bda2` | 1 | 1 | 0 |
| `bldsa` | 14 | 7 | **7** |

于是每次上传是在 14 个节点里轮询，**50% 概率撞上坏证书**。biliup 内部那 5 次 reqwest 重试解决不了——它在同一条线上退避，握手照样失败。换个新进程会重新解析，所以进程级重试大约一半能救回来；实测有一次连挂两次、第 3 次才过。

#### 处置：钉一条证书干净的线

`automation/config.json` 已经钉到 `tx`。**`upload` 段是在投稿那一刻实时读盘的**，改完立刻
生效、不用重启也不用等下一轮——这正是为了救火：其余配置项在循环开头读一次，改了要等下
一轮，而一轮最长 30 分钟，够失败好几个视频。

```json
"upload": { "line": "tx", "retries": 3, "retry_delay_seconds": 60 }
```

进程级重试保留作为兜底，但正常情况不该再被触发。

#### 怎么复查线路的证书健康度

B 站什么时候续证书不由我们决定，`tx` 也可能哪天轮到它过期。投稿又开始失败时，先跑这个：

```bash
now=$(date +%s)
for line in tx bda2 bldsa; do
  H="upos-cs-upcdn$line.bilivideo.com"; good=0; bad=0
  for ip in $(getent ahostsv4 $H | awk '{print $1}' | sort -u); do
    end=$(timeout 8 openssl s_client -connect "$ip:443" -servername "$H" </dev/null 2>/dev/null \
          | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -z "$end" ] && continue
    [ "$(date -d "$end" +%s)" -lt "$now" ] && bad=$((bad+1)) || good=$((good+1))
  done
  printf '%-6s 有效 %d 过期 %d\n' "$line" "$good" "$bad"
done
```

挑一条 `过期 0` 且节点数多的换上去即可。可选线路：`bldsa` `cnbldsa` `andsa` `atdsa` `bda2`
`cnbd` `anbd` `atbd` `tx` `cntx` `antx` `attx` `bda` `txa` `alia`。

**注意**：`curl https://upos-cs-upcdnXXX.bilivideo.com/OK` 这种探测**不可靠**——它每次只碰到
一个 IP，好坏全看运气，测出来的成功率是随机的。必须逐 IP 查证书。

#### 一个错误的中间结论

最初把这个归因为「上传 CDN 连通性波动 + biliup 选中了探测超时的线路」。选线日志里那个
`cost: 340282366920938463463374607431768211455`（`u128::MAX`，探测超时的哨兵值）确实可疑，
但它是伴随现象不是原因——真正的原因一直在报错最后一行写着，只是当时没往下翻。

**注意**：投稿失败不会写入 history，视频下一轮会自动重排，所以不会丢。

### 5.5 Gemini 返回 400 `User location is not supported for the API use`

不是 key、配额或代码问题，是**出口 IP 被拒**。判断要点：如果是间歇性的（时好时坏），
说明请求走了不止一条出口路径。

实测过的三条出口（2026-08-29）：

| 出口 | Gemini |
|---|---|
| WARP 的 IPv4 | ❌ 0/16 全拒 |
| WARP 的 IPv6 | ✅ 可用 |
| VPS 原生 IPv4 `45.192.198.87` (JP) | ✅ 17/17 |

也就是说 **WARP 反而是问题所在**，VPS 自己的 IPv4 出口 Gemini 完全接受。

**注意这个结论是会翻转的。** 代理最初挂 WARP 正是因为 VPS 原生 IP 被 Google 封过；
现在反了过来，因为 Gemini 是滥用重灾区、WARP 出口段被封得更狠。哪条干净取决于当时的
封禁态势，不要把任何一条当成永久答案。

所以代码侧不押注单条路径，而是让**重试在两条路径间轮换**
（`backend/utils/gemini_transport.py`）：

| attempt | route | 说明 |
|---|---|---|
| 0, 2, 4 | `direct-v4` | 代理换成 `socks5://` 且本地解析 DNS + 钉死 IPv4。服务端只收到 IP 字面量，匹配不上 `geosite:google`，落到直连出站 |
| 1, 3, 5 | `default` | 保持原有代理环境变量，走服务端正常域名分流（当前挂 WARP） |

任何一条还活着流水线就能跑；某条被封了下一次尝试自动换另一条，**不需要改代码**。
封禁态势长期变化后想调整优先级，改 `gemini_transport.py` 的 `ROUTES` 顺序即可。

失败日志会带上当时用的路径，便于判断是哪条挂了：

```
⚠️ Attempt 1 failed (route=direct-v4): ...
```

**决定性的是本地解析，不是 IP 版本**——实测 `socks5` 本地解析不加 v4 限制也是 6/6，而
`socks5h`（服务端解析）加了 v4 限制仍然只有 4/6，因为客户端的限制根本没被用上：

```
socks5  本地解析 + 强制v4     6/6
socks5  本地解析 不限制        6/6
socks5h 服务端解析 + 强制v4    4/6   ← 客户端限制无效
http    (原行为)              2/6
```

钉死 IPv4 只是为了不依赖本地解析器恰好把 A 记录排在前面。

想完全关掉绕行（比如服务端已修好分流）：设 `GEMINI_PROXY=""`，此时全部尝试走 `default`。
想换端口：默认从 `HTTPS_PROXY` 换 scheme 得到，跟着一起变，不用改代码。

**服务端的根治办法**（可选）：在 3x-ui 里加一条优先级高于 `geosite:google` 的规则，把
`domain:googleapis.com` 指向 direct 出站，并设 `domainStrategy: UseIPv4`。这样浏览器等
其他客户端也一并受益。注意别把整个 `geosite:google` 从 WARP 摘掉——YouTube 那边还要用。

#### 一个踩过的坑：别拿响应时间推断网络路径

排查时我们看到「成功的请求平均 2067ms、被拒的平均 901ms」，据此推断是两条不同路径。
**这个推理是错的**：400 是 Google 直接拒绝、根本不做模型推理，所以天然就快；200 要真的
生成内容，慢是推理耗时。LLM 接口的延迟差主要来自推理而非网络跳数，不能当路径指纹用。

要定位路径，用出口身份而不是延迟：

```bash
# 各模式的出口 IP（socks5=本地解析, socks5h=服务端解析）
curl -s -x socks5h://127.0.0.1:10808 https://www.cloudflare.com/cdn-cgi/trace | grep -E '^(ip|loc|warp)='
curl -s -x socks5://127.0.0.1:10808 --ipv4 https://www.cloudflare.com/cdn-cgi/trace | grep -E '^(ip|loc|warp)='
# 查出口归属
curl -s https://rdap.arin.net/registry/ip/<IP> | python3 -m json.tool | head -20
```

注意这个出口身份是对 `cloudflare.com` 测的。如果分流规则按域名走，它反映不了 Gemini 那条路；
要看 Gemini 的出口，得临时把一个会回显来源 IP 的域名加进同一条规则。

---

---

## 6. 验证脚本

**改完 yt-dlp 相关配置后必须实测**，因为同样的配置在不同时间成功率可能完全不同。单次成功不能说明问题，要连测 5 次以上看成功率。

```bash
cd backend && cat > /tmp/probe.py <<'PY'
import sys, os, shutil, tempfile, yt_dlp
sys.path.insert(0, os.path.dirname(os.path.abspath('.')) + '/backend')
from config.settings import HTTP_PROXY, YT_DLP_COOKIES
vid = sys.argv[1]
fd, tmp = tempfile.mkstemp(suffix=".txt"); os.close(fd)
shutil.copyfile(YT_DLP_COOKIES, tmp)          # 永远用副本，别让 yt-dlp 写回主文件
cfg = {'format':'bestvideo+bestaudio/best','proxy':HTTP_PROXY,'socket_timeout':30,
       'extractor_args':{'youtube':{'player_client':['mweb']}},
       'skip_download':True,'quiet':True,'no_warnings':True,'cookiefile':tmp}
try:
    with yt_dlp.YoutubeDL(cfg) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    rf = info.get('requested_formats') or [info]
    print("OK  " + " + ".join(f"{f.get('format_id')}({f.get('height') or 'audio'})" for f in rf))
except Exception as e:
    print("BOT" if "not a bot" in str(e) else f"ERR {str(e)[:80]}")
finally: os.unlink(tmp)
PY
for i in 1 2 3 4 5; do ../venv/bin/python3 /tmp/probe.py <video_id>; done
```

期望输出：`OK  399(1080) + 251(audio)`，5/5 全过。

**注意**：任何直接调 yt-dlp 的脚本都必须先把 `cookies.txt` 复制到临时文件再用。yt-dlp 会把响应的 `Set-Cookie` 写回 cookiefile，YouTube 风控时返回的是匿名 Set-Cookie，会一点点冲掉主文件里的认证 token。`mover.py:make_cookies_copy()` 和 `media_downloader.py` 都已经这么做了。

---

## 7. 补投单个视频

```bash
cd automation
../venv/bin/python3 backfill.py "<youtube_url>"                # 复用 config.json 第 0 个频道的分区/标签
../venv/bin/python3 backfill.py "<url>" --tid 21 --tags a,b    # 手动覆盖
../venv/bin/python3 backfill.py "<url>" --no-history           # 不写 history
```

它直接 import `mover.py` 的 `load_config` / `process_and_upload`，所以处理参数和自动搬运完全一致，不会出现两套逻辑漂移。写 history 时用的是同一个带文件锁的 `save_history`，与常驻服务并发安全。

---

## 8. 诊断「产出为零 / 最近没更新」

这个症状出现过三次，**三次都不是服务挂了**（两次过滤规则、一次确实没有匹配的视频）。
所以顺序是先量化判定分布，再怀疑故障——反过来会浪费大量时间在健康的组件上。

### 第一步：服务活着吗

```bash
systemctl status bili-mover --no-pager | head -5
```

看 `Active: active (running)` 和 `since`。如果 `since` 很近说明刚重启过（可能崩过），
否则进程本身没问题，直接进第二步。

### 第二步：数判定分布

```bash
journalctl -u bili-mover --since "2 days ago" --no-pager > /tmp/mv.log

grep -c "should process"    /tmp/mv.log   # 命中并进入流水线
grep -c "关键字不匹配"       /tmp/mv.log   # 拉到描述但没有 keyword
grep -c "命中排除词"         /tmp/mv.log   # 被 exclude 干掉
grep -c "拉取描述失败"       /tmp/mv.log   # ⚠️ 见下面「静默陷阱」
grep -oE "命中排除词 '[^']*'" /tmp/mv.log | sort | uniq -c | sort -rn
```

怎么读：

| 现象 | 含义 |
|---|---|
| 三类计数**全为 0**，但有「发现 300 个视频」 | 窗口内全部已在 history —— 频道没发新视频，或 `playlist_items` 窗口太小被旧视频占满 |
| `关键字不匹配` 占绝大多数 | 正常。日テレ每天大量普通新闻不带 `#newsevery` |
| 某个排除词命中数异常高 | 看 §4，确认是过滤器还是误配。**别急着删，先问用户** |
| `拉取描述失败` > 0 | 真故障，见下 |

### 第三步：静默陷阱 —— 描述拉取失败会被当成「不匹配」

`mover.py` 里 `fetch_video_description()` 失败时返回空字符串，调用方拿到 `""` 后
`keyword in ""` 为 False，于是走「关键字不匹配」分支，**把视频永久写入 history**。
也就是说 YouTube 风控导致的拉描述失败，表现和「这个视频确实不匹配」完全一样，
只在日志里多一行 `⚠️ 拉取描述失败`。

所以 `拉取描述失败` 的计数必须单独看。如果它非零，那些视频是被误丢的，
要按 §3 的姿势从 history 里捞回来，并检查 cookies（§2）。

### 第四步：确认某条被跳过的视频到底该不该跳

不要靠读标题推理，直接拉描述实测：

```bash
./venv/bin/yt-dlp --cookies cookies.txt --skip-download --ignore-no-formats-error \
  --print "%(description)s" "https://www.youtube.com/watch?v=<id>" \
  | grep -oiE "#newsevery"
```

有输出 = 描述确实命中 keyword，那它是被排除词拦下的；无输出 = 本来就不该处理。

