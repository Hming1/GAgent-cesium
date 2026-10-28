# 对话记录持久化

用于恢复聊天上下文、展示历史，并为 Agent 对话质量评估提供会话级事实源。

## 表结构

| 表 | 作用 |
|----|------|
| `conversations` | 会话：`conversation_id`、用户、session、标题、消息数、最后消息时间 |
| `conversation_messages` | 有序消息：role、content、时间、attachments、tool 信息、关联 `run_id` |

SQL 脚本：`backend/sql/create_conversation_tables.sql`  
Alembic：`backend/alembic/versions/20261012_add_conversations.py`

## 写入时机

每次聊天成功结束（`/api/chat` 与 `/api/chat/stream`）后 best-effort 写入：

1. upsert `conversations`（按前端 `options.conversation_id`，缺省回退 `session_id`）
2. 追加本轮 human 消息（query + 当前图层 attachments）
3. 追加本轮 ai / tool 结果消息，并挂上 `agent_runs.id`（若 audit 开启）

写入失败只打日志，不影响聊天主路径。

## API

- `GET /api/conversations?session_id=...&limit=20`：列出会话（登录用户优先按 `user_id`）
- `GET /api/conversations/{conversation_id}?include_tool_messages=true`：拉取有序消息

## 前端约定

请求 `options.conversation_id` 必须传入（`chatInterfaceStore` 的 conversationId）。  
新对话调用 `startNewConversation()` 生成新 id。

## 与 Agent Audit 的关系

| 能力 | conversations | agent_runs / events |
|------|---------------|----------------------|
| 会话历史展示 / 恢复 | 主数据源 | 辅助 |
| 工具执行质量排查 | 可经 `run_id` 关联 | 主数据源 |
| 对话质量评估 | 会话级样本 | run 级轨迹 |

## 迁移

```bash
cd backend
poetry run alembic upgrade head
# 或在 Navicat 执行 sql/create_conversation_tables.sql
```
