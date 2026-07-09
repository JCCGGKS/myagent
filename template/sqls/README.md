# SQL 建表脚本

本目录存放 myagent 后端依赖的 MySQL 建表 DDL，字段与 `app/model/` 下的 SQLAlchemy ORM 模型保持一致。

## 文件清单

| 文件 | 说明 | 对应 ORM |
|------|------|----------|
| `01_users.sql` | 用户表（注册 / 登录 / 找回密码） | `app/model/user.py` |
| `02_sessions.sql` | 会话相关 5 张表（sessions / messages / state_snapshots / tool_calls / handoff_records） | `app/model/session.py` |
| `run.sh` | 建表执行脚本（按文件名顺序遍历执行 `*.sql`） | — |

## 表概览

```
users (1) ──── (N) sessions (1) ─┬─ (N) messages           会话消息流
                                 ├─ (N) state_snapshots    会话状态快照
                                 ├─ (N) tool_calls         工具调用审计
                                 └─ (N) handoff_records    转人工记录
```

- `users` 与 `sessions` 通过 `user_id` 逻辑关联（未设外键，便于匿名/游客会话）
- `sessions` 下 4 张子表均通过 `session_id` 外键关联，`ON DELETE CASCADE` 跟随会话清理

## 执行方式

### 方式一：docker（默认）

表建到 docker 容器内的 MySQL，无需宿主机安装 mysql 客户端。

```bash
bash template/sqls/run.sh
```

环境变量覆盖：

- `CONTAINER` — MySQL 容器名（默认 `myagent-mysql`）
- `MYSQL_ROOT_PASSWORD` — 容器内 root 密码（默认 `root`）

### 方式二：宿主机直连

读 `config/llm_config.${APP_ENV}.yml` 的 `mysql` 段连接数据库。

```bash
bash template/sqls/run.sh --host
```

- `APP_ENV` — 配置环境（默认 `test`，对应读取 `config/llm_config.test.yml`）

## 新增表 / 修改表结构

1. 新增表：在当前目录新建 `NN_xxx.sql`（`NN` 为序号，确保在依赖表之后执行）
2. `run.sh` 会自动按文件名排序遍历执行所有 `*.sql`，无需改脚本
3. 同步更新 `app/model/` 下的 ORM 模型，保持 DDL 与模型字段一致
4. 所有 DDL 使用 `CREATE TABLE IF NOT EXISTS`，可重复执行

## 已存在表加列

`CREATE TABLE IF NOT EXISTS` 不会修改已存在的表。若生产表已建好但缺列（如 `messages.sanitized_content`），需手动执行：

```sql
ALTER TABLE messages ADD COLUMN sanitized_content TEXT NOT NULL AFTER content;
```

## 环境约定

- 引擎：`InnoDB`
- 字符集：`utf8mb4` / `utf8mb4_unicode_ci`
- 时间戳：`TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP`（`updated_at` 加 `ON UPDATE CURRENT_TIMESTAMP`）
- 布尔值：ORM 用 `Boolean`，MySQL 用 `TINYINT(1)`
- JSON 字段：ORM 用 `JSON`，MySQL 用 `JSON` 类型（5.7+）
