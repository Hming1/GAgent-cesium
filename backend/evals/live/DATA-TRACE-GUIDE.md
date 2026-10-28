# 数据结果获取与溯源判断指南

> 适用项目：`D:\code\Gagent-cesium`（GeoAgent）
> 验证时间：2026-10-21，基于实际运行验证（非仅读代码）
> 验证脚本：[`verify_trace.py`](verify_trace.py)

---

## 一、结论速览

| 问题 | 答案 |
|------|------|
| Agent 搜索的数据结果能拿到吗？ | ✅ **能**。`/api/chat/stream` 的 `result` 事件返回 `geodata_results`，含完整元数据 |
| 能展示数据详情吗？ | ✅ **能（图层级）**。前端点"详情"显示描述、来源、类型、边界框、处理信息 |
| 能看到要素级属性表吗？ | ⚠️ **UI 不直接支持**。需取回 `data_link` 的 GeoJSON，或让 Agent 用 `attribute_tool2` 描述 |
| 结果与预期不符能溯源吗？ | ✅ **能，四层可查**（见 §四） |
| 有现成的审计查询接口吗？ | ❌ **没有**。审计已入库，但需直接查 PostgreSQL |
| 数据文件持久化了吗？ | ⚠️ **没有**。`/app/uploads` 未挂载，重建容器会丢失 |

---

## 二、数据结果怎么拿到（三种方式）

### 方式 1：前端 UI

聊天返回后，结果面板（`SearchResults.tsx`）每条结果提供：

- 标题、`llm_description` 摘要
- **类型**按钮 → 显示 `layer_type`
- **详情**按钮 → 弹出：

| 详情面板字段 | 对应数据字段 |
|---|---|
| 描述 | `llm_description` / `description` |
| 数据来源 | `data_source` |
| 图层类型 | `layer_type` |
| 边界框 | `bounding_box` |
| 来源图层 | `processing_metadata.origin_layers` |
| 操作 | `processing_metadata.operation` |
| 使用的 CRS | `processing_metadata.crs_used` |
| CRS 名称 | `processing_metadata.crs_name` |
| 选择原因 | `processing_metadata.selection_reason` |
| 预计误差 | `processing_metadata.expected_error` |

> 注意：UI **不显示** `data_link`、`sha256`、`size`、`id`、`properties`。

### 方式 2：API 响应（完整字段）

`POST /api/chat/stream` 的 `event: result` 里 `geodata_results` 每条包含：

```jsonc
{
  "id": "42dfe55108f745dc900b3ff39ce459e0_237036391.json",
  "name": "深圳市",
  "title": "深圳市",
  "data_source": "Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright",
  "data_source_id": "geocodeNominatim",        // ← 哪个工具产出
  "data_type": "GeoJson",
  "data_origin": "tool",
  "data_link": "http://39.105.94.209/api/stream/42dfe...json",  // ← 原始数据地址
  "layer_type": "GeoJSON",
  "bounding_box": "POLYGON((115.389 21.821, ...))",
  "sha256": "fec0a0ed505d7396f51a71bc00c0918a8954dd4b4808c46bbae897bea237ef09",
  "size": 143911,
  "score": 0.66507068790013,
  "properties": {
    "place_id": 237036391,
    "osm_type": "relation",
    "osm_id": 3464353,                          // ← 可回溯到 OSM 原始对象
    "licence": "Data © OpenStreetMap contributors, ODbL 1.0..."
  },
  "processing_metadata": { "operation": "buffer", "crs_used": "EPSG:32650", ... }
}
```

### 方式 3：原始数据文件

```bash
# 直接取回 GeoJSON（实测 HTTP 200，143911 bytes）
curl -s "http://<BASE_URL>/api/stream/<id>" -o data.geojson

# 校验完整性：sha256 必须与响应里的字段一致
sha256sum data.geojson
# fec0a0ed...ef09  ← 与 geodata_results[].sha256 完全相同（已验证）
```

也可以在容器内直接找文件：

```bash
docker exec gagent-cesium-backend-1 ls -lh /app/uploads | head
docker cp gagent-cesium-backend-1:/app/uploads/<id> ./data.geojson
```

---

## 三、完整字段含义（溯源用）

| 字段 | 含义 | 溯源价值 |
|------|------|----------|
| `id` | 产物文件标识 | 用于 `data_link` 取回、审计比对 |
| `data_source` | 人类可读的数据来源（含许可） | 判断是 OSM / 高德 / PostGIS / 计算产物 |
| `data_source_id` | 产出来源标识 | **关键**：`geocodeNominatim` / `geocodeAmap` / `PostGIS` / `GeoAgentGeoprocess` / `GeoAgentPythonAnalysis` |
| `name` / `title` | 图层名 / 显示名 | 定位是哪一步的产物 |
| `data_type` | `GeoJson` / `postgis` / `Raster` | 数据类型 |
| `data_origin` | `tool` / `uploaded` / `geprocessing` | 是工具产出还是用户上传 |
| `data_link` | 原始数据 URL | **关键**：取回真实几何与属性 |
| `bounding_box` | 空间范围 WKT | 判断范围是否符合预期 |
| `sha256` / `size` | 文件指纹与大小 | **完整性校验**，排除文件损坏 |
| `score` | 相似度/置信分 | 数据检索类结果的相关性 |
| `properties` | 上游原始属性 | **关键**：常含 `osm_id`/`place_id`/`licence` |
| `processing_metadata` | 处理过程 | **关键**：算子、CRS、输入图层 |

---

## 四、溯源判断的四层模型

### L1 — 图层级：这是什么东西？

**看**：`data_source`、`data_source_id`、`data_type`、`data_origin`

**判断**：
- `data_source_id = geocodeNominatim` → 来自 OSM/Nominatim
- `data_source_id = geocodeAmap` → 来自高德（国内 POI 更全，但坐标系需注意）
- `data_source_id = PostGIS` → 来自你自己的 `layers` 库某张表
- `data_source_id = GeoAgentGeoprocess` → 是空间计算产物，**不是原始数据**
- `data_source_id = GeoAgentPythonAnalysis` → 沙箱计算结果，精度取决于依赖与算法

> ⚠️ 若看到 `GeoAgentPythonAnalysis`，要特别警惕：沙箱曾缺 `geopandas`，
> 会退化为"按米转度"近似算法。修复后应优先看到 `GeoAgentGeoprocess`。

### L2 — 原始数据级：几何和属性对不对？

**做法**：取回 `data_link` 的 GeoJSON，检查：

```bash
curl -s "<data_link>" -o out.geojson
python -c "
import json
d = json.load(open('out.geojson', encoding='utf-8'))
feats = d.get('features') if d.get('type')=='FeatureCollection' else [d]
print('type:', d.get('type'), 'features:', len(feats))
f = feats[0]
print('geometry:', f['geometry']['type'])
print('props:', list(f['properties'].keys())[:20])
"
```

**注意**：有时返回的是单个 `Feature` 而非 `FeatureCollection`
（实测深圳市边界就是 `{"type":"Feature", ...}`，`features` 为 0 是正常的）。

**校验完整性**：`sha256sum` 与 `sha256` 字段比对，不一致说明文件被改动或损坏。

### L3 — 上游源级：能不能回到原始出处？

**看** `properties` 里的标识符：

| 来源 | 可回溯字段 | 怎么用 |
|------|-----------|--------|
| OSM / Nominatim | `osm_type` + `osm_id` | 访问 `https://www.openstreetmap.org/relation/3464353` 查看原始边界 |
| 高德 / 百度 | `place_id` 等 | 在高德开放平台按 POI ID 复查 |
| PostGIS | 表名在 `name` / `data_source` 里 | `SELECT count(*) FROM layers.public."layer_深圳市";` |
| NASA / ECMWF | 时间戳、参数在 `properties` | 对照官方数据接口 |

**实测示例**：深圳市边界 `osm_type=relation`、`osm_id=3464353`，
直接打开 `https://www.openstreetmap.org/relation/3464353` 即可看到同一几何。

### L4 — 执行轨迹级：Agent 到底调了什么？

**审计表已默认开启**（`enable_agent_audit=True`），记录在 `agent_runs` / `agent_run_events`。

**没有查询接口，需直接查库**：

```bash
# 1) 找到这次会话的运行
docker exec gagent-cesium-db-1 psql -U app -d app -c "
SELECT id, endpoint, status, model_name, left(query,50) AS query, started_at
FROM agent_runs
WHERE session_id = '<你的 session_id>'
ORDER BY created_at DESC LIMIT 5;"

# 2) 看完整工具链（这是判断"它是不是查错地方"的核心证据）
docker exec gagent-cesium-db-1 psql -U app -d app -c "
SELECT sequence, event_type, name,
       left(coalesce(input::text,''), 80)  AS input,
       left(coalesce(output::text,''), 100) AS output
FROM agent_run_events
WHERE run_id = '<上面的 id>'
ORDER BY sequence;"
```

**实测输出示例**（14 条事件）：

```
1  run_start    /chat/stream                    {"query": "把深圳市行政边界加载到地图上..."}
2  tool_start   geocode_using_nominatim_to_geostate   {"query":"深圳市","require_boundary":true}
3  tool_end     geocode_using_nominatim_to_geostate   Command(update={...})
5  state_update geocode_using_nominatim_to_geostate   status=success
6  tool_start   attribute_tool2                  describe_dataset
7  tool_end     attribute_tool2                  {"operation":"describe_dataset",...}
8-13 llm_start/llm_end ×3
14 run_end      success                         duration_ms=19401
```

**能判断什么**：
- 用了哪个工具、传了什么参数（`query` 是否被改写、`require_boundary` 是否设对）
- 工具返回是否成功（`status`）
- 每一步耗时（`llm_end.latency_ms`）
- 最终状态（`run_end.status`）

---

## 五、"结果和预期不一样"怎么排查

按下面顺序走，能定位 90% 的差异：

### 步骤 1：先看是不是数据源不同（最常见）

```bash
# 查这次用了哪个数据源
psql -c "SELECT name, event_type FROM agent_run_events WHERE run_id='...' AND event_type='tool_start';"
```

| 你的预期 | 实际可能 | 差异原因 |
|---|---|---|
| 想查国内的 POI | 走了 Nominatim/OSM | 国内 OSM 覆盖差，应走 `geocode_overpass` 或高德 |
| 想查行政边界 | 走了 POI 检索 | 应设 `require_boundary=True` |
| 想用自己库里的表 | 走了外部地理编码 | 应显式说"用数据库里的表" |
| 想要原始数据 | 拿到的是计算结果 | `data_source_id` 是 `GeoAgentGeoprocess` |

### 步骤 2：再看空间范围对不对

比对 `bounding_box` 与你预期的范围：

```bash
# 从响应里取 bounding_box，看经纬度是否覆盖预期区域
```

常见问题：地理编码把"深圳市"解析成了市中心点而非行政边界；
或 POI 检索半径过大/过小。

### 步骤 3：看要素数量与属性

```bash
curl -s "<data_link>" -o out.geojson
python -c "
import json
d=json.load(open('out.geojson',encoding='utf-8'))
f=d.get('features') if d.get('type')=='FeatureCollection' else [d]
print('数量:', len(f))
print('几何类型:', {x['geometry']['type'] for x in f})
print('属性键:', list(f[0]['properties'].keys()))
"
```

数量明显偏少 → 可能是查询范围限制、`row_limit` 截断，或用了低覆盖数据源。

### 步骤 4：看 CRS 与处理过程（计算结果专用）

```bash
psql -c "SELECT operation, crs_used, auto_selected, origin_layers FROM ..."
```

或用 API 响应里的 `processing_metadata`。

**要点**：
- `crs_used = EPSG:4326` 却做了米制缓冲 → **精度有问题**（度不是米）
- 正确应为本地投影，如 `EPSG:32650`（UTM 50N）或 `EPSG:3857`
- `origin_layers` 列出了输入图层，可核对是否用错了图层
- `auto_selected = true` 表示 CRS 是自动选的，`selection_reason` 说明了理由

### 步骤 5：看面积/长度类结果是否受 CRS 影响

面积、缓冲距离、长度这类量测对投影敏感。
同一块地在 `EPSG:4326` 直接算面积会得到**平方度**（无意义），
必须投影后再算。若结果数量级明显离谱，先查 `crs_used`。

### 步骤 6：确认不是数据本身变了

OSM / 高德的数据会随时间变化。若同一查询隔天结果不同：

```bash
# 比对 sha256
sha256sum out_今天.geojson out_昨天.geojson
```

不同则说明上游数据变了，不是系统问题。

---

## 六、实操速查

```bash
cd D:\code\Gagent-cesium

# ---- 1. 复现一次查询并拿到完整详情（含 data_link 取回与 sha256 校验）----
cd backend\evals\live
..\..\.venv\Scripts\python.exe -X utf8 verify_trace.py

# ---- 2. 查最近的审计运行 ----
docker exec gagent-cesium-db-1 psql -U app -d app -c "
SELECT id, session_id, left(query,40) AS q, status, started_at
FROM agent_runs ORDER BY created_at DESC LIMIT 10;"

# ---- 3. 查某次运行的工具链 ----
docker exec gagent-cesium-db-1 psql -U app -d app -c "
SELECT sequence, event_type, name
FROM agent_run_events
WHERE run_id='<run_id>' ORDER BY sequence;"

# ---- 4. 取回原始 GeoJSON ----
curl -s "http://<BASE_URL>/api/stream/<id>" -o data.geojson
sha256sum data.geojson

# ---- 5. 看磁盘上的产物 ----
docker exec gagent-cesium-backend-1 ls -lht /app/uploads | head -20
docker cp gagent-cesium-backend-1:/app/uploads/<id> ./data.geojson

# ---- 6. 核对 PostGIS 原始表 ----
docker exec gagent-cesium-db-1 psql -U app -d layers -c "
SELECT count(*) FROM public.\"layer_深圳市\";"
```

---

## 七、已知限制（重要）

| 限制 | 影响 | 建议 |
|------|------|------|
| **无审计查询 API** | 只能查库，非技术用户无法自助溯源 | 可加 `GET /api/audit/runs?session_id=` 接口 |
| **`uploads/` 未挂载卷** | 重建容器会丢失全部产物（当前 146MB / 140 文件） | compose 加 `- ./data/uploads:/app/uploads` |
| **UI 无要素级属性表** | 看不到每个点的字段值 | 取 `data_link`，或让 Agent 用 `attribute_tool2` 的 `list_fields`/`describe_dataset` |
| **`data_link` 用外部 IP** | `.env.external` 里 `BASE_URL=http://39.105.94.209`，换网络可能打不开 | 本地开发改为 `http://localhost:8000` |
| **无数据血缘图** | 多步派生关系要自己串 `origin_layers` | 按 `processing_metadata.origin_layers` 手工回溯 |
| **`data_link` 可能是 Feature** | 解析器若只认 `FeatureCollection` 会得到 0 要素 | 两种都兼容处理 |

---

## 八、一句话总结

**能拿到、能展示、能溯源**，但溯源能力分散在三处：
前端详情面板（图层级）、`data_link` 的 GeoJSON（数据级）、
`agent_runs`/`agent_run_events`（执行级）。

判断差异时的顺序是：
**先查数据源（L1）→ 再查范围与要素（L2）→ 回溯原始出处（L3）→ 最后看工具链（L4）**。
绝大多数"结果不对"是第一步的数据源选错，或第四步的地理编码把行政区当成了中心点。
