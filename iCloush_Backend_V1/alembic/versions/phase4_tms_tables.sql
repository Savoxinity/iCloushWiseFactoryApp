-- ═══════════════════════════════════════════════════
-- iCloush 智慧工厂 — Phase 4 机动物流中台 数据库迁移
-- 创建三张新表：vehicle_fleet, delivery_routes, logistics_dispatches
-- 执行方式：docker exec -i icloush-db psql -U icloush -d icloush_db < phase4_tms_tables.sql
-- ═══════════════════════════════════════════════════

BEGIN;

-- ─── 1. 车辆台账 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS vehicle_fleet (
    id              SERIAL PRIMARY KEY,
    plate_number    VARCHAR(20) NOT NULL UNIQUE,
    vehicle_type    VARCHAR(20) NOT NULL DEFAULT 'medium',
    brand           VARCHAR(64),
    color           VARCHAR(16),
    vin             VARCHAR(32),
    mileage         INTEGER NOT NULL DEFAULT 0,

    -- 四险一金倒计时
    inspection_due      DATE,
    compulsory_ins_due  DATE,
    commercial_ins_due  DATE,
    maintenance_due     DATE,

    -- 载重
    load_capacity   INTEGER NOT NULL DEFAULT 60,
    load_unit       VARCHAR(8) NOT NULL DEFAULT '袋',

    -- 状态
    status          VARCHAR(20) NOT NULL DEFAULT 'idle',

    -- 关联现有 vehicles 表
    legacy_vehicle_id INTEGER REFERENCES vehicles(id),

    -- GPS 预留
    gps_device_id   VARCHAR(64),
    last_gps_lat    DOUBLE PRECISION,
    last_gps_lng    DOUBLE PRECISION,
    last_gps_time   TIMESTAMPTZ,

    remark          TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_vehicle_fleet_status ON vehicle_fleet(status);
CREATE INDEX IF NOT EXISTS ix_vehicle_fleet_plate ON vehicle_fleet(plate_number);

COMMENT ON TABLE vehicle_fleet IS '车辆台账 — Phase 4 机动物流中台';
COMMENT ON COLUMN vehicle_fleet.inspection_due IS '年检到期日';
COMMENT ON COLUMN vehicle_fleet.compulsory_ins_due IS '交强险到期日';
COMMENT ON COLUMN vehicle_fleet.commercial_ins_due IS '商业险到期日';
COMMENT ON COLUMN vehicle_fleet.maintenance_due IS '常规保养到期日';


-- ─── 2. 送货排线 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS delivery_routes (
    id                      SERIAL PRIMARY KEY,
    route_name              VARCHAR(100) NOT NULL,
    description             TEXT,
    stops                   JSONB DEFAULT '[]'::JSONB,
    estimated_duration_min  INTEGER,
    estimated_distance_km   DOUBLE PRECISION,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE delivery_routes IS '送货排线 — 固化客户节点与标准时效';
COMMENT ON COLUMN delivery_routes.stops IS 'JSON数组: [{seq, client_name, address, expected_eta, contact_phone, remark}]';


-- ─── 3. 出车调度单 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS logistics_dispatches (
    id              SERIAL PRIMARY KEY,
    work_date       DATE NOT NULL,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicle_fleet(id),
    route_id        INTEGER REFERENCES delivery_routes(id),
    driver_id       INTEGER NOT NULL REFERENCES users(id),
    assistant_id    INTEGER REFERENCES users(id),

    status          VARCHAR(20) NOT NULL DEFAULT 'pending',

    stop_checkins   JSONB DEFAULT '[]'::JSONB,

    departed_at     TIMESTAMPTZ,
    returned_at     TIMESTAMPTZ,
    actual_mileage  INTEGER,

    remark          TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_dispatch_work_date ON logistics_dispatches(work_date);
CREATE INDEX IF NOT EXISTS ix_dispatch_vehicle ON logistics_dispatches(vehicle_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_driver ON logistics_dispatches(driver_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_status ON logistics_dispatches(status);

COMMENT ON TABLE logistics_dispatches IS '出车调度单 — 车-线-人三位一体';
COMMENT ON COLUMN logistics_dispatches.stop_checkins IS 'JSON数组: [{seq, client_name, expected_eta, checked_in_at}]';


-- ─── 种子数据：示例车辆 ────────────────────────────
INSERT INTO vehicle_fleet (plate_number, vehicle_type, brand, load_capacity, inspection_due, compulsory_ins_due, commercial_ins_due, maintenance_due)
VALUES
    ('沪A12345', 'large',  '福田欧马可', 120, '2026-06-15', '2026-05-01', '2026-05-01', '2026-04-20'),
    ('沪B67890', 'medium', '江铃顺达',   80,  '2026-08-20', '2026-07-15', '2026-07-15', '2026-05-10'),
    ('沪C11111', 'medium', '五十铃',     60,  '2026-12-01', '2026-11-01', '2026-11-01', '2026-06-01'),
    ('沪D22222', 'small',  '长安星卡',   40,  '2026-09-10', '2026-04-10', '2026-04-10', '2026-04-05')
ON CONFLICT (plate_number) DO NOTHING;


-- ─── 种子数据：示例排线 ────────────────────────────
INSERT INTO delivery_routes (route_name, description, stops, estimated_duration_min, estimated_distance_km)
VALUES
    (
        '市区南线-早班',
        '覆盖浦东陆家嘴-世纪大道沿线酒店',
        '[
            {"seq": 1, "client_name": "珀丽酒店", "address": "浦东新区陆家嘴环路1000号", "expected_eta": "08:30", "contact_phone": "021-58881234"},
            {"seq": 2, "client_name": "香格里拉大酒店", "address": "浦东新区富城路33号", "expected_eta": "09:15", "contact_phone": "021-68828888"},
            {"seq": 3, "client_name": "东方商旅", "address": "浦东新区东方路818号", "expected_eta": "10:00", "contact_phone": "021-58765432"}
        ]'::JSONB,
        120,
        35.5
    ),
    (
        '郊区北线-午班',
        '覆盖嘉定-安亭工业区',
        '[
            {"seq": 1, "client_name": "嘉定希尔顿", "address": "嘉定区博乐路100号", "expected_eta": "13:00", "contact_phone": "021-59581111"},
            {"seq": 2, "client_name": "安亭假日酒店", "address": "安亭镇墨玉南路888号", "expected_eta": "14:00", "contact_phone": "021-69581234"}
        ]'::JSONB,
        90,
        48.2
    )
ON CONFLICT DO NOTHING;

COMMIT;

-- ═══════════════════════════════════════════════════
-- 验证
-- ═══════════════════════════════════════════════════
SELECT 'vehicle_fleet' AS table_name, COUNT(*) AS row_count FROM vehicle_fleet
UNION ALL
SELECT 'delivery_routes', COUNT(*) FROM delivery_routes
UNION ALL
SELECT 'logistics_dispatches', COUNT(*) FROM logistics_dispatches;
