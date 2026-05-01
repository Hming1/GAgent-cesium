# NaLaMap 项目构建逻辑总览

本文基于仓库中的实际配置文件整理，目标是说明项目如何从源码进入可运行状态，以及本地开发、容器部署、CI/CD、测试之间的关系。

## 1. 构建对象与技术栈

项目是典型的三层组合：

- `backend`：Python + FastAPI（业务与 AI 代理能力）
- `frontend`：Next.js + React（Web 界面）
- `nginx`：反向代理与入口编排（统一对外端口、健康检查、流式代理）

数据层默认使用 PostGIS（`postgis/postgis:16-3.4`），并支持可选 Azure Blob 存储与多种 LLM Provider。

## 2. 本地非容器构建链路

### 2.1 Backend（Poetry）

后端依赖管理在 `backend/pyproject.toml`，开发流程是：

1. 安装依赖：`poetry install`
2. 启动服务：`poetry run python main.py`

关键点：

- 入口在 `backend/main.py`
- Windows 下会主动切换 `WindowsSelectorEventLoopPolicy`，避免异步事件循环兼容性问题
- `lifespan` 启动阶段会执行数据库初始化（`init_db`）并加载部署配置

### 2.2 Frontend（Node/Next.js）

前端脚本在 `frontend/package.json`：

- 开发：`npm run dev`（`next dev --turbopack`）
- 构建：`npm run build`（`next build`）
- 生产启动：`npm run start`（`next start`）

关键点：

- `frontend/next.config.ts` 设置了 `output: "standalone"`，用于容器化产物最小化
- 构建时忽略 ESLint/TypeScript 错误（`ignoreDuringBuilds` 与 `ignoreBuildErrors`），意味着推荐在 CI 中单独兜底质量检查

## 3. 数据库与迁移逻辑

### 3.1 运行期数据库接入

数据库配置由 `backend/core/config.py` 从环境变量读取：

- 优先 `DATABASE_AZURE_URL`
- 回退 `DATABASE_URL`

`backend/db/session.py` 会将 URL 转为异步驱动形式（如 `postgresql+psycopg://`），并在应用启动时执行 `Base.metadata.create_all`。

### 3.2 Alembic 迁移

迁移配置在：

- `backend/alembic.ini`
- `backend/alembic/env.py`

特点：

- 可从环境变量覆盖连接串
- 支持 `postgis://` 到异步 psycopg URL 的转换
- 迁移执行使用 AsyncEngine

## 4. 容器构建逻辑（核心）

### 4.1 Backend 镜像（多阶段）

`backend/Dockerfile` 是三阶段：

1. `export` 阶段：用 Poetry 导出 `requirements.txt`
2. `build` 阶段：创建虚拟环境并用 pip 安装依赖（包含编译原生依赖所需系统库）
3. `runtime` 阶段：仅保留运行时库和应用代码，最终以 uvicorn 启动

这样做的目标是降低运行镜像体积并减少 Poetry 在运行时的复杂性。

### 4.2 Frontend 镜像（多阶段）

`frontend/Dockerfile` 分三段：

1. `deps`：安装 Node 依赖
2. `builder`：执行 Next.js 构建
3. `runner`：仅复制 `standalone` 产物 + 静态资源，以非 root 用户运行

`frontend/entrypoint.sh` 会在容器启动时注入 `runtime-env.js`，将 API 地址等变量以运行时配置形式暴露给浏览器，避免在构建期写死环境。

### 4.3 Nginx 镜像与模板化配置

`nginx/Dockerfile` + `nginx/docker-entrypoint.sh` 负责将环境变量渲染进 `nginx.conf`（模板文件为 `nginx/nginx.conf.envsubst`）。

Nginx 负责：

- 对外统一入口（默认 `:80`）
- `/health/nginx`、`/health/backend`、`/health/frontend` 健康检查
- `/` 返回 loading 页面，`/map` 反代前端
- `/api/*` 与 SSE 接口的流式代理优化（禁用关键缓冲）

## 5. Compose 运行模式

项目内存在多套 Compose 文件，分别服务不同场景：

- `docker-compose.yml`：标准整栈运行（frontend + backend + nginx + db）
- `dev.docker-compose.yml`：开发模式，前后端热更新
- `cloud-test.docker-compose.yml`：模拟云端 runtime-env 可写挂载
- `azure-debug.docker-compose.yml`：对齐 Azure Container Apps 的调试拓扑
- `e2e-performance/docker-compose.e2e.yml`：性能测试专用栈

这意味着项目采用了“同一代码，多编排入口”的策略：

- 开发强调迭代速度（reload/hot reload）
- 线上强调稳定拓扑和代理行为
- 测试强调可复现和隔离

## 6. CI/CD 构建与发布逻辑

### 6.1 CI（`.github/workflows/ci.yml`）

主要包含四类任务：

1. `test`：后端 Poetry 安装 + pytest
2. `lint`：flake8 + black 校验
3. `e2e-performance`：拉起专用 Compose 并执行性能测试
4. `frontend-performance`：Playwright 性能相关测试

结论：CI 不仅做静态质量检查，也执行整栈级别性能验证。

### 6.2 Docker 发布（`.github/workflows/docker-publish.yml`）

矩阵构建三个镜像：

- `frontend`
- `backend`
- `nginx`

并推送 GHCR，标签策略包含分支、PR、语义化版本和 commit sha。之后通过 `repository_dispatch` 将镜像元数据发送到基础设施仓库触发部署流程。

## 7. 构建逻辑的关键设计理念

从配置可以看出项目采用了以下构建思路：

1. 前后端独立构建，但通过 Nginx 在运行时统一入口
2. 构建期与运行期解耦（尤其前端 runtime-env 注入）
3. 本地开发、云调试、性能测试使用不同 Compose 文件隔离关注点
4. 镜像发布与基础设施部署解耦（镜像发布后再分发部署事件）
5. 对流式接口和冷启动体验做了专项代理与健康检查设计

## 8. 一条完整路径示例（开发者视角）

### 8.1 本地开发（推荐）

1. 后端：`cd backend && poetry install && poetry run python main.py`
2. 前端：`cd frontend && npm i && npm run dev`
3. 浏览器访问 `http://localhost:3000`（前端）或 `http://localhost:8000/docs`（后端 API 文档）

### 8.2 容器整栈

1. 根目录执行：`docker-compose up --build`
2. 访问 `http://localhost`（经 Nginx 进入 loading -> /map）
3. 用 `/health/*` 路径检查组件就绪状态

## 9. 可关注的改进点（可选）

- 前端生产构建当前忽略 TS/ESLint 错误，建议在 CI 中增加强制 `next build` 类型检查阶段
- Backend 与 Frontend Dockerfile 使用了不同基础镜像策略（slim/alpine + node25/python13），可按部署平台统一优化
- `create_all` 与 Alembic 并存时，建议明确环境边界（开发自动建表 vs 生产只走迁移）

---

如果你希望，我可以继续基于这份文档再生成一份“按角色拆分”的版本（开发、测试、运维各一页），并补上对应命令清单与故障排查路径。