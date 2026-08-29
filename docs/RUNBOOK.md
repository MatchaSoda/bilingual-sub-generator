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
| `automation/config.json` | ❌ 每轮循环重新读 |
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

日志形如：

```
error sending request for url (https://upos-cs-upcdnbldsa.bilivideo.com/...)
├─▶ client error (Connect)
```

**这是间歇性的，不是配置错误。** B 站上传 CDN 的连通性会波动——同一个主机同一分钟内多次测试可能全通、也可能全挂，和代理无关（B 站走直连）。

关键要看 biliup 的**选线日志**：

```
line.rs:99: ...upcdn=bda2&zone=cs: 1270      ← 探测到的耗时(ms)
line.rs:99: ...upcdn=tx&zone=cs: 433
line.rs:99: ...upcdn=estx&zone=cs: 1112
line.rs:99: ...upcdn=akbd&zone=cs: 1502
uploader.rs:402: Line { probe_url: "//upos-cs-upcdnbldsa.bilivideo.com/OK",
                        cost: 340282366920938463463374607431768211455 }   ← 选中的
```

那个天文数字是 `u128::MAX`，是 biliup 给**探测失败/超时**线路的哨兵值。上面 4 条线都探通了（`tx` 最快 433ms），它却选了一条没探通的 `bldsa`——然后 reqwest 在这条死线上退避重试 5 次，全部失败。

biliup 自身的重试只在**同一条线路**上打转，所以选错线时重试多少次都没用。**有效的做法是换个进程重来**——biliup 每次启动都会重新探测选线。

处置：

1. `upload_to_bilibili()` 已内置重试（默认 3 次、间隔 60s），每次都是全新的 biliup 进程，会重新选线。通常第二次就过了。
2. 如果某条线持续有问题，在 `automation/config.json` 里钉死一条已知良好的：

```json
"upload": { "line": "tx", "retries": 3, "retry_delay_seconds": 60 }
```

可选值：`bldsa` `cnbldsa` `andsa` `atdsa` `bda2` `cnbd` `anbd` `atbd` `tx` `cntx` `antx` `attx` `bda` `txa` `alia`。`line` 为 `null` 表示交给 biliup 自动选（默认）。

3. 手工探一遍当前哪条线通：

```bash
for h in bldsa tx bda2 estx; do
  ok=0; for i in 1 2 3; do
    c=$(timeout 8 curl -s -o /dev/null -w "%{http_code}" "https://upos-cs-upcdn$h.bilivideo.com/OK"); [ "$c" = 200 ] && ok=$((ok+1))
  done; printf '%-8s %s/3\n' "$h" "$ok"
done
```

**注意**：投稿失败不会写入 history，视频下一轮会自动重排，所以单次失败不需要人工干预。

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
