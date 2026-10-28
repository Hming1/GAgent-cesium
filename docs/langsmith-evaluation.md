# LangSmith 真实对话追踪与人工评分

项目通过 LangChain/LangGraph 原生回调上传追踪。当前锁定的 LangSmith SDK 为
`0.4.29`，由 LangChain 依赖引入，无需为开启追踪升级智能体框架。
数据库的 `agent_runs` / `agent_run_events` 与 LangSmith 是两套独立记录；
开启数据库审计不代表开启 LangSmith，关闭数据库审计也不会关闭 LangSmith。

## 配置与启动

后端需要以下环境变量（仅配置在后端，不配置到 `NEXT_PUBLIC_*`）：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=<你的 LangSmith API key>
LANGSMITH_PROJECT=geoagent
# 仅当密钥需要明确选择工作区时设置：
# LANGSMITH_WORKSPACE_ID=<workspace UUID>
```

本地从 `backend/` 启动时，`core/config.py` 先加载该目录的 `.env.local`
（覆盖已有变量），再用 `load_dotenv()` 查找 `.env` 作为回退。
当前项目根目录 `.env` 已提供 LangSmith 配置；如需本地覆盖，使用
`backend/.env.local`。Docker 使用 compose 的 `env_file` 配置。
按 [CONTRIBUTING.md](../CONTRIBUTING.md) 启动/重启后端以应用代码或配置修改。

追踪会向配置的 LangSmith 服务发送消息、工具参数、工具结果和图状态。
`LANGSMITH_API_KEY` 与模型服务 API key 是不同凭据。

## 查看真实调用

1. 在 LangSmith 的 Tracing 中打开 `geoagent`。
2. 在应用中发送一轮聊天，结束后刷新项目；根调用名称为 `GeoAgent`。
3. 展开调用树，查看模型输入/输出、工具参数/结果、异常和耗时。
4. 在 Threads 中按 `thread_id` 查看多轮会话。

聊天和流式聊天共用 `services/agent_trace.py`，其 metadata 包括：

| 字段 | 用途 |
|---|---|
| `thread_id` | 优先使用 `conversation_id`；旧客户端缺省时回退有效 `session_id` |
| `conversation_id` | 对应数据库会话标识 |
| `application_session_id` | 浏览器 session，避免将不同对话合并成一个 LangSmith thread |
| `agent_run_id` | 对应数据库 `agent_runs.id`；数据库审计不可用时不填写 |
| `endpoint` | `/chat` 或 `/chat/stream` |
| `model_provider`、`model_name` | 便于筛选模型 |

这些 metadata 会继承到模型与工具子调用。LangSmith 自身的 run ID 与数据库
`agent_runs.id` 不是同一个值，应通过 `metadata.agent_run_id` 关联。
元数据只影响更新代码后产生的新追踪；历史追踪不会自动补齐会话归属。
未进入智能体执行的请求（例如等待计划确认时的直接返回）不生成 `GeoAgent` 追踪。

## 人工评分

评分标准的版本化来源是
[`manual_review.json`](../backend/evals/langsmith/manual_review.json)。
使用队列 `geoagent-manual-review`，或直接在追踪的 `… → Notes` 中填写反馈。

| 反馈字段 | 判断内容 |
|---|---|
| `nalamap_task_completion` | 是否完成用户目标，或合理澄清/请求确认 |
| `nalamap_tool_selection` | 工具、参数、顺序是否正确，是否存在无效重复 |
| `nalamap_groundedness` | 回答是否有工具结果/上下文支持，是否如实说明失败 |
| `nalamap_spatial_correctness` | 地点、区域、距离单位、坐标系和空间产物是否正确 |

三个分值：**1 满足要求、0.5 部分满足、0 不满足**。
不适用或缺乏验证证据时留空，并补充 Notes；不要用 0 代表“无法判断”。
根调用用于评估整轮效果；需要定位工具问题时，也可在工具子调用上添加反馈。
`success` 只表示执行未抛出异常，不能替代正确性评分。

在项目追踪列表中选中希望评估的真实调用，加入 `geoagent-manual-review`
队列，逐条检查并提交分数。新追踪会持续上传；加入人工评审队列是独立动作，
本配置没有设置自动入队或 LLM 自动打分规则。
先标注正常、失败、多步工具调用和多轮追问等不同样本，再按反馈字段比较结果。
只有人工提交反馈后才会产生评分，不会为了展示指标预填分数。

## 排查

- 无新追踪：确认实际运行的后端加载了上述环境变量、项目名和区域 endpoint；检查后端 LangSmith 上传错误日志。
- 有追踪但没有 Threads：确认已重启至包含 `agent_trace.py` 的代码，并产生新会话。
- 有追踪但没有评分：追踪与评分是独立功能，打开 Notes 或评审队列提交人工反馈。
- 数据库有记录、LangSmith 没有：分别检查审计与 LangSmith 配置/网络；不会自动从数据库回填追踪。
- 模型 token/费用缺失：取决于模型服务返回的 usage 信息和平台的模型计价支持，不能直接视为未调用模型。

## 官方参考

- [LangChain 原生追踪](https://docs.langchain.com/langsmith/trace-with-langchain)
- [会话分组](https://docs.langchain.com/langsmith/threads)
- [设置评分标准](https://docs.langchain.com/langsmith/set-up-feedback-criteria)
- [在追踪中人工评分](https://docs.langchain.com/langsmith/annotate-traces-inline)
- [评审队列与评分配置](https://docs.langchain.com/langsmith/annotation-queues-sdk)
