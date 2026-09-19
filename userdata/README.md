# userdata/ —— Docker 部署的全部用户数据

这个目录挂载进容器的 `/app/userdata`，里面的文件全部 git 忽略：

| 文件 | 内容 | 谁生成 |
|---|---|---|
| `.env` | Gemini key、代理、开关 | 向导（模板 `docker/env.example`） |
| `cookies.txt` | YouTube 登录 cookie（Netscape 格式） | 你从浏览器导出后放进来 |
| `cookies.json` | B 站登录信息 | 向导里 `biliup login` 扫码 |
| `config.json` | 要搬运的频道、过滤规则、流水线参数 | 向导（模板 `automation/config.json.example`） |
| `history.json` | 已处理过的视频 id | 运行时 |
| `data/` | 生成好的双语视频和封面 | 运行时 |
| `.setup-done` | 向导跑完的标记 | 向导 |

第一次用：`./docker-start.sh`，它会带你把这些填好。完整说明见 `docs/DOCKER.md`。
