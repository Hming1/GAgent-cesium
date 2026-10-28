# Docker 环境配置

项目将共享配置与访问方式相关配置分开：

- 根目录 `.env`：数据库连接、模型地址和第三方密钥等共享配置。
- `.env.local`：本地前后端分端口调试配置。
- `.env.external`：经过 Nginx 和 FRP 的公网部署配置。

两个覆盖文件会在 `.env` 之后加载，因此同名变量以覆盖文件为准。它们已被 Git 忽略；仓库中的 `.env.local.example` 和 `.env.external.example` 是安全模板。

## 本地调试

首次使用时：

```powershell
Copy-Item .env.local.example .env.local
docker compose -f dev.docker-compose.yml up -d --build
```

浏览器访问 `http://localhost:3000`，前端直接请求 `http://localhost:8000/api`。本地使用 HTTP，因此 `COOKIE_SECURE=false`。

## 公网部署

首次使用时：

```powershell
Copy-Item .env.external.example .env.external
```

编辑 `.env.external` 中的公开访问地址，然后启动：

```powershell
docker compose up -d --build
```

当前 FRP 仅提供 HTTP 时必须使用 `COOKIE_SECURE=false`。正式部署应配置 HTTPS 域名，并设置：

```env
BASE_URL=https://map.example.com
FRONTEND_BASE_URL=https://map.example.com
COOKIE_SECURE=true
```

修改环境文件后需要重新创建前后端容器；修改 Cookie 策略后还应清理浏览器旧 Cookie 并重新登录：

```powershell
docker compose up -d --force-recreate backend frontend nginx
```
