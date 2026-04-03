# iCloush 智慧工厂后端 V1.0

**技术栈：** FastAPI + PostgreSQL (SQLAlchemy 2.0 Async) + Redis + WebSocket

**部署目标：** 微信云托管 (WeChat Cloud Run)

---

## 项目结构

```
iCloush_Backend_V1/
├── app/
│   ├── api/v1/           # API 路由
│   │   ├── auth.py       # 认证（微信登录 + 账号密码）
│   │   ├── tasks.py      # 任务（RBAC + 状态机）
│   │   ├── zones.py      # 工区
│   │   ├── users.py      # 员工管理
│   │   ├── schedule.py   # 排班
│   │   ├── iot.py        # IoT 设备
│   │   ├── upload.py     # COS STS 临时密钥
│   │   ├── reports.py    # 报表
│   │   ├── mall.py       # 积分商城
│   │   └── points.py     # 积分
│   ├── core/
│   │   ├── config.py     # 配置管理
│   │   ├── database.py   # 数据库连接
│   │   └── security.py   # JWT + RBAC
│   ├── models/
│   │   └── models.py     # SQLAlchemy 模型
│   ├── ws/
│   │   └── iot_ws.py     # WebSocket 实时推送
│   └── main.py           # FastAPI 入口
├── scripts/
│   └── init_db.py        # 数据库初始化 + 种子数据
├── Dockerfile            # 微信云托管适配
├── docker-compose.yml    # 本地开发
├── requirements.txt      # Python 依赖
├── .env.example          # 环境变量模板
└── README.md
```

---

## 快速开始

### 本地开发

```bash
# 1. 复制环境变量
cp .env.example .env
# 编辑 .env 填入真实值

# 2. Docker Compose 启动
docker-compose up -d

# 3. 初始化数据库 + 种子数据
docker-compose exec api python -m scripts.init_db

# 4. 访问 API 文档
open http://localhost:8000/docs
```

### 微信云托管部署

1. 将代码推送到 Git 仓库
2. 在微信云托管控制台创建服务，关联仓库
3. 配置环境变量（参考 `.env.example`）
4. 云托管会自动构建 Docker 镜像并部署

---

## 核心 API

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/v1/auth/wechat-login` | 微信登录 | 公开 |
| POST | `/api/v1/auth/verify` | 账号密码登录 | 公开 |
| GET | `/api/v1/auth/me` | 当前用户信息 | 登录 |
| GET | `/api/v1/tasks` | 任务列表（RBAC） | 登录 |
| POST | `/api/v1/tasks/{id}/accept` | 接单 | 登录 |
| POST | `/api/v1/tasks/{id}/count` | 计件 | 负责人 |
| POST | `/api/v1/tasks/{id}/submit` | 提交审核 | 负责人 |
| POST | `/api/v1/tasks/{id}/review` | 审核 | role>=5 |
| POST | `/api/v1/tasks` | 创建任务 | role>=5 |
| GET | `/api/v1/zones` | 工区列表 | 登录 |
| POST | `/api/v1/schedule/assign` | 分配排班 | role>=5 |
| POST | `/api/v1/schedule/remove` | 移除排班 | role>=5 |
| GET | `/api/v1/iot/dashboard` | IoT 仪表盘 | role>=5 |
| GET | `/api/v1/upload/sts` | COS 临时密钥 | 登录 |
| WS | `/ws/iot` | 实时推送 | 登录 |

---

## 任务状态机

```
待接单(0) ──accept──→ 进行中(2) ──submit──→ 待审核(3) ──pass──→ 已完成(4)
                          ↑                               ↓
                          └──── fail (is_rejected=true) ←──┘
```

---

## 数据库模型

| 表 | 说明 | 关键字段 |
|---|---|---|
| users | 员工 | wechat_openid, role, current_zones, skill_tags |
| zones | 工区 | code, zone_type, capacity, 沙盘定位 |
| tasks | 任务 | status(状态机), assignee_id, is_rejected |
| task_records | 执行流水 | action_type, delta_count, photo_urls |
| iot_devices | IoT 设备 | temp, speed, chemical_pct, alerts |
| vehicles | 车辆 | plate, status, load_current |
| point_ledger | 积分账本 | delta, reason |
| mall_items | 商城商品 | points_cost, stock |
| daily_production | 每日产能 | total_sets, efficiency_kpi |

---

## 微信云托管适配

- **免鉴权内部链路：** 当部署在微信云托管时，请求头自动携带 `x-wx-openid`，后端直接读取，无需调用微信服务器换取 session_key
- **端口：** Dockerfile 监听 80 端口（云托管要求）
- **健康检查：** `/health` 端点

---

## 测试账号

| 用户名 | 密码 | 角色 | 工区 |
|--------|------|------|------|
| zhangwei | zw123456 | 超级管理员(9) | 全厂 |
| liufang | lf123456 | 主管(5) | 水洗区、质检区 |
| wangqiang | wq123456 | 普通员工(1) | 水洗区 |
| chenxia | cx123456 | 普通员工(1) | 熨烫区、折叠打包区 |
| zhaomin | zm123456 | 组长(3) | 分拣中心、物流调度 |
