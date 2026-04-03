# iCloush V4.0 后端全面 Bug 审计报告

## 一、前端→后端 API 路由对照表（缺失/不匹配的路由）

### BUG-01: 商城兑换路由 404
- **前端调用**: `POST /api/v1/mall/exchange` (data: `{item_id: xxx}`)
- **后端实际**: `POST /api/v1/mall/redeem/{item_id}` (路径参数)
- **问题**: 路由路径不匹配 + 参数传递方式不匹配（前端用body传item_id，后端用路径参数）
- **修复**: 在 mall.py 新增 `POST /exchange` 路由，接收 `{item_id: int}` body

### BUG-02: 兑换记录路由 404
- **前端调用**: `GET /api/v1/exchange/records`
- **后端实际**: main.py 第60行注册了 `mall.router` 到 `/api/v1/exchange` 前缀，所以实际路径是 `/api/v1/exchange/records` → 对应 mall.py 的 `/records`
- **问题**: 这个路由实际上应该能工作，但 mall.py 的 `/records` 返回的是 PointLedger 数据（delta < 0），缺少前端需要的 `name`, `icon`, `points_cost`, `status` 字段
- **修复**: 需要新建 ExchangeRecord 模型或在兑换时记录完整信息

### BUG-03: 排班保存路由 404
- **前端调用**: `POST /api/v1/schedule/save`
- **后端实际**: 不存在此路由
- **修复**: 在 schedule.py 新增 `/save` 路由（或前端改为实时单条保存）

### BUG-04: 排班复制路由 404
- **前端调用**: `POST /api/v1/schedule/copy`
- **后端实际**: 不存在此路由
- **修复**: 在 schedule.py 新增 `/copy` 路由

### BUG-05: 请假路由 404
- **前端调用**: `POST /api/v1/leave` (schedule/index.js)
- **后端实际**: 不存在此路由
- **修复**: 在 schedule.py 新增 `/leave` 路由（或新建 leave.py）

### BUG-06: 权限管理 - 角色修改路由 404
- **前端调用**: `PATCH /api/v1/users/{id}/role` (data: `{role: xxx}`)
- **后端实际**: 不存在此路由（只有 `PUT /api/v1/users/{id}`）
- **修复**: 在 users.py 新增 `PATCH /{user_id}/role` 路由

### BUG-07: 员工停用路由 404
- **前端调用**: `POST /api/v1/users/{id}/disable`
- **后端实际**: 不存在此路由
- **修复**: 在 users.py 新增 `POST /{user_id}/disable` 路由

## 二、排班 422 错误（字段名不匹配）

### BUG-08: schedule/assign 422 错误
- **前端发送**: `{ user_id: staffId, zone_id: targetZoneId, date: util.today() }`
- **后端 AssignRequest**: `{ user_id: int, zone_code: str }`
- **问题1**: 前端传 `zone_id`（整数），后端期望 `zone_code`（字符串如"zone_a"）
- **问题2**: 前端传 `date` 字段，后端 Schema 不接受此字段
- **修复**: 后端 AssignRequest 改为接受 zone_id（int）或 zone_code（str），增加 date 可选字段；或者两种都支持

### BUG-09: schedule/remove 422 错误
- **同 BUG-08**: 前端传 zone_id，后端期望 zone_code

## 三、产能录入 422 错误

### BUG-10: production/daily POST 422 错误
- **前端发送**: `{ date: util.today(), total_sets: s, worker_count: n, work_hours: h }`
- **后端 DailyProductionCreate**: `{ date: str, total_sets: int, worker_count: int, work_hours: float, efficiency_kpi: float }`
- **问题**: 前端没有传 `efficiency_kpi` 字段，但后端 Schema 要求此字段（没有默认值）
- **修复**: 后端 efficiency_kpi 改为 Optional，在后端自动计算

## 四、用户管理字段不匹配

### BUG-11: PUT /users/{id} 500 错误
- **前端发送**: `{ name, role, avatar_key, skills, is_multi_post }`
- **后端 UserUpdateRequest**: `{ name, role, phone, skills, avatar, is_active }`
- **问题1**: 前端传 `skills`，后端 Schema 字段名是 `skills`，但 update_user 函数里引用的是 `req.skill_tags`（第90行），而 Schema 里没有 `skill_tags` 字段
- **问题2**: 前端传 `avatar_key`，后端 Schema 字段名是 `avatar`
- **问题3**: 前端传 `is_multi_post`，后端 Schema 没有此字段
- **修复**: 统一 UserUpdateRequest 字段名与前端一致

### BUG-12: _serialize_user 缺少字段
- **问题**: 前端需要 `avatar_key`, `phone`, `is_multi_post` 等字段，但 _serialize_user 没有返回
- **修复**: 补充返回字段

## 五、auth.py 重复定义

### BUG-13: auth.py 有两个 password_login 函数
- **问题**: 第34-65行和第68-85行定义了两个同名函数 `password_login`，且都注册到 `/verify` 路由
- **第一个函数**（34-65行）在 return 之后还有死代码（微信登录逻辑）
- **修复**: 删除重复的第二个函数，清理第一个函数中的死代码

## 六、报表 summary 返回数据不匹配

### BUG-14: reports/summary 返回数据不满足前端需求
- **前端期望字段**: `total_output`, `done_tasks`, `running_tasks`, `rejected_tasks`, `pending_tasks`, `avg_efficiency`, `zone_ranking`, `staff_ranking`
- **后端实际返回**: `total_sets`, `avg_efficiency`, `records`
- **问题**: 后端只返回产能数据，没有任务统计、工区排名、员工排名
- **修复**: 重写 reports/summary 接口，聚合任务数据 + 产能数据

## 七、util.js 缺失函数

### BUG-15: util.yesterday 不存在
- **前端调用**: `util.yesterday()` (schedule/index.js copyYesterday)
- **后端**: N/A（前端问题）
- **修复**: 在 util.js 中添加 yesterday 函数并导出

## 八、排班数据不持久化

### BUG-16: 排班 assign/remove 使用 JSON 字段存储，SQLAlchemy 可能不检测变化
- **问题**: `user.current_zones` 是 JSON 类型，SQLAlchemy 对 JSON 字段的原地修改（如 list.append）不会自动标记为脏数据
- **代码**: schedule.py 第40-43行 `zones = list(user.current_zones or []); zones.append(...); user.current_zones = zones`
- **分析**: 代码已经用了 `zones = list(...)` 创建新列表再赋值，理论上应该能触发变更检测
- **但**: 需要确认 SQLAlchemy 是否正确检测到 JSON 字段变更。可能需要加 `flag_modified`
- **修复**: 在赋值后添加 `from sqlalchemy.orm.attributes import flag_modified; flag_modified(user, 'current_zones')`

## 九、main.py 路由重复注册

### BUG-17: reports.router 和 mall.router 被注册了两次
- **问题**: 
  - 第56行: `reports.router` → `/api/v1/reports`
  - 第59行: `reports.router` → `/api/v1/production` （重复注册同一个 router）
  - 第57行: `mall.router` → `/api/v1/mall`
  - 第60行: `mall.router` → `/api/v1/exchange` （重复注册同一个 router）
- **影响**: 同一个 router 注册到两个前缀，可能导致路由冲突或意外行为
- **修复**: 将 production 和 exchange 的路由分离到独立的 router 中，或在 reports/mall 中用条件处理

## 十、WebSocket user_id=0 问题

### BUG-18: WS 连接 user_id=0
- **日志**: `ws://192.168.1.4:8000/ws/iot?user_id=0&role=1`
- **问题**: 前端在未登录或登录信息未同步时传了 user_id=0
- **代码**: iot_ws.py 第98行 `if not user_id:` 会关闭连接
- **修复**: 前端问题，但后端应该容错处理

## 总结：需要修改的文件清单

1. **app/api/v1/users.py** - BUG-06, BUG-07, BUG-11, BUG-12
2. **app/api/v1/mall.py** - BUG-01, BUG-02
3. **app/api/v1/schedule.py** - BUG-03, BUG-04, BUG-05, BUG-08, BUG-09, BUG-16
4. **app/api/v1/reports.py** - BUG-10, BUG-14
5. **app/api/v1/auth.py** - BUG-13
6. **app/main.py** - BUG-17
7. **miniprogram/utils/util.js** - BUG-15
