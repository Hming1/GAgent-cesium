# 仅邀请注册

GeoAgent 默认使用 `REGISTRATION_MODE=invite`。已有账号仍可通过密码或已关联的
OIDC 身份登录；创建任何新账号时，都必须使用一个有效、与注册邮箱一致且只能
使用一次的邀请。

## 部署数据库结构

生成邀请前，请先执行数据库迁移：

```bash
cd backend
poetry run alembic upgrade head
```

如果 Windows PowerShell 中没有安装 Poetry，但项目已有 `.venv`，可直接执行：

```powershell
cd D:\code\Gagent-cesium\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

在开发环境中，应用启动时也会通过 SQLAlchemy `create_all` 创建缺失的数据表；
生产环境应使用 Alembic 执行迁移。

## 生成邀请

可以在已正确配置的后端项目目录中执行：

```bash
cd backend
poetry run python -m scripts.create_registration_invite user@example.com
```

Windows PowerShell 也可以直接使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m scripts.create_registration_invite user@example.com
```

该命令会输出一个邀请链接，链接中包含邀请码明文的唯一副本。请通过可信渠道
将链接发送给指定用户。邀请码默认有效期为 7 天；可使用 `--hours 24` 将有效期
设置为 24 小时，或指定其他小时数。

使用 Docker Compose 部署时执行：

```bash
docker compose exec backend /app/.venv/bin/python -m scripts.create_registration_invite user@example.com
```

## 注册模式

- `invite`（默认）：必须提供邮箱匹配、未过期且未使用的邀请码。
- `closed`：禁止创建任何新的密码账号或 OIDC 账号。
- `open`：明确启用公开注册。

已有的 OIDC 用户无需再次获得邀请即可登录。创建新的 OIDC 账号时，既需要有效
邀请，也要求身份提供商返回 `email_verified=true`。数据库只保存邀请码的
SHA-256 哈希值；创建账号时会锁定对应邀请记录，并在同一个数据库事务中完成
账号创建和邀请码消费，从而避免邀请码被重复使用。
