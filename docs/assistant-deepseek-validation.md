# Assistant DeepSeek 验证说明

## 文档目标

本文档记录当前项目第一阶段中，助手工作台、DeepSeek 兼容接口、知识库检索和 workflow + RAG 链路的人工验证方法与结论。

这里保留人工验证，而不是全部写成自动化外网测试，原因是：

- 外部模型调用依赖真实网络与真实密钥
- 当前项目的自动化回归更关注本地运行时正确性
- 外部提供方返回内容存在时效性和不稳定性

## 验证前提

### 运行环境

- 仓库：`C:\Users\Ilya\PycharmProjects\AGENT`
- Python 环境：`agent_rag`
- 模型接口：OpenAI-compatible
- 当前验证目标：DeepSeek

### 推荐启动命令

```powershell
cd C:\Users\Ilya\PycharmProjects\AGENT
conda activate agent_rag
$env:AGENT_RUNTIME_MODEL_API_KEY="your-api-key"
.\scripts\start-local.ps1 -Port 8010 -DbUrl "sqlite+aiosqlite:///./runtime-clean.db"
```

如果没有显式覆盖，脚本默认会使用：

- `AGENT_RUNTIME_MODEL_BASE_URL=https://api.deepseek.com`
- `AGENT_RUNTIME_MODEL_NAME=deepseek-v4-flash`
- `AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS=60`

## 启动前模型鉴权自检

在项目侧联调前，建议先直接对 DeepSeek 做一次最小鉴权：

```powershell
$headers = @{
  Authorization = "Bearer $env:AGENT_RUNTIME_MODEL_API_KEY"
  "Content-Type" = "application/json"
}

$body = @{
  model = "deepseek-v4-flash"
  messages = @(
    @{
      role = "user"
      content = "hello"
    }
  )
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.deepseek.com/chat/completions" `
  -Headers $headers `
  -Body $body
```

如果这一步失败，先不要排查项目代码，先修正模型鉴权。

## 知识库准备

### 1. 准备本地目录

示例目录：

```text
C:\Users\Ilya\PycharmProjects\AGENT\local_kb
```

其中至少放入一批可检索文档，例如 `incident triage` 相关说明。

### 2. 注册与导入

```powershell
$base = "http://127.0.0.1:8010"
$tenant = "tenant-debug3"
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

成功条件：

- `status = success`
- `document_count > 0`
- `chunk_count > 0`

## `/assistant` 人工验证

### 场景 1：页面可以正常打开

1. 打开 [http://127.0.0.1:8010/assistant](http://127.0.0.1:8010/assistant)
2. 确认页面渲染正常
3. 确认 tenant、会话列表、消息区、活动区都可见

成功标准：

- 页面无空白
- 浏览器控制台无明显前端错误
- 会话创建按钮与消息发送区可操作

### 场景 2：普通聊天链路可用

1. 创建一个 `chat` 会话
2. 发送一句简单消息，例如：`请介绍一下你自己`

成功标准：

- 返回 assistant 消息
- 会话活动区出现关联 run

### 场景 3：知识库问答链路可用

1. 使用与知识库相同的 `tenant_id`
2. 在知识库选择区选中刚才导入成功的知识库
3. 提问：`根据知识库回答 incident triage 的标准流程是什么？`

成功标准：

- 系统能够触发 `rag_search`
- 返回基于知识库内容的答案
- 不出现 `tool not allowed: rag_search`
- 不出现 `invalid rag_search arguments`

### 场景 4：知识库缺失答案时保持保守

提问：

```text
知识库里有没有关于数据库备份频率的明确规定？
```

成功标准：

- 助手明确说明当前知识库未检索到对应规定
- 不应无根据编造频率策略

## Workflow + RAG 人工验证

### 关键前提

- workflow 请求不能漏 `tenant_id`
- workflow 发布前，`knowledge.default_kb_ids` 必须都存在于当前 tenant 下
- workflow 启动前，目标知识库必须是 `success`

### 推荐验证路径

优先使用 `/v1/workflows` 这组接口。

#### 1. 创建 workflow

定义中至少包含：

- 一个会触发检索的任务目标
- `knowledge.default_kb_ids`

#### 2. 发布 workflow 版本

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri ($base + "/v1/workflows/" + $workflowId + "/versions/1/publish") `
  -ContentType "application/json" `
  -Body (@{
    tenant_id = $tenant
  } | ConvertTo-Json)
```

#### 3. 启动 workflow

```powershell
$launch = Invoke-RestMethod `
  -Method Post `
  -Uri ($base + "/v1/workflows/" + $workflowId + "/launch") `
  -ContentType "application/json" `
  -Body (@{
    tenant_id = $tenant
    version = 1
    input = @{
      query = "incident triage"
    }
    metadata = @{
      requested_by = "operator-a"
    }
  } | ConvertTo-Json -Depth 10)

$runId = $launch.run_id
```

#### 4. 轮询运行结果

```powershell
1..20 | ForEach-Object {
  $run = Invoke-RestMethod -Uri ($base + "/v1/runs/" + $runId)
  $run
  if ($run.status -in @("completed", "failed", "cancelled")) { break }
  Start-Sleep -Milliseconds 500
}
```

### 成功标准

- run 最终进入 `completed`
- 返回内容明确引用知识库中的 `incident triage` 流程
- 不再出现以下旧问题：
  - `invalid rag_search arguments`
  - `knowledge base not found or inaccessible: all`
  - `Field required: kb_ids`

## 当前人工验证结论

当前已经人工验证通过的闭环包括：

- DeepSeek 兼容接口真实鉴权可用
- `/assistant` 页面可正常打开
- `/assistant` 普通对话可用
- `/assistant` 知识库问答可用
- 知识库无答案时会保守回答
- workflow + 默认知识库绑定 + `rag_search` 可正常完成

其中，关于知识库问答已经明确验证过两类结果：

1. 询问 `incident triage` 标准流程时，能够从知识库中检索并返回流程内容。
2. 询问数据库备份频率时，能够明确表示“当前知识库未检索到相关规定”，而不是直接编造答案。

## 当前实现中的重要说明

### 1. assistant 与 workflow 都依赖 tenant 一致性

以下对象必须属于同一个 tenant：

- assistant 会话
- 选中的知识库
- workflow
- workflow 默认知识库绑定

### 2. workflow 的默认知识库注入已打通

当前实现里，workflow 启动时会把默认 `default_kb_ids` 注入到 supervisor 的初始观察中，因此模型即使没有主动补齐 `kb_ids`，也可以回退到 workflow 的默认知识库配置。

### 3. 占位型 `kb_ids` 会自动回退

如果模型传入：

- `all`
- `default`
- `*`
- 空字符串

系统会把它们视为占位值而不是有效知识库，并回退到默认知识库绑定。

## 回归基线

当前记录在案的回归结果：

```text
195 passed, 2 warnings in 111.50s
```

警告仍为已知 `aiosqlite` 线程退出问题，不阻塞当前验证结论。

## 相关文档

- [README](../README.md)
- [运维手册](operations-runbook.md)
- [延期项路线图](deferred-roadmap.md)
