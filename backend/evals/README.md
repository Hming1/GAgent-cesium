# Agent Evals

## LangSmith 真实对话人工评估

真实聊天通过 LangChain/LangGraph 原生追踪进入 LangSmith，支持按会话分组，
并通过 metadata 关联数据库审计记录。查看与评分步骤见
[LangSmith 配置指南](../../docs/langsmith-evaluation.md)；
人工评审标准见 [manual_review.json](langsmith/manual_review.json)。

## Live Geospatial Capability Eval（19 cases，端到端实测）

真实调用 LLM 的端到端评估：发送自然语言地理问题，记录工具调用链、产物与耗时，
自动判定回答质量与工具选择质量。

**完整报告见 [`live/agent-geospatial-eval.md`](live/agent-geospatial-eval.md)**
（含方法学、评分规则、19 题逐题结果、缺陷清单与修复建议）。

```bash
cd backend/evals/live

# 全量（走生产路径 /chat/stream）
python -X utf8 run_live_eval.py --mode stream --timeout 900

# 单题
python -X utf8 run_live_eval.py --only G01,P01,X01 --mode stream

# 结果汇总
python -X utf8 gen_tables.py
```

关键前提：

- `options` 中 `geoserver_backends`、`tools`、`model_settings.{model_provider,model_name,max_tokens}`
  为**必填**，缺失直接 500。
- 题库用注册表 key 书写，运行时比对需经 `TOOL_NAME_MAP` 映射
  （如 `geocode_nominatim` → `geocode_using_nominatim_to_geostate`）。
- 必须在**流式**端点测试：非流式 `/chat` 的递归上限仅 25，会系统性低估多步能力。

## Inefficient Space + PostGIS Harness（10 cases，确定性）

确定性 harness（不依赖 LLM），覆盖：

- Skill 关键词路由（低效空间 / PostGIS / 组合）
- 字段推断与澄清问题
- fixture 判别结果类型
- plan aliases

文件：

- [`harness/cases_inefficient_postgis.json`](harness/cases_inefficient_postgis.json)
- [`harness/runner.py`](harness/runner.py)
- [`harness/test_harness_inefficient_postgis.py`](harness/test_harness_inefficient_postgis.py)

运行：

```bash
cd backend
poetry run pytest evals/harness/test_harness_inefficient_postgis.py -q
poetry run python -m evals.harness.runner
```

## Expanded Harness（200 cases，确定性）

基于现有 Skill 关键词、字段别名、plan aliases、system prompt 与 live/questions
题库改写的大规模确定性套件（不依赖 LLM）。

文件：

- [`harness/cases_expanded_200.json`](harness/cases_expanded_200.json)
- [`harness/generate_cases_200.py`](harness/generate_cases_200.py)（可再生成）
- [`harness/test_harness_expanded_200.py`](harness/test_harness_expanded_200.py)

运行：

```bash
cd backend
# 如需重新生成题库
poetry run python -m evals.harness.generate_cases_200

poetry run pytest evals/harness/test_harness_expanded_200.py -q
poetry run python -m evals.harness.runner expanded_200
```

## Audit 通过率脚本

基于 `agent_runs` / `agent_run_events`（或 JSON 导出）统计：

- 运行成功且无工具错误
- 低效/PostGIS 相关 query 是否命中期望工具

```bash
# 内置样例（无 DB）
poetry run python -m evals.scripts.audit_pass_rate --sample

# 读库（近 7 天）
poetry run python -m evals.scripts.audit_pass_rate --hours 168

# 读导出 JSON
poetry run python -m evals.scripts.audit_pass_rate --from-json path/to/runs.json --out report.json
```
