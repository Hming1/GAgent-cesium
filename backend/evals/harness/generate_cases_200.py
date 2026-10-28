"""Generate a 200-case deterministic harness suite from project skills/terms.

Usage:
    poetry run python -m evals.harness.generate_cases_200
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from services.agent_skills import build_plan_tool_aliases
from services.agent_skills.inefficient_space import INEFFICIENT_TERMS
from services.agent_skills.postgis import POSTGIS_LOAD_TERMS, POSTGIS_TERMS
from services.inefficient_space.field_mapping import FIELD_ALIASES

HARNESS_DIR = Path(__file__).resolve().parent
OUT_PATH = HARNESS_DIR / "cases_expanded_200.json"

POSTGIS_TOOLS = [
    "list_postgis_layers",
    "load_postgis_layer",
    "get_custom_geoserver_data",
    "geoprocess",
    "attribute_tool2",
    "search_metadata",
]

INEFF_TOOLS = [
    "get_inefficient_presets",
    "infer_inefficient_field_mapping",
    "analyze_inefficient_space",
    "list_postgis_layers",
    "load_postgis_layer",
    "run_python_analysis",
    "geoprocess",
]

COMBO_TOOLS = [
    "list_postgis_layers",
    "load_postgis_layer",
    "get_inefficient_presets",
    "infer_inefficient_field_mapping",
    "analyze_inefficient_space",
    "get_custom_geoserver_data",
    "run_python_analysis",
]

ALL_INEFF_REQUIRED = [
    "get_inefficient_presets",
    "infer_inefficient_field_mapping",
    "analyze_inefficient_space",
]


def _postgis_list_queries() -> List[str]:
    templates = [
        "查看{term}里有哪些内容",
        "帮我列出{term}",
        "请查询{term}有哪些可用项",
        "我想盘点一下{term}",
        "先不要加载，只看{term}",
        "有哪些{term}可以分析？",
        "请用{term}做一次表清单",
        "检查当前配置的{term}",
    ]
    queries: List[str] = []
    for term in POSTGIS_TERMS:
        for tpl in templates:
            queries.append(tpl.format(term=term))
    # Extra paraphrases inspired by questions_agent_core / live cases.
    extras = [
        "数据库里有没有名字里带 park 或 公园 的空间表？先列出来，不要直接加载全部。",
        "我要查我们自己库里的空间数据表做分析，GeoServer 上那些 WMS 先别管。",
        "查看 PostGIS 中 geometry_columns 相关空间表",
        "postgresql 里有哪些空间表",
        "postgres 数据库里有什么表",
        "List PostGIS spatial tables first, do not load yet",
        "Show me database spatial tables matching road",
        "查询数据库有没有 parks 相关表",
        "资料库里有哪些空间表",
        "資料庫空間表有哪些",
    ]
    queries.extend(extras)
    return queries


def _postgis_load_queries() -> List[str]:
    tables = [
        "public.city_parks",
        "public.parcels",
        "public.roads",
        "layers.layer_深圳市",
        "public.landuse",
        "schema.table",
    ]
    verbs = list(POSTGIS_LOAD_TERMS) + ["导入到当前地图", "加载到地图", "add to map"]
    queries: List[str] = []
    for table in tables:
        for verb in verbs:
            queries.append(f"{verb} PostGIS 的 {table}")
            queries.append(f"从数据库{verb} {table}")
    extras = [
        "加载 PostGIS 的 public.city_parks 到地图",
        "把数据库里 parks 相关表加载到地图",
        "从 postgis 导入 public.parcels 到当前地图",
        "load postgres table public.roads to map",
        "把深圳市的行政边界表加载到地图上",
        "加载数据库空间表 public.landuse",
    ]
    queries.extend(extras)
    return queries


def _ineff_queries() -> List[str]:
    templates = [
        "请识别{term}",
        "帮我做一次{term}",
        "按规则执行{term}分析",
        "我想做{term}判别并上图",
        "开始{term}，先不要用 Python 沙箱",
        "对当前地块跑{term}",
        "请用专用工具完成{term}",
        "Evaluate {term} for parcels",
    ]
    queries: List[str] = []
    for term in INEFFICIENT_TERMS:
        for tpl in templates:
            queries.append(tpl.format(term=term))
    extras = [
        "请识别工业低效用地",
        "做一次闲置空地判别",
        "按容积率判别低效空间",
        "从数据库加载地块后识别低效空间和闲置空地",
        "建筑密度判别商业低效",
        "居住低效用地识别",
        "idle vacant land screening",
        "vacant land inefficient analysis",
        "识别低效用地并汇总面积",
        "低效空间阈值用默认预设即可",
    ]
    queries.extend(extras)
    return queries


def _combo_queries() -> List[str]:
    return [
        "从数据库加载地块后识别低效空间和闲置空地",
        "先查看数据库空间表，再做低效用地判别",
        "加载 PostGIS parcels 后做容积率判别",
        "查询数据库地块表并识别工业低效",
        "从资料库导入地块，然后做闲置空地分析",
        "postgis 加载地块后 analyze inefficient space",
        "查看数据库有哪些表，接着做低效空间",
        "加载数据库空间表再识别居住低效",
        "先 list 数据库表，再做建筑密度判别",
        "数据库里找 parcels，加载后做闲置用地判别",
        "从 postgresql 加载地块并识别商业低效",
        "查询数据库并执行 inefficient 分析",
        "加载 postgis 表后做 vacant land 判别",
        "查看空间表并识别低效用地",
        "从数据库导入地块做低效空间上图",
        "postgis + 低效空间组合分析",
        "资料库加载地块后容积率判别",
        "数据库空间表加载后 idle vacant 判别",
        "加载 schema.table 后再做工业低效",
        "先查数据库再做低效空间预设说明",
    ]


def _negative_queries() -> List[Dict[str, Any]]:
    """Queries without PostGIS/inefficient keyword triggers.

    Note: deterministic routing is keyword-based. Mentions of 「数据库」/「PostGIS」/
    「低效空间」会命中 trigger，不能作为负例。
    """
    forbid_all = [
        "list_postgis_layers",
        "load_postgis_layer",
        "analyze_inefficient_space",
        "get_inefficient_presets",
        "infer_inefficient_field_mapping",
    ]
    queries = [
        "你好，你是谁？",
        "平台支持哪些空间分析算子？列出 buffer 和 overlay",
        "先不要连库，也不要跑判别，只介绍能力",
        "从已配置 GeoServer 找道路相关 WMS 图层",
        "把杭州市行政边界加到地图，只要多边形",
        "以上海人民广场为中心找医院 POI",
        "杭州市明天的天气怎么样？",
        "看看北京最近有没有火点",
        "只把 rivers 图层改成蓝色透明",
        "对当前图层做 200 米缓冲区（图层已在地图）",
        "帮我找中学，地点还没定，先问我城市",
        "WMS/WFS 服务目录有哪些",
        "列出会话里已有图层，不要重新外网搜索",
        "把全世界学校都找出来——请先收敛到一个城市",
        "对当前选中图层做空间关系分析，可能是相交或裁剪，你看着办",
    ]
    cases = []
    for idx, query in enumerate(queries, start=1):
        cases.append(
            {
                "id": f"neg-routing-{idx:03d}",
                "skill": "none",
                "mode": "routing",
                "query": query,
                "available_tools": COMBO_TOOLS
                + ["geocode_nominatim", "geocode_overpass", "style_layers", "ecmwf_weather"],
                "expect_required_tools": [],
                "forbid_required_tools": forbid_all,
            }
        )
    return cases


def _infer_cases() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # Full Chinese match
    cases.append(
        {
            "id": "infer-full-zh",
            "skill": "inefficient_space",
            "mode": "infer_mapping",
            "columns": ["容积率", "建筑密度", "用地性质", "税收", "闲置年限"],
            "expect_matched": {
                "far": "容积率",
                "building_density": "建筑密度",
                "land_use": "用地性质",
                "tax_output": "税收",
                "idle_years": "闲置年限",
            },
            "expect_clarifying_question": False,
        }
    )

    # English aliases
    cases.append(
        {
            "id": "infer-full-en",
            "skill": "inefficient_space",
            "mode": "infer_mapping",
            "columns": [
                "floor_area_ratio",
                "building_density",
                "land_use",
                "tax_per_mu",
                "vacant_years",
            ],
            "expect_matched": {
                "far": "floor_area_ratio",
                "building_density": "building_density",
                "land_use": "land_use",
                "tax_output": "tax_per_mu",
                "idle_years": "vacant_years",
            },
            "expect_clarifying_question": False,
        }
    )

    # Short aliases
    cases.append(
        {
            "id": "infer-short-aliases",
            "skill": "inefficient_space",
            "mode": "infer_mapping",
            "columns": ["rjl", "jzmd", "ydxz", "shuishou", "idle_year"],
            "expect_matched": {
                "far": "rjl",
                "building_density": "jzmd",
                "land_use": "ydxz",
                "tax_output": "shuishou",
                "idle_years": "idle_year",
            },
            "expect_clarifying_question": False,
        }
    )

    # Case-insensitive
    cases.append(
        {
            "id": "infer-case-insensitive",
            "skill": "inefficient_space",
            "mode": "infer_mapping",
            "columns": ["FAR", "Density", "LANDUSE", "TAX", "IDLE_YEARS"],
            "expect_matched": {
                "far": "FAR",
                "building_density": "Density",
                "land_use": "LANDUSE",
                "tax_output": "TAX",
                "idle_years": "IDLE_YEARS",
            },
            "expect_clarifying_question": False,
        }
    )

    # Missing critical -> clarifying
    missing_sets = [
        (["name", "area_m2"], ["land_use"]),
        (["id", "geom"], ["land_use"]),
        (["用地性质"], ["far"]),  # land_use present, far/building_density missing -> far first
        (["容积率"], ["land_use"]),  # land_use missing first in CRITICAL_FIELDS order
        (["建筑密度", "闲置年限"], ["land_use"]),
        (["税收产出"], ["land_use"]),
        (["type_code", "area"], ["land_use"]),
        (["parcel_id"], ["land_use"]),
    ]
    for idx, (cols, critical) in enumerate(missing_sets, start=1):
        cases.append(
            {
                "id": f"infer-missing-{idx:02d}",
                "skill": "inefficient_space",
                "mode": "infer_mapping",
                "columns": cols,
                "expect_critical_missing_contains": critical,
                "expect_clarifying_question": True,
            }
        )

    # Per-alias smoke: each alias alone should match its canonical when other criticals present
    base_ok = {
        "far": "容积率",
        "building_density": "建筑密度",
        "land_use": "用地性质",
    }
    idx = 0
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            idx += 1
            columns = ["容积率", "建筑密度", "用地性质", "税收", "闲置年限"]
            # replace the canonical chinese with this alias
            replace_map = {
                "far": "容积率",
                "building_density": "建筑密度",
                "land_use": "用地性质",
                "tax_output": "税收",
                "idle_years": "闲置年限",
            }
            target = replace_map[canonical]
            columns = [alias if c == target else c for c in columns]
            cases.append(
                {
                    "id": f"infer-alias-{canonical}-{idx:03d}",
                    "skill": "inefficient_space",
                    "mode": "infer_mapping",
                    "columns": columns,
                    "expect_matched": {**base_ok, canonical: alias}
                    if canonical in base_ok
                    else {**base_ok, canonical: alias},
                    "expect_clarifying_question": False,
                }
            )
    return cases


def _plan_alias_cases() -> List[Dict[str, Any]]:
    aliases = build_plan_tool_aliases()
    items = sorted(aliases.items())
    cases: List[Dict[str, Any]] = []
    chunk_size = 6
    for i in range(0, len(items), chunk_size):
        chunk = dict(items[i : i + chunk_size])
        cases.append(
            {
                "id": f"plan-aliases-chunk-{(i // chunk_size) + 1:02d}",
                "skill": "registry",
                "mode": "plan_aliases",
                "aliases": chunk,
            }
        )
    return cases


def _registry_cases() -> List[Dict[str, Any]]:
    return [
        {
            "id": "registry-core-tools",
            "skill": "registry",
            "mode": "registry_tools",
            "expect_tools_present": [
                "list_postgis_layers",
                "load_postgis_layer",
                "geocode_nominatim",
                "geocode_overpass",
                "geoprocess",
                "attribute_tool2",
                "style_layers",
                "search_metadata",
                "list_user_layers",
                "create_execution_plan",
                "get_custom_geoserver_data",
                "analyze_inefficient_space",
                "infer_inefficient_field_mapping",
                "get_inefficient_presets",
            ],
        },
        {
            "id": "registry-osint-python",
            "skill": "registry",
            "mode": "registry_tools",
            "expect_tools_present": [
                "world_bank_indicators",
                "ecmwf_weather",
                "nasa_fire_data",
                "nasa_gibs_layer",
                "list_nasa_gibs_layers",
                "run_python_analysis",
            ],
        },
        {
            "id": "registry-styling-tools",
            "skill": "registry",
            "mode": "registry_tools",
            "expect_tools_present": [
                "style_layers",
                "apply_color_scheme",
                "autostyle_new_layers",
                "check_and_autostyle",
                "color_by_attribute",
            ],
        },
        {
            "id": "registry-metadata-categories",
            "skill": "registry",
            "mode": "registry_tools",
            "expect_tool_metadata": {
                "list_postgis_layers": {"category": "data_retrieval"},
                "load_postgis_layer": {"category": "data_retrieval"},
                "geoprocess": {"category": "geoprocessing"},
                "attribute_tool2": {"category": "attributes"},
                "style_layers": {"category": "styling"},
                "search_metadata": {"category": "metadata"},
                "create_execution_plan": {"category": "planning"},
                "geocode_nominatim": {"category": "geocoding"},
                "geocode_overpass": {"category": "geocoding"},
                "analyze_inefficient_space": {"category": "analysis"},
            },
        },
        {
            "id": "registry-no-azure-leftovers",
            "skill": "registry",
            "mode": "registry_tools",
            "forbid_tools_present": [
                "azure_blob_search",
                "azure_openai",
                "fake_tool",
            ],
        },
    ]


def _system_prompt_cases() -> List[Dict[str, Any]]:
    return [
        {
            "id": "prompt-chinese-reply",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["You MUST ALWAYS reply in Chinese"],
        },
        {
            "id": "prompt-skill-rules",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["Skill 调用规则", "geodata_layers"],
        },
        {
            "id": "prompt-clarify-one",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["只问一个会真正阻塞执行的澄清问题"],
        },
        {
            "id": "prompt-style-optin",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["样式是 opt-in"],
        },
        {
            "id": "prompt-fail-converge",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["工具失败收敛", "最多再尝试 1 次合理回退", "禁止空转"],
        },
        {
            "id": "prompt-postgis-routing",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": [
                "list_postgis_layers",
                "load_postgis_layer",
                "别管 GeoServer",
                "不要把 GeoServer 当作默认兜底",
            ],
        },
        {
            "id": "prompt-inefficient",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["低效空间", "analyze_inefficient_space"],
        },
        {
            "id": "prompt-geoprocess",
            "skill": "registry",
            "mode": "system_prompt",
            "expect_contains": ["geoprocess"],
        },
    ]


def _analyze_fixture_cases() -> List[Dict[str, Any]]:
    return [
        {
            "id": "analyze-fixture-basic",
            "skill": "inefficient_space",
            "mode": "analyze_fixture",
            "fixture": "inefficient_parcels.geojson",
            "expect_min_matched": 2,
            "expect_types_present": ["idle_vacant", "industrial"],
            "expect_types_absent": ["efficient"],
        },
        {
            "id": "analyze-fixture-has-idle",
            "skill": "inefficient_space",
            "mode": "analyze_fixture",
            "fixture": "inefficient_parcels.geojson",
            "expect_min_matched": 1,
            "expect_types_present": ["idle_vacant"],
        },
        {
            "id": "analyze-fixture-has-industrial",
            "skill": "inefficient_space",
            "mode": "analyze_fixture",
            "fixture": "inefficient_parcels.geojson",
            "expect_min_matched": 1,
            "expect_types_present": ["industrial"],
        },
    ]


def build_cases(target: int = 200) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # Fixed structural cases first
    cases.extend(_registry_cases())
    cases.extend(_system_prompt_cases())
    cases.extend(_analyze_fixture_cases())
    cases.extend(_plan_alias_cases())
    cases.extend(_negative_queries())
    cases.extend(_infer_cases())

    # Routing expansions
    for idx, query in enumerate(_postgis_list_queries(), start=1):
        cases.append(
            {
                "id": f"postgis-list-{idx:03d}",
                "skill": "postgis",
                "mode": "routing",
                "query": query,
                "available_tools": POSTGIS_TOOLS,
                "expect_required_tools": ["list_postgis_layers"],
                "forbid_required_tools": ["get_custom_geoserver_data"],
            }
        )

    for idx, query in enumerate(_postgis_load_queries(), start=1):
        cases.append(
            {
                "id": f"postgis-load-{idx:03d}",
                "skill": "postgis",
                "mode": "routing",
                "query": query,
                "available_tools": POSTGIS_TOOLS,
                "expect_required_tools": ["list_postgis_layers", "load_postgis_layer"],
            }
        )

    for idx, query in enumerate(_ineff_queries(), start=1):
        cases.append(
            {
                "id": f"ineff-routing-{idx:03d}",
                "skill": "inefficient_space",
                "mode": "routing",
                "query": query,
                "available_tools": INEFF_TOOLS,
                "expect_required_tools": ["analyze_inefficient_space"],
                "forbid_required_tools": ["run_python_analysis"],
            }
        )

    for idx, query in enumerate(_combo_queries(), start=1):
        cases.append(
            {
                "id": f"combo-routing-{idx:03d}",
                "skill": "combined",
                "mode": "routing",
                "query": query,
                "available_tools": COMBO_TOOLS,
                "expect_required_tools": [
                    "list_postgis_layers",
                    "analyze_inefficient_space",
                ],
            }
        )

    # De-duplicate by id, then trim/pad to exactly target
    seen = set()
    unique: List[Dict[str, Any]] = []
    for case in cases:
        cid = case["id"]
        if cid in seen:
            continue
        seen.add(cid)
        unique.append(case)

    if len(unique) < target:
        # Pad with more postgis list paraphrases using numeric suffixes
        pad_i = 0
        while len(unique) < target:
            pad_i += 1
            term = POSTGIS_TERMS[pad_i % len(POSTGIS_TERMS)]
            unique.append(
                {
                    "id": f"postgis-list-pad-{pad_i:03d}",
                    "skill": "postgis",
                    "mode": "routing",
                    "query": f"请再次列出{term}（样例 {pad_i}）",
                    "available_tools": POSTGIS_TOOLS,
                    "expect_required_tools": ["list_postgis_layers"],
                    "forbid_required_tools": ["get_custom_geoserver_data"],
                }
            )
    elif len(unique) > target:
        # Prefer keeping non-routing structural cases; sample routing by category.
        keep_prefix = [
            c
            for c in unique
            if not str(c["id"]).startswith(
                ("postgis-list-", "postgis-load-", "ineff-routing-", "combo-routing-")
            )
        ]
        buckets = {
            "postgis-list-": [
                c for c in unique if str(c["id"]).startswith("postgis-list-")
            ],
            "postgis-load-": [
                c for c in unique if str(c["id"]).startswith("postgis-load-")
            ],
            "ineff-routing-": [
                c for c in unique if str(c["id"]).startswith("ineff-routing-")
            ],
            "combo-routing-": [
                c for c in unique if str(c["id"]).startswith("combo-routing-")
            ],
        }
        need = target - len(keep_prefix)
        if need < 0:
            unique = unique[:target]
        else:
            # Allocate slots: list 35% / load 25% / ineff 25% / combo 15%
            ratios = {
                "postgis-list-": 0.35,
                "postgis-load-": 0.25,
                "ineff-routing-": 0.25,
                "combo-routing-": 0.15,
            }
            quotas = {key: max(1, int(need * ratio)) for key, ratio in ratios.items()}
            # Fix rounding so sum(quotas) == need
            while sum(quotas.values()) > need:
                for key in ("postgis-list-", "postgis-load-", "ineff-routing-"):
                    if quotas[key] > 1 and sum(quotas.values()) > need:
                        quotas[key] -= 1
            while sum(quotas.values()) < need:
                quotas["postgis-list-"] += 1

            selected: List[Dict[str, Any]] = []
            for key, quota in quotas.items():
                selected.extend(buckets[key][:quota])
            unique = keep_prefix + selected[:need]

    # Re-number is not needed; assert exact count
    assert len(unique) == target, f"expected {target} cases, got {len(unique)}"
    return unique


def main() -> None:
    cases = build_cases(200)
    OUT_PATH.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    modes: Dict[str, int] = {}
    skills: Dict[str, int] = {}
    for case in cases:
        modes[case["mode"]] = modes.get(case["mode"], 0) + 1
        skills[case.get("skill", "")] = skills.get(case.get("skill", ""), 0) + 1
    print(f"Wrote {len(cases)} cases -> {OUT_PATH}")
    print("modes:", json.dumps(modes, ensure_ascii=False))
    print("skills:", json.dumps(skills, ensure_ascii=False))


if __name__ == "__main__":
    main()
