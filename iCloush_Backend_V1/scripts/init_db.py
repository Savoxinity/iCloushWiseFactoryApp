"""
iCloush 智慧工厂 — 数据库初始化脚本
═══════════════════════════════════════════════════
自动建表 + 注入基础数据（与前端 mockData.js 完全对齐）

修复清单：
  BUG-1  序列重置在 session.commit() 之后执行
         如果 commit 失败，序列重置也不会执行
         → 将序列重置放在 commit 之后，但加 try/except 保护
  BUG-2  序列重置 SQL 中 is_identity = 'YES' 可能不匹配 SQLAlchemy 自增列
         PostgreSQL 中 SQLAlchemy autoincrement 列可能用 serial/bigserial
         → 改用更通用的 pg_get_serial_sequence 检测方式

用法：
  cd /path/to/iCloush_Backend_V1
  python -m scripts.init_db
"""
import asyncio
import sys
import os

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, AsyncSessionLocal, Base
from app.models.models import (
    User, Zone, Task, IoTDevice, Vehicle,
    MallItem, DailyProduction,
)


async def init():
    print("🔧 正在创建数据库表...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("✅ 数据库表创建完成")

    async with AsyncSessionLocal() as session:
        # ═══════════════════════════════════════════
        # 1. 工区数据（10 个工区，与前端 ZONES 完全对齐）
        # ═══════════════════════════════════════════
        print("📍 注入工区数据...")
        zones = [
            Zone(id=1, name="水洗区", code="zone_a", floor=1, color="#3B82F6",
                 zone_type="wash", capacity=4, pipeline_order=1,
                 pos_left="5%", pos_top="20%", pos_width="22%", pos_height="35%",
                 iot_summary={"temp": 72, "speed": 45, "chemical": 88},
                 iot_summary_text="洗涤龙运行中 72°C", status="running"),
            Zone(id=2, name="烘干区", code="zone_b", floor=1, color="#F59E0B",
                 zone_type="dry_clean", capacity=3, pipeline_order=2,
                 pos_left="30%", pos_top="20%", pos_width="18%", pos_height="35%",
                 iot_summary={"temp": 85, "speed": 30},
                 iot_summary_text="烘干机组 85°C", status="running"),
            Zone(id=3, name="熨烫区", code="zone_c", floor=1, color="#8B5CF6",
                 zone_type="iron", capacity=6, pipeline_order=3,
                 pos_left="52%", pos_top="20%", pos_width="20%", pos_height="35%",
                 iot_summary={"temp": 180, "speed": 12},
                 iot_summary_text="蒸汽熨烫 180°C", status="running"),
            Zone(id=4, name="折叠打包区", code="zone_d", floor=1, color="#00FF88",
                 zone_type="fold", capacity=4, pipeline_order=4,
                 pos_left="75%", pos_top="20%", pos_width="20%", pos_height="35%",
                 iot_summary={},
                 iot_summary_text="人工折叠", status="running"),
            Zone(id=5, name="分拣中心", code="zone_e", floor=1, color="#EC4899",
                 zone_type="sort", capacity=3, pipeline_order=5,
                 pos_left="5%", pos_top="62%", pos_width="22%", pos_height="30%",
                 iot_summary={},
                 iot_summary_text="RFID 分拣", status="running"),
            Zone(id=6, name="物流调度", code="zone_f", floor=1, color="#06B6D4",
                 zone_type="logistics", capacity=2, pipeline_order=6,
                 pos_left="30%", pos_top="62%", pos_width="18%", pos_height="30%",
                 iot_summary={},
                 iot_summary_text="3 车在途", status="running"),
            Zone(id=7, name="手工精洗", code="zone_g", floor=2, color="#F97316",
                 zone_type="hand_wash", capacity=2, pipeline_order=7,
                 pos_left="5%", pos_top="20%", pos_width="22%", pos_height="35%",
                 iot_summary={},
                 iot_summary_text="精洗工位", status="running"),
            Zone(id=8, name="质检区", code="zone_h", floor=2, color="#EF4444",
                 zone_type="sort", capacity=2, pipeline_order=8,
                 pos_left="30%", pos_top="20%", pos_width="18%", pos_height="35%",
                 iot_summary={},
                 iot_summary_text="质检台", status="running"),
            Zone(id=9, name="化料间", code="zone_i", floor=2, color="#A855F7",
                 zone_type="storage", capacity=1, pipeline_order=9,
                 pos_left="52%", pos_top="20%", pos_width="20%", pos_height="35%",
                 iot_summary={"chemical": 75},
                 iot_summary_text="化料库存 75%", status="running"),
            Zone(id=10, name="仓储区", code="zone_j", floor=2, color="#6B7280",
                 zone_type="storage", capacity=2, pipeline_order=10,
                 pos_left="75%", pos_top="20%", pos_width="20%", pos_height="35%",
                 iot_summary={},
                 iot_summary_text="成品仓库", status="running"),
        ]
        session.add_all(zones)
        await session.flush()

        # ═══════════════════════════════════════════
        # 2. 员工数据（与前端 USERS 完全对齐）
        # ═══════════════════════════════════════════
        print("👥 注入员工数据...")
        users = [
            User(id=1, username="zhangwei", password_hash="zw123456",
                 name="张伟", phone="138****1001", role=9,
                 skill_tags=["洗涤龙", "单机洗烘", "展布机平烫", "物流驾驶"], current_zones=["zone_a", "zone_b", "zone_c", "zone_d", "zone_e"],
                 avatar_key="male_admin_01", is_multi_post=True,
                 total_points=2400, monthly_points=680, task_completed=48),
            User(id=2, username="liufang", password_hash="lf123456",
                 name="刘芳", phone="138****1002", role=5,
                 skill_tags=["布草分拣", "手工洗涤", "熨烫"], current_zones=["zone_a", "zone_h"],
                 avatar_key="female_supervisor_01", is_multi_post=True,
                 total_points=1850, monthly_points=520, task_completed=35),
            User(id=3, username="wangqiang", password_hash="wq123456",
                 name="王强", phone="138****1003", role=1,
                 skill_tags=["洗涤龙", "单机洗烘"], current_zones=["zone_a"],
                 avatar_key="male_washer_01", is_multi_post=True,
                 total_points=960, monthly_points=280, task_completed=22),
            User(id=4, username="chenxia", password_hash="cx123456",
                 name="陈霞", phone="138****1004", role=1,
                 skill_tags=["展布机平烫", "平烫后处理"], current_zones=["zone_c", "zone_d"],
                 avatar_key="female_ironer_01", is_multi_post=True,
                 total_points=1100, monthly_points=310, task_completed=28),
            User(id=5, username="zhaomin", password_hash="zm123456",
                 name="赵敏", phone="138****1005", role=3,
                 skill_tags=["布草分拣", "衣服分拣"], current_zones=["zone_e", "zone_f"],
                 avatar_key="female_driver_01", is_multi_post=True,
                 total_points=1500, monthly_points=420, task_completed=32),
        ]
        session.add_all(users)
        await session.flush()

        # ═══════════════════════════════════════════
        # 3. 任务数据（与前端 TASKS 完全对齐）
        # ═══════════════════════════════════════════
        print("📋 注入任务数据...")
        tasks = [
            Task(id=1, title="洗涤龙日常计件", task_type="routine", zone_id=1,
                 status=2, priority=2, points_reward=80,
                 target_count=200, current_progress=127, unit="件",
                 requires_photo=False, assignee_id=3,
                 description="完成水洗区洗涤龙的日常计件任务，确保每批次清洗质量达标。"),
            Task(id=2, title="熨烫区周巡检", task_type="periodic", zone_id=3,
                 status=3, priority=3, points_reward=120,
                 target_count=1, current_progress=1, unit="次",
                 requires_photo=True, assignee_id=4,
                 description="对熨烫区所有设备进行周度巡检，检查蒸汽管路、温控系统、安全阀门。"),
            Task(id=3, title="客户专属制服交付", task_type="specific", zone_id=4,
                 status=0, priority=4, points_reward=200,
                 target_count=50, current_progress=0, unit="套",
                 requires_photo=True, assignee_id=None,
                 description="上海大厦 VIP 客户专属制服加急处理，需在 48 小时内完成清洗、熨烫、打包。"),
            Task(id=4, title="分拣中心 RFID 校准", task_type="periodic", zone_id=5,
                 status=2, priority=2, points_reward=100,
                 target_count=1, current_progress=0, unit="次",
                 requires_photo=True, assignee_id=5,
                 description="校准分拣中心所有 RFID 读写器，确保标签识别率 > 99.5%。"),
            Task(id=5, title="烘干区温控检查", task_type="periodic", zone_id=2,
                 status=4, priority=2, points_reward=60,
                 target_count=1, current_progress=1, unit="次",
                 requires_photo=True, assignee_id=2,
                 description="检查烘干区所有烘干机温控系统，记录各机组温度偏差。"),
        ]
        session.add_all(tasks)
        await session.flush()

        # ═══════════════════════════════════════════
        # 4. IoT 设备数据
        # ═══════════════════════════════════════════
        print("⚙️ 注入 IoT 设备数据...")
        devices = [
            IoTDevice(name="洗涤龙 #1", zone_id=1, device_type="washer",
                      status="running", temp=72.5, speed=45, chemical_pct=88, cycle_count=1247),
            IoTDevice(name="洗涤龙 #2", zone_id=1, device_type="washer",
                      status="running", temp=70.2, speed=42, chemical_pct=82, cycle_count=1189),
            IoTDevice(name="烘干机 #1", zone_id=2, device_type="dryer",
                      status="running", temp=85.0, speed=30, cycle_count=892),
            IoTDevice(name="烘干机 #2", zone_id=2, device_type="dryer",
                      status="warning", temp=92.0, speed=28, cycle_count=756,
                      alerts=[{"msg": "温度偏高", "level": "warning"}]),
            IoTDevice(name="蒸汽熨斗 #1", zone_id=3, device_type="iron",
                      status="running", temp=180.0, speed=12),
            IoTDevice(name="蒸汽熨斗 #2", zone_id=3, device_type="iron",
                      status="running", temp=175.0, speed=14),
            IoTDevice(name="RFID 读写器", zone_id=5, device_type="rfid",
                      status="running"),
            IoTDevice(name="化料配比泵", zone_id=9, device_type="pump",
                      status="running", chemical_pct=75),
        ]
        session.add_all(devices)
        await session.flush()

        # ═══════════════════════════════════════════
        # 5. 车辆数据
        # ═══════════════════════════════════════════
        print("🚛 注入车辆数据...")
        vehicles = [
            Vehicle(plate="沪A·12345", vehicle_type="厢式货车 4.2m", status="out",
                    driver_id=5, load_current=45, load_max=60, unit="袋"),
            Vehicle(plate="沪B·67890", vehicle_type="电动三轮", status="in",
                    load_current=0, load_max=20, unit="袋"),
            Vehicle(plate="沪A·55555", vehicle_type="厢式货车 2.5m", status="out",
                    driver_id=None, load_current=30, load_max=40, unit="袋"),
        ]
        session.add_all(vehicles)
        await session.flush()

        # ═══════════════════════════════════════════
        # 6. 积分商城数据
        # ═══════════════════════════════════════════
        print("🏆 注入积分商城数据...")
        mall_items = [
            MallItem(name="调休半天", category="福利", points_cost=500, stock=10, icon="🏖", description="可兑换半天调休"),
            MallItem(name="食堂加餐券", category="餐饮", points_cost=100, stock=50, icon="🍱", description="食堂加餐一次"),
            MallItem(name="定制工服", category="装备", points_cost=1000, stock=5, icon="👔", description="定制款工服一件"),
            MallItem(name="电影票", category="娱乐", points_cost=300, stock=20, icon="🎬", description="电影票两张"),
            MallItem(name="超市购物卡", category="购物", points_cost=800, stock=8, icon="🛒", description="100元超市购物卡"),
        ]
        session.add_all(mall_items)
        await session.flush()

        # ═══════════════════════════════════════════
        # 7. 每日产能数据（近 7 天）
        # ═══════════════════════════════════════════
        print("📊 注入产能数据...")
        daily_data = [
            DailyProduction(date="2026-03-24", total_sets=1820, worker_count=12, work_hours=8.0, efficiency_kpi=92.3),
            DailyProduction(date="2026-03-25", total_sets=1950, worker_count=14, work_hours=8.5, efficiency_kpi=94.1),
            DailyProduction(date="2026-03-26", total_sets=1780, worker_count=11, work_hours=8.0, efficiency_kpi=89.7),
            DailyProduction(date="2026-03-27", total_sets=2100, worker_count=15, work_hours=9.0, efficiency_kpi=96.5),
            DailyProduction(date="2026-03-28", total_sets=1900, worker_count=13, work_hours=8.0, efficiency_kpi=91.8),
            DailyProduction(date="2026-03-29", total_sets=2050, worker_count=14, work_hours=8.5, efficiency_kpi=95.2),
            DailyProduction(date="2026-03-30", total_sets=1680, worker_count=10, work_hours=7.5, efficiency_kpi=88.4),
        ]
        session.add_all(daily_data)

        await session.commit()

    # ═══════════════════════════════════════════
    # 8. 重置所有表的自增序列（避免手动指定 id 后新增记录冲突）
    # ═══════════════════════════════════════════
    print("🔄 重置自增序列...")
    sequence_reset_sql = """
        DO $$
        DECLARE
            tbl TEXT;
            max_id BIGINT;
            seq_name TEXT;
        BEGIN
            FOR tbl IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
            LOOP
                -- 尝试获取该表 id 列的序列
                BEGIN
                    seq_name := pg_get_serial_sequence(tbl, 'id');
                EXCEPTION WHEN OTHERS THEN
                    seq_name := NULL;
                END;

                IF seq_name IS NOT NULL THEN
                    EXECUTE format('SELECT COALESCE(MAX(id), 1) FROM %I', tbl) INTO max_id;
                    EXECUTE format('SELECT setval(%L, %s)', seq_name, max_id);
                    RAISE NOTICE 'Reset % to %', seq_name, max_id;
                END IF;
            END LOOP;
        END $$;
    """
    from sqlalchemy import text
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sequence_reset_sql))
        print("✅ 自增序列已重置")
    except Exception as e:
        print(f"⚠️ 序列重置时出现异常（可忽略）: {e}")

    print("\n✅ 全部基础数据注入完成！")
    print("=" * 50)
    print(f"  工区：10 个")
    print(f"  员工：5 人")
    print(f"  任务：5 条")
    print(f"  IoT设备：8 台")
    print(f"  车辆：3 辆")
    print(f"  商城商品：5 件")
    print(f"  产能记录：7 天")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(init())
