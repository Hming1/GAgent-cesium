# ARCHITECTURE.md - NaLaMap 系统架构

> **新增架构补充**：本文后续代码已引入 Agent Harness、Skill 与 Python 分析沙盒的最小实现路径。该补充说明 NaLaMap 如何把新 agent 能力显式暴露为工具，并把动态 Python 数据分析隔离到独立 sandbox 容器中。

## Agent Harness、Skill 与 Python 分析沙盒

本节补充 NaLaMap 后续扩展 agent 能力时推荐采用的架构：用 harness 做可重复评估，用 skill 表达 agent 可调用能力，用独立 sandbox 容器执行高风险 Python 数据分析。

### 设计目标

- 主 FastAPI backend 只负责编排、状态管理、可信业务逻辑和结果落图。
- 新能力应显式暴露为 LangChain `@tool` 或 MCP tool，而不是只藏在 prompt 里。
- agent 或用户提供的动态 Python 代码不能在主 backend 进程里执行。
- Python 分析结果如果产生新图层，应继续遵守 NaLaMap 现有约定：把结果写成 `GeoDataObject` 并更新到 `geodata_results`，由前端地图选择和渲染。

### 概念架构

```text
用户请求
    |
    v
NaLaMap Chat API
    |
    v
LangGraph GeoAgent
    |
    +--> 内置工具
    |       - geocoding
    |       - geoprocessing
    |       - attributes
    |       - styling
    |       - GeoServer discovery
    |
    +--> Skill 工具
            |
            +--> 本地 LangChain @tool
            |
            +--> 外部 MCP 工具
            |
            +--> Python analysis sandbox tool
                    |
                    v
              analysis-sandbox 容器
                    |
                    v
              JSON 摘要、artifact、GeoJSON 输出
                    |
                    v
              GeoDataObject 结果进入前端地图
```

### Agent Skill 边界

在 NaLaMap 中，skill 不建议做成隐式 prompt 能力，而应落成明确的工具接口：

- **本地 skill**：放在 `backend/services/tools/` 下，用 LangChain `@tool` 定义，并注册到 `backend/services/default_agent_settings.py`。适合可信、核心、需要直接更新 `GeoDataAgentState` 的能力。
- **外部 skill**：由独立 MCP server 提供，NaLaMap 通过现有 MCP 集成加载。适合组织私有、可插拔、单独部署或高风险能力。

每个 skill 都应有清晰的参数 schema、明确 docstring、资源上限、稳定输出结构。如果会生成地图图层，应返回或持久化 GeoJSON，并更新 `geodata_results`。

### Python 分析沙盒

Python sandbox 是独立服务，用来对当前会话图层执行受限数据分析。backend 不直接执行动态 Python，而是把有限的图层数据和分析任务发送给 sandbox。

第一阶段执行链路如下：

1. agent 调用 `run_python_analysis`。
2. tool 从 `GeoDataAgentState` 中解析用户选择的 `geodata_layers`。
3. 对 GeoJSON 图层做受限加载，并按 feature 数量截断，避免把超大数据直接送入 sandbox。
4. backend 把 `analysis_goal`、可选 Python `code` 和序列化后的图层输入发送给 sandbox。
5. sandbox 在独立容器内执行代码，并施加 timeout 和输出大小限制。
6. sandbox 返回 `summary`、`stdout`、`stderr`、`result`，以及可选的 `geojson_outputs`。
7. backend 将返回的 GeoJSON 输出存储为文件，并包装成 `GeoDataObject` 写入 `geodata_results`。

### 沙盒安全边界

sandbox 容器应被视为不可信执行环境，需要尽量限制能力：

- 不传入 LLM API key、数据库 URL、云存储密钥或用户认证 secret。
- 生产环境应使用非 root 用户运行。
- 设置运行时间、内存、CPU 和输出大小限制。
- 使用只读文件系统，只开放临时可写目录。
- 不挂载项目源码，不挂载 Docker socket。
- 只允许 backend 通过内部容器网络访问 sandbox。

sandbox 能降低风险，但不能单独视为完整安全边界。生产部署还需要容器加固、网络策略、请求鉴权、可观测性和任务清理机制。

### Agent Harness

harness 是 agent 行为的可重复评估层，建议放在 `backend/evals/` 下。它负责：

- 固定用户 query 和初始 `geodata_layers`。
- 固定 model settings 和 tool settings。
- 捕获 tool call 顺序和参数。
- 检查是否调用了预期 skill。
- 检查是否生成合法 GeoJSON 和预期 `GeoDataObject`。
- 记录运行时间、错误率和回归指标。

在大改 prompt、tool 描述、动态工具选择或新增 skill 前，应先补 harness case，保证优化后能和基线行为比较。

### 实现位置

- `backend/services/tools/python_analysis_tool.py`：暴露给 GeoAgent 的 LangChain tool。
- `backend/services/sandbox/client.py`：backend 到 sandbox 的 HTTP client。
- `backend/models/sandbox.py`：sandbox 请求和响应模型。
- `sandbox/`：独立 FastAPI 服务，负责受限 Python 执行。
- `docker-compose.yml` 与 `dev.docker-compose.yml`：增加可选 `analysis-sandbox` 服务，并放在内部网络。
- `backend/evals/`：后续放 agent harness 场景和回放测试。

---

> **用途**：全面说明 NaLaMap 的系统架构、组件组织方式与设计模式。  
> **面向对象**：需要理解系统结构的开发者、架构师与贡献者。

---

## 目录

1. [系统概览](#系统概览)
2. [高层架构](#高层架构)
3. [后端架构](#后端架构)
4. [前端架构](#前端架构)
5. [数据流与通信](#数据流与通信)
6. [AI Agent 架构](#ai-agent-架构)
7. [数据库与存储](#数据库与存储)
8. [部署架构](#部署架构)
9. [安全架构](#安全架构)
10. [扩展点](#扩展点)

---

## 系统概览

**NaLaMap** 是一个地理空间 AI 平台，允许用户使用自然语言与地理数据进行交互。系统将现代 Web 技术与 AI 能力结合起来，为地理空间分析提供直观的操作界面。

### 核心能力

- **地理空间数据管理**：上传、展示并管理矢量/栅格数据
- **AI 驱动分析**：通过自然语言进行地理空间查询
- **智能样式设计**：AI 辅助地图样式与可视化
- **地理处理**：自动化空间操作，如缓冲区、相交等
- **数据发现**：查找并整合外部地理空间数据源
- **地理编码**：基于 OSM 与 GeoNames 的位置搜索

### 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | Next.js 15、React 19、TypeScript、Leaflet、Tailwind CSS |
| **后端** | Python 3.11+、FastAPI、Uvicorn |
| **AI / ML** | LangChain、LangGraph、OpenAI / Azure / Google / Mistral / DeepSeek |
| **数据库** | PostgreSQL（含 PostGIS）、SQLite-vec |
| **基础设施** | Docker、Docker Compose、Nginx |
| **地图能力** | Leaflet、OpenStreetMap、WMS / WFS / WMTS / WCS |

---

## 高层架构

```text
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │            Next.js 前端（端口 3000）                  │  │
│  │  - React 组件  - Zustand 状态  - Leaflet 地图         │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │  │  │
                    HTTP / WebSocket
                          │  │  │
┌─────────────────────────────────────────────────────────────┐
│                    Nginx 反向代理                           │
│            （请求路由、CORS、静态资源服务）                 │
└─────────────────────────────────────────────────────────────┘
                          │  │  │
              ┌───────────┴──┴──┴───────────┐
              │                             │
              ▼                             ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│      FastAPI 后端        │    │       外部服务           │
│       （端口 8000）      │    │                          │
│                          │    │  - OpenAI / Azure AI     │
│  ┌────────────────────┐  │    │  - Google Gemini         │
│  │    API 接口层      │  │    │  - Mistral AI            │
│  └────────────────────┘  │    │  - DeepSeek              │
│  ┌────────────────────┐  │◄───┤  - OSM / GeoNames        │
│  │   AI Agent 系统    │  │    │  - OGC 服务              │
│  │    （LangGraph）   │  │    │  - Azure Blob Storage    │
│  └────────────────────┘  │    └──────────────────────────┘
│  ┌────────────────────┐  │
│  │  地理空间工具集合  │  │
│  └────────────────────┘  │
│  ┌────────────────────┐  │
│  │    向量存储        │  │
│  │   （SQLite-vec）   │  │
│  └────────────────────┘  │
└──────────────────────────┘
              │
              ▼
┌──────────────────────────┐
│    PostgreSQL 数据库     │
│     （含 PostGIS）       │
│   - 用户会话             │
│   - 图层元数据           │
│   - 设置项               │
└──────────────────────────┘
```

---

## 后端架构

### 目录结构

```text
backend/
├── main.py                    # FastAPI 应用入口
├── pyproject.toml             # Poetry 依赖与配置
├── poetry.lock                # 锁定依赖
│
├── api/                       # API 接口定义
│   ├── nalamap.py             # 主聊天 / Agent API
│   ├── data_management.py     # 数据上传 / 管理接口
│   ├── settings.py            # 设置 CRUD 接口
│   ├── auto_styling.py        # 自动样式接口
│   ├── ai_style.py            # AI 样式接口
│   ├── file_streaming.py      # 文件上传 / 流式接口
│   └── debug.py               # 调试 / 测试接口
│
├── core/                      # 核心配置
│   └── config.py              # 环境变量、配置项
│
├── models/                    # 数据模型（Pydantic）
│   ├── geodata.py             # GeoDataObject、LayerStyle
│   ├── states.py              # DataState、GeoDataAgentState
│   ├── settings_model.py      # 设置相关模型
│   ├── user.py                # 用户模型
│   └── messages/              # 消息模型
│       └── chat_messages.py   # NaLaMapRequest、NaLaMapResponse
│
├── services/                  # 业务逻辑
│   ├── single_agent.py        # 单 ReAct Agent（当前方案）
│   ├── multi_agent_orch.py    # 多 Agent 编排（遗留）
│   ├── background_tasks.py    # 异步后台任务
│   ├── default_agent_settings.py # 默认 Agent 配置
│   │
│   ├── agents/                # AI Agent 实现（遗留）
│   │   ├── nala_map_ai.py     # 主地理空间 AI Agent
│   │   ├── langgraph_agent.py # 基于 LangGraph 的 Agent
│   │   ├── supervisor_agent.py # Agent supervisor / router
│   │   └── geoprocessing_agent.py # 地理处理专用 Agent
│   │
│   ├── ai/                    # LLM Provider 集成
│   │   ├── llm_config.py      # LLM 配置管理
│   │   ├── openai.py          # OpenAI 集成
│   │   ├── azureai.py         # Azure OpenAI 集成
│   │   ├── google_genai.py    # Google Gemini 集成
│   │   ├── mistralai.py       # Mistral AI 集成
│   │   └── deepseek.py        # DeepSeek 集成
│   │
│   ├── tools/                 # AI Agent 工具（函数调用）
│   │   ├── geocoding.py       # 地理编码工具（OSM、GeoNames）
│   │   ├── styling_tools.py   # 地图样式工具
│   │   ├── geoprocess_tools.py # 地理处理操作
│   │   ├── attribute_tools.py # 属性分析
│   │   ├── librarian_tools.py # 数据发现 / 搜索
│   │   ├── geostate_management.py # 图层状态管理
│   │   ├── wms_tools.py       # OGC 服务工具
│   │   └── geoprocessing/     # 更细粒度的地理处理操作
│   │       └── ops/           # 单个空间操作
│   │
│   ├── database/              # 数据库连接器
│   │   └── database.py        # PostgreSQL 连接
│   │
│   └── storage/               # 文件存储抽象层
│       └── ...                # Azure Blob / 本地存储
│
├── tests/                     # 测试套件
│   ├── conftest.py            # pytest fixtures
│   ├── test_*.py              # 测试文件
│   └── ...
│
└── uploads/                   # 本地文件上传目录（开发环境）
```

### API 层

**位置**：`backend/api/`

API 层使用 FastAPI 定义 REST 接口。关键接口包括：

| 接口 | 用途 | 方法 |
|------|------|------|
| `/api/chat` | AI Agent 交互 | POST |
| `/api/upload` | 文件上传 | POST |
| `/api/settings` | 设置项 CRUD | GET、POST、PUT、DELETE |
| `/api/auto-style` | 自动样式 | POST |
| `/api/ai-style` | AI 样式 | POST |
| `/docs` | Swagger API 文档 | GET |

**示例接口**（`api/nalamap.py`）：

```python
@router.post("/chat")
async def chat_with_nalamap(request: NaLaMapRequest) -> NaLaMapResponse:
    """AI Agent 聊天主入口。"""
    # 处理请求，调用 agent，返回响应
```

### 服务层

**位置**：`backend/services/`

服务层承载业务逻辑，并负责组织整个 AI Agent 系统。

#### 单 Agent 系统（当前方案）

**文件**：`services/single_agent.py`

当前实现基于 LangGraph 的 `create_react_agent`，使用一个**单一 ReAct Agent**：

- **GeoAgent**：一个统一的 Agent，可访问所有工具
- **工具选择**：Agent 根据上下文推理应该调用哪些工具
- **可配置**：每个会话都可以自定义工具与系统提示词
- **状态管理**：使用 `GeoDataAgentState` 跟踪图层、结果与对话

**关键函数**：`create_geo_agent(model_settings, selected_tools)`

- 创建并返回一个已经配置好的 ReAct Agent
- 根据设置动态加载工具
- 如果用户提供自定义系统提示词，则优先使用

**默认工具**（`services/default_agent_settings.py`）：

- 地理编码工具（Nominatim、Overpass）
- 地理处理工具（buffer、clip、union 等）
- 样式工具（手动样式、自动样式、配色方案）
- 属性工具（查询、过滤、汇总）
- 状态管理工具（元数据搜索、对象描述）
- 数据发现工具（GeoServer、PostGIS）

#### 多 Agent 架构（遗留）

**文件**：`services/multi_agent_orch.py`

遗留的多 Agent 系统过去使用 supervisor 对请求进行路由：

- **Supervisor Agent**：将请求分发给不同的专用 Agent
- **Geo Helper Agent**：处理地理空间查询与操作
- **Librarian Agent**：搜索与发现外部数据源

**状态**：目前已逐步废弃，当前主流程已切换到单 Agent。为了兼容性，仍可通过 `/chat2` 访问旧实现。

#### Agent 工作流

单 Agent 的执行模式如下：

1. 接收用户查询
2. 使用配置好的工具与提示词创建 Agent
3. Agent 进入 ReAct 循环（Reason → Act → Observe）
4. 根据需要调用工具完成任务
5. 生成响应并返回给前端

### AI 工具

**位置**：`backend/services/tools/`

工具是 AI Agent 可调用的函数，用于执行具体动作。所有工具统一注册在 `services/default_agent_settings.py` 中，并且可以按会话动态配置。

#### 工具分类

- **地理编码**（`geocoding.py`）
  - `geocode_using_nominatim_to_geostate`：基于 OpenStreetMap Nominatim 的位置搜索
  - `geocode_using_overpass_to_geostate`：基于 Overpass API 的 POI 搜索，如餐馆、医院等

- **地理处理**（`geoprocess_tools.py`）
  - `geoprocess_tool`：统一的空间操作工具，支持缓冲区、裁剪、合并、相交、质心等
  - 这些操作针对会话状态中已有的图层执行

- **样式设计**（`styling_tools.py`）
  - `style_map_layers`：显式参数驱动的手动样式
  - `auto_style_new_layers`：对新图层进行智能自动样式
  - `check_and_auto_style_layers`：自动检查并修正图层样式
  - `apply_intelligent_color_scheme`：基于色彩理论的智能配色

- **属性分析**（`attribute_tools.py`）
  - `attribute_tool`：统一的属性操作工具
  - 可查询图层属性、过滤要素、汇总数值字段
  - 通过安全的 CQL-lite 谓词语言进行过滤

- **状态管理**（`geostate_management.py`）
  - `metadata_search`：通过语义相似度搜索已有数据集
  - `describe_geodata_object`：获取指定图层的详细信息

- **数据发现**
  - `get_custom_geoserver_data`（`geoserver/custom_geoserver.py`）：从自定义 GeoServer 获取数据
  - `query_librarian_postgis`（`librarian_tools.py`）：在 PostGIS 数据库中搜索相关数据集

**工具定义模式**：

```python
from langchain.tools import tool

@tool
def geocode_using_nominatim_to_geostate(
    state: GeoDataAgentState,
    location: str
) -> dict:
    """
    使用 Nominatim 将位置名称地理编码为坐标。

    Args:
        state: 当前 agent 状态
        location: 地点名称或地址

    Returns:
        包含坐标、边界框和 GeoJSON 的字典
    """
    # 具体实现
    return result
```

### 模型层

**位置**：`backend/models/`

Pydantic 模型用于定义系统中的核心数据结构：

- **GeoDataObject**（`geodata.py`）：表示一个地图图层
- **LayerStyle**（`geodata.py`）：图层样式属性
- **DataState**（`states.py`）：Agent 对话状态
- **SettingsSnapshot**（`settings_model.py`）：用户设置快照

### 数据库层

**位置**：`backend/services/database/`

使用带 PostGIS 扩展的 PostgreSQL 来存储空间相关与会话相关信息：

- 用户会话
- 图层元数据
- 设置项存储
- 向量嵌入检索（语义搜索由 SQLite-vec 支持）

---

## 前端架构

### 目录结构

```text
frontend/
├── app/                        # Next.js App Router
│   ├── page.tsx               # 主页面
│   ├── layout.tsx             # 根布局
│   ├── globals.css            # 全局样式
│   │
│   ├── components/            # React 组件
│   │   ├── ColorInjector.tsx  # 动态颜色注入
│   │   ├── StoreProvider.tsx  # Zustand Store Provider
│   │   │
│   │   ├── chat/              # 聊天界面组件
│   │   │   ├── AgentInterface.tsx
│   │   │   ├── ChatMessage.tsx
│   │   │   └── ...
│   │   │
│   │   ├── maps/              # 地图组件
│   │   │   ├── MapComponent.tsx # 主 Leaflet 地图
│   │   │   ├── LayerRenderer.tsx
│   │   │   └── ...
│   │   │
│   │   ├── sidebar/           # 侧边栏组件
│   │   │   ├── Sidebar.tsx
│   │   │   ├── LayerManagement.tsx
│   │   │   └── ...
│   │   │
│   │   └── settings/          # 设置相关组件
│   │       ├── SettingsPanel.tsx
│   │       ├── ColorSettings.tsx
│   │       ├── ModelSettings.tsx
│   │       └── ToolSettings.tsx
│   │
│   ├── hooks/                 # 自定义 React hooks
│   │   ├── useMapInteraction.ts
│   │   ├── useLayerState.ts
│   │   └── ...
│   │
│   ├── stores/                # Zustand 状态管理
│   │   ├── mapStore.ts        # 地图状态（图层、视口）
│   │   ├── chatStore.ts       # 聊天状态（消息、会话）
│   │   ├── uiStore.ts         # UI 状态（侧边栏、弹窗、面板）
│   │   ├── settingsStore.ts   # 设置状态
│   │   └── ...
│   │
│   ├── models/                # TypeScript 类型 / 接口
│   │   └── ...
│   │
│   └── utils/                 # 工具函数
│       └── ...
│
├── tests/                     # Playwright E2E 测试
│   ├── leaflet-map.spec.ts
│   ├── chat-interface.spec.ts
│   ├── settings.spec.ts
│   └── fixtures/              # 测试夹具
│
├── public/                    # 静态资源
│   └── ...
│
├── package.json               # 依赖声明
├── tsconfig.json              # TypeScript 配置
├── tailwind.config.ts         # Tailwind CSS 配置
├── playwright.config.ts       # Playwright 配置
└── next.config.mjs            # Next.js 配置
```

### 组件架构

**主页面结构**（`app/page.tsx`）：

```text
┌─────────────────────────────────────────────────────────┐
│                    主页面（page.tsx）                  │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Sidebar   │  │ Map Component│  │ Agent Interface│  │
│  │            │  │  （Leaflet） │  │   （聊天）      │  │
│  │  - Tools   │  │              │  │                │  │
│  │  - Layers  │  │  - Layers    │  │  - Messages    │  │
│  │  - Settings│  │  - Controls  │  │  - Input       │  │
│  └────────────┘  └──────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 状态管理（Zustand）

**位置**：`app/stores/`

Zustand 提供轻量、基于 Hook 的状态管理方案：

- **mapStore**：图层数据、地图视口、选中的要素
- **chatStore**：聊天消息、会话管理、流式状态
- **uiStore**：UI 状态，如侧边栏、弹窗、面板
- **settingsStore**：用户偏好与颜色配置

**Store 模式**：

```typescript
import { create } from 'zustand';

interface MapState {
  layers: Layer[];
  viewport: Viewport;
  addLayer: (layer: Layer) => void;
  removeLayer: (id: string) => void;
}

export const useMapStore = create<MapState>((set) => ({
  layers: [],
  viewport: { center: [0, 0], zoom: 2 },
  addLayer: (layer) => set((state) => ({
    layers: [...state.layers, layer]
  })),
  removeLayer: (id) => set((state) => ({
    layers: state.layers.filter((l) => l.id !== id)
  })),
}));
```

### 地图集成（Leaflet）

**位置**：`app/components/maps/`

Leaflet 提供交互式地图能力：

- **MapComponent.tsx**：主地图容器
- **LayerRenderer.tsx**：渲染 GeoJSON 图层
- **Controls**：自定义地图控件，如缩放、全屏等

**地图能力**：

- 展示矢量数据（GeoJSON）
- 展示栅格数据（WMS、WMTS）
- 要素选择与编辑
- 自定义样式（颜色、描边、填充）
- 地理编码搜索
- 绘图工具

### API 通信

**模式**：前端通过 `fetch` 与后端通信：

```typescript
// 示例：发送聊天消息
const response = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    messages: [...],
    geodata: [...],
    session_id: sessionId,
  }),
});

const data = await response.json();
```

---

## 数据流与通信

### 聊天交互流程

```text
用户输入（Frontend）
    │
    ▼
Chat Store（Zustand）
    │
    ▼
POST /api/chat（Backend）
    │
    ▼
创建单 Agent（create_geo_agent）
    │
    ├─→ 配置 LLM
    ├─→ 加载系统提示词
    └─→ 加载启用的工具（来自设置）
    │
    ▼
ReAct Agent 循环
    │
    ├─→ 推理下一步动作
    ├─→ 选择并调用工具
    │       │
    │       ├─→ geocode_using_nominatim_to_geostate
    │       ├─→ geocode_using_overpass_to_geostate
    │       ├─→ geoprocess_tool
    │       ├─→ style_map_layers
    │       ├─→ attribute_tool
    │       └─→ metadata_search
    │
    ├─→ 观察工具结果
    └─→ 重复，直到答案准备完成
    │
    ▼
Agent 响应（JSON）
    │
    ▼
前端更新状态
    │
    ├─→ Chat Store（新增消息）
    ├─→ Map Store（新增图层 / 结果）
    └─→ UI 更新（重新渲染）
```

**关键接口**：

- `/api/chat`：当前主接口，使用单 ReAct Agent
- `/api/chat2`：遗留接口，使用多 Agent 编排，已废弃

### 图层管理流程

```text
用户动作（添加图层）
    │
    ▼
前端事件处理
    │
    ▼
Map Store（addLayer）
    │
    ├─→ POST /api/upload（如果是文件上传）
    │       │
    │       └─→ 后端保存文件
    │
    └─→ 图层添加到 Leaflet 地图
    │
    ▼
地图重新渲染并显示新图层
```

### 设置项流程

```text
用户修改设置
    │
    ▼
Settings 组件
    │
    ▼
POST /api/settings（Backend）
    │
    ▼
数据库（PostgreSQL）
    │
    ▼
响应（更新后的设置）
    │
    ▼
Settings Store（Zustand）
    │
    ▼
UI 更新（颜色、工具等）
```

---

## AI Agent 架构

### 基于 LangGraph 的单 Agent 系统

**位置**：`backend/services/single_agent.py`

NaLaMap 使用一个基于 LangGraph `create_react_agent` 的**单一 ReAct Agent**。它可以访问多个专业工具，并通过推理循环决定该调用哪些工具来回应用户请求。

```text
┌─────────────────────────────────────────────────────────┐
│                单一 ReAct Agent（GeoAgent）            │
│             （负责推理并选择合适的工具）               │
└─────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┬──────────────┐
          │               │               │              │
          ▼               ▼               ▼              ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 地理编码工具 │  │ 地理处理工具 │  │ 样式设计工具 │  │ 属性分析工具 │
│              │  │              │  │              │  │              │
│ - Nominatim  │  │ - Buffer     │  │ - Manual     │  │ - Query      │
│ - Overpass   │  │ - Clip       │  │ - Auto-style │  │ - Filter     │
│              │  │ - Intersect  │  │ - Color      │  │ - Summarize  │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘

          ▼               ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 元数据搜索   │  │ Geoserver    │  │ Librarian    │
│ 工具         │  │ 工具         │  │ 工具         │
│              │  │              │  │              │
│ - Describe   │  │ - Custom     │  │ - PostGIS    │
│ - Search     │  │   Geoserver  │  │   Search     │
└──────────────┘  └──────────────┘  └──────────────┘
```

### 可用工具

**位置**：`backend/services/tools/`

Agent 可使用的工具类别如下：

| 类别 | 工具 | 用途 |
|------|------|------|
| **地理编码** | `geocode_using_nominatim_to_geostate`、`geocode_using_overpass_to_geostate` | 将地点名称转为坐标、查找 POI |
| **地理处理** | `geoprocess_tool` | 空间操作，如 buffer、clip、union、intersect |
| **样式设计** | `style_map_layers`、`auto_style_new_layers`、`check_and_auto_style_layers`、`apply_intelligent_color_scheme` | 地图图层的视觉样式定制 |
| **属性分析** | `attribute_tool` | 查询、过滤和分析图层属性 |
| **状态管理** | `metadata_search`、`describe_geodata_object` | 搜索并描述已有图层 |
| **数据发现** | `get_custom_geoserver_data`、`query_librarian_postgis` | 查找外部数据源 |

**工具配置**：工具可以按会话启用或禁用，因此 Agent 的能力可按用户设置进行裁剪。

### Agent 创建

**函数**：`single_agent.py` 中的 `create_geo_agent()`

创建 Agent 时会注入以下元素：

- **LLM**：通过 `get_llm()` 配置，支持多个 Provider
- **Tools**：根据用户设置动态加载
- **State Schema**：`GeoDataAgentState`，用于跟踪消息、图层与结果
- **System Prompt**：定义 Agent 行为的系统提示词，可自定义
- **Tool Binding**：默认 `parallel_tool_calls=False`，按顺序执行工具

```python
def create_geo_agent(
    model_settings: Optional[ModelSettings] = None,
    selected_tools: Optional[List[ToolConfig]] = None,
) -> CompiledStateGraph:
    llm = get_llm()
    system_prompt = DEFAULT_SYSTEM_PROMPT  # 或来自设置的自定义提示词
    tools_dict = create_configured_tools(DEFAULT_AVAILABLE_TOOLS, selected_tools)
    tools = list(tools_dict.values())

    return create_react_agent(
        name="GeoAgent",
        state_schema=GeoDataAgentState,
        tools=tools,
        model=llm.bind_tools(tools, parallel_tool_calls=False),
        prompt=system_prompt,
    )
```

### Agent 状态

**GeoDataAgentState**（`models/states.py`）：

```python
class GeoDataAgentState(TypedDict):
    messages: List[BaseMessage]               # 对话历史
    geodata_layers: List[GeoDataObject]       # 当前地图图层
    geodata_results: List[GeoDataObject]      # 查询结果
    geodata_last_results: List[GeoDataObject] # 上一次结果
    results_title: str                        # 结果标题
    options: SettingsSnapshot                 # 用户设置
    remaining_steps: int                      # 最大推理步数
```

### ReAct 循环

Agent 采用 **ReAct（Reasoning + Acting）** 模式：

1. **用户查询** → Agent 收到问题
2. **推理** → Agent 思考需要调用哪些工具
3. **行动** → Agent 调用合适的工具
4. **观察** → Agent 获取工具执行结果
5. **重复** → 重复 2 到 4，直到得到答案
6. **响应** → Agent 生成最终回复

**示例流程**：

```text
用户："显示柏林的医院"
    ↓
Agent 推理："我需要先定位柏林，再搜索医院"
    ↓
动作 1：调用 geocode_using_nominatim_to_geostate("Berlin")
    ↓
观察：{lat: 52.52, lon: 13.405, bbox: [...]}
    ↓
Agent 推理："现在我可以在这个区域搜索医院"
    ↓
动作 2：调用 geocode_using_overpass_to_geostate("hospital", bbox)
    ↓
观察：[50 个医院的 GeoJSON 列表]
    ↓
Agent 推理："我已经拿到数据，可以回复用户"
    ↓
响应："我已将柏林的 50 家医院添加到地图中"
```

### 多 Agent 架构（遗留）

> **注意**：多 Agent 编排系统（`services/multi_agent_orch.py`）目前**不再是主流程**。虽然 `/chat2` 仍然使用这套旧架构，但主入口 `/chat` 已经切换为上面介绍的单 Agent 方案。

当年的多 Agent 系统包括：

- **Supervisor Agent**：把请求路由给专用 Agent
- **Geo Helper Agent**：处理地理空间查询
- **Librarian Agent**：搜索外部数据

未来如果遇到更复杂的场景，这种架构仍有可能重新启用。

### LLM Provider 抽象

**位置**：`backend/services/ai/`

系统通过统一接口支持多个 LLM Provider：

- `llm_config.py`：配置管理
- `openai.py`：OpenAI GPT 模型
- `azureai.py`：Azure OpenAI 模型
- `google_genai.py`：Google Gemini 模型
- `mistralai.py`：Mistral AI 模型
- `deepseek.py`：DeepSeek 模型

**Provider 选择方式**：通过环境变量 `LLM_PROVIDER` 控制。

---

## 数据库与存储

### PostgreSQL 数据库

**用途**：持久化数据存储

**概念性 Schema**：

```sql
-- 用户会话
CREATE TABLE sessions (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    user_id VARCHAR
);

-- 图层元数据
CREATE TABLE layers (
    id VARCHAR PRIMARY KEY,
    session_id VARCHAR REFERENCES sessions(id),
    name VARCHAR,
    data_type VARCHAR,
    data_source VARCHAR,
    geojson_data JSONB,
    style JSONB,
    visible BOOLEAN,
    created_at TIMESTAMP
);

-- 设置项
CREATE TABLE settings (
    session_id VARCHAR PRIMARY KEY,
    color_settings JSONB,
    model_settings JSONB,
    tool_settings JSONB,
    updated_at TIMESTAMP
);
```

### 向量存储（SQLite-vec）

**用途**：对数据描述进行语义搜索

**使用方式**：

- 存储图层描述的向量嵌入
- 支持自然语言搜索
- 查找相似数据集

### 文件存储

**本地存储**（开发环境）：

- 位置：`backend/uploads/`
- 用于存放上传文件，如 GeoJSON、Shapefile、KML

**Azure Blob Storage**（生产环境）：

- 通过环境变量 `USE_AZURE_STORAGE` 配置
- 使用 SAS Token 提供安全的上传 / 下载
- 元数据保存在 PostgreSQL 中

---

## 部署架构

### 开发环境

```text
┌─────────────────────────────────────────────────────────┐
│                     开发者机器                         │
│  ┌───────────────┐       ┌────────────────┐            │
│  │   Backend     │       │   Frontend     │            │
│  │   （Python）  │       │   （Next.js）  │            │
│  │   Port 8000   │◄──────┤   Port 3000    │            │
│  └───────────────┘       └────────────────┘            │
└─────────────────────────────────────────────────────────┘
```

**启动命令**：

```bash
# 终端 1
cd backend && poetry run python main.py

# 终端 2
cd frontend && npm run dev
```

### Docker 开发环境

```text
┌─────────────────────────────────────────────────────────┐
│      Docker Compose（dev.docker-compose.yml）          │
│  ┌───────────────┐       ┌────────────────┐            │
│  │   Backend     │       │   Frontend     │            │
│  │  Container    │       │  Container     │            │
│  │  Port 8000    │◄──────┤  Port 3000     │            │
│  └───────────────┘       └────────────────┘            │
│         │                        │                      │
│         └────────┬───────────────┘                      │
│                  │                                      │
│         ┌────────▼─────────┐                            │
│         │   Volume Mounts  │                            │
│         │   （Hot Reload） │                            │
│         └──────────────────┘                            │
└─────────────────────────────────────────────────────────┘
```

**启动命令**：

```bash
docker-compose -f dev.docker-compose.yml up --build
```

### 生产环境

```text
┌─────────────────────────────────────────────────────────┐
│                        Internet                        │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│            Nginx 反向代理（端口 80）                    │
│  - SSL / TLS 终止                                      │
│  - 静态资源服务                                        │
│  - 负载均衡                                            │
│  - CORS 处理                                           │
└─────────────────────────────────────────────────────────┘
                │                    │
      ┌─────────┴─────────┐  ┌──────┴─────────┐
      │                   │  │                │
      ▼                   ▼  ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Backend    │  │   Frontend   │  │ PostgreSQL   │
│  Container   │  │  Container   │  │   Database   │
│  （FastAPI） │  │  （Next.js） │  │              │
│  Port 8000   │  │  Port 3000   │  │  Port 5432   │
└──────────────┘  └──────────────┘  └──────────────┘
```

**启动命令**：

```bash
docker-compose up --build
```

### 云部署（Azure Container Apps）

**参考文档**：`docs/azure-container-apps-config.md`

- 后端与前端分别部署为独立容器应用
- 文件上传使用 Azure Blob Storage
- 数据库使用托管 PostgreSQL
- 环境变量通过 Azure Key Vault 管理

---

## 安全架构

### 认证与授权

**当前**：基于 Session（开发环境）
**未来**：OAuth2、JWT Token

### CORS 配置

**位置**：`backend/main.py`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,  # 来自 .env
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### API Key 管理

- LLM API Key 存储在环境变量中
- 永远不应提交到版本控制
- 应定期轮换

### 文件上传安全

- 文件类型校验
- 文件大小限制
- 沙箱化处理
- 病毒扫描（生产环境）

### 数据库安全

- 参数化查询，防止 SQL 注入
- 连接池
- SSL / TLS 连接（生产环境）

---

## 扩展点

### 新增 AI 工具

1. 在 `backend/services/tools/` 中创建工具函数
2. 在 `backend/services/agents/` 中把工具接入 Agent
3. 在 `backend/tests/` 中编写测试
4. 如果需要 UI 变更，则同步更新前端

**示例**：

```python
# backend/services/tools/my_new_tool.py
from langchain.tools import tool

@tool
def my_new_tool(param: str) -> dict:
    """提供给 LLM 的工具描述。"""
    # 具体实现
    return {"result": "..."}
```

### 新增 LLM Provider

1. 在 `backend/services/ai/` 中创建 Provider 文件
2. 实现 `get_llm()` 函数
3. 在 `llm_config.py` 中注册该 Provider
4. 更新文档

### 新增前端组件

1. 在 `app/components/` 下创建组件
2. 在 `app/models/` 中添加类型定义
3. 如果涉及状态，接入 Store
4. 在 `tests/` 中编写测试

### 新增 OGC 服务类型

1. 在 `backend/services/tools/` 中创建服务处理器
2. 增加元数据提取逻辑
3. 在 `MapComponent.tsx` 中更新前端渲染逻辑
4. 补充测试

---

## 相关文档

- **开发指南**：`AGENTS.md`
- **贡献说明**：`CONTRIBUTING.md`
- **颜色自定义**：`docs/color-customization.md`
- **运行时环境**：`docs/runtime-environment.md`
- **Azure 部署**：`docs/azure-container-apps-config.md`

---

**最后更新**：2025 年 10 月  
**维护团队**：NaLaMap Development Team
