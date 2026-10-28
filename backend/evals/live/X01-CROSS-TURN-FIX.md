# X01 跨轮续接：问题分析与改进方案

> 问题：跨轮追问「对刚才的图层做缓冲」时，Agent 回答"地图上没有图层"并放弃。
> 结论：**已修复**。X01 从 FAIL 转为稳定 PASS（3/3），单题 10s 完成。

---

## 一、原判断需要修正

我最初把 X01 判为"Agent 保守但合理的交互选择"，这个结论**不准确**。

真实原因是**代码缺口**，不是模型偏好：

```
前端 useGeoAgent.ts:192    geodata_last_results: currentChatState.geoDataList
后端 api/nalamap.py:654        state["geodata_last_results"] = request.geodata_last_results
后端 api/nalamap.py:657        state["geodata_results"] = []          ← 每轮重置为空
```

而 `resolve_input_layers()` 的回退只看 `geodata_results`，**没看 `geodata_last_results`**。

所以链条是：

```
上一轮产物 → 前端存入 geodata_last_results → 后端正确接收
                                              ↓
                          但处理工具读不到（只查 geodata_results，它是空的）
                                              ↓
                                    Agent 看到「无图层」→ 反问
```

**验证**（容器内实测）：

```
state: geodata_layers=0, geodata_results=0, geodata_last_results=1
resolve_input_layers 返回: (空)      ← 这就是 X01 的根因
```

---

## 二、三层修复

### L1 工具层：补上 geodata_last_results 回退

`services/tools/utils.py`：

```python
for source in ("geodata_results", "geodata_last_results"):
    for item in state.get(source) or []:
        ...
```

修复后同一测试：

```
resolve_input_layers 返回: ['深圳市']   ← 能读到了
```

### L2 决策层：改提示词

工具能读到还不够——Agent 看到 `geodata_layers` 为空仍会放弃。在
`services/agent_skills/registry.py` 的 `BASE_SYSTEM_PROMPT` 增加：

```markdown
# 结果图层可直接处理（重要）
- geodata_layers 为空 **不代表** 没有可用数据。只要 geodata_results 或
  geodata_last_results 中有图层，就视为可用输入。
- 用户用「刚才的」「上面那个」指代上一轮产物时，直接从结果集合取用，
  不要要求用户先去地图里勾选。
- 处理类工具已支持读取结果图层，因此可以直接调用；
  **不要**因为 geodata_layers 为空就放弃或反问。
```

修复后 3 次实测：**3/3 全部成功**，工具链只有 `geoprocess_tool` 一个。

### L3 一致性：list_user_layers 也要看跨轮结果

`services/tools/geostate_management.py`：

```python
last_results = state.get("geodata_last_results") or []
all_layers = (
    [(layer, "geodata_layers") for layer in layers]
    + [(layer, "geodata_results") for layer in result_layers]
    + [(layer, "geodata_last_results") for layer in last_results]   # 新增
)
```

否则 Agent 调用这个工具查状态时，会看到"空"而再次误判。

---

## 三、修复引发的连锁问题（以及如何解决）

这次修复**引入了两个新问题**，值得记录：

### 副作用 1：list_user_layers 死循环

改成返回 `[]` 后，Agent 会反复调用它"确认"，**连续 26 次后递归爆栈**（69s 失败）。
提示词的"不要重复调用"约束**无效**——模型不遵守软约束。

**解决**：空结果时不再返回 `[]`，而是返回一条**带终止指令的哨兵记录**：

```python
if not all_layers:
    return [{
        "status": "empty",
        "layer_count": 0,
        "message": (
            "No layers are available... This is the final answer - "
            "do NOT call list_user_layers again. ..."
        ),
    }]
```

修复后：**3/3 通过，3–6 秒**（原先 69 秒爆栈）。

### 副作用 2：异常不再被吞，暴露了真实缺陷

修复 P03 时发现 `ops/*.py` 里 **8 处** `except Exception: return []`——把真实错误
伪装成"空结果"。改为抛出后，暴露出：

```
Error in op_clip: 'mask' should be GeoDataFrame/(Multi)Polygon, got MultiPoint
```

即**裁剪时把点图层当 mask**（参数顺序反了）。这个问题以前被静默吞掉，
表现为"裁剪结果为空"。

**解决**：
1. `op_clip` 加类型校验，给出可执行错误
2. `geoprocess_tools._order_layers_for_op()` 自动交换顺序
   （当 `layers[0]` 是面、`layers[1]` 是点时）

---

## 四、最终复测结果

### X01 专项（3 次连续）

| 轮次 | 结果 | 耗时 | 工具链 |
|------|------|------|--------|
| 1 | ✅ PASS | 9.7s | `geoprocess_tool` |
| 2 | ✅ PASS | 10.9s | `geoprocess_tool` |
| 3 | ✅ PASS | 9.3s | `geoprocess_tool` |

输出均为正确的 100 米缓冲图层，UTM 50N 投影，原图层未被覆盖。

### 全量回归演进

| 版本 | 通过 | 得分 | 说明 |
|------|------|------|------|
| v2（仅 L1 工具层） | 17/19 | 37/43 | X01 仍不稳定（1/3 失败） |
| v3（L1+L2 提示词） | 16/19 | 36/43 | X01 稳定，但 N02 死循环 |
| **v4（+L3 哨兵记录）** | **18/19** | **40/43 (93.0%)** | N02 稳定，剩 P02 波动 |

---

## 五、剩余问题

**P02 仍有波动**：全量回归时 6 秒零工具调用（Agent 选择先问数据来源），
单独运行时通过。这是**模型决策波动**，不是代码缺陷。

**建议**：若要进一步提高稳定性，可在提示词中针对"已知数据在数据库里"
的场景加明确指令；但过度约束可能损害其他场景的灵活性，需要权衡。

---

## 六、改动文件清单

| 文件 | 改动 |
|------|------|
| `services/tools/utils.py` | 回退来源增加 `geodata_last_results` |
| `services/agent_skills/registry.py` | 新增"结果图层可直接处理"与"查询类工具终止规则" |
| `services/tools/geostate_management.py` | list_user_layers 纳入跨轮结果；空时返回哨兵记录 |
| `services/tools/geoprocessing/ops/*.py` | 8 处异常不再吞掉（改为 raise） |
| `services/tools/geoprocessing/ops/clip.py` | 增加 mask 类型校验 |
| `services/tools/geoprocess_tools.py` | 自动纠正图层顺序；异常转可读 ToolMessage |

> ⚠️ 以上改动通过 `docker cp` 注入运行中的容器，源码已写入宿主机。
> **重建 backend 镜像才会持久化**（构建期 DNS 问题仍未解决）。
