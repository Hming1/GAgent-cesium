# GeoAgent

GeoAgent 是一个开源平台，用来以自然语言查找和分析地理空间数据。它把 Web 应用和智能体放在一起，让用户直接在地图上查看、检索和处理地理信息。

## 功能

* 上传矢量数据并在地图上显示。
* 用 OSM 和 GeoNames 做地理编码（例如医院、学校、道路、铁路）。几何类型过滤会把查询落到对应的要素类型上，例如返回道路线段而不是公交站。
* 接入已有的开放数据门户，或使用自己的数据库。
* **城市低效空间识别**：独立工作台按容积率、建筑密度、闲置年限、税收产出、用地性质等指标，识别工业、商业、居住低效用地和闲置空地。见 [低效空间说明](docs/inefficient-space.md)。
* 通过对话向智能体询问数据内容和质量。
* **多模型提供方**：可选 vLLM、Kimi 或 DeepSeek。
* 用智能体辅助设置地图和图层样式。
* 用自然语言做地理处理，例如缓冲区、质心、相交。
* 按具体用途、处理逻辑和数据源，搭建并分享给非地理信息专业人员使用的 GIS 应用。
* 工具箱可以继续扩展，例如接入文档或网页检索。
* **配色**：可以按机构品牌或个人偏好调整界面颜色。见 [配色说明](docs/color-customization.md)。

## 版本策略

GeoAgent 的发布版本遵循 [语义化版本](https://semver.org/)，格式为 `MAJOR.MINOR.PATCH`：

- **MAJOR**：不兼容的 API 变更、重大架构调整，或会破坏现有功能的改动
- **MINOR**：向后兼容的新功能，例如新的地理工具、新数据源、界面改进
- **PATCH**：向后兼容的缺陷修复、安全补丁和小改进

**发布标签：** Git 标签格式为 `v{MAJOR}.{MINOR}.{PATCH}`，例如 `v1.0.0`、`v1.2.3`。

**预发布版本**可以使用 `-alpha`、`-beta` 或 `-rc`，例如 `v1.1.0-beta.1`。

**当前版本：** 项目仍在开发中。核心功能完成并经过充分测试后，第一个稳定版会标为 `v1.0.0`。

## 项目结构

```
GAgent-cesium/
├── backend/              # Python FastAPI 后端
│   ├── api/              # API 端点
│   ├── core/             # 核心配置
│   ├── models/           # 数据模型
│   ├── services/         # 业务逻辑
│   │   ├── agents/       # 智能体实现
│   │   ├── ai/           # 模型提供方
│   │   ├── database/     # 数据库连接
│   │   └── tools/        # 智能体工具
│   └── main.py           # 应用入口
├── frontend/             # Next.js 前端
│   ├── app/              # Next.js 应用
│   │   ├── components/   # React 组件
│   │   ├── hooks/        # 自定义 Hooks
│   │   └── page.tsx      # 主页面
│   └── public/           # 静态资源
└── nginx/                # 对外提供服务的 Nginx 配置
```

> 系统架构见 [ARCHITECTURE.md](ARCHITECTURE.md)，中文版见 [ARCHITECTURE.zh-CN.md](ARCHITECTURE.zh-CN.md)。  
> 给 AI 编程助手的仓库说明见 [AGENTS.md](AGENTS.md)，中文版见 [AGENTS.zh-CN.md](AGENTS.zh-CN.md)。

## 简化关系示意

下图概括 GeoAgent 的工作方式，例子是用户要求修改地图上某个矢量图层的样式。

<img width="950" height="534" alt="GeoAgent 处理图层样式请求的关系示意" src="https://github.com/user-attachments/assets/6a09918a-fbd0-4860-a362-a5d4f55e871a" />

## 开始使用

### 环境要求

- **Git**
- **Python 3.10+**
- **Node.js 18+**
- **Docker 与 Docker Compose**（可选）
- **[Poetry](https://python-poetry.org/docs/)**（后端依赖）

### 快速开始

按下面的步骤在本机运行。

#### 1. 克隆仓库

```bash
git clone https://github.com/Hming1/GAgent-cesium.git
cd GAgent-cesium
```

#### 2. 配置环境变量

在仓库根目录根据 `.env.example` 创建 `.env`：

```bash
cp .env.example .env
```

`.env` 里主要有这些配置：

- **模型提供方**：选择 vLLM、Kimi 或 DeepSeek，并填写对应密钥
- **数据库**：Docker Compose 提供的本地 PostGIS（`app` 和 `layers`）
- **API 地址**：后端 API 的基地址
- **注册安全**：默认新账号需要一次性邀请码。见 [邀请注册](docs/invite-registration.md)
- **可选服务**：可用 LangSmith 追踪智能体调用
- **地理编码回退**：在 `.env` 中设置 `AMAP_WEB_SERVICE_KEY`（高德 Web 服务密钥）和/或 `BAIDU_GEOCODING_AK`。地名和边界查询先走 Nominatim，再试高德，最后试百度。**国内 POI**（学校、医院等）在地点像中国地名且已设置 `AMAP_WEB_SERVICE_KEY` 时，优先用高德 Place Search；海外或高德无结果时回退到 Overpass/OSM。国内服务返回的坐标会转成 WGS84 再写入 GeoJSON。

**地图 / WMTS 投影：**

后端默认丢弃没有 WebMercator（EPSG:3857 系列）TileMatrixSet 的 WMTS 图层，避免投影不一致的瓦片被画出来。

控制这个行为的环境变量：

`NALAMAP_FILTER_NON_WEBMERCATOR_WMTS`（默认 `true`）

设为 `false` 会放行全部 WMTS 图层。瓦片若不是 WebMercator，画面可能对不齐。

细节见 `docs/wmts.md`。

默认数据库地址只连接本机的 PostGIS 容器。如果部署要暴露到本机以外，先改掉本地数据库凭据。

**同一时间以一个提供方为准。** 可以配置多个可用提供方。界面优先使用 `DEFAULT_LLM_PROVIDER` 或 `LLM_PROVIDER`；在界面里明确选择的模型会覆盖环境变量里的回退值。

**支持的 `LLM_PROVIDER` 及模型：**

| 提供方 | LLM_PROVIDER | 默认模型 | 模型变量 | 其他配置 |
|----------|-------------------|---------------|-------------------|--------------------------|
| vLLM | `vllm` | `Qwen3.8-27B` | `VLLM_MODEL` | `VLLM_BASE_URL`，可选 `VLLM_API_KEY` |
| Kimi | `kimi` | `kimi-k2.6` | `KIMI_MODEL` | `KIMI_API_KEY` |
| DeepSeek | `deepseek` | `deepseek-chat` | `DEEPSEEK_MODEL` | `DEEPSEEK_API_KEY` |

**配置示例：**

```bash
# 选择提供方
LLM_PROVIDER=vllm
DEFAULT_LLM_PROVIDER=vllm
VLLM_BASE_URL=http://localhost:18000/v1
VLLM_MODEL=Qwen3.8-27B
VLLM_API_KEY=none
# 在 Docker 里，这个地址必须从后端容器访问得到。
```

各提供方都可以通过环境变量指定模型。未指定时，GeoAgent 使用面向地理任务、成本较低的默认模型。

要改温度、`max_tokens`、超时等参数，编辑 `backend/services/ai/` 下对应文件：

- `vllm.py`
- `kimi.py`
- `deepseek.py`

每个文件里的 `get_llm()` 可以调整 `temperature`、`max_tokens`、`max_retries` 等参数。

#### 3. 启动后端（Python / FastAPI）

```bash
cd backend

# 建议把虚拟环境创建在仓库内
poetry config virtualenvs.create true
poetry install

poetry run python main.py
```

后端地址：`http://localhost:8000`  
API 文档：`http://localhost:8000/docs`

#### 4. 启动前端（Next.js）

另开一个终端：

```bash
cd frontend
npm i
npm run dev
```

前端地址：`http://localhost:3000`

### 使用 Docker 部署

1. 按上一节配好环境变量。
2. 启动：

   ```bash
   docker-compose up
   ```

3. 在 `http://localhost:80` 打开应用。

Nginx 还在 `http://localhost:8081` 提供第二个前端代理，默认转发到 `http://host.docker.internal:3001`。端口和上游可以用 `SECOND_FRONTEND_PROXY_PORT`、`SECOND_FRONTEND_PROTOCOL`、`SECOND_FRONTEND_URL` 覆盖。

### Docker 开发环境

需要热重载的完整开发环境：

```bash
docker-compose -f dev.docker-compose.yml up --build
```

本地调试和对外部署使用不同的 URL 与 Cookie 配置。启动对应的 Compose 栈之前，先看 [Docker 环境配置](docs/environment-profiles.md)。

## 技术栈

### 后端

- **FastAPI**：用来构建 API 的 Web 框架
- **LangChain**：组织语言模型应用
- **LangGraph**：编排智能体工作流
- **vLLM / Kimi / DeepSeek**：自然语言处理的模型提供方
- **Uvicorn**：运行 FastAPI 的 ASGI 服务器

### 前端

- **Next.js 15**
- **React 19**
- **Cesium**：三维地图
- **Tailwind CSS**
- **TypeScript**

### 基础设施

- **Docker**
- **Nginx**：Web 服务器和反向代理

## 测试

后端和前端都有测试。

### 后端（pytest）

```bash
cd backend
poetry run pytest tests/

# 更详细的输出
poetry run pytest tests/ -v

# 按标记运行，例如 unit、integration、styling
poetry run pytest tests/ -m unit
```

### 前端（Playwright）

```bash
cd frontend

# 首次需要安装浏览器
npx playwright install --with-deps

npm test

# 交互式界面
npx playwright test --ui
```

测试约定见 [CONTRIBUTING.md](CONTRIBUTING.md#testing-guidelines)，前端测试说明见 [frontend/tests/README.md](frontend/tests/README.md)。

部分测试会读取环境变量（例如 `OPENAI_API_KEY`）。能用模拟数据的地方会避免访问外部服务。

## 常见问题

**后端报 “Address already in use”：**

- 查看 8000 端口：`lsof -i :8000`
- 结束占用进程：`kill <PID>`

**模型接口报错：**

- 确认仓库根目录有 `.env`
- 确认对应密钥或地址已填写，例如 `KIMI_API_KEY`、`DEEPSEEK_API_KEY`、`VLLM_BASE_URL`
- `LLM_PROVIDER` 必须是 `vllm`、`kimi` 或 `deepseek` 之一

**前端起不来：**

- 确认 Node.js 18+：`node --version`
- 清缓存：`npm cache clean --force`
- 重装依赖：`rm -rf node_modules && npm i`

## 安全

不要把带有真实密钥的 `.env` 提交进版本库。以 `.env.example` 为模板，在本地填写自己的凭据。定期轮换密钥并查看用量。用户上传的文件也不应提交进版本库。

生产部署时：

* 用环境变量或密钥管理系统保存凭据
* 启用 HTTPS/TLS
* 配置身份验证和授权
* 定期做安全检查并更新依赖

发现安全漏洞时，请发邮件到 [info@nalamap.org](mailto:info@nalamap.org)，不要在 Issue 里公开。

## 文档

- **[README.md](README.md)**：项目概览和快速开始（本文件）
- **[CONTRIBUTING.md](CONTRIBUTING.md)**：开发、测试、代码检查和排错
- **[AGENTS.md](AGENTS.md)** / **[AGENTS.zh-CN.md](AGENTS.zh-CN.md)**：给 AI 编程助手的仓库说明
- **[ARCHITECTURE.md](ARCHITECTURE.md)** / **[ARCHITECTURE.zh-CN.md](ARCHITECTURE.zh-CN.md)**：系统架构、智能体、数据流和部署
- **[backend/tests/README.md](backend/tests/README.md)**：后端测试
- **[backend/services/tools/README.md](backend/services/tools/README.md)**：智能体工具
- **[frontend/tests/README.md](frontend/tests/README.md)**：前端测试
- **[docs/](docs/)**：专项说明
  - 配色
  - [本地存储与矢量检索](docs/local-storage-and-search.md)
  - [城市低效空间识别](docs/inefficient-space.md)
  - [对话历史](docs/conversation-history.md)

## 参与贡献

欢迎提交改进。开发与测试约定见：

- **[贡献指南](CONTRIBUTING.md)**
- **[AGENTS.md](AGENTS.md)**
- **[ARCHITECTURE.md](ARCHITECTURE.md)**
- **[行为准则](CODE_OF_CONDUCT.md)**

也可以加入 [Discord](http://discord.nalamap.org/)。社区会定期讨论路线图、功能需求和正在进行的工作。

## 许可证

本项目使用 MIT 许可证，详见 LICENSE 文件。

## 致谢

这个项目来自一个具体需求：让地理数据探索少一些专业门槛。地图和模型能力都建立在开源组件上。感谢贡献者和开源社区。

### 本地存储与检索

文件使用本地存储。GeoServer 检索默认用哈希嵌入和 SQLite-vec，也仍然支持自定义的本地嵌入实现。持久化和索引迁移见 [本地存储与检索](docs/local-storage-and-search.md)。

## 地图底图

Cesium 默认使用高德标准地图。切换界面主题不会覆盖已经选中的底图。可选底图包括 OSM、Carto 浅色/深色、Google 卫星/混合/地形、高德标准/卫星/混合、天地图矢量/卫星/混合。

天地图需要浏览器类型令牌。Docker 部署请在根目录的 `.env`（或覆盖它的 `.env.external`）设置 `NEXT_PUBLIC_TIANDITU_TOKEN`。重建或替换前端容器后生效；只改令牌时，重新创建容器即可。令牌由 `/runtime-env.js` 在运行时提供，不必写进镜像。`frontend/.env.local` 只给本地开发用，Docker 构建会排除它。请在天地图控制台为实际访问域名配置限制。高德 Web 服务密钥和百度地理编码 AK 用于地址查询，不用于这里的瓦片底图。

首次瓦片请求持续 12 秒仍未成功，或重试一次仍失败时，页面会改用备用底图，并标明实际使用的来源。可以点击「重试原底图」恢复。卫星底图优先回退到卫星来源。备用来源不会循环重试；全部失败时，页面会提示检查网络。天地图从第 1 级请求，并限制各来源的最大瓦片级别，避免请求不受支持的级别。

各来源仍要求浏览器能访问对应的服务域名。配置正确和自动回退不能代替服务商权限、有效令牌或网络连通性。高德标准瓦片使用[官方示例中的 wprd 地址](https://lbs.amap.com/api/maps-javascript-api/reference/layer/tilelayer)。

若高德和天地图经系统代理出现 `ERR_CONNECTION_CLOSED`，而直连正常，可在代理软件中为 `*.is.autonavi.com` 和 `*.tianditu.gov.cn` 配置直连，或加入 Windows 当前用户的代理绕过列表。这是访问地图的电脑网络设置，前端容器不会改它。代理软件重设系统代理时，可能会覆盖绕过列表。
