# AI 智能体工具

该目录包含 GeoAgent AI 智能体可调用的工具函数。这些工具让智能体能够与地理空间数据交互、执行空间分析，并管理当前会话中的应用状态。

工具函数本身仍放在 `backend/services/tools/`；面向智能体的能力编排、提示词片段、工具元数据和路由规则现在由 `backend/services/agent_skills/` 中的 Skill Registry 统一管理。

## 工具分类

### 地理编码 (`geocoding.py`)

用于将地点名称转换为坐标、边界或兴趣点数据。

- `geocode_using_nominatim_to_geostate`：使用 OSM Nominatim 搜索地点，例如城市、地址和行政区。
  When Nominatim fails or finds nothing, address geocoding, Overpass center lookup, weather, fire, imagery, and country geometry all try Amap then Baidu. Address results are WGS84 point layers. For administrative boundaries or clipping, set `require_boundary=True` and query a place name/adcode (use `maxRows=1` for one city). This accepts polygon results from Nominatim, then uses Amap district search with `extensions=all`, converts GCJ-02 to WGS84 and validates polygon topology. It never substitutes Amap/Baidu address points for a boundary. Set AMAP_WEB_SERVICE_KEY and/or BAIDU_GEOCODING_AK on the backend. After editing the root .env, recreate the backend container to load changed environment values; restarting an existing container does not reload them. If container DNS fails, set `BACKEND_DNS_SERVER` in the root .env to a DNS server reachable from Docker (the current local deployment uses its LAN DNS). Apply it when recreating the backend. A system proxy used by Docker must also permit the provider HTTPS endpoints.
- `geocode_using_overpass_to_geostate`：在指定范围内搜索 POI（医院、学校、餐厅等）。国内查询在配置了 `AMAP_WEB_SERVICE_KEY` 时优先使用高德地点搜索；失败或境外再回退 OpenStreetMap Overpass。高德单次检索翻页约 200 条封顶，因此地级市/直辖市范围会先查行政区划，按区县逐个检索后去重合并；区县及以下或地标半径检索直接查询。遇到高德 QPS 限流会短暂退避重试。高德返回 GCJ-02，入库前会转成 WGS84（EPSG:4326）以便与天地图/OSM 对齐；前端在切换到高德底图时再把图层坐标临时转回 GCJ-02 显示。

### 空间处理 (`geoprocess_tools.py`)

用于对矢量数据执行空间操作。

- `geoprocess_tool`：统一的空间处理入口，支持以下操作：
  - **Buffer**：围绕要素创建缓冲区。
  - **Clip**：使用一个图层裁剪另一个图层。
  - **Intersect**：计算重叠区域。
  - **Union**：合并多个图层。
  - **Centroid**：计算要素中心点。
  - **Dissolve**：根据属性字段融合要素。

### 样式设置 (`styling_tools.py`)

用于控制地图中的图层可视化样式。样式工具可读 `geodata_layers` /
`geodata_results` / `geodata_last_results`，成功后会把图层 promote 到地图。

- `style_map_layers`：应用手动样式，例如颜色、透明度和边线（整层单色）。
- `auto_style_new_layers`：根据数据内容自动生成样式。
- `check_and_auto_style_layers`：检查并更新需要自动样式的图层。
- `apply_intelligent_color_scheme`：根据色彩理论给多个图层分别上色。
- `color_layers_by_attribute`：按属性字段做层内分类上色（写入
  `style_conditions`，供 Cesium 按要素着色）；用户说「按区上色」时应优先用它。

### 属性分析 (`attribute_tools.py`, `attribute_tool2.py`)

用于分析、筛选和汇总地图要素的属性表数据。

- `attribute_tool`：使用类 SQL 条件查询和筛选数据，例如 `population > 100000`。
- `attribute_tool2`：简化版属性工具，支持字段列表、统计汇总、唯一值、筛选、排序、字段选择和数据集描述。

### 状态管理 (`geostate_management.py`)

用于管理当前会话中的地理数据状态。

- `list_user_layers`：列出当前地图上已加载的图层和工具生成的结果图层。
- `metadata_search`：使用语义相似度搜索已加载图层或近期结果。
- `add_layers_to_map`：将结果集合中的图层 promote 到 `geodata_layers`（上图），
  避免要求用户手动勾选结果列表。
- `describe_geodata_object`：获取指定图层的详细元数据。
- `create_execution_plan`：为复杂任务创建待用户确认的执行计划。
  开启计划模式后，当前请求仅允许调用此工具，生成计划后立即结束，等待下一次确认请求；
  多轮历史中的旧确认不授权新任务。计划步骤先转换为字典，再生成预览文本，兼容结构化参数解析。

### Python 分析 (`python_analysis_tool.py`)

用于在主后端进程之外执行受限的自定义数据分析。

- `run_python_analysis`：将选中的当前 GeoJSON 类图层和可选 Python 代码发送到隔离的 `analysis-sandbox` 服务。该工具会返回聊天摘要，并将沙箱生成的 GeoJSON 输出作为 `GeoDataObject` 存入 `geodata_results`。按名称解析图层时会同时搜索 `geodata_layers` 与 `geodata_results`（裁剪/缓冲结果层无需先上图）。
  - 沙箱 `inputs` 形状为 `{analysis_goal, layers: [...], params}`，**不是** `{图层名: geojson}`。注入助手：`find_layer(name)` / `layer_to_gdf(layer)` / `load_gdfs([...])`。
  - 环境变量：`PYTHON_ANALYSIS_SANDBOX_URL`（必填才能调用）、`PYTHON_ANALYSIS_MAX_FEATURES_PER_LAYER`（默认 2000）、`PYTHON_ANALYSIS_MAX_CALLS`（默认 5，会话级硬上限）、`PYTHON_ANALYSIS_SANDBOX_TIMEOUT`。
  - 图层被截断时工具消息会 WARNING；提高 `max_features_per_layer` 后重跑一次即可。面积 TopN 请投影到米制 CRS（如 EPSG:32650）再 `gdf.geometry.area`。
  - 修改 `sandbox/app/runner.py` 后**必须**重建 `analysis-sandbox` 镜像（`docker compose up --build analysis-sandbox`）；未重建会出现 `NameError: find_layer is not defined`。改 backend 工具逻辑只需重建/重启 `backend`。
  - 面积 TopN 优先：`geoprocess`（area）→ `attribute_tool2`（sort_by），避免浪费沙箱重试配额。

### 低效空间判别 (`inefficient_space_tools.py`)

用于城市低效空间识别（闲置空地、工业/商业/居住低效），对应 Skill `inefficient_space`。

- `get_inefficient_presets`：返回默认字段映射、阈值、类型标签与配色。
- `infer_inefficient_field_mapping`：从地块图层属性推断容积率/建筑密度/闲置年限/税收/用地性质字段；关键字段缺失时只返回一个澄清问题。
- `analyze_inefficient_space`：执行规则判别，将结果图层写入 `geodata_results`（可选加入地图），并返回分类汇总；若传入 `city_name` 会附带城市阈值记忆建议。

推荐 Agent 工作流：PostGIS/上传加载地块 → 字段推断 →（必要时澄清）→ 判别 → 中文汇总。独立业务面板见 `/inefficient-space` 与 `docs/inefficient-space.md`。

### Python 分析沙箱的联网/安装包模式

默认 `analysis-sandbox` 以非 root 用户、只读文件系统和最小 Linux capability 运行。这样更适合生产或多人环境，但运行时代码不能安装系统包，也不适合在分析代码里临时 `pip install` 大量依赖。

本地开发如需让沙箱以 root 身份运行，并允许联网下载 Python 包，可以叠加根目录的 `docker-compose.sandbox-unrestricted.yml`：

```bash
docker-compose -f dev.docker-compose.yml -f docker-compose.sandbox-unrestricted.yml up --build analysis-sandbox backend
```

生产编排也可以叠加同一个 override：

```bash
docker-compose -f docker-compose.yml -f docker-compose.sandbox-unrestricted.yml up --build
```

启用后，分析代码可通过当前 Python 解释器安装包，例如：

```python
import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "pip", "install", "contextily"],
    check=True,
)

import contextily
result = {"contextily_version": contextily.__version__}
```

可在 `.env` 中配置下载源和代理：

```env
PIP_INDEX_URL=https://pypi.org/simple
PIP_TRUSTED_HOST=
HTTP_PROXY=
HTTPS_PROXY=
NO_PROXY=localhost,127.0.0.1,backend,analysis-sandbox
```

注意：该模式会显著降低隔离强度，只建议在本地可信环境中使用。

### PostGIS 数据库 (`postgis_tools.py`)

用于发现和加载已配置 PostGIS 数据库中的空间表。

- `list_postgis_layers`：从 `geometry_columns` 列出可用空间表，可选按查询字符串过滤。
- `load_postgis_layer`：将选中的 PostGIS 表导出为已存储的 GeoJSON 数据流，并返回可用于地图显示、属性分析和空间处理的 `GeoDataObject`。


连接池生命周期：智能体的同步工具会为每次调用创建独立事件循环，因此数据库操作使用局部异步连接池，并在同一事件循环内关闭。不要跨工具调用缓存 `AsyncConnectionPool`，否则后台任务会随旧事件循环结束而停止，后续查询可能等待 30 秒后报 `PoolTimeout`，即使数据库和 `/api/postgis/tables` 接口正常。列表查询只读取 `geometry_columns` 元数据，PostGIS 扩展应在数据库初始化时启用。


### 数据发现 (`librarian_tools.py`, `geoserver/`)

用于查找外部或内部数据源。

- `query_librarian_postgis`：在内部 PostGIS 数据库中搜索数据集。
- `get_custom_geoserver_data`：连接外部 GeoServer 实例并获取数据。

## Skill 注册模式

智能体不再直接在 `backend/services/default_agent_settings.py` 中维护大段工具清单和系统提示词。当前模式如下：

- `backend/services/agent_skills/base.py`：定义 `AgentSkill`、工具展示元数据、动态选择元数据和关键词触发器。
- `backend/services/agent_skills/*.py`：每个文件声明一个具体 Skill，例如 PostGIS、GeoServer、属性分析、空间处理、样式、元数据、外部数据和 Python 分析。
- `backend/services/agent_skills/registry.py`：按顺序组合所有 Skill，并生成旧代码仍然使用的三个兼容变量：
  - `DEFAULT_AVAILABLE_TOOLS`
  - `TOOL_METADATA`
  - `DEFAULT_SYSTEM_PROMPT`

`backend/services/default_agent_settings.py` 现在只是兼容入口，从 Skill Registry 构建上述变量。动态工具选择器和计划工具别名也读取同一套 Skill 定义，避免 PostGIS、GeoServer、metadata 等规则在多个文件中重复维护。

## 添加新工具

1. 在合适的 `backend/services/tools/` 模块中创建新函数，并使用 `@tool` 装饰器。
2. 编写清晰的参数定义和 docstring；这些说明会被 LLM 用来判断何时调用工具。
3. 实现工具逻辑，并确保输入校验和错误信息清晰。
4. 在 `backend/services/agent_skills/` 中新增或更新对应 Skill：
   - `tools`：注册工具 key 到工具对象。
   - `tool_metadata`：配置设置页和 UI 展示信息。
   - `selector_metadata`：配置动态工具选择的语义描述。
   - `prompt`：写清楚何时使用、何时避免、与其他 Skill 的优先级。
   - `plan_aliases`：如需支持计划模式中的别名，添加归一化映射。
   - `keyword_triggers`：如需对明确关键词强制带上工具，在 Skill 内声明。
5. 如果是新 Skill，在 `backend/services/agent_skills/registry.py` 中加入 `SKILLS` 顺序。
6. 在 `backend/tests/` 中添加测试，至少覆盖工具注册、动态选择元数据和关键路由规则。
7. 如果工具面向用户或智能体工作流，更新本 README。
