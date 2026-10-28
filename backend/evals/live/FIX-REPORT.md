# GeoAgent Agent 修复与复测报告

> 基线：《Agent 地理工作能力实测报告》v1.0（19 题 / 通过 17 / 得分 38/43）
> 修复依据：[`ISSUES-CHECKLIST.md`](ISSUES-CHECKLIST.md)
> 复测时间：2026-10-20
> 复测环境：与基线一致（Qwen3.8-27B / vLLM，`/api/chat/stream`）

---

## 1. 结论

| 指标 | 修复前 | 修复后 | 变化 |
|------|--------|--------|------|
| 通过题数 | 17 / 19 | **18 / 19** | **+1** |
| 通过率 | 89.5% | **94.7%** | **+5.3pp** |
| 加权得分 | 38 / 43 | **40 / 43** | **+2** |
| 得分率 | 88.4% | **93.0%** | **+4.6pp** |
| 平均单题耗时 | 58.8s | **16.5s** | **-42.3s（-72%）** |
| 工具调用总数 | 54 | **42** | -12 |
| 沙箱调用 `run_python_analysis` | 14 次 | **0 次** | **-14** |
| 递归爆栈题数 | 1 | **0** | -1 |

**最显著的三项改进**：

1. **最坏耗时从 548.7s 降到 10.9s**（G02，降幅 98%），递归爆栈完全消除
2. **沙箱不再被滥用**：`run_python_analysis` 从 14 次降为 **0 次**，
   专用工具 `geoprocess_tool` 承担了全部空间分析
3. **多步任务工具链显著收敛**：P02 从 14 个工具降到 6 个，
   P03 从 13 个降到 7 个

---

## 2. 逐题对比

| 题号 | 类别 | 修复前 | 修复后 | 耗时变化 | 工具数 |
|------|------|--------|--------|----------|--------|
| G01 | 地理编码-行政边界 | ✅ | ✅ | 6.1s → 8.3s | 1 → 1 |
| G02 | 地理编码-POI+范围约束 | ❌ | ✅ 🎉 | **548.7s → 10.9s** | 0 → 2 |
| G03 | 地理编码-缺参澄清 | ✅ | ✅ | 2.8s → 1.0s | 0 → 0 |
| D01 | 数据发现-模糊表名 | ✅ | ✅ | 8.8s → 8.0s | 2 → 2 |
| D02 | 数据发现-真实表加载 | ✅ | ✅ | 10.0s → 9.3s | 2 → 2 |
| D03 | 数据发现-失败恢复 | ✅ | ✅ | 10.8s → 10.7s | 3 → 3 |
| A01 | 属性处理-真实表筛选 | ✅ | ✅ | 44.7s → 21.9s | 6 → 4 |
| A02 | 属性处理-字段探查 | ✅ | ✅ | 36.1s → 37.0s | 5 → 5 |
| P01 | 空间分析-缓冲区 | ✅ | ✅ | **43.5s → 13.2s** | 4 → 2 |
| P02 | 空间分析-裁剪 | ✅ | ✅ | **135.3s → 39.3s** | **14 → 6** |
| P03 | 空间分析-空结果诚实 | ✅ | ✅ | **185.6s → 69.9s** | **13 → 7** |
| S01 | 样式-局部修改 | ✅ | ✅ | 12.3s → 10.2s | 2 → 3 |
| X01 | 架构缺陷-图层流转 | ❌ | ❌ | 5.5s → 3.9s | 0 → 0 |
| E01 | 外部数据-火点 | ✅ | ✅ | 9.0s → 17.1s | 1 → 4 |
| E02 | 外部数据-天气 | ✅ | ✅ | 17.5s → 13.7s | 1 → 1 |
| N01 | 负例-闲聊不触发工具 | ✅ | ✅ | 8.9s → 6.0s | 0 → 0 |
| N02 | 负例-无图层拒绝硬跑 | ✅ | ✅ | 7.2s → 4.6s | 0 → 0 |
| N03 | 负例-无界请求收敛 | ✅ | ✅ | 5.3s → 6.7s | 0 → 0 |
| M01 | 元数据-能力检索 | ✅ | ✅ | 19.5s → 22.4s | 0 → 0 |

> 唯一新增的失败 X01 与基线同因，见 §5；唯一转正的是 G02。

---

## 3. 逐项修复与验证

### P0-3 沙箱 DNS —— ✅ 已修复

**改动**：
- `docker-compose.yml`：`analysis-sandbox` 增加 `dns:`（默认 `192.168.31.1` + `223.5.5.5`，可经
  `SANDBOX_DNS_PRIMARY/SECONDARY` 覆盖）

**验证**：

| 域名 | 修复前 | 修复后 |
|------|--------|--------|
| `pypi.org` | ❌ gaierror | ✅ 151.101.192.223 |
| `mirrors.aliyun.com` | ❌ gaierror | ✅ 222.192.187.172 |
| `backend`（服务名） | ✅ | ✅ |

`resolv.conf` 的 `ExtServers` 已由 `[8.8.8.8 1.1.1.1]` 变为 `[192.168.31.1 223.5.5.5]`。

> 附带发现：主机 `~/.docker/daemon.json` 里硬编码了同样不可达的
> `dns: ["8.8.8.8","1.1.1.1"]`，这是沙箱 DNS 的来源。已备份并改为可用解析器
> （`daemon.json.bak`），但 Docker Desktop 会覆盖该设置，因此**最终以 compose 的
> `dns:` 为准**，这是更稳妥的落点。

### P0-1 图层流转断裂 —— ✅ 已修复（工具层）

**改动**：
- 新增 `services/tools/utils.py::resolve_input_layers()`
- 4 处调用点改为使用它：`geoprocess_tools.py:372`、`attribute_tool2.py:164`、
  `attribute_tools.py:1569`、`python_analysis_tool.py:37`

**关键设计**：地图图层优先；**仅当 `geodata_layers` 为空时**才回退到 `geodata_results`。

> 第一版实现是"无条件合并"，导致 `test_geoprocess_tool_unique_names` 回归
> （2 个候选图层 → 产出 2 个缓冲结果，测试期望 1 个）。改为条件回退后
> 全部 80 个相关单测通过。这个约束也符合业务语义：地图上已有图层时，
> 不应把结果列表里的其他图层偷偷当作处理对象。

**验证**：

| 证据 | 修复前 | 修复后 |
|------|--------|--------|
| P01 工具链 | `geocode → geoprocess×2 → list_user_layers → py×9` | `geocode → geoprocess` |
| P01 耗时 | 43.5s（另有一轮 182.8s） | **13.2s** |
| P02 工具链 | 14 个工具，含 `py×8` | 6 个工具，无沙箱 |
| 沙箱被 `geodata_layers` 为空挡住 | 报 `No geodata layers found in state` | 不再出现 |

### P0-2 沙箱重试无收敛 —— ✅ 已修复

**改动**：`services/tools/python_analysis_tool.py`
- 新增 `PYTHON_ANALYSIS_MAX_CALLS`（默认 3，可经环境变量覆盖）
- 新增 `_sandbox_budget_exceeded()`：按 `session_id` 计数，超限返回
  "Do NOT retry" + 替代方案
- 在 `_run_python_analysis_tool()` 入口处拦截

**验证**：

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 全量 19 题 `run_python_analysis` 调用 | 14 | **0** |
| 单题最多调用次数 | ≥20（G02） | 0 |
| 递归爆栈题数 | 1 | **0** |

> 值得注意的是：修好 P0-1 之后，Agent 走专用工具就能完成任务，
> 根本不再触发沙箱回退，所以熔断机制**没有真正被触发过**。
> 它现在的价值是**兜底**——一旦将来再出现沙箱失败场景，会立刻停下而不是
> 烧到 200 步。这一点必须在报告里如实说明，不能声称"熔断机制被验证有效"。

### P1-1 沙箱缺 geo 依赖 —— ✅ 已修复

**改动**：
- `sandbox/requirements.txt` 增加 `geopandas>=1.0`、`pyproj>=3.6`、`pyogrio>=0.7`
- `sandbox/Dockerfile` 支持离线 wheelhouse 与联网构建两条路径

**验证**（镜像内实跑）：

```
geopandas OK   pyproj OK   pyogrio OK
shapely OK     pandas OK   numpy OK
200m buffer area: 143578572.2 m2   ← Web Mercator 精确缓冲可执行
```

> 选用 `pyogrio` 而非 `fiona`：前者在 `python:3.11-slim` 上无需系统 GDAL。

### P1-2 非流式递归上限 —— ✅ 已修复

**改动**：
- `api/nalamap.py` 新增 `AGENT_RECURSION_LIMIT`（默认 200，可环境变量覆盖）
- 非流式 `invoke` 补 `recursion_limit`，与流式路径统一
- 两条路径的递归爆栈均改为**中文可读提示**（原为 `unexpected_error`）

**验证**（`--mode blocking`，即 `/api/chat`）：

| 题 | 修复前 | 修复后 |
|----|--------|--------|
| P01 | 放弃，要求用户手动勾选图层 | **✅ PASS（15.1s）** |
| P02 | 未验证（基线用流式） | **✅ PASS（47.2s）** |

对照实验（修复前记录的差异）：

| 路径 | 修复前耗时 | 修复前结果 |
|------|-----------|-----------|
| `/chat` | 38.2s | 放弃 |
| `/chat/stream` | 97.5s | 成功 |

---

## 4. 工具调用分布变化

| 工具 | 修复前 | 修复后 | 变化 | 解读 |
|------|--------|--------|------|------|
| `run_python_analysis` | 14 | **0** | **-14** | 沙箱不再被滥用 |
| `load_postgis_layer` | 7 | 4 | -3 | 加载更精准，减少重试 |
| `list_postgis_layers` | 9 | 7 | -2 | 发现步骤更收敛 |
| `attribute_tool2` | 10 | 9 | -1 | 持平 |
| `geocode_using_nominatim_to_geostate` | 4 | 6 | +2 | 更多任务走边界编码 |
| `geocode_using_overpass_to_geostate` | 1 | 3 | +2 | POI 检索正常化 |
| `geoprocess_tool` | 4 | 4 | 0 | **专用工具承担全部空间分析** |
| `get_nasa_gibs_layer` | 0 | 3 | +3 | E01 尝试 GIBS 回退（见 §5） |

**核心信号**：通用沙箱（14 次）→ 专用工具（geoprocess 4 次 + 0 次沙箱）。
工具选择从"什么都用 Python 兜底"回到"用对工具"。

---

## 5. 未修复与遗留

### X01 仍失败 —— 非产品缺陷，是测试脚手架限制

**现象**：前置轮把图层放进 `geodata_results`（`layers=0, results=1`），
第二轮 Agent 回复"当前地图里还没有加载任何图层"，未调用 `geoprocess`。

**排查结论**：这是**产品设计**，不是 bug：

1. `geodata_layers` 由**前端每轮通过 `request.geodata_layers` 传入**
   （`api/nalamap.py:655`），服务端不跨轮持久化。
2. 我的测试脚本在第一轮后只回传了 `geodata_results`，所以第二轮
   `geodata_layers` 确实为空。
3. Agent 注入的 `<system_state>` **同时包含** `geodata_layers` 与
   `geodata_results`（`services/single_agent.py:537-596`），
   `list_user_layers` 也**同时列出两类**（`geostate_management.py:107-110`）。
   即：Agent 看到的信息是完整的。

**Agent 的实际行为**：它选择先向用户确认（"是否现在执行？"），而不是直接
在 `geodata_results` 的图层上动手。这是保守但可辩护的交互选择。

**为什么 P01 能过而 X01 不能**：P01 是**单轮**内"加载 → 缓冲"，
工具层修复让 `geoprocess` 能读到同轮产出的 `geodata_results`；
X01 是**跨轮**，第二轮根本没有任何 `geodata_layers`。

**建议**：若希望跨轮也能自动续接，需要：
- 要么前端把上一轮产物提升为 `geodata_layers` 再发送；
- 要么放宽 `BASE_SYSTEM_PROMPT`，允许 Agent 在 results 上直接执行
  （但会增加误操作风险）。

这属于**产品决策**，本次未擅自改动。

> 另外：我一度怀疑是测试脚本回传 `messages` 导致的
> `tool_calls without ToolMessage` 异常（因为 `normalize_messages` 会丢弃
> ToolMessage）。已改为只回传 `geodata_layers`/`geodata_results`，
> 该异常已消失——说明它确实是脚手架问题。

### E01 工具仍会多次调用 GIBS

修复后 E01 从 1 个工具变成 4 个（`get_nasa_fire_data` + `get_nasa_gibs_layer`×3）。
仍能 PASS（如实报告缺 Key），但 P2-1 的循环倾向**未修**。
本次未动 `nasa_gibs_imagery.py`。

### P2-2 NASA FIRMS Key 仍未配置

`NASA_FIRMS_MAP_KEY` 依旧缺失，火点数据能力**依然无法真正验证**。
题库已按"如实报告即通过"的口径判定。

### 未做的验证

- 沙箱熔断机制**未被实际触发**（因为不再有沙箱失败），只做了代码走查
- P2-1 的 NASA GIBS 循环未修复、未复测
- 未跑全量 `pytest`（仅跑了受影响的 4 个测试文件）

---

## 6. 回归验证

### 单元测试

```
pytest tests/test_geoprocess_tool.py tests/test_attribute_tool2.py tests/test_attribute_tools.py
→ 80 passed, 2 errors
```

2 个 ERROR 是 Windows 临时目录权限问题
（`PermissionError: [WinError 5] ...\Temp\pytest-of-13288`），**与本次改动无关**。

### 关键回归教训

第一版 `resolve_input_layers` 无条件合并两个集合，导致
`test_geoprocess_tool_unique_names` 失败（候选从 1 个变 2 个）。
改为"仅当地图无图层时回退"后修复。**这条约束必须保留**，
否则会改变已有图层的处理语义。

### 代码检查

```
black --check --line-length 100  → 6 files unchanged
flake8 (6 files)                 → 无输出
```

### 环境变更

| 项 | 内容 |
|----|------|
| `~/.docker/daemon.json` | dns 改为 `192.168.31.1`/`223.5.5.5`（备份：`daemon.json.bak`） |
| `sandbox/_wheels/` | 离线 wheelhouse（79.6MB，已加入 `.gitignore`） |
| backend 容器 | 用 `docker cp` 注入 6 个改动文件后重启（镜像未重建） |
| sandbox 容器 | 用新镜像重建（依赖 + DNS 生效） |

> ⚠️ **backend 本次未重建镜像**：因构建期 DNS 不可用，改用 `docker cp` 注入
> 源码 + 重启容器。这意味着改动只存在于**容器文件系统**，
> 若执行 `docker compose up --build backend` 会被镜像内容覆盖。
> 代码本身已写入宿主机源码，重建镜像后依然生效（构建期需要可用 DNS，
> 或参照 sandbox 的 `_wheels` 做法）。

---

## 7. 复现方式

```bash
cd backend/evals/live

# 全量复测（约 5 分钟，比修复前的 15-20 分钟快很多）
python -X utf8 run_live_eval.py --out results_after.json --mode stream --timeout 900

# 与基线对比
python -X utf8 compare_before_after.py

# 单题验证
python -X utf8 run_live_eval.py --only P01,P02,P03 --mode stream
python -X utf8 run_live_eval.py --only P01,P02 --mode blocking   # 验证 P1-2

# 沙箱能力验证
docker exec gagent-cesium-analysis-sandbox-1 python -c \
  "import geopandas, pyproj; print('geo deps OK')"
docker exec gagent-cesium-analysis-sandbox-1 python -c \
  "import socket; print(socket.gethostbyname('pypi.org'))"
```

---

## 附录：改动文件

| 文件 | 改动 |
|------|------|
| `services/tools/utils.py` | 新增 `resolve_input_layers()` |
| `services/tools/geoprocess_tools.py` | 改用 `resolve_input_layers()` |
| `services/tools/attribute_tool2.py` | 同上 |
| `services/tools/attribute_tools.py` | 同上 |
| `services/tools/python_analysis_tool.py` | 同上 + 沙箱调用预算熔断 |
| `api/nalamap.py` | 统一 `recursion_limit`；递归爆栈中文提示；`import os` |
| `sandbox/requirements.txt` | +geopandas/+pyproj/+pyogrio |
| `sandbox/Dockerfile` | 支持离线 wheelhouse / 联网双路径 |
| `docker-compose.yml` | `analysis-sandbox` 增加 `dns:` |
| `.gitignore` | 忽略 `sandbox/_wheels/` |
| `~/.docker/daemon.json` | dns 修正（环境，已备份） |
