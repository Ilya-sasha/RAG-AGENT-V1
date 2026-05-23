# 运维手册

## 文档目标

本文档对应当前 `agent_runtime.main:app` 的 v1 本地运行与交付边界，重点覆盖：

- 如何启动、停止、检查服务
- 如何核对模型、数据库、知识库配置
- 如何排查 `/assistant`、`/admin`、workflow、RAG 相关常见故障
- 当前版本的已知限制和已验证结果

本文档不扩展为完整生产平台手册；高可用部署、tracing、外部向量库、完整 RBAC 等能力属于后续阶段。

## 当前运行拓扑

当前 v1 默认是单服务拓扑：

- 一个 FastAPI 进程
- 一个 SQLite 数据库
- 一个本地 embedding 模型目录
- 一个 OpenAI-compatible 模型接入层
- 本地静态页面 `/assistant` 与 `/admin`

这意味着当前版本更适合单机开发、验收、PoC 和第一阶段闭环交付，而不是多实例生产集群。

## 标准启动

### 推荐路径

```powershell
cd C:\Users\Ilya\PycharmProjects\AGENT
conda activate agent_rag
$env:AGENT_RUNTIME_MODEL_API_KEY="your-api-key"
.\scripts\start-local.ps1
```

### 推荐隔离测试路径

如果你要做一轮干净排查，优先隔离数据库文件：

```powershell
.\scripts\start-local.ps1 -Port 8010 -DbUrl "sqlite+aiosqlite:///./runtime-clean.db"
```

### 当前脚本默认值

- Python：`C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe`
- Host：`127.0.0.1`
- Port：`8000`
- DB：`sqlite+aiosqlite:///./runtime.db`
- Base URL：`https://api.deepseek.com`
- Model：`deepseek-v4-flash`
- Timeout：`60`
- Embedding root：
  `C:\models\embedding_models\iic\nlp_gte_sentence-embedding_chinese-base`

### 启动成功标志

控制台出现以下日志即表示服务已经拉起：

```text
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

## 停止服务

- 前台启动：直接 `Ctrl+C`
- 如果端口残留占用，先查监听进程，再结束对应进程

PowerShell 示例：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

## 基础健康检查

### HTTP 健康检查

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok"}
```

### 指标检查

```powershell
Invoke-WebRequest http://127.0.0.1:8000/metrics
```

期望返回 Prometheus 文本指标。

### 页面入口检查

- `/assistant`
- `/admin`
- `/docs`
- `/redoc`

## 知识库运维

### 注册知识库

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
```

### 导入知识库

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "$base/internal/knowledge-bases/$kbId/ingest?tenant_id=$tenant"
```

### 查看状态

```powershell
Invoke-RestMethod `
  -Uri "$base/internal/knowledge-bases/$kbId/status?tenant_id=$tenant"
```

成功时关注这几个字段：

- `status`
- `document_count`
- `chunk_count`
- `last_error`

### 重建索引

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "$base/internal/knowledge-bases/$kbId/reindex?tenant_id=$tenant"
```

## 助手工作台运维

`/assistant` 是用户侧入口，主要用于：

- `chat` 会话
- `task` 会话
- 查看会话消息
- 查看运行活动
- 处理审批
- 绑定当前 tenant 下的知识库

常见检查点：

- 当前 tenant 是否正确
- 当前 tenant 下是否真的有知识库
- 已选知识库是否导入成功
- 模型 API Key 是否有效

## 管理控制台运维

`/admin` 是运维侧入口，主要用于：

- 服务总览
- `/health` 与 `/metrics` 快速查看
- workflow 列表和详情
- workflow 启动
- workflow run 列表与详情
- 知识库注册、ingest、reindex
- 审批查询与处理
- 原始 run 查询与事件回放

## Workflow 运维要点

### 发布前检查

workflow 发布前，必须保证：

- 请求体中包含 `tenant_id`
- `knowledge.default_kb_ids` 中的每个知识库都已在当前 tenant 下存在

否则常见报错为：

- `tenant_id is required`
- `unknown knowledge base: <kb_id>`

### 启动前检查

workflow 启动前，必须保证：

- 目标版本已发布
- 关联知识库状态为 `success`

否则常见报错为：

- `workflow template version is not published`
- `knowledge base is not ready for retrieval`

### 当前已修复的 RAG 链路问题

当前版本已经验证通过以下修复：

- workflow 默认 `default_kb_ids` 会自动注入到 supervisor 的初始观察中
- 显式传入 `["all"]`、`["default"]`、`["*"]` 或空白 `kb_ids` 时，系统会回退到默认知识库绑定

因此，workflow + RAG 的默认闭环已经可以直接工作。

## 常见故障排查

### 1. 端口被占用

典型报错：

```text
error while attempting to bind on address ('127.0.0.1', 8000)
```

排查步骤：

1. 查看端口监听者
2. 结束旧进程，或换端口重启

示例：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
.\scripts\start-local.ps1 -Port 8008
```

### 2. 服务启动后立刻退出

优先排查：

- 是否误用了已损坏或带脏数据的 SQLite 文件
- 是否在旧 tenant / 旧知识库状态上继续测试
- 模型 API Key 是否有效

建议优先隔离一轮新数据库：

```powershell
.\scripts\start-local.ps1 -Port 8010 -DbUrl "sqlite+aiosqlite:///./runtime-clean.db"
```

### 3. `/assistant` 回答 `Authentication Fails`

优先检查：

- `AGENT_RUNTIME_MODEL_API_KEY`
- `AGENT_RUNTIME_MODEL_BASE_URL`
- `AGENT_RUNTIME_MODEL_NAME`

当前默认应为：

- `https://api.deepseek.com`
- `deepseek-v4-flash`

建议先单独用 PowerShell 对 DeepSeek 做一次鉴权调用，确认 key 本身可用，再回到项目侧排查。

### 4. `Your api key: ****test is invalid`

这是模型侧返回的鉴权失败，不是前端问题。通常是：

- 环境变量里仍然残留旧 key
- 当前终端没有继承你以为已经设置好的 key
- 启动脚本前后使用了不同 shell / 不同会话

### 5. 新 tenant 下没有知识库

这是正常现象。知识库是按 tenant 隔离的。

处理方式：

1. 在新 tenant 下重新注册知识库
2. 执行 ingest
3. 在 `/assistant` 中切换到同一个 tenant 并重新选择知识库

### 6. 知识库状态 `failed`

优先检查：

- `root_path` 是否真实存在
- 目录下是否有可解析文档
- `AGENT_RUNTIME_EMBEDDING_MODEL_ROOT` 是否正确
- embedding 模型目录是否完整

### 7. `knowledge base not ready for retrieval`

表示知识库还没准备好用于检索。通常是：

- 还没 ingest
- ingest 失败
- 仍在 `pending` / `running`

先看状态接口：

```powershell
Invoke-RestMethod `
  -Uri "$base/internal/knowledge-bases/$kbId/status?tenant_id=$tenant"
```

### 8. workflow 查询返回缺少 `tenant_id`

这类接口经常要求 query string 传入 `tenant_id`，例如：

- `GET /v1/workflows/{workflow_id}?tenant_id=<tenant>`
- `GET /v1/workflow-runs/{run_id}?tenant_id=<tenant>`

不要省略这个参数。

### 9. `invalid rag_search arguments`

当前版本里，这类错误通常来自：

- 当前 tenant 没有默认知识库绑定
- workflow 定义里缺失有效 `default_kb_ids`
- 模型传入了错误或占位的 `kb_ids`

目前默认知识库自动注入与占位值回退已修复。如果仍出现该错误，应优先检查 workflow 定义和当前 tenant 下的知识库实际状态。

## 回归与验收基线

当前记录在案的结果：

- 全量回归：
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
- 最近一次结果：
  `195 passed, 2 warnings in 111.50s`

当前 2 条 warning 为已知 `aiosqlite` 线程退出问题，已纳入延期计划，不阻塞 v1 使用与验收。

## 当前已知限制

- 单服务、单 SQLite
- 未接入 tracing
- 未完成完整认证和 RBAC
- DeepSeek 联调仍以人工验证为主，不写入自动化外网测试
- `aiosqlite` 线程 warning 仍待后续清理

## 相关文档

- [README](../README.md)
- [DeepSeek 与助手验证说明](assistant-deepseek-validation.md)
- [延期项路线图](deferred-roadmap.md)
