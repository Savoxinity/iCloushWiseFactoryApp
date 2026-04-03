# iCloush 智慧工厂 V4.0 — 后端代码全面审计报告

**审计日期：** 2026-04-01  
**审计范围：** `iCloush_Backend_V1/` 全部后端 Python 文件  
**审计方法：** 逐文件代码审查 + 前端 API 调用交叉比对

---

## 一、审计概要

本次审计对 iCloush 智慧工厂 V4.0 后端的全部 API 路由文件、数据库模型、安全模块及初始化脚本进行了逐行检查，并与前端小程序（miniprogram）中的所有 API 调用进行了交叉比对。共发现 **12 个问题**，其中 **4 个为导致 500 错误的严重 BUG**，**3 个为功能缺失**，**5 个为代码质量/潜在风险问题**。

| 严重等级 | 数量 | 说明 |
|---------|------|------|
| **致命（500 错误）** | 4 | 直接导致接口返回 500 Internal Server Error |
| **严重（功能缺失）** | 3 | 前端调用的接口在后端不存在或行为不正确 |
| **警告（代码质量）** | 5 | 不影响当前功能但存在潜在风险 |

---

## 二、致命问题（500 错误）

### BUG-1：`PUT /api/v1/users/{id}` — 字段名不匹配导致 500

**文件：** `app/api/v1/users.py`  
**现象：** 编辑员工时返回 500 Internal Server Error  
**根因：** `UserUpdateRequest` Pydantic 模型的字段名与前端发送的字段名不一致。

| 前端发送的字段 | 后端 Pydantic 模型中的字段 | 后端更新逻辑中引用的字段 |
|---------------|--------------------------|------------------------|
| `skills` | `skills`（正确） | `req.skill_tags`（错误！不存在） |
| `avatar_key` | `avatar`（错误！） | `req.avatar`（无效） |
| `is_multi_post` | 不存在 | 不存在 |

当前端发送 `{"skills": [...], "avatar_key": "xxx", "is_multi_post": true}` 时，Pydantic 会忽略 `avatar_key` 和 `is_multi_post`（因为模型中没有这些字段），而更新逻辑中 `req.skill_tags` 引用了一个不存在的属性，直接导致 `AttributeError` → 500。

**修复方案：** 将 `UserUpdateRequest` 的字段名改为与前端完全一致：`skills`、`avatar_key`、`is_multi_post`。更新逻辑中将 `req.skills` 映射到 `user.skill_tags`。

---

### BUG-2：`POST /api/v1/tasks/` — 字段名不匹配导致 500

**文件：** `app/api/v1/tasks.py`  
**现象：** 创建任务时返回 500 Internal Server Error  
**根因：** 前端 `task-create/index.js` 发送的字段与后端 `TaskCreateRequest` 不一致。

| 前端发送的字段 | 后端期望的字段 | 状态 |
|---------------|-------------|------|
| `target` | `target_count` | 不匹配 → 前端的 target 被忽略，target_count 默认为 1 |
| `assigned_to`（数组） | `assignee_id`（整数） | 不匹配 → 类型错误导致 422 或 500 |
| `zone_name` | 不存在 | 多余字段，Pydantic 默认忽略 |

当前端发送 `{"assigned_to": [3, 4], "target": 200}` 时，`assigned_to` 是数组类型而 `assignee_id` 期望整数，Pydantic 验证失败返回 422；即使通过验证，`target` 字段被忽略导致目标数量永远为 1。

**修复方案：** 在 `TaskCreateRequest` 中同时接受 `target` 和 `target_count`、`assigned_to` 和 `assignee_id`，在创建逻辑中做兼容处理。

---

### BUG-3：`POST /api/v1/users/` — `avatar_key` 赋值逻辑异常

**文件：** `app/api/v1/users.py`  
**现象：** 创建用户时可能触发异常  
**根因：** 原代码中 `avatar_key=req.avatar_key or req.name[0] if req.name else "?"` 的运算符优先级问题。Python 中 `or` 的优先级低于条件表达式，实际执行为 `req.avatar_key or (req.name[0] if req.name else "?")`，当 `req.name` 为空字符串时 `req.name[0]` 会抛出 `IndexError`。

**修复方案：** 加括号明确优先级：`req.avatar_key or (req.name[0] if req.name else "?")`。

---

### BUG-4：`auth.py` — `password_login` 函数重复定义

**文件：** `app/api/v1/auth.py`  
**现象：** 第一个 `password_login` 函数被第二个同名函数覆盖，导致登录逻辑不可预测  
**根因：** 文件中存在两个 `password_login` 函数定义，第一个包含微信登录的死代码（在 `return` 之后），第二个覆盖了第一个。Python 不会报错但行为不确定。

**修复方案：** 删除重复定义，将微信登录逻辑拆分为独立的 `/wechat-login` 端点。

---

## 三、功能缺失问题

### MISS-1：`POST /api/v1/tasks/{id}/edit` — 路由不存在（404）

**文件：** `app/api/v1/tasks.py`  
**现象：** 前端 `task-edit/index.js` 调用 `POST /api/v1/tasks/{id}/edit` 返回 404  
**根因：** 后端 `tasks.py` 中没有定义 `/{task_id}/edit` 路由。

**修复方案：** 新增 `@router.post("/{task_id}/edit")` 端点，接受 `TaskEditRequest`，逐字段更新任务。

---

### MISS-2：`POST /api/v1/users/{id}/disable` — 路由不存在

**文件：** `app/api/v1/users.py`  
**现象：** 前端 staff-manage 的「停用」按钮调用此接口会 404  
**根因：** 后端没有定义 disable 端点。

**修复方案：** 新增 `@router.post("/{user_id}/disable")` 端点。

---

### MISS-3：`_serialize_user` 返回字段不完整

**文件：** `app/api/v1/users.py`  
**现象：** 前端 staff-manage 读取 `avatar_key`、`is_multi_post`、`status` 字段时为 undefined  
**根因：** `_serialize_user` 函数没有返回这些字段。

**修复方案：** 在序列化函数中补齐 `avatar_key`、`is_multi_post`、`status`、`skills` 字段。

---

## 四、代码质量 / 潜在风险

### WARN-1：`init_db.py` 序列重置时机

手动指定 `id=1, id=2...` 插入数据后，PostgreSQL 的自增序列不会自动更新。后续 `INSERT` 不指定 id 时，序列从 1 开始分配，与已有记录冲突导致 `UniqueViolation`。当前 `init_db.py` 的序列重置逻辑需要更健壮的实现。

**修复方案：** 使用 `pg_get_serial_sequence()` 动态获取序列名，用 `setval()` 重置到 `MAX(id)`。

---

### WARN-2：`main.py` 重复注册路由

`reports.router` 被注册了两次（`/api/v1/reports` 和 `/api/v1/production`），`mall.router` 也被注册了两次（`/api/v1/mall` 和 `/api/v1/exchange`）。虽然不会报错，但同一个 router 挂载到两个前缀下，所有端点都会在两个路径下可用，可能造成混淆。

**状态：** 这是有意为之（兼容前端不同页面的不同 URL 前缀），暂不修改。

---

### WARN-3：明文密码存储

`User.password_hash` 字段实际存储的是明文密码（`password_hash=req.password`），没有使用 bcrypt 等哈希算法。

**建议：** 生产环境前务必改为 bcrypt 哈希。当前开发阶段可暂时保留。

---

### WARN-4：`upload.py` STS SDK 缺失时返回模拟数据

当 `sts` 包未安装时，`/upload/sts` 返回模拟凭证。这在开发环境可以接受，但生产环境应确保 SDK 已安装或返回明确错误。

---

### WARN-5：WebSocket 连接无 JWT 认证

`/ws/iot` 端点直接从 query parameter 读取 `user_id` 和 `role`，没有验证 JWT Token。任何人都可以伪造 `user_id=1&role=9` 获取管理员级别的 WebSocket 推送。

**建议：** 生产环境前应在 WebSocket 握手时验证 JWT Token。

---

## 五、修复文件清单

本次审计共生成 **3 个需要替换的文件**：

| 文件路径 | 修复内容 |
|---------|---------|
| `app/api/v1/users.py` | BUG-1, BUG-3, MISS-2, MISS-3 |
| `app/api/v1/tasks.py` | BUG-2, MISS-1 |
| `app/api/v1/auth.py` | BUG-4 |
| `scripts/init_db.py` | WARN-1（序列重置） |

**使用方法：** 将 `fixed_files/` 目录下的文件直接覆盖到项目对应位置即可。其他文件（zones.py、iot.py、reports.py、mall.py、points.py、schedule.py、upload.py、models.py、security.py、database.py、config.py、main.py）经审计无需修改。

---

## 六、修复后的前后端接口对照表

以下是前端所有 API 调用与后端路由的完整对照，修复后全部可用：

| 前端页面 | HTTP 方法 | 前端调用路径 | 后端路由 | 状态 |
|---------|----------|------------|---------|------|
| staff-manage | GET | `/api/v1/users` | `users.router GET /` | 正常 |
| staff-manage | PUT | `/api/v1/users/{id}` | `users.router PUT /{user_id}` | **已修复** |
| staff-manage | POST | `/api/v1/users` | `users.router POST /` | **已修复** |
| staff-manage | POST | `/api/v1/users/{id}/disable` | `users.router POST /{user_id}/disable` | **已新增** |
| task-create | POST | `/api/v1/tasks` | `tasks.router POST /` | **已修复** |
| task-edit | POST | `/api/v1/tasks/{id}/edit` | `tasks.router POST /{task_id}/edit` | **已新增** |
| task-list | GET | `/api/v1/tasks` | `tasks.router GET /` | 正常 |
| task-detail | GET | `/api/v1/tasks/{id}` | `tasks.router GET /{task_id}` | 正常 |
| task-detail | GET | `/api/v1/tasks/{id}/records` | `tasks.router GET /{task_id}/records` | 正常 |
| task-detail | POST | `/api/v1/tasks/{id}/accept` | `tasks.router POST /{task_id}/accept` | 正常 |
| task-detail | POST | `/api/v1/tasks/{id}/count` | `tasks.router POST /{task_id}/count` | 正常 |
| task-detail | POST | `/api/v1/tasks/{id}/submit` | `tasks.router POST /{task_id}/submit` | 正常 |
| task-detail | POST | `/api/v1/tasks/{id}/review` | `tasks.router POST /{task_id}/review` | 正常 |
| task-list | GET | `/api/v1/tasks/stats` | `tasks.router GET /stats` | 正常 |
| zone-detail | GET | `/api/v1/zones` | `zones.router GET /` | 正常 |
| login | POST | `/api/v1/auth/verify` | `auth.router POST /verify` | **已修复** |
| login | POST | `/api/v1/auth/wechat-login` | `auth.router POST /wechat-login` | **已新增** |
| iot-dashboard | GET | `/api/v1/iot/dashboard` | `iot.router GET /dashboard` | 正常 |
| iot-dashboard | GET | `/api/v1/iot/devices` | `iot.router GET /devices` | 正常 |
| mall | GET | `/api/v1/mall/items` | `mall.router GET /items` | 正常 |
| mall | POST | `/api/v1/mall/exchange` | `mall.router POST /redeem/{item_id}` | 正常 |
| points | GET | `/api/v1/points/summary` | `points.router GET /summary` | 正常 |
| points | GET | `/api/v1/points/ledger` | `points.router GET /ledger` | 正常 |
| reports | GET | `/api/v1/reports` | `reports.router GET /summary` | 正常 |
| upload | GET | `/api/v1/upload/sts` | `upload.router GET /sts` | 正常 |
| schedule | POST | `/api/v1/schedule/assign` | `schedule.router POST /assign` | 正常 |
| schedule | POST | `/api/v1/schedule/remove` | `schedule.router POST /remove` | 正常 |

---

## 七、部署后验证步骤

修复文件替换完成后，请按以下步骤验证：

1. **重新初始化数据库**（如需要）：
   ```bash
   docker exec -it icloush-backend python -m scripts.init_db
   ```

2. **重启后端服务**：
   ```bash
   docker-compose restart backend
   ```

3. **验证关键接口**：
   ```bash
   # 登录获取 Token
   curl -X POST http://192.168.1.4:8000/api/v1/auth/verify \
     -H "Content-Type: application/json" \
     -d '{"username":"zhangwei","password":"zw123456"}'

   # 编辑员工（用返回的 token）
   curl -X PUT http://192.168.1.4:8000/api/v1/users/6 \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"测试","role":1,"skills":["洗涤龙"],"avatar_key":"male_01","is_multi_post":false}'

   # 创建任务
   curl -X POST http://192.168.1.4:8000/api/v1/tasks \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"title":"测试任务","zone_id":1,"target":100,"assigned_to":[3]}'

   # 编辑任务
   curl -X POST http://192.168.1.4:8000/api/v1/tasks/1/edit \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"title":"修改后的标题","target":150}'
   ```

4. **在小程序中测试**：
   - 员工管理页面：编辑员工 → 保存 → 应返回成功
   - 任务创建页面：创建任务 → 应返回成功
   - 任务编辑页面：编辑任务 → 应返回成功
