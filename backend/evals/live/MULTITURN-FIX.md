# 多轮对话工具失效：根因与修复

> **现象**：一次对话中只能调用一次工具，之后所有轮次都无法正常调用。
> **结论**：已修复。根因是 `normalize_messages()` 丢弃了 ToolMessage，导致
> 从第 2 轮起历史非法。修复后 6 轮连续对话全部正常调用工具。

---

## 一、根因

`backend/api/nalamap.py` 的 `normalize_messages()`：

```python
elif t == "tool":
    continue  # TODO: Fix required tool call missing    ← 未完成的代码
```

**这一行丢弃了所有 ToolMessage**，但保留了带 `tool_calls` 的 AIMessage。

于是历史变成：

```
HumanMessage("加载深圳边界")
AIMessage(tool_calls=[geocode...])      ← 宣告调用工具
                                        ← ToolMessage 被删了！
HumanMessage("现在做缓冲")
```

LLM 提供商校验时报错：

```
INVALID_CHAT_HISTORY:
Found AIMessages with tool_calls that do not have a corresponding ToolMessage.
```

**为什么表现为"一次之后就不能用了"**：第 1 轮历史是干净的，能成功调用工具；
从第 2 轮起，历史里有了未配对的工具调用，**每一轮都必然失败**，且错误信息与
"工具坏了"高度相似，极易误判。

---

## 二、复现证据

### 修复前（4 轮）

| 轮次 | 耗时 | 工具 | 结果 |
|------|------|------|------|
| 1 | 4.8s | `geocode_using_nominatim_to_geostate` | ✅ |
| 2 | **0.1s** | **（无）** | ❌ INVALID_CHAT_HISTORY |
| 3 | **0.1s** | **（无）** | ❌ 同上 |
| 4 | **0.1s** | **（无）** | ❌ 同上 |

第 2 轮起 0.1 秒就失败——因为校验在调用 LLM 之前就抛错了，与模型无关。

### 关键区别：为什么单轮测试发现不了

如果每轮都发空 `messages`（我之前的评测脚本就是这样），历史始终干净，
**永远测不出这个 bug**。必须模拟前端回传累积历史才能复现：

```python
# frontend/app/hooks/useGeoAgent.ts:185
const requestMessages = appendHumanMessage(queryText);   # 累积历史
```

这是本次最重要的教训：**评测脚本不模拟真实前端行为，就会漏掉整类缺陷**。

---

## 三、修复内容

### 1. 恢复 ToolMessage（核心）

```python
elif t == "tool":
    tool_call_id = (
        getattr(m, "tool_call_id", None)
        or getattr(m, "tool", None)
        or _extract_tool_call_id(m)
    )
    if not tool_call_id:
        # 无法配对时降级为普通消息，避免内容丢失
        normalized.append(HumanMessage(content=f"[tool result] {content}"))
        continue
    normalized.append(ToolMessage(
        content=content, tool_call_id=str(tool_call_id), name=tool_name
    ))
```

### 2. 保证 tool_call id 稳定

```python
call_id = tc.get("id") or func.get("id") or f"call_{uuid.uuid4().hex[:24]}"
```

ToolMessage 靠 id 与 tool_call 配対，id 缺失会让配对失效。

### 3. 兜底清理孤儿调用

新增 `_drop_orphan_tool_calls()`：规范化结束后，删除所有找不到对应
ToolMessage 的 tool_calls。

```python
answered = {msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage)}
# 保留有答复的调用；全部无答复则整条 AIMessage 的 tool_calls 清空
```

作用：**历史里已有的坏数据不会继续污染后续轮次**，用户不必重开会话。

### 4. 同步修复 function 分支

同样的 `continue` 死代码一并移除。

---

## 四、验证

### 修复后（6 轮连续对话）

| 轮次 | 问题 | 工具 | 结果 |
|------|------|------|------|
| 1 | 加载深圳边界 | `geocode_using_nominatim_to_geostate` | ✅ 3.9s |
| 2 | 做 200 米缓冲区 | `geoprocess_tool` | ✅ 7.6s |
| 3 | 统计图层数量 | `list_user_layers` | ✅ 3.9s |
| 4 | 查数据库表 | `list_postgis_layers` | ✅ 15.3s |
| 5 | 加载广东省边界 | `load_postgis_layer` | ✅ 5.5s |
| 6 | 现在有几个图层 | `list_user_layers` | ✅ 4.2s |

**6/6 全部正常，无任何错误。**

### 全量回归

19 题：18 通过 / 40 分（93.0%），与修复前一致，**无回归**。

---

## 五、经验教训

**① 不要留下 `continue` + TODO 的死代码。**
`continue # TODO: Fix required tool call missing` 是一个明确的未完成标记，
但它让"多轮工具"这个核心功能静默失效，且错误信息指向 LLM 提供商，
排查时很容易归因错误。

**② 评测必须模拟真实客户端行为。**
本次 19 题回归全部通过，却漏掉了这个 bug——因为脚本每轮发空 `messages`。
真实前端会累积历史。**测试脚手架与前端不一致，测试就失去意义。**

建议：把多轮场景加入回归套件（`repro_multiturn_msgs.py` 可直接复用）。

**③ 错误信息具有误导性。**
"INVALID_CHAT_HISTORY" + "tool_calls without ToolMessage" 读起来像是
模型或客户端的问题，实际是**服务端自己删掉了数据**。

---

## 六、改动文件

| 文件 | 改动 |
|------|------|
| `api/nalamap.py` | 恢复 ToolMessage；tool_call id 兜底；新增 `_drop_orphan_tool_calls()` |

> 改动通过 `docker cp` 注入运行中的容器，源码已写入宿主机。
> 重建 backend 镜像后才会持久化。
