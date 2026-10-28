# GeoAgent Agent 地理能力 — 问题处理清单

> 来源：《Agent 地理工作能力实测报告》（`agent-geospatial-eval.md`）
> 实测结果：19 题 / 通过 17 / 加权得分 38/43（88.4%）
> 本文档：逐条给出**问题定位 → 根因 → 解决办法 → 验收标准**
> 生成时间：2026-10-20
>
> ✅ **执行结果见 [`FIX-REPORT.md`](FIX-REPORT.md)**：修复后 18/19、40/43（93.0%），
> 平均耗时 58.8s → 16.5s，沙箱调用 14 → 0 次。

---

## 总览

| 编号 | 问题 | 级别 | 影响题 | 状态 |
|------|------|------|--------|------|
| P0-1 | 图层流转断裂 | 🔴 P0 | P01-P03, X01, S01 | ✅ 已修复（工具层） |
| P0-2 | 沙箱重试无收敛 | 🔴 P0 | G02, P01-P03 | ✅ 已修复（未实际触发） |
| P0-3 | 沙箱 DNS 失效（新发现） | 🔴 P0 | 所有沙箱回退任务 | ✅ 已修复 |
| P1-1 | 沙箱缺 geo 依赖 | 🟠 P1 | P01-P03 | ✅ 已修复 |
| P1-2 | 非流式递归上限过低 | 🟠 P1 | 所有多步任务 | ✅ 已修复 |
| P2-1 | NASA GIBS 工具循环 | 🟡 P2 | E01 | ⬜ 未处理 |
| P2-2 | NASA FIRMS 缺 Key | 🟡 P2 | E01 | ⬜ 未处理（需密钥） |
| P3-1 | 测试口径未固化 | 🔵 P3 | — | ⬜ 未处理 |

处理顺序建议：**P0-3 → P0-1 → P0-2 → P1-1 → P1-2 → P2 → P3**。

> P0-3 排最前：DNS 不通会让沙箱内**任何**下载/安装必然失败，
> 是 P0-2 重试循环的直接诱因之一，先修它成本最低、收益最大。

---

## P0-3 沙箱 DNS 失效（本次新增发现）

### 问题表现

沙箱容器内**所有外部域名解析失败**：

```bash
docker exec gagent-cesium-analysis-sandbox-1 python -c "import socket; \
  socket.gethostbyname('pypi.org')"
# → gaierror（Temporary failure in name resolution）
```

实测对比：

| 域名 | 沙箱内 | backend 容器内 |
|------|--------|----------------|
| `pypi.org` | ❌ FAIL (gaierror) | ✅ 151.101.64.223 |
| `db` | ❌ FAIL | ✅ 172.20.0.4 |
| `backend` | ✅ 172.21.0.3 | ✅ |
| `host.docker.internal` | ❌ FAIL | ✅（有 extra_hosts） |

### 精确根因

`/etc/resolv.conf` 对比：

```
# 沙箱（异常）
options ndots:0
# ExtServers: [8.8.8.8 1.1.1.1]      ← 公网 DNS

# backend（正常）
options ndots:0
# ExtServers: [192.168.31.1]          ← 本机网关 DNS
```

进一步验证（沙箱内直连探测）：

| 目标 | 结果 |
|------|------|
| `8.8.8.8:53` TCP 连通 | ✅ OK（能建立连接） |
| 向 `8.8.8.8` 发 DNS 查询 | ❌ TimeoutError |
| 向 `192.168.31.1` 发 DNS 查询 | ✅ 正常返回 90 字节 |

**结论**：本机网络只允许 `192.168.31.1`（网关）做 DNS 转发，
`8.8.8.8`/`1.1.1.1` 的 DNS 请求被丢弃（TCP 能通但 UDP DNS 被拦）。
Docker 给沙箱分配的上游 DNS 是公网地址，导致沙箱内解析全废。

> 这是**本机环境**问题，不是代码 bug；但因为它让沙箱的下载/安装能力归零，
> 会放大 P0-2 的重试循环，且在**任何类似网络环境**的用户机器上都会复现。

### 解决办法

**① 给沙箱显式配置可用 DNS**（推荐，改 compose）

在 `docker-compose.yml` 的 `analysis-sandbox` 服务下加：

```yaml
  analysis-sandbox:
    dns:
      - 192.168.31.1      # 与本机网关一致；换机器时改为该机器可用 DNS
    # 或使用公共可用 DNS：
    # dns:
    #   - 223.5.5.5
    #   - 119.29.29.29
```

更稳妥的做法是通过 .env 注入，避免硬编码：

```yaml
    dns:
      - ${SANDBOX_DNS_PRIMARY:-223.5.5.5}
      - ${SANDBOX_DNS_SECONDARY:-119.29.29.29}
```

**② 增加沙箱启动自检**

在 `sandbox/app/main.py` 的 startup 钩子里检查外网域名解析，
失败则打 warning（不阻断启动）：

```python
@app.on_event("startup")
async def _check_dns():
    import socket
    try:
        socket.gethostbyname("pypi.org")
    except Exception:
        logger.warning(
            "Sandbox DNS resolution failed; runtime pip install / HTTP fetch "
            "will not work. Configure `dns:` for the analysis-sandbox service."
        )
```

**③ 若网络确实受限，改为镜像预装**

见 P1-1：把 geo 依赖**预装进镜像**，就不依赖沙箱内 `pip install`。
两条路可并行——① 修 DNS，③ 兜底。

### ✅ 修复方案已验证

实测对照（同一 `python:3.11-slim` 镜像）：

| 启动方式 | `socket.gethostbyname('pypi.org')` |
|----------|-----------------------------------|
| `docker run --rm python:3.11-slim` | ❌ `gaierror` |
| `docker run --rm --dns 192.168.31.1 ...` | ✅ `151.101.64.223` |

即：**加 `--dns` 后解析立即恢复**，与 compose 里 `dns:` 配置等价，
方案确认有效。

### 验收标准

1. 沙箱内解析正常：
   ```bash
   docker exec gagent-cesium-analysis-sandbox-1 python -c \
     "import socket; print(socket.gethostbyname('pypi.org'))"
   # 期望：输出 IP，无 gaierror
   ```
2. `db`、`host.docker.internal` 在沙箱内可达（如业务需要）
3. 沙箱内 `pip install` 成功（unrestricted 模式下）

---

## P0-1 图层流转断裂（架构级）

### 问题表现

工具产出的图层只写入 `geodata_results`（结果列表），而下游消费型工具只从
`geodata_layers`（地图已选图层）读取，导致：

- 「加载 → 处理」必须由用户在 UI 手动勾选图层才能串联
- Agent 无法独立完成端到端地理工作流
- 实用信号：`geodata_layers` 累计 6 vs `geodata_results` 累计 16（**约 63% 产物进不了图层**）

### 精确根因（代码审计结论）

对 `backend/services/tools/` 全量扫描（脚本：`audit_state_io.py`）：

| 工具文件 | 写 layers | 写 results | 读 layers | 判定 |
|----------|----------:|-----------:|----------:|------|
| `postgis_tools.py` | 1 | 1 | 1 | ✅ 双写，正常 |
| `inefficient_space_tools.py` | 1 | 1 | 2 | ✅ 双写，正常 |
| `geocoding.py` | **0** | 3 | 0 | ⚠️ 只写 results |
| `geoprocess_tools.py` | **0** | 1 | 1 | ❌ 只写 results 却读 layers |
| `attribute_tool2.py` | **0** | 3 | 1 | ❌ 只写 results 却读 layers |
| `attribute_tools.py` | **0** | 3 | 3 | ❌ 只写 results 却读 layers |
| `python_analysis_tool.py` | **0** | 1 | 1 | ❌ 只写 results 却读 layers |
| `geostate_management.py` | **0** | 1 | 2 | ❌ 只写 results 却读 layers |

**关键细节**：`load_postgis_layer` 的 `add_to_map` 参数**默认为 True**
（`postgis_tools.py:329`），所以 PostGIS 加载路径本身正常。
真正断裂的是**地理编码 → 空间处理**这条链：

```
geocode_nominatim          →  geodata_results  ✅ 有数据
    ↓
geoprocess(buffer)         →  读 geodata_layers  ❌ 空 → 报错
```

实测报错原文（P03）：
```
Error: No geodata layers found in state. Please add or select layers first.
```

### 解决办法

**方案 A（推荐，改动最小）——统一"可处理图层"解析**

新增一个共享的图层解析函数，让所有消费型工具同时接受两个字段：

```python
# backend/services/tools/utils.py（新增）
from typing import Any, List, Optional

def resolve_input_layers(
    state: Any,
    layer_names: Optional[List[str]] = None,
    *,
    include_results: bool = True,
) -> List[Any]:
    """返回可处理图层：优先 geodata_layers，可选合并 geodata_results。

    去重规则：按 layer.id 去重，geodata_layers 优先（同名时保留前者）。
    """
    layers = list(state.get("geodata_layers") or [])
    if include_results:
        seen = {getattr(x, "id", None) for x in layers if getattr(x, "id", None)}
        for item in state.get("geodata_results") or []:
            lid = getattr(item, "id", None)
            if lid and lid in seen:
                continue
            if lid:
                seen.add(lid)
            layers.append(item)
    if layer_names:
        from services.tools.utils import match_layer_names  # 复用现有实现
        return match_layer_names(layers, layer_names)
    return layers
```

改造调用点（共 5 处）：

| 文件 | 行号 | 现状 | 改为 |
|------|------|------|------|
| `geoprocess_tools.py` | 372 | `layers = state.get("geodata_layers") or []` | `layers = resolve_input_layers(state)` |
| `attribute_tool2.py` | 164 | 同上 | 同上 |
| `attribute_tools.py` | 1569 | 同上 | 同上 |
| `python_analysis_tool.py` | 37 | `list(state.get("geodata_layers") or [])` | `resolve_input_layers(state)` |
| `geostate_management.py` | 107 / 193 | 同上 | 视语义决定是否合并 results |

> ⚠️ `geostate_management.py` 的两处需人工判断：`list_user_layers` 语义上**应只列
> 地图图层**（回答"地图上有什么"），不宜混入 results。建议保持原样，仅改 4 处。

**方案 B（备选）——写侧双写**

让 `geocode_*`、`geoprocess`、`attribute_*` 产出新图层时同时写 `geodata_layers`。

- 优点：读写语义一致，改动集中
- 缺点：会自动把用户没选的图层塞进地图，**改变 UI 行为**，风险较高
- 建议：仅在产品确认"工具产出自动上图"是期望行为时采用

**推荐组合**：方案 A（读侧兼容）+ 保持 `add_to_map` 显式控制写侧，
不动默认 UI 行为。

### ✅ 方案可行性已验证

已在容器内用真实 `GeoDataObject` + 真实 `match_layer_names` 验证
（脚本：`verify_p01_fix.py`，可在容器内运行）：

| 场景 | 结果 |
|------|------|
| 现状只读 `geodata_layers`（地理编码后） | 可用图层 **0** → 复现断裂 |
| 合并 `geodata_results` 后 | 可用图层 **2**，能按名精确选中「深圳市」 |
| 误选风险：只传「深圳市」 | 只选中「深圳市」，未误中餐饮点 |
| 去重：同一图层同时在两处 | 合并后 **1** 个（按 `id` 去重生效） |

名称匹配风险专项验证（`verify_matching_risk.py`）：

| 传入 | 匹配结果 | 判断 |
|------|----------|------|
| `['深圳市']` | `['深圳市']` | 精确 |
| `['深圳']` | `['深圳市']` | 前缀可解析（合理） |
| `['广东省']` | `['广东省']` | 精确 |
| `['layer_park_areas_near_深圳']` | 同名表 | 精确 |
| `['某某不存在']` | `[]` | 正确返回空，不乱匹配 |
| `['深圳范围内 · Restaurant · 点']` | 同名 | 精确 |

**结论**：`match_layer_names`（`cutoff=0.6`）在本场景下不会误选；
方案 A 可安全落地。

### 验收标准

1. 单轮完成"地理编码 → 缓冲"且**无需用户手动勾选**：
   ```bash
   python -X utf8 run_live_eval.py --only P01,X01 --mode stream
   # 期望：P01、X01 均 PASS，工具链含 geoprocess_tool 且 geodata_results_count ≥ 2
   ```
2. X01（跨轮图层）从 FAIL 转 PASS
3. `geodata_layers / geodata_results` 比值由 6/16 提升至 > 60%
4. 回归：`pytest backend/tests/test_geoprocess_tool.py -q` 全绿

---

## P0-2 沙箱重试无收敛

### 问题表现

`run_python_analysis` 在同一题内被反复调用，直到耗尽递归上限：

| 题目 | 沙箱调用次数 | 结果 |
|------|-------------|------|
| P01 | 9 | 勉强完成 |
| P02 | 7–8 | 完成 |
| P03 | 8 | 完成 |
| **G02** | **≥20** | ❌ `Recursion limit of 200 reached`（耗时 548.7s） |

### 精确根因

1. `BASE_SYSTEM_PROMPT` 已有约束：
   > "连续两次同类工具失败后必须停止继续调工具，向用户给出可选下一步，禁止空转。"

   但这是**提示词层**的自然语言约束，模型不保证遵守 → 需**代码层强制**。

2. 沙箱缺 `geopandas`（见 P1-1），导致首次调用必失败 → 触发重试 →
   每次重试换写法但同样失败 → 正反馈循环。

3. 无任何 per-session 工具调用计数或熔断机制。

### 解决办法

**① 加 per-session 沙箱调用熔断**

在 `backend/services/tools/python_analysis_tool.py` 入口处加计数，
基于已有的 `session_id`（`state.options.session_id`）：

```python
# 模块级
_SANDBOX_CALLS: Dict[str, int] = {}
_MAX_SANDBOX_CALLS = 3   # 单轮上限


def _check_sandbox_budget(state, tool_call_id) -> Optional[Command]:
    session_id = _session_id_of(state) or "unknown"
    used = _SANDBOX_CALLS.get(session_id, 0)
    if used >= _MAX_SANDBOX_CALLS:
        return Command(update={"messages": [ToolMessage(
            name="run_python_analysis",
            content=(
                f"Error: sandbox call budget exhausted ({used}/{_MAX_SANDBOX_CALLS}) "
                "for this session. Do NOT retry. Report the limitation to the user "
                "and propose an alternative (e.g. geoprocess tool or uploading data)."
            ),
            tool_call_id=tool_call_id,
            status="error",
        )]})
    _SANDBOX_CALLS[session_id] = used + 1
    return None
```

要点：
- 计数按 `session_id` 隔离，避免跨题/跨用户污染
- 超限后返回**明确的终止指令**（"Do NOT retry" + 给替代方案），而非仅报错
- 需在会话结束时清理该 key（复用 `services/conversation` 的生命周期钩子）

**插入位置**：`python_analysis_tool.py` 的 `_run_python_analysis_tool()`
（唯一入口，第 153 行 `max_features = ...` 之前）。

**✅ 前置条件已验证**：`state.get("options")` 返回 `SettingsSnapshot` 实例，
`getattr(options, "session_id")` 可正常取出（实测 `abc-123`），
熔断 key 有可靠来源，无需改状态模型。

**② 连续失败熔断（更通用的兜底）**

在 ReAct 循环外统一拦截：同一 `(tool_name)` 连续失败 ≥2 次即阻止再次调用。
LangGraph 侧可用 `post_model_hook` 或工具包装器实现，避免每个工具各写一份。

**③ 提高递归上限并降级为可读错误**

- 流式：`recursion_limit` 200 → 保持，但需在爆栈前被 ①② 拦住
- 爆栈时**不要**返回通用 `unexpected_error`，改为可读提示：
  ```python
  except GraphRecursionError:
      msg = ("任务步骤过多已中止。可能是某工具反复失败。"
             "建议缩小范围或指定具体数据源后重试。")
  ```

### 验收标准

1. `G02` 不再出现 `Recursion limit`；沙箱调用 ≤3 次，且返回可读结论
2. 全部 19 题沙箱调用总数 ≤ 8（当前 14+）
3. 任意题目耗时 **< 180s**（当前最坏 548.7s）
4. 新增单测：模拟沙箱连续失败，断言第 4 次调用被拦并返回终止文案

```bash
python -X utf8 run_live_eval.py --only G02,P02,P03 --mode stream
# 期望：3 题全 PASS，且 summarize.py 中 run_python_analysis 计数显著下降
```

---

## P1-1 沙箱缺 geo 依赖

### 问题表现

沙箱容器实测（`gagent-cesium-analysis-sandbox-1`）：

| 包 | 状态 |
|---|---|
| `shapely` | ✅ OK |
| `pandas` | ✅ OK |
| `numpy` | ✅ OK |
| `geopandas` | ❌ MISSING |
| `pyproj` | ❌ MISSING |
| `fiona` | ❌ MISSING |

后果：
- Agent 首选 `import geopandas as gpd` 必失败 → 触发 P0-2 的重试
- 回退到 `shapely` 手写近似（按米转度），**精度不可保证**
- 同一任务不同轮次精度不一致（有轮次自述"近似"，有轮次称"Web Mercator 精确"）

### 解决办法

**① 补齐依赖**（改沙箱镜像）

文件：`sandbox/requirements.txt`（当前仅 6 行：fastapi/uvicorn/pydantic/numpy/pandas/shapely）

追加：

```text
geopandas>=1.0
pyproj>=3.6
pyogrio>=0.7
```

> **不要用 `fiona`**：它需要系统 GDAL 库，slim 镜像上装起来麻烦。
> 已实测 `pyogrio` 路线在 `python:3.11-slim` 上可直接 `pip install` 成功，
> 无需任何系统依赖。

**② 沙箱自检接口**

新增健康检查，CI/启动时验证关键包可用，缺失即报警：

```python
# sandbox/app/runner.py 或独立 healthcheck
REQUIRED = ["geopandas", "pyproj", "shapely", "pandas", "numpy"]
missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
if missing:
    raise RuntimeError(f"sandbox missing geo deps: {missing}")
```

**③ 降级策略显式化**

若确实无法装依赖，应在工具描述里明确"沙箱不支持精确投影缓冲，
请优先用 geoprocess"，并把近似算法标注在结果里（当前仅在文字中偶然提及）。

### ✅ 依赖方案已验证可用

在 `python:3.11-slim` 上实测安装（配好 DNS 后）：

```
geopandas 1.2.0
pyproj    3.7.2
pyogrio   0.13.0
shapely   2.2.0
buffer area (m2, in 3857): 143578572.2
OK: Web Mercator 精确缓冲可执行
```

**关键结论**：
- `geopandas + pyproj + pyogrio` 在 slim 镜像上**无需安装系统 GDAL** 即可工作
- 走 `pyogrio` 而非 `fiona`，避免 GDAL 系统依赖，镜像体积与构建复杂度更低
- Web Mercator（EPSG:3857）缓冲实测可执行，能替代当前的"按米转度"近似

建议的 `sandbox/requirements.txt` 追加内容：

```text
geopandas>=1.0
pyproj>=3.6
pyogrio>=0.7
```

### 验收标准

1. 沙箱内 `python -c "import geopandas, pyproj"` 成功
2. P01 输出的缓冲图层经抽检，与 `geoprocess` 结果几何偏差 < 1%（米制）
3. 沙箱调用次数随之下降（与 P0-2 联动验收）

---

## P1-2 非流式端点递归上限过低

### 问题表现

| 端点 | 递归上限 | 出处 |
|------|----------|------|
| `POST /api/chat` | **25** | `models/states.py:136` 默认 + `api/nalamap.py:655` `remaining_steps=10` |
| `POST /api/chat/stream` | **200** | `api/nalamap.py:1187` 显式设置 |

同一缓冲题实测：

| 路径 | 耗时 | 结果 |
|------|------|------|
| `/chat` | 38.2s | 放弃，要求用户去 UI 勾选图层 |
| `/chat/stream` | 97.5s | 成功产出缓冲区图层 |

### 解决办法

**① 统一上限**（推荐）

`api/nalamap.py` 非流式 `invoke` 调用处补 `recursion_limit`：

```python
executor_result = single_agent.invoke(
    state,
    debug=debug_enabled,
    config={"callbacks": callbacks, "recursion_limit": 200},   # ← 新增
)
```

**② 爆栈降级为可读错误**（无论 ① 是否采纳都应做）

见 P0-2 的 ③。

**③ 文档标注**

在 API 文档中注明：多步复杂任务建议使用 `/chat/stream`。

### 验收标准

1. `python -X utf8 run_live_eval.py --mode blocking --only P01,P02` 两题均能出结果
   （不再 500）
2. 非流式与流式的工具链基本一致
3. 爆栈时返回中文可读提示，而非 `unexpected_error`

---

## P2-1 NASA GIBS 工具循环

### 问题表现

E01 某轮日志持续输出：

```
NASA GIBS request: location=Beijing, layer=list, category=fire
```

`get_nasa_gibs_layer` 被反复调用上百次，最终 `Recursion limit of 200`。

**关键**：单独重跑同一问题**行为正常**——正确调用 `get_nasa_fire_data` 并如实
报告缺 Key。属**偶发**，但一旦触发即 500。

### 根本原因（待确认）

`layer=list` 说明工具在"列可用图层"与"取图层"两种语义间反复。
可能原因：

- 工具返回图层清单后，未在提示/返回中明确"下一步该传什么 layer id"
- 模型误把"列清单"当成"已获取数据"，继续下一次调用
- 缺少同一工具连续调用的熔断（与 P0-2 同源）

### 解决办法

**① 返回结构化 next_step**

工具返回图层清单时，明确写出应调用的参数：

```
Available layers: viirs_snpp_fire_day, ...
Next: call get_nasa_gibs_layer with layer="viirs_snpp_fire_day" (do NOT call with layer="list" again).
```

**② 复用 P0-2 的连续失败/重复调用熔断**

同一工具在同一 session 内以相同参数调用 ≥2 次即拦截。

**③ 参数校验**

`layer="list"` 与正式图层名走不同分支，前者不应进入 retrieve 路径。

### 验收标准

1. E01 连续跑 5 次，均无 `get_nasa_gibs_layer` 超过 2 次
2. 日志中不再出现连续 `layer=list`

---

## P2-2 NASA FIRMS 缺 Key

### 问题表现

`.env` 与容器环境均无 `NASA_FIRMS_MAP_KEY`，火点数据能力实际不可用。

**Agent 行为正确**：如实报告"需要配置 MAP_KEY"，并给出替代方案（GIBS 影像）。

### 解决办法

**① 配置密钥**（若需该能力）

```bash
# .env
NASA_FIRMS_MAP_KEY=<从 https://firms.modaps.eosdis.nasa.gov/api/map_key/ 申请>
```

**② 评估口径修正**

已在题库中加 `allow_config_error: true`——缺凭据时"如实报告"即算通过。
这是**正确**的口径，不应因环境缺配置而判能力缺陷。

**③ 若无密钥，UI 侧降级**

在设置页标注该能力"未配置"，避免用户误以为可用。

### 验收标准

1. 配置密钥后，E01 能返回真实火点要素（`geodata_results_count ≥ 1`）
2. 未配置时，E01 仍 PASS（如实报告 + 不误用 Overpass）

---

## P3-1 测试口径未固化

### 问题表现

本次测试中修正了 5 处判定口径（详见报告 §2.6），若不固化，下次测试会重复踩坑：

| 坑 | 现象 |
|----|------|
| 工具名两套 | 用 key 比对运行时名 → 所有编码题误判 FAIL |
| 跨轮图层不存在 | 未加 `setup` → 依赖前置的题必然 FAIL |
| 过度要求工具 | M01 要求必须调 `search_metadata`，但直接作答也准确 |
| 不认回退成功 | 沙箱回退产出图层却判失败 |
| 缺配置当缺陷 | 缺 NASA Key 判能力不足 |

### 解决办法

**① 纳入 CI**

在 `.github/workflows/` 加一个可选 job（手动触发或定时），跑快速子集：

```yaml
- name: Agent geospatial smoke eval
  run: |
    cd backend/evals/live
    python -X utf8 run_live_eval.py --only G01,D01,G03,N01,N02,N03 --mode stream
  # 只跑快题（<60s 合计），避免 CI 超时；P 类留给 nightly
```

**② 判定逻辑单测**

把 `judge()` 做成纯函数并加单测，用构造的 `record` 覆盖 5 类边界：

```python
def test_judge_allows_fallback_success():
    rec = {... "geodata_results_brief": [{"data_source": "GeoAgentPythonAnalysis"}] ...}
    assert judge(case_with_no_fake_success, rec)["passed"]
```

**③ 题库版本化**

`cases_live.json` 加 `version` 字段（已有），口径变更时同步 bump 并在
报告 §2.6 追加一行，形成可追溯记录。

### 验收标准

1. `pytest backend/evals/live/test_judge.py -q` 全绿
2. CI 中 smoke eval 可手动触发
3. 口径变更均有记录

---

## 附：验证命令速查

```bash
cd backend/evals/live

# 全量回归（约 15-20 分钟）
python -X utf8 run_live_eval.py --mode stream --timeout 900
python -X utf8 gen_tables.py

# 针对 P0-1
python -X utf8 run_live_eval.py --only P01,X01,S01 --mode stream

# 针对 P0-2
python -X utf8 run_live_eval.py --only G02,P02,P03 --mode stream

# 针对 P1-2
python -X utf8 run_live_eval.py --mode blocking --only P01,P02

# 针对 P2-1
python -X utf8 repro_e01.py

# 状态读写字审计（验证 P0-1 改造范围）
python -X utf8 audit_state_io.py

# 针对 P0-3（沙箱 DNS）
docker exec gagent-cesium-analysis-sandbox-1 python -c \
  "import socket; print(socket.gethostbyname('pypi.org'))"

# 针对 P1-1（沙箱依赖）
docker exec gagent-cesium-analysis-sandbox-1 python -c \
  "import geopandas, pyproj; print(geopandas.__version__, pyproj.__version__)"
```

## 附：已完成的验证

本文档中的方案不是纸上设计，关键结论均已实测：

| 验证项 | 方法 | 结果 |
|--------|------|------|
| P0-1 方案 A 可行 | 容器内构造真实 state，跑 `resolve_input_layers` | ✅ 能精确选中目标图层，按 `id` 去重生效 |
| P0-1 误匹配风险 | `verify_matching_risk.py` 覆盖 8 种名称 | ✅ 不误选；不存在的名字返回空 |
| P0-2 熔断可行性 | 检查 `state.options.session_id` 可取 | ✅ 返回 `SettingsSnapshot`，`session_id` 可读 |
| P0-3 DNS 修复 | `docker run --dns 192.168.31.1` vs 不加 | ✅ 加后解析成功，不加 gaierror |
| P1-1 依赖可装 | slim 镜像内 `pip install` + 跑投影缓冲 | ✅ geopandas 1.2.0 / pyproj 3.7.2 / pyogrio 0.13.0 均可用 |

验证脚本：`verify_p01_fix.py`、`verify_matching_risk.py`、`audit_state_io.py`、
`_test_sandbox_deps.sh`（均在本目录）。

## 附：改动文件清单

| 优先级 | 文件 | 改动 |
|--------|------|------|
| P0-3 | `docker-compose.yml`（analysis-sandbox 服务） | 加 `dns:` 配置 |
| P0-3 | `sandbox/app/main.py` | startup 时 DNS 自检 + warning |
| P0-1 | `services/tools/utils.py` | 新增 `resolve_input_layers()` |
| P0-1 | `services/tools/geoprocess_tools.py:372` | 改用解析函数 |
| P0-1 | `services/tools/attribute_tool2.py:164` | 同上 |
| P0-1 | `services/tools/attribute_tools.py:1569` | 同上 |
| P0-1 | `services/tools/python_analysis_tool.py:37` | 同上 |
| P0-2 | `services/tools/python_analysis_tool.py` | 新增调用预算熔断 |
| P0-2 | `services/single_agent.py` | 连续失败熔断 / 爆栈可读错误 |
| P1-1 | `sandbox/requirements.txt` | 加 geopandas/pyproj（+pyogrio 免 GDAL） |
| P1-2 | `api/nalamap.py`（非流式 invoke） | 补 `recursion_limit` |
| P2-1 | `services/tools/nasa_gibs_imagery.py` | 结构化 next_step + 参数分支 |
| P2-2 | `.env` / 设置页 | 配置 Key 或标注未配置 |
| P3-1 | `.github/workflows/`、`evals/live/test_judge.py` | CI + 单测 |
