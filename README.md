# Agent Runtime

这是当前项目的第一版可运行交付物：一个面向本地运行的工具型助手运行时。它已经具备真实模型接入、知识库检索、助手工作台、管理控制台、工作流与多 agent 运行的基础闭环，当前默认以 DeepSeek 兼容接口作为首个落地验证目标。

## 当前这版能做什么

- 通过 OpenAI-compatible 接口接入外部大模型，默认配置为 DeepSeek
- 提供用户侧助手工作台：`/assistant`
- 提供运维侧管理控制台：`/admin`
- 支持本地知识库注册、导入、切块、向量检索和 `rag_search`
- 支持 workflow 创建、发布、启动、运行状态查看和事件回放
- 支持多 tenant、审批流、运行轨迹和基础可观测性

## 当前不包含什么

- 还不是完整企业平台
- 还没有完整认证、RBAC 和长期记忆体系
- tracing 已列入后续计划，当前版本未接入
- 当前默认仍是单服务、单 SQLite、本地 embedding 模型路径

## 推荐启动方式

当前仓库默认运行环境是本机 Conda 环境 `agent_rag`。

在 PowerShell 中执行：

```powershell
cd C:\Users\Ilya\PycharmProjects\AGENT
conda activate agent_rag
$env:AGENT_RUNTIME_MODEL_API_KEY="your-api-key"
.\scripts\start-local.ps1
```

脚本会自动注入以下默认值：

- Python：`C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe`
- Host：`127.0.0.1`
- Port：`8000`
- DB：`sqlite+aiosqlite:///./runtime.db`
- Model base URL：`https://api.deepseek.com`
- Model name：`deepseek-v4-flash`
- Model timeout：`60`
- Embedding model root：
  `C:\models\embedding_models\iic\nlp_gte_sentence-embedding_chinese-base`

如果你想隔离一轮新测试，推荐显式换一个数据库文件：

```powershell
.\scripts\start-local.ps1 -Port 8010 -DbUrl "sqlite+aiosqlite:///./runtime-clean.db"
```

## 其他受支持的 v1 运行路径

### Fresh environment

除本机现成的 `agent_rag` 以外，v1 也支持从一个 `fresh environment` 启动。标准路径如下：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
$env:AGENT_RUNTIME_MODEL_API_KEY="your-api-key"
.\scripts\start-local.ps1
```

这条路径适合另一台机器或另一个开发者从零复现当前版本。无论走 `agent_rag` 还是 `fresh environment`，默认数据库仍是 `runtime.db`，健康检查入口仍是 `/health`。

### Docker Compose

当前仓库也保留了 `docker compose` 路径，用于验证容器化交付是否仍满足 v1 约束。标准命令：

```bash
docker compose up --build
```

这里的容器模式仍然是 `single-service topology`，不是多实例生产编排。它更适合作为 `production-oriented` 的交付检查入口，而不是完整 production deployment guidance。

`docker-compose.yml` 当前依赖以下变量：

- `HOST_PUBLISHED_PORT`
- `CONTAINER_AGENT_RUNTIME_HOST`
- `CONTAINER_AGENT_RUNTIME_PORT`
- `CONTAINER_AGENT_RUNTIME_DB_URL`
- `CONTAINER_AGENT_RUNTIME_EMBEDDING_MODEL_ROOT`

对应关系是：

- 容器内数据库默认落在 `/data/runtime.db`
- 宿主机模型目录通过 bind mount 挂载到 `/models/embedding_models`
- 模型目录挂载为 `read-only`

如果你需要走容器路径，可以先检查 [.env.example](.env.example) 中这些变量的默认值，再执行 `docker compose up --build`。

## 启动成功后的入口

- 助手工作台：[http://127.0.0.1:8000/assistant](http://127.0.0.1:8000/assistant)
- 管理控制台：[http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)
- 健康检查：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- 指标接口：[http://127.0.0.1:8000/metrics](http://127.0.0.1:8000/metrics)
- OpenAPI：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Redoc：[http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## 从 0 到在 `/assistant` 里问知识库

### 1. 准备知识库目录

把 `.md`、`.txt` 等文本文件放到一个本地目录，例如：

```text
C:\Users\Ilya\PycharmProjects\AGENT\local_kb
```

### 2. 注册并导入知识库

下面是一套可直接执行的 PowerShell 命令：

```powershell
$base = "http://127.0.0.1:8000"
$tenant = "tenant-a"
$kbId = "kb-ops"

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/internal/knowledge-bases" `
  -ContentType "application/json" `
  -Body (@{
    kb_id = $kbId
    tenant_id = $tenant
    name = "Ops KB"
    root_path = "C:\Users\Ilya\PycharmProjects\AGENT\local_kb"
    metadata = @{}
  } | ConvertTo-Json)

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/internal/knowledge-bases/$kbId/ingest?tenant_id=$tenant"

Invoke-RestMethod `
  -Uri "$base/internal/knowledge-bases/$kbId/status?tenant_id=$tenant"
```

成功时，最后一条返回里应看到：

- `status = success`
- `document_count > 0`
- `chunk_count > 0`

### 3. 在 `/assistant` 中提问

1. 打开 `/assistant`
2. 输入同一个 `tenant_id`
3. 创建 `chat` 会话
4. 在知识库选择区绑定刚才的知识库
5. 提问，例如：`根据知识库回答 incident triage 的标准流程是什么？`

如果知识库内容存在，助手会触发 `rag_search` 并基于检索结果回答；如果知识库没有答案，当前版本会倾向于明确说明“未检索到”，而不是直接编造。

## 工作流快速验证

如果你想验证 workflow 与默认知识库绑定链路，可以使用 `/v1/workflows`。发布前要注意两件事：

- `tenant_id` 不能漏
- workflow `knowledge.default_kb_ids` 中的知识库必须已经在当前 tenant 下注册成功

当前实现已经修复以下两类问题：

- workflow 启动时会把默认 `kb_ids` 自动注入到 supervisor 的初始观察中
- 如果模型传入占位值 `kb_ids`，例如 `all`、`default`、`*` 或空值，系统会回退到默认知识库绑定

## 当前验证结论

目前这版已经完成以下闭环验证：

- DeepSeek 兼容接口联调通过
- `/assistant` 普通对话可用
- `/assistant` 知识库问答可用
- workflow + `rag_search` 默认知识库回退可用
- “知识库中没有答案”时能给出保守回答

最近一次完整回归结果为：

```text
195 passed, 2 warnings in 111.50s
```

其中 2 条 warning 为已知的 `aiosqlite` 线程退出问题，已列入后续清理计划，不阻塞当前版本交付。

## 相关文档

- [运维手册](docs/operations-runbook.md)
- [DeepSeek 与助手验证说明](docs/assistant-deepseek-validation.md)
- [延期项路线图](docs/deferred-roadmap.md)
