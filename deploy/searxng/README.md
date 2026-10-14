# Sariana 本机免 Key 搜索

应用默认免 Key 网页搜索无需 Docker。本目录仅供选择自己部署 SearXNG 的高级用户使用，不随应用准备服务，也不是普通安装用户的必要步骤。

手动部署后在应用选择「已有 SearXNG 服务」并填写端口 8080 地址，应用只连接接口，不管理容器。

这套配置在 Windows Docker Desktop 的 Linux 容器中运行 SearXNG，与已启动的 Ollama Qwen 搭配。搜索接口只映射本机 `127.0.0.1:8080`，启用 HTML/JSON，选用 Bing、DuckDuckGo 和 Wikipedia。无需搜索 API Key，不部署 Valkey/Redis 或反向代理。搜索仍依赖联网和上游引擎可达性。

配置依据 [官方容器部署](https://docs.searxng.org/admin/installation-docker.html)、[设置合并规则](https://docs.searxng.org/admin/settings/settings.html) 和 [Search API](https://docs.searxng.org/dev/search_api.html)。JSON 必须在 `search.formats` 中开启，否则请求会返回 403。本机私有实例关闭 limiter；官方 limiter 需要 Valkey，见 [server 设置](https://docs.searxng.org/admin/settings/settings_server.html)。

## 启动

先打开 Docker Desktop，确认 Linux 容器引擎就绪。在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\searxng\start.ps1
```

脚本首次生成随机服务端 secret，并写到被 Git 忽略的 `.local/searxng/config/settings.yml`；它是服务内部密钥，不是需申请的 API Key，不会打印。重复运行保留已有配置和缓存。随后校验 Compose、启动容器、等待网页就绪，并检查 JSON 搜索。首次启动会下载官方镜像；只运行 `-PrepareOnly` 可准备和校验配置而不启动容器。

浏览器打开 `http://127.0.0.1:8080` 搜索。PowerShell 可查看接口结果：

```powershell
$result = Invoke-RestMethod 'http://127.0.0.1:8080/search?q=SearXNG&format=json'
$result.results | Select-Object -First 5 title, url
```

## 桌宠配置

桌宠右键 → 本地二创工坊 → 智能体 · 联网搜索设置：

| 配置项 | 填写 |
| --- | --- |
| 开启桌宠智能体 | 勾选 |
| 模型服务 | 本地模型 · Ollama / LM Studio |
| Base URL | `http://127.0.0.1:11434/v1` |
| 模型名称 | `qwen3:1.7b` |
| 模型 API Key | 留空 |
| 搜索服务 | SearXNG · 自建搜索 |
| SearXNG 地址 | `http://127.0.0.1:8080` |
| 搜索 API Key | 留空 |

保存后，从桌宠搜索按钮输入话题。需要验证真实 SearXNG + Qwen 链路时，在安装了项目依赖的 Python 环境执行：

```powershell
.venv\Scripts\python.exe -B scripts/verify_companion_agent_local.py --search-url http://127.0.0.1:8080 --topic '介绍 SearXNG 的主要用途'
```

## 管理

以下命令均从项目根目录执行：

```powershell
# 查看状态和日志
docker compose -f deploy/searxng/compose.yaml ps
docker compose -f deploy/searxng/compose.yaml logs --tail 50
# 停止，保留配置和缓存
docker compose -f deploy/searxng/compose.yaml stop
# 再次启动
docker compose -f deploy/searxng/compose.yaml up -d
# 修改 .local/searxng/config/settings.yml 后应用
docker compose -f deploy/searxng/compose.yaml restart
# 显式更新镜像，再重新创建服务
docker compose -f deploy/searxng/compose.yaml pull
docker compose -f deploy/searxng/compose.yaml up -d
```

`latest` 只在首次拉取或显式更新时获取当前镜像，服务重启不会自动下载新版；需要可重复部署时，可将 compose 的 image 固定为已验证镜像的 digest。

端口 8080 被占用时，改 compose 的宿主端口和对应 Base URL，再同步修改脚本探测地址及桌宠配置。JSON 返回空列表通常需要检查上游引擎网络、验证码或限流；本机服务运行不代表所有搜索引擎都可用。可在生成的 settings.yml 调整引擎列表，模板不会覆盖已有个人配置。
