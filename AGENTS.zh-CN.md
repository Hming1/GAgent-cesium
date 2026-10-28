# AGENTS.zh-CN.md — AI 开发上下文（中文版）

> **目标读者**：AI 编程助手（Cursor、Copilot、DeepSeek 等）与自动化开发工具。
>
> 本文件是 [AGENTS.md](AGENTS.md) 的中文版本，规则与路径保持一致。
> 标准开发流程请参阅 **[CONTRIBUTING.md](CONTRIBUTING.md)**（该文档目前仅有英文版）。

---

## 📌 本仓库说明（Gagent-cesium 分支）

本仓库是 [GeoAgent](https://github.com/nalamap/nalamap) 的一个分支，相对上游的主要差异：

- 前端地图在 Leaflet 之外引入了 **Cesium 3D 地球**（`resium` + `cesium`），
  见 `frontend/app/components/maps/CesiumMapClient.tsx` 与 `CesiumBasemapLayers.tsx`。
- 新增 **Agent 技能注册表** `backend/services/agent_skills/`，
  取代了原先集中在 `default_agent_settings.py` 里的配置方式。
- 其他新增模块：`services/inefficient_space/`（低效空间识别）、
  `services/conversation/`（会话持久化）、`services/memory/`（短期记忆）、
  `services/auth/`（邀请制注册）、`services/tools/geocoding_fallback.py`（高德/百度回退）。

---

## 🤖 AI 助手的核心准则

参与本仓库开发时，你**必须**遵守以下规则：

1. **唯一事实来源（Single Source of Truth）**
   所有开发流程（测试、Lint、运行）都以 **[CONTRIBUTING.md](CONTRIBUTING.md)** 为准，
   不要臆造其他替代流程。

2. **测试驱动开发（TDD）**
   - **始终**先运行已有测试，建立基线。
   - **始终**为新功能或缺陷修复编写新测试。
   - **验证**改动时运行对应的测试套件（后端 `pytest`，前端 `playwright`）。

3. **代码质量**
   - **Lint 是强制的**。修改文件后，必须运行 [CONTRIBUTING.md](CONTRIBUTING.md) 中定义的
     linter（`flake8`、`black`、`npm run lint`）。
   - 立即修复 lint 报错，不要提交带 lint 违规的代码。

4. **文档**
   - 如果改动了某个组件的工作方式，更新对应的 `README.md`。
   - 如果新增了工具，更新 `backend/services/tools/README.md`。
   - 如果新增了依赖，更新 `pyproject.toml` 或 `package.json`。

---

## 🗺️ 仓库地图与上下文

帮助你高效浏览代码库：

### 后端结构（`backend/`）

- **应用入口**：`main.py`（FastAPI app），所有 router 统一挂载在 `/api` 前缀下，
  涵盖 auth、nalamap（主对话）、layers、maps、postgis_layers、data_management、
  ai_style、auto_styling、conversations、memory、mcp、proxy、settings、
  file_streaming、debug、inefficient_space 等。
- **API 层**：`api/`（FastAPI 端点）。
- **业务逻辑**：`services/`（AI Agent、工具、数据库逻辑）
  - `services/agents/`：早期版本的 Agent 实现（legacy）。
  - `services/agent_skills/`：**Agent 技能注册表**，按领域拆分（`geocoding`、
    `geoprocessing`、`styling`、`postgis`、`osint`、`planning`、`python_analysis`、
    `metadata`、`attributes`、`inefficient_space`、`registry`、`base`）。
    新增工具必须在此注册。
  - `services/tools/`：**核心 AI 工具**（地理编码、地理处理）。
    详见 `backend/services/tools/README.md`。
  - `services/ai/`：LLM provider 抽象层（`vllm` / `kimi` / `deepseek`），
    每个 provider 暴露 `get_llm()`。
  - `services/single_agent.py`：主 Agent 入口（LangGraph ReAct）。
  - `services/tool_selector.py`：工具选择逻辑。
  - `services/multi_agent_orch.py`：多 Agent 编排。
- **数据模型**：`models/`（Pydantic 模型）、`db/models/`（SQLAlchemy 模型）。
- **数据库**：`db/session.py`（连接与会话）、`alembic/`（迁移脚本）。
- **测试**：`tests/`（pytest 套件）。详见 `backend/tests/README.md`。

### 前端结构（`frontend/`）

- **页面**：`app/page.tsx`（主入口）。
- **组件**：`app/components/`（React 组件）
  - `maps/`：地图实现，包含 `CesiumMapClient.tsx`（Cesium 3D）与
    `LeafletMapClient.tsx`（Leaflet 2D）。
  - `chat/`：AI 对话界面。
  - `sidebar/`：图层与底图管理侧栏。
  - `inefficient-space/`：城市低效空间识别工作台。
- **状态管理**：`app/stores/`（Zustand stores）。
- **测试**：`tests/`（Playwright E2E）。详见 `frontend/tests/README.md`。

### 关键配置文件

- `backend/pyproject.toml`：Python 依赖与工具配置（flake8、black、pytest markers）。
- `frontend/package.json`：Node 依赖与脚本。
- `docker-compose.yml`：生产部署。
- `dev.docker-compose.yml`：开发环境（热重载）。
- `.env` / `.env.example`：环境变量模板（LLM provider、数据库、地理编码密钥等）。
  本地调试与外部部署使用不同的 URL / Cookie 配置，
  启动前请先阅读 `docs/environment-profiles.md`。

---

## 🛠️ Agent 常见任务

### 1. 新增一个 AI 工具

当需要为 AI 助手增加新能力时：

1. 在 `backend/services/tools/` 下创建工具函数。
2. 使用 `langchain.tools` 的 `@tool` 装饰器。
3. 在 `backend/tests/` 中添加单元测试。
4. **注册工具**：在 `backend/services/agent_skills/` 下对应的 Skill 中登记
   （`tools`、`tool_metadata`、`selector_metadata`、`prompt`、`plan_aliases`）。
   注意：`backend/services/default_agent_settings.py` 只是重新导出注册表构建的结果，
   不要直接修改它。
5. 在 `backend/services/tools/README.md` 中补充文档。

### 2. 修改 Agent 工作流

主 Agent 逻辑位于 `backend/services/single_agent.py`（LangGraph ReAct Agent）。

- 若修改系统提示词：编辑 `BASE_SYSTEM_PROMPT`，或 `backend/services/agent_skills/`
  中某个 Skill 的 `prompt`；`DEFAULT_SYSTEM_PROMPT` 由它们组合而成。
- 若修改工具选择逻辑：查看 `create_geo_agent` 与 `backend/services/tool_selector.py`。

### 3. 调试

如果测试失败：

- **后端**：阅读 `pytest` 输出，用 `pytest -vv` 查看更多细节；
  如有 `backend/app_output.log` 也一并查看。
- **前端**：使用 `npx playwright test --ui`，或查看 HTML 报告。

---

## 🔄 快速命令参考

> **完整列表见 [CONTRIBUTING.md](CONTRIBUTING.md)。**

- **运行后端测试**：`cd backend && poetry run pytest`
- **运行前端测试**：`cd frontend && npx playwright test`
- **Lint 后端**：`cd backend && poetry run flake8 . && poetry run black .`
- **Lint 前端**：`cd frontend && npm run lint`
- **启动后端**：`cd backend && poetry run python main.py`（端口 8000）
- **启动前端**：`cd frontend && npm run dev`（端口 3000）
