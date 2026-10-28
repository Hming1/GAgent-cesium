# GeoAgent Agent 地理工作能力实测报告

> **测试对象**：`D:\code\Gagent-cesium`（GeoAgent 分支，Cesium 前端 + Agent 技能注册表）
> **测试时间**：2026-10-20
> **模型**：`Qwen3.8-27B`（vLLM @ `host.docker.internal:18000`）
> **端点**：`POST /api/chat/stream`（前端生产路径）
> **文档版本**：v1.0
>
> 📋 **对应的可施工清理清单见 [`ISSUES-CHECKLIST.md`](ISSUES-CHECKLIST.md)**
> （逐条给出定位、根因、解决办法、验证证据与验收标准）
>
> ✅ **已按清单修复并复测，结果见 [`FIX-REPORT.md`](FIX-REPORT.md)**
> （18/19、40/43，平均耗时 58.8s → 16.5s，沙箱调用 14 → 0 次）

---

## 0. 结论摘要

| 指标 | 结果 |
|------|------|
| 测试题数 | 19 |
| 通过 | 17 |
| 通过率 | **89.5%** |
| 加权得分 | **38/43（88.4%）** |
| 平均单题耗时 | 58.8s |

**一句话结论**：Agent 在**工具选择准确性**和**负例收敛**上表现优秀（8/8 负例与澄清类全过，
零工具误用），但在**多步空间分析链路的收敛性**上有明显缺陷——一旦首选工具不可用，
会陷入 Python 沙箱重试循环，最坏情况耗尽 200 步递归上限并返回通用错误。

**三个必须优先修的问题**：

1. **图层流转断裂**（P0，架构级）：工具产出只进 `geodata_results`，而所有消费型工具
   只读 `geodata_layers`。导致"加载 → 处理"必须由用户在 UI 手动勾选才能串联。
2. **沙箱重试无收敛**（P0）：`run_python_analysis` 单题最多被调用 9–14 次，
   缺乏失败即停机制，是递归爆栈的直接原因。
3. **沙箱缺 geo 依赖**（P1）：`geopandas`/`pyproj`/`fiona` 缺失，导致空间分析只能走
   近似算法或下载回退，结果精度不可保证。

---

## 1. 为什么需要这份文档

仓库已有 `backend/evals/harness/` 确定性测试，但它**完全不调用 LLM**，只验证：

- Skill 关键词路由（`required_tool_keys_for_query`）
- 字段映射函数（`infer_mapping_from_columns`）
- 工具注册表完整性、system prompt 拼装、plan aliases

它回答不了核心问题：**这个 Agent 真的能把地理活干完吗？**

真实能力取决于模型是否选对工具、参数是否合理、多步链路能否收敛、失败时是否诚实。
这类问题只能靠**发送真实问题、观察真实工具调用链**来评估。本文档记录的就是这套
端到端实测的方法学、过程与结论。

---

## 2. 测试方法

### 2.1 被测架构

```
┌────────────┐   POST /api/chat/stream (SSE)   ┌──────────────────┐
│ 测试脚本    │ ──────────────────────────────> │ FastAPI          │
│ (Python)   │ <────────────────────────────── │ + LangGraph ReAct│
└────────────┘  tool_start/tool_end/result     └────────┬─────────┘
                                                         │
                        ┌────────────────────────────────┼────────────────┐
                        ▼                                ▼                ▼
                 PostGIS (layers 库)              外部 API         Python 沙箱
                 15 张真实空间表              Nominatim/高德/百度    run_python_analysis
                                              Overpass/NASA/ECMWF   (容器独立网络)
```

### 2.2 关键方法学结论：必须测流式端点

这是本次测试**最重要的发现之一**。

两个端点的 LangGraph 递归上限不同：

| 端点 | 递归上限 | 出处 |
|------|----------|------|
| `POST /api/chat` | **25** | `models/states.py:136` 默认值 + `api/nalamap.py:655` `remaining_steps=10` |
| `POST /api/chat/stream` | **200** | `api/nalamap.py:1187` 显式 `recursion_limit: 200` |

同一道缓冲题（"加载深圳边界 → 做 200m 缓冲"）的实测差异：

| 路径 | 耗时 | 结果 | 产物 |
|------|------|------|------|
| `/api/chat`（非流式） | 38.2s | 放弃，要求用户先去 UI 勾选图层 | `results=1`，无缓冲结果 |
| `/api/chat/stream`（流式） | 97.5s | 成功产出 `深圳市_200m缓冲区` | `results=2` |

**前端实际走 `/chat/stream`**。所以：

> ⚠️ 用 `/chat` 评估复杂地理任务会**系统性低估**能力；
> 但反过来，`/chat` 的 500 错误（递归爆栈）也是真实存在的健壮性缺陷。

### 2.3 请求构造（必填字段陷阱）

`options` 是严格的 Pydantic 模型 `SettingsSnapshot`，缺任一必填字段直接 **500**：

```json
{
  "query": "把杭州市的行政边界加到地图上",
  "messages": [],
  "options": {
    "session_id": "eval-g01-xxxxxxxx",
    "conversation_id": "eval-g01-xxxxxxxx",
    "geoserver_backends": [],          // 必填，可为 []
    "tools": [],                       // 必填，[] = 启用全部默认工具
    "model_settings": {
      "model_provider": "vllm",        // 必填
      "model_name": "Qwen3.8-27B",     // 必填
      "max_tokens": 4096,              // 必填，≥1
      "plan_mode": false,
      "enable_agent_audit": false,     // 关闭：避免写库干扰计时
      "enable_memory": false,          // 关闭：隔离跨题记忆污染
      "enable_short_term_memory": false,
      "enable_long_term_memory": false
    }
  }
}
```

典型报错（漏字段时）：

```
pydantic_core.ValidationError: 4 validation errors for SettingsSnapshot
geoserver_backends  Field required
model_settings.model_provider  Field required
model_settings.model_name  Field required
model_settings.max_tokens  Field required
```

### 2.4 工具名两套映射（判定必踩的坑）

注册表 key 与 LangChain 运行时 `tool.name` **不一致**：

| 注册表 key | 运行时 `tool.name` |
|---|---|
| `geocode_nominatim` | `geocode_using_nominatim_to_geostate` |
| `geocode_overpass` | `geocode_using_overpass_to_geostate` |
| `geoprocess` | `geoprocess_tool` |
| `style_layers` | `style_map_layers` |
| `apply_color_scheme` | `apply_intelligent_color_scheme` |
| `search_metadata` | `metadata_search` |
| `ecmwf_weather` | `get_ecmwf_weather_data` |
| `nasa_fire_data` | `get_nasa_fire_data` |
| `world_bank_indicators` | `get_world_bank_data` |
| `autostyle_new_layers` | `auto_style_new_layers` |
| `check_and_autostyle` | `check_and_auto_style_layers` |
| `analyze_inefficient_space` | `analyze_inefficient_space_tool` |

若按 key 直接比对，**所有地理编码类题目都会被误判为失败**。测试脚本内维护
`TOOL_NAME_MAP` 做解析。

> 完整清单（24 个工具）可在容器内导出：
> ```bash
> docker exec gagent-cesium-backend-1 python -c "
> from services.agent_skills import build_available_tools
> t = build_available_tools()
> print({k: v.name for k, v in t.items()})"
> ```

### 2.5 评分规则

每题有 `weight`（1–3，按业务重要性）。判定项：

| 判定项 | 含义 | 违反后果 |
|--------|------|----------|
| `expect_tools` | 必须出现的工具 | 每个缺失 -1 |
| `forbid_tools` | 不得出现的误用工具 | 每次误用 -1 |
| `expect_any_tool` | 是否应调用工具 | 空跑/多余调用 -1 |
| `expect_geodata_min` | 最少地理产物数 | 不足 -1 |
| `expect_keywords` | 须提及的关键词 | 缺失 -1 |
| `expect_clarification` | 缺参时是否提问 | 未问 -1 |
| `expect_no_fake_success` | 失败时不得谎称成功 | 自相矛盾 -1 |
| `expect_field_discovery` | 字段未知时先探查 | 盲猜 -1 |
| `allow_config_error` | 缺凭据时如实报告即算通过 | — |

计分：`score = max(0, weight - 违反项数)`；**全部判定项通过才算 PASS**。

### 2.6 判定规则的三次修正（过程记录）

初版题库有 3 处误判，修正过程本身就是有价值的经验：

| 题 | 初版问题 | 根因 | 修正 |
|----|----------|------|------|
| G01 等全部地理编码题 | 全部 FAIL | 用了注册表 key 直接比对运行时名 | 引入 `TOOL_NAME_MAP` |
| S01 / P03 | 必然 FAIL | 跨轮"刚才的图层"不存在（每题独立 session） | 改为单轮完成，或加 `setup` 多轮前置 |
| M01 | FAIL | 要求必须调 `search_metadata`，但 Agent 直接依据工具 description 作答且**内容准确** | 改为允许直接作答，只校验算子名真实性 |
| P03 | FAIL | 沙箱回退成功产出了图层，但规则只认 `geodata_layers` | 认可 `GeoAgentPythonAnalysis` 来源的回退产物 |
| E01 | FAIL | 环境缺 `NASA_FIRMS_MAP_KEY`，Agent 如实报告却被判失败 | 新增 `allow_config_error` |

---

## 3. 题库设计

19 道题覆盖 8 类地理工作场景。文件：`backend/evals/live/cases_live.json`

| 类别 | 题号 | 考察点 |
|------|------|--------|
| **地理编码** | G01–G03 | 行政边界 vs POI、范围约束、缺参澄清 |
| **数据发现** | D01–D03 | 先 list 后 load、真实表加载、失败恢复 |
| **属性处理** | A01–A02 | 真实表统计、字段探查顺序 |
| **空间分析** | P01–P03 | 缓冲、裁剪、空结果诚实 |
| **样式** | S01 | 局部改色、opt-in |
| **架构缺陷专测** | X01 | 跨轮图层可见性 |
| **外部数据** | E01–E02 | NASA 火点、ECMWF 天气 |
| **负例** | N01–N03 | 闲聊不触发工具、无图层拒绝硬跑、无界收敛 |
| **元数据** | M01 | 能力查询 |

### 3.1 设计原则

**① 锚定真实数据，不编造**

`layers` 库真实存在的表（实测记录数）：

| 表名 | 要素数 | 用途 |
|------|--------|------|
| `layer_深圳市` | 1 | 行政区边界（缓冲/裁剪主体） |
| `layer_广东省` | 1 | 上级边界（覆盖关系陷阱） |
| `layer_深圳餐饮` | 8 067 | 点数据（裁剪对象） |
| `layer_park_areas_near_深圳` | 1 950 | 公园面（模糊表名检索目标） |
| `layer_深圳市_school_面` | 2 276 | 学校（字段探查） |

**② 用 `forbid_tools` 测"误用"，而非只测"能否完成"**

- G01 问行政边界 → 用 `geocode_overpass` 搜 POI 即**语义误用**
- E01 问火点 → 用 Overpass 搜"火点"POI 冒充即**数据源误用**
- S01 只改一个图层 → 用 `apply_color_scheme` 全局改色即**副作用越界**

**③ 依赖前置状态的题必须显式声明**

每题独立 `session_id`，"刚才那个图层"不会自动存在。题库用 `setup` 字段在
同一 session 内先跑前置轮：

```json
"setup": ["把深圳市行政边界加载到地图上"]
```

---

## 4. 执行方式

```bash
# 前置：后端已运行
curl http://localhost:8000/health     # 期望 {"status":"healthy",...}

cd backend/evals/live

# 全量跑（生产路径，推荐）
python -X utf8 run_live_eval.py --mode stream --timeout 900

# 只跑指定题
python -X utf8 run_live_eval.py --only G01,P01,S01 --mode stream

# 研究非流式递归上限影响
python -X utf8 run_live_eval.py --mode blocking --only P01,P02

# 汇总表格
python -X utf8 gen_tables.py
```

产出 `results_final.json`（`summary` + 逐题 `records`），每条记录含：
工具链（名称+参数）、工具返回预览、最终回答、地理产物、耗时、判定明细。

> **Windows 编码**：必须加 `-X utf8`。否则遇到 `©` 等字符会
> `UnicodeEncodeError: 'gbk' codec can't encode character '\xa9'`。
> 这只是终端显示问题，不影响结果文件。

### 辅助脚本

| 脚本 | 用途 |
|------|------|
| `run_live_eval.py` | 主运行器（发问 + 判定） |
| `gen_tables.py` | 生成 Markdown 表格 |
| `summarize.py` | 统计汇总与失败详情 |
| `compare_paths_final.py` | 对比 `/chat` 与 `/chat/stream` |
| `repro_e01.py` | 复现 NASA 工具循环 |
| `verify_style_single_turn.py` | 验证样式工具单轮可用性 |

---

## 5. 测试结果

### 5.1 总体

| 指标 | 数值 |
|------|------|
| 题目总数 | 19 |
| 通过 | 17 |
| 失败 | 2 |
| 通过率 | **89.5%** |
| 加权得分 | **38/43（88.4%）** |
| 平均耗时 | 58.8s |

### 5.2 逐题结果

| 题号 | 类别 | 结果 | 耗时 | 工具链 | 得分 |
|------|------|------|------|--------|------|
| G01 | 地理编码-行政边界 | ✅ PASS | 6.1s | geocode_nominatim | 2/2 |
| G02 | 地理编码-POI+范围约束 | ❌ FAIL | 548.7s | （递归爆栈） | 0/2 |
| G03 | 地理编码-缺参澄清 | ✅ PASS | 2.8s | （零工具，正确提问） | 2/2 |
| D01 | 数据发现-模糊表名 | ✅ PASS | 8.8s | list → list | 2/2 |
| D02 | 数据发现-真实表加载 | ✅ PASS | 10.0s | list → load | 2/2 |
| D03 | 数据发现-失败恢复 | ✅ PASS | 10.8s | load → list → list | 2/2 |
| A01 | 属性处理-真实表统计 | ✅ PASS | 44.7s | list → load → attribute×4 | 2/2 |
| A02 | 属性处理-字段探查 | ✅ PASS | 36.1s | list → load → attribute×3 | 2/2 |
| P01 | 空间分析-缓冲区 | ✅ PASS | 43.5s | geocode → list → load → geoprocess | 3/3 |
| P02 | 空间分析-裁剪 | ✅ PASS | 135.3s | list → load×2 → geoprocess → py×8 | 3/3 |
| P03 | 空间分析-空结果诚实 | ✅ PASS | 185.6s | geocode×2 → geoprocess → py×8 | 3/3 |
| S01 | 样式-局部修改 | ✅ PASS | 12.3s | geocode → style | 2/2 |
| X01 | 架构缺陷-图层流转 | ❌ FAIL | 5.5s | （零工具，报告无图层） | 0/3 |
| E01 | 外部数据-火点 | ✅ PASS | 9.0s | nasa_fire_data | 2/2 |
| E02 | 外部数据-天气 | ✅ PASS | 17.5s | ecmwf_weather | 2/2 |
| N01 | 负例-闲聊不触发工具 | ✅ PASS | 8.9s | （零工具） | 2/2 |
| N02 | 负例-无图层拒绝硬跑 | ✅ PASS | 7.2s | （零工具） | 3/3 |
| N03 | 负例-无界请求收敛 | ✅ PASS | 5.3s | （零工具） | 3/3 |
| M01 | 元数据-能力检索 | ✅ PASS | 19.5s | （零工具，直接作答） | 1/1 |

### 5.3 工具调用分布

| 工具 | 调用次数 | 观察 |
|------|----------|------|
| `run_python_analysis` | **14** | ⚠️ 占比过高，是重试循环的主要载体 |
| `attribute_tool2` | 10 | 属性题正常使用 |
| `list_postgis_layers` | 9 | 数据发现主力 |
| `load_postgis_layer` | 7 | 加载主力 |
| `geocode_using_nominatim_to_geostate` | 4 | 边界获取 |
| `geoprocess_tool` | 4 | ⚠️ 偏低，被沙箱替代 |
| `list_user_layers` | 2 | 状态检查 |
| `geocode_using_overpass_to_geostate` | 1 | POI |
| `style_map_layers` | 1 | 样式 |
| `get_nasa_fire_data` | 1 | 火点 |
| `get_ecmwf_weather_data` | 1 | 天气 |

**关键信号**：专用空间工具 `geoprocess_tool` 只被调用 4 次，而通用沙箱
`run_python_analysis` 被调用 14 次。**专用工具被通用工具挤占**，
这正是 `geodata_layers` 断裂导致的连锁反应。

### 5.4 产物统计与大图景

| 指标 | 数值 |
|------|------|
| `geodata_layers` 累计 | **6** |
| `geodata_results` 累计 | **16** |
| 图层/结果比 | **6/16 ≈ 37%** |

即：**约 63% 的地理产物只停留在结果列表，进不了地图图层**。

---

## 6. 问题清单

### P0-1 图层流转断裂（架构级）

**现象**：工具产出的图层写入 `geodata_results`，但所有消费型工具只读 `geodata_layers`。

**证据链**：

1. 代码定位 —— `services/tools/geoprocess_tools.py:372`
   ```python
   layers = state.get("geodata_layers") or []
   ```
   第 375 行：为空则直接返回 `Error: No geodata layers found in state.`

2. 实测报错 —— P03 中 `geoprocess_tool` 返回：
   ```
   Error: No geodata layers found in state. Please add or select layers first.
   ```

3. Agent 自行诊断（P03 回答原文）：
   > "广东省边界图层……**未保留在当前地图状态中**（`geodata_layers` 为空），工具无法读取其数据。
   > 深圳餐饮点图层……同样**不在 `geodata_layers` 中**，裁剪工具只能访问 `geodata_layers` 里的图层。"

4. X01 专项复现 —— 前置轮"把深圳市行政边界加载到地图上"执行成功
   （`results=1`），但下一轮 Agent 报告"当前地图上还没有加载任何图层"。

**后果**：所有"加载 → 处理"的多步工作流必须由用户在 UI 手动勾选图层才能继续，
**Agent 无法独立完成闭环地理任务**。

**影响面**：P01、P02、P03、X01、S01 全部受此影响；也是专用工具被沙箱挤占的根因。

### P0-2 沙箱重试无收敛

**现象**：`run_python_analysis` 在同一题内被反复调用，直到耗尽递归上限。

**证据**：

| 题目 | `run_python_analysis` 调用次数 | 结果 |
|------|-------------------------------|------|
| P01（某轮） | 9 | 勉强完成 |
| P02（某轮） | 7–8 | 完成 |
| P03 | 8 | 完成 |
| **G02** | **≥ 20** | ❌ `Recursion limit of 200 reached` |

G02 耗时 **548.7 秒**后返回通用错误：
```
unexpected_error: Recursion limit of 200 reached without hitting a stop condition.
```

`BASE_SYSTEM_PROMPT` 里已写明"连续两次同类工具失败后必须停止继续调工具"，
但**该约束对沙箱重试未生效**。

### P1-1 沙箱缺 geo 依赖

**实测**（`gagent-cesium-analysis-sandbox-1`）：

| 包 | 状态 |
|---|---|
| `shapely` | ✅ OK |
| `pandas` | ✅ OK |
| `numpy` | ✅ OK |
| `geopandas` | ❌ MISSING |
| `pyproj` | ❌ MISSING |
| `fiona` | ❌ MISSING |

**后果**：Agent 首选的 `import geopandas as gpd` 必然失败，然后才回退到
`shapely` 手写几何运算。P01 某轮回答坦承：

> "当前 Python 沙箱缺少 geopandas/shapely，缓冲区是用「按米转度、沿边界向外偏移」的
> **近似方式**生成的……可能与专业 GIS 的精确缓冲略有偏差。"

后续轮次（依赖装好后）改为 "在 Web Mercator 投影下做了精确的 200 米缓冲区"，
说明**同一任务的结果精度不稳定**。

### P1-2 非流式端点递归上限过低

`/api/chat` 的 `recursion_limit=25`（`nalamap.py:1187` 的流式路径是 200）。
凡涉及 3 步以上工具链的请求，在非流式路径下极易 500。

实测同一缓冲题：`/chat` 放弃并要求用户手动勾选图层；`/chat-stream` 成功。

### P2-1 NASA GIBS 工具易陷入循环

E01 某轮出现 `get_nasa_gibs_layer` 被调用上百次（日志持续输出
`NASA GIBS request: location=Beijing, layer=list, category=fire`），最终递归爆栈。

复现验证：单独重跑同一问题时**行为正常**（正确调 `get_nasa_fire_data` 并如实报告
缺 API Key）。属**偶发**但严重——一旦触发即 500。

### P2-2 外部依赖缺凭据

`NASA_FIRMS_MAP_KEY` 未配置，火点数据能力实际不可用。Agent 如实报告并给出替代方案
（行为正确），但**该能力在评估中无法真正验证**。

### 观察项：非缺陷但有优化空间

| 现象 | 说明 |
|------|------|
| M01 零工具作答 | Agent 直接依据工具 description 列出算子，内容准确（`buffer`/`overlay`/`sjoin`/`centroid` 等确实存在于 `geoprocess_tool` 描述中），非编造 |
| 允许沙箱回退成功 | P03 主路径失败后，沙箱真实算出 `clipped_count=188` 并产出图层，结论有据 |
| 沙箱可访问后端 | 沙箱能用 `backend:8000` 访问后端（`host.docker.internal` 不通），这是回退路径能工作的前提 |

---

## 7. 结论与建议

### 7.1 能力评价

| 维度 | 评价 | 依据 |
|------|------|------|
| **工具选择准确性** | ⭐⭐⭐⭐⭐ 优秀 | 19 题**零工具误用**；边界/POI、火点/POI、局部样式/全局改色等陷阱全部避开 |
| **澄清与收敛** | ⭐⭐⭐⭐⭐ 优秀 | G03/N02/N03 三个负例全过，缺参只问一个关键问题，无界请求主动收敛 |
| **失败诚实度** | ⭐⭐⭐⭐☆ 良好 | 报错可读、不伪造成功、缺 Key 如实报告；P03 回退结果有据 |
| **单步任务** | ⭐⭐⭐⭐⭐ 优秀 | 地理编码、数据发现、属性统计、天气、火点均稳定可用 |
| **多步空间分析** | ⭐⭐☆☆☆ 待改进 | 缓冲/裁剪能出结果，但依赖沙箱近似，且易陷入重试循环 |
| **任务闭环能力** | ⭐☆☆☆☆ 不足 | 图层流转断裂导致必须人工介入，无法独立完成"加载→处理→出图" |
| **性能** | ⭐⭐☆☆☆ 待改进 | 平均 58.8s；最坏 548.7s 后失败（递归爆栈） |

**综合判断**：作为**地理数据查询与单步分析助手**已具备可用水平；
作为**自主完成端到端地理工作流的 Agent** 尚不成熟，核心卡点在图层流转与循环收敛。

### 7.2 修复建议（按优先级）

**P0 — 必须修**

1. **打通图层流转**
   工具产出结果时，若语义上是"可供后续处理的图层"，应同时写入 `geodata_layers`
   或提供 `auto_promote` 机制；或让 `geoprocess`/`style_layers` 同时接受
   `geodata_results` 作为输入候选。
   - 参考位置：`services/tools/geoprocess_tools.py:372`、`style_map_layers` 同类逻辑

2. **给沙箱重试加硬收敛**
   - 同一 `session_id` 内对 `run_python_analysis` 设调用上限（建议 ≤3）
   - 连续 2 次同类失败后强制走"向用户报告 + 给替代方案"分支
   - 现有 `BASE_SYSTEM_PROMPT` 的收敛规则需在代码层强制，而非仅靠提示词

**P1 — 应修**

3. **补齐沙箱 geo 依赖**：`geopandas`、`pyproj`、`fiona`
   否则"精确缓冲"与"近似缓冲"结果不一致，且浪费大量重试轮次。

4. **统一递归上限**：非流式 `/chat` 从 25 提升到与流式一致的 200，
   或对多步任务返回明确的"请改用流式"错误而非 500。

**P2 — 建议**

5. **修 NASA GIBS 循环**：`get_nasa_gibs_layer` 返回图层列表后应终止该分支，
   避免 `layer=list` 被反复调用。

6. **配置 `NASA_FIRMS_MAP_KEY`**：否则火点能力无法验证。

7. **补充 e2e 回归**：把本套 19 题纳入 CI（可先跑快速子集 G/D/N 类，
   跳过耗时的 P 类），防止回归。

### 7.3 复现指引

```bash
# 1. 确认服务
curl http://localhost:8000/health

# 2. 全量回归
cd backend/evals/live
python -X utf8 run_live_eval.py --mode stream --timeout 900

# 3. 查看结果
python -X utf8 gen_tables.py

# 4. 复现 P0-1（图层流转）
python -X utf8 run_live_eval.py --only X01 --mode stream

# 5. 复现 P0-2（沙箱循环）
python -X utf8 run_live_eval.py --only G02 --mode stream

# 6. 复现 P1-2（递归上限差异）
python -X utf8 compare_paths_final.py
```

---

## 附录 A：文件清单

| 文件 | 说明 |
|------|------|
| `agent-geospatial-eval.md` | 本文档 |
| `cases_live.json` | 19 题题库（含期望/禁止工具、判定规则） |
| `run_live_eval.py` | 主运行器 |
| `results_final.json` | 最终回归原始结果 |
| `gen_tables.py` | Markdown 表格生成 |
| `summarize.py` | 统计汇总 |
| `compare_paths_final.py` | 流式/非流式对比 |
| `repro_e01.py` | NASA 循环复现 |
| `verify_style_single_turn.py` | 样式单轮验证 |
| `probe.py` / `inspect_response.py` | 初期探查脚本 |

## 附录 B：环境快照

| 项 | 值 |
|----|-----|
| 操作系统 | Windows（Docker Desktop） |
| 后端容器 | `gagent-cesium-backend-1`（Python 3.13） |
| 沙箱容器 | `gagent-cesium-analysis-sandbox-1` |
| 数据库 | `postgis/postgis:16-3.4`，库 `app` + `layers`，用户 `app` |
| LLM | `Qwen3.8-27B` via vLLM (`host.docker.internal:18000/v1`) |
| 已确认缺失 | `NASA_FIRMS_MAP_KEY`、`geopandas`、`pyproj`、`fiona` |
| 已确认可用 | Nominatim、高德（`AMAP_WEB_SERVICE_KEY`）、百度（`BAIDU_GEOCODING_AK`）、Overpass、Open-Meteo |
