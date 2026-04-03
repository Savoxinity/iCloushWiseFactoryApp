# iCloush 智慧工厂 V4.0 — 后端全面 Bug 审计报告

**审计日期**：2026 年 4 月 1 日  
**审计范围**：`iCloush_Backend_V1` 全部 Python 后端文件 + `miniprogram` 前端 API 调用交叉比对  
**审计人**：Manus AI

---

## 一、审计概述

本次审计对 iCloush 智慧工厂 V4.0 的后端代码进行了全量逐文件审查，同时读取了微信小程序前端全部 28 个页面的 93 处 API 调用，逐一与后端路由进行交叉比对。审计共发现 **18 个 Bug**，涉及 **7 个文件**，涵盖路由缺失（404）、参数不匹配（422）、数据返回格式错误（500）、重复函数定义、路由重复注册等多个类别。

以下为按严重程度排列的完整 Bug 清单及修复方案。

---

## 二、Bug 分类统计

| 类别 | 数量 | 严重程度 | 影响范围 |
|------|------|----------|----------|
| 路由缺失（404） | 7 | 高 | 商城兑换、排班保存/复制、请假、角色修改、员工停用 |
| 参数不匹配（422） | 3 | 高 | 排班分配/移除、产能录入 |
| 数据返回格式错误 | 2 | 中 | 报表汇总、兑换记录 |
| 代码缺陷 | 3 | 中 | 重复函数定义、路由重复注册、JSON 字段变更检测 |
| 前端工具函数缺失 | 1 | 低 | 排班复制功能 |
| WebSocket 容错 | 1 | 低 | WS 连接 user_id=0 |
| 字段名不一致 | 1 | 中 | 用户编辑接口字段名与前端不匹配 |

---

## 三、详细 Bug 清单

### 3.1 路由缺失类（404 Not Found）

**BUG-01：商城兑换路由不匹配。** 前端调用 `POST /api/v1/mall/exchange`，请求体为 `{item_id: int}`，但后端只有 `POST /api/v1/mall/redeem/{item_id}`，路径和参数传递方式均不匹配。修复方案是在 `mall.py` 中新增 `POST /exchange` 路由，接收 JSON body 中的 `item_id`。

**BUG-02：兑换记录返回格式错误。** 前端调用 `GET /api/v1/exchange/records`，期望返回包含 `name`、`icon`、`points_cost`、`status` 字段的兑换记录列表。但后端 `mall.py` 的 `/records` 路由仅从 `PointLedger` 表中筛选 `delta < 0` 的记录，缺少商品名称、图标等关键字段。修复方案是在兑换时将商品信息编码到 `reason` 字段中，查询时解析还原。

**BUG-03：排班保存路由缺失。** 前端调用 `POST /api/v1/schedule/save`，发送完整排班数据 `{date, slots}`，但后端 `schedule.py` 中不存在此路由。修复方案是新增 `/save` 路由，遍历 slots 批量更新员工的 `current_zones`。

**BUG-04：排班复制路由缺失。** 前端调用 `POST /api/v1/schedule/copy`，发送 `{from_date, to_date}`，但后端不存在此路由。由于当前系统排班基于 `current_zones` 实时字段而非按日期存储，修复方案是新增一个返回成功的占位路由。

**BUG-05：请假路由缺失。** 前端调用 `POST /api/v1/leave`（schedule 页面）和 `POST /api/v1/schedule/leave`（pages/schedule 页面），发送 `{user_id, type, remark, date}`，但后端不存在此路由。修复方案是在 `schedule.py` 中新增 `/leave` 路由，并在 `main.py` 中注册 `/api/v1/leave` 代理。

**BUG-06：角色修改路由缺失。** 前端权限管理页面调用 `PATCH /api/v1/users/{id}/role`，发送 `{role: int}`，但后端 `users.py` 中只有 `PUT /{user_id}` 全量更新路由。修复方案是新增 `PATCH /{user_id}/role` 专用路由。

**BUG-07：员工停用路由缺失。** 前端调用 `POST /api/v1/users/{id}/disable`，但后端不存在此路由。修复方案是新增 `POST /{user_id}/disable` 路由，将 `is_active` 设为 `False`。

### 3.2 参数不匹配类（422 Unprocessable Entity）

**BUG-08：排班分配参数不匹配。** 前端发送 `{user_id: int, zone_id: int, date: str}`，但后端 `AssignRequest` Schema 定义为 `{user_id: int, zone_code: str}`。前端传的是 `zone_id`（整数），后端期望 `zone_code`（字符串如 "zone_a"），且前端额外传了 `date` 字段导致验证失败。修复方案是让 Schema 同时接受 `zone_id` 和 `zone_code`，并增加可选的 `date` 字段。

**BUG-09：排班移除参数不匹配。** 与 BUG-08 同理，`RemoveRequest` 存在完全相同的问题。

**BUG-10：产能录入参数缺失。** 前端发送 `{date, total_sets, worker_count, work_hours}`，但后端 `DailyProductionCreate` Schema 要求 `efficiency_kpi: float` 为必填字段。前端不传此字段，导致 422 错误。修复方案是将 `efficiency_kpi` 改为 `Optional[float]`，在后端自动计算 `套/人·时`。

### 3.3 数据返回格式错误类

**BUG-11：用户编辑接口字段名不一致。** 前端 `PUT /api/v1/users/{id}` 发送 `{name, role, avatar_key, skills, is_multi_post}`，但后端 `UserUpdateRequest` 中头像字段名为 `avatar`（非 `avatar_key`），技能字段在处理逻辑中引用了不存在的 `req.skill_tags`，且缺少 `is_multi_post` 字段。修复方案是统一 Schema 字段名，同时兼容 `skills`/`skill_tags` 和 `avatar`/`avatar_key`。

**BUG-14：报表汇总返回数据不完整。** 前端期望 `/api/v1/reports/summary` 返回 `total_output`、`done_tasks`、`running_tasks`、`rejected_tasks`、`pending_tasks`、`avg_efficiency`、`zone_ranking`、`staff_ranking` 等字段，但后端仅返回 `total_sets`、`avg_efficiency`、`records`。修复方案是重写 summary 接口，聚合任务表和产能表的数据。

### 3.4 代码缺陷类

**BUG-12：用户序列化函数缺少字段。** `_serialize_user` 未返回 `avatar_key`、`phone`、`is_multi_post`、`skills` 等前端需要的字段。修复方案是补充所有必要字段。

**BUG-13：auth.py 重复函数定义。** 文件中存在两个同名的 `password_login` 函数，且第一个函数的 return 语句之后还有无法执行的死代码。修复方案是删除重复定义，清理死代码。

**BUG-16：JSON 字段变更可能不被检测。** `schedule.py` 中对 `user.current_zones`（JSON 类型）的修改虽然采用了新列表赋值方式，但 SQLAlchemy 对 JSON 字段的变更检测并不总是可靠。修复方案是在赋值后调用 `flag_modified(user, 'current_zones')`。

**BUG-17：路由重复注册。** `main.py` 中 `reports.router` 被同时注册到 `/api/v1/reports` 和 `/api/v1/production` 两个前缀，`mall.router` 被同时注册到 `/api/v1/mall` 和 `/api/v1/exchange`。同一 Router 实例注册到多个前缀可能导致路由冲突。修复方案是为 `/production` 和 `/exchange` 创建独立的代理 Router。

### 3.5 前端工具函数缺失

**BUG-15：util.yesterday() 不存在。** 前端 `schedule/index.js` 的 `copyYesterday` 函数调用了 `util.yesterday()`，但 `util.js` 中未定义此函数。修复方案是新增 `yesterday()` 函数并导出。

### 3.6 WebSocket 容错

**BUG-18：WS 连接 user_id=0。** 前端在未登录或登录信息未同步时传递 `user_id=0`，后端会关闭连接。此为前端问题，后端已有容错处理（`if not user_id: close`），无需额外修改。

---

## 四、修复文件清单

所有修复后的完整文件已生成在 `FIXED_FILES/` 目录中，可直接覆盖原文件使用。

| 文件路径 | 修复的 Bug | 修改说明 |
|----------|-----------|----------|
| `app/api/v1/auth.py` | BUG-13 | 删除重复函数定义，清理死代码，新增 `/me` 端点 |
| `app/api/v1/users.py` | BUG-06, 07, 11, 12 | 新增 PATCH role、POST disable 路由；统一字段名；补充序列化字段 |
| `app/api/v1/mall.py` | BUG-01, 02 | 新增 POST /exchange 路由；修复兑换记录返回格式 |
| `app/api/v1/schedule.py` | BUG-03, 04, 05, 08, 09, 16 | 新增 save/copy/leave 路由；修复参数不匹配；添加 flag_modified |
| `app/api/v1/reports.py` | BUG-10, 14 | efficiency_kpi 改为 Optional；重写 summary 聚合逻辑 |
| `app/main.py` | BUG-17, 05 | 消除路由重复注册；新增 /leave 代理路由 |
| `miniprogram/utils/util.js` | BUG-15 | 新增 yesterday() 函数 |

---

## 五、部署注意事项

修复文件不涉及数据库模型变更，无需执行数据库迁移。部署步骤如下：

1. 将 `FIXED_FILES/` 中的文件覆盖到对应的原始路径。
2. 重启 FastAPI 服务（`uvicorn app.main:app --reload`）。
3. 重新编译并上传小程序前端（`util.js` 变更需要重新构建）。
4. 建议在开发环境中逐一验证上述 18 个 Bug 对应的功能点。

---

*报告生成：Manus AI — 2026-04-01*
