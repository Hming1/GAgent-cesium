# 城市低效空间判别与识别（一期）

独立业务工作台，用于按指标体系对矢量地块进行低效空间判别，并将结果专题上图。

## 入口

- 前端路由：`/inefficient-space`
- 侧栏图标：低效空间判别（Building 图标）
- 布局：左侧配置面板 + 中央地图 + 右侧（结果摘要 + 智能体对话）
- **Agent 聊天**：右侧「低效空间助手」支持自然语言触发（如「识别工业低效用地」「闲置空地判别」），由 `inefficient_space` Skill 编排 PostGIS 加载 → 字段推断 → 判别 → 汇总

## Agent Skill

| 工具键 | 作用 |
|--------|------|
| `get_inefficient_presets` | 默认阈值与字段别名 |
| `infer_inefficient_field_mapping` | 推断字段映射；缺关键字段时只问一个问题 |
| `analyze_inefficient_space` | 执行判别并上图 |

计划模式别名含：`低效空间`、`闲置空地`、`容积率判别`。开启 Plan Mode 时建议步骤：加载数据 → 字段映射 → 判别分析 → 结果说明。

## Harness / 评估

低效空间 + PostGIS 确定性 harness（10 条）与 audit 通过率脚本：

- [`backend/evals/README.md`](../backend/evals/README.md)
- `poetry run pytest evals/harness/test_harness_inefficient_postgis.py -q`
- `poetry run python -m evals.scripts.audit_pass_rate --sample`

## 一期能力

- **优先从 PostGIS 数据库加载**地块 / POI / 企业空间表（复用 `/api/postgis/tables` 与 `/api/postgis/layer/...`）
- 也可选择会话中已加载图层，或上传本地矢量作为备选
- 配置字段映射与四类阈值
- 输出命中要素 GeoJSON、统计摘要、按 `inefficient_type` 专题配色

一期影像仅作参考对照图层使用，不做自动影像解译。

数据库依赖与主站 PostGIS 一致：需配置 `GEODATA_DATABASE_URL`。

## 判别类型

| 类型键 | 中文 | 默认颜色 |
|--------|------|----------|
| `idle_vacant` | 闲置空地 | `#7f8c8d` |
| `industrial` | 工业低效 | `#c0392b` |
| `commercial` | 商业低效 | `#e67e22` |
| `residential` | 居住低效 | `#8e44ad` |

优先级：闲置空地优先；其余按用地性质路由到工业 / 商业 / 居住。

## 标准指标字段

| 规范名 | 含义 | 常见别名 |
|--------|------|----------|
| `far` | 容积率 | 容积率、plot_ratio |
| `building_density` | 建筑密度 | 建筑密度、density |
| `idle_years` | 闲置年限 | 闲置年限 |
| `tax_output` | 税收产出 | 税收、tax |
| `land_use` | 用地性质 | 用地性质、用地类型 |

## API

### `GET /api/inefficient-space/presets`

返回默认字段映射、阈值、用地性质提示词、类型标签与颜色。

### `POST /api/inefficient-space/analyze`

请求体主要字段：

```json
{
  "parcel_data_link": "http://localhost:8000/api/stream/....geojson",
  "poi_data_link": null,
  "enterprise_data_link": null,
  "field_mapping": { "far": "far", "land_use": "land_use" },
  "thresholds": {},
  "enabled_types": ["idle_vacant", "industrial", "commercial", "residential"],
  "include_non_match": false,
  "result_name": "低效空间判别结果"
}
```

响应：

```json
{
  "layer": { "id": "...", "data_link": "...", "style": { "style_conditions": {} } },
  "summary": {
    "total": 100,
    "matched": 23,
    "by_type": { "industrial": { "count": 10, "area_sqm": 12345 } },
    "area_stats": { "matched_area_sqm": 12345, "total_area_sqm": 99999 }
  }
}
```

结果要素属性至少包含：`inefficient_type`、`inefficient_score`、`matched_rules`、关键指标字段。

## 代码位置

- 后端服务：`backend/services/inefficient_space/`
- 后端 API：`backend/api/inefficient_space.py`
- 前端页面：`frontend/app/inefficient-space/page.tsx`
- 前端面板：`frontend/app/components/inefficient-space/`
- 测试：`backend/tests/test_inefficient_space.py`
