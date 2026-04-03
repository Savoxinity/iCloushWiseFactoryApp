"""
Phase 3B/3C 财务模块数据库迁移脚本
═══════════════════════════════════════════════════
新增表：
  - invoices              发票表
  - expense_claims        报销单表
  - cost_category         成本分类表
  - management_cost_ledger 管理成本流水表
  - missing_invoice_ledger 欠票台账表

修改表：
  - 无（所有新功能使用新表）

执行方式：
  alembic upgrade head
  或手动执行 SQL
"""

# Alembic 迁移文件格式
revision = 'phase3bc_001'
down_revision = None  # 根据实际迁移链调整
branch_labels = None
depends_on = None


def upgrade():
    """创建 Phase 3B/3C 所需的数据库表"""
    import sqlalchemy as sa
    from alembic import op

    # ── 发票表 ──
    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('invoice_type', sa.String(50), comment='发票类型'),
        sa.Column('invoice_code', sa.String(50), comment='发票代码'),
        sa.Column('invoice_number', sa.String(50), comment='发票号码'),
        sa.Column('invoice_date', sa.Date, comment='开票日期'),
        sa.Column('check_code', sa.String(50), comment='校验码'),
        sa.Column('buyer_name', sa.String(200), comment='购方名称'),
        sa.Column('buyer_tax_id', sa.String(50), comment='购方税号'),
        sa.Column('seller_name', sa.String(200), comment='销方名称'),
        sa.Column('seller_tax_id', sa.String(50), comment='销方税号'),
        sa.Column('pre_tax_amount', sa.Numeric(12, 2), comment='不含税金额'),
        sa.Column('tax_amount', sa.Numeric(12, 2), comment='税额'),
        sa.Column('total_amount', sa.Numeric(12, 2), comment='价税合计'),
        sa.Column('remark', sa.Text, comment='备注'),
        sa.Column('image_url', sa.String(500), comment='发票图片URL'),
        sa.Column('ocr_raw_json', sa.JSON, comment='OCR原始JSON'),
        sa.Column('verify_status', sa.String(20), server_default='pending', comment='核验状态'),
        sa.Column('verify_result_json', sa.JSON, comment='核验结果JSON'),
        sa.Column('business_type', sa.String(50), comment='业务分类'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── 报销单表 ──
    op.create_table(
        'expense_claims',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('purpose', sa.String(500), nullable=False, comment='报销事由'),
        sa.Column('claimed_amount', sa.Numeric(12, 2), nullable=False, comment='报销金额'),
        sa.Column('voucher_type', sa.String(20), nullable=False, comment='凭证类型: invoice/receipt'),
        sa.Column('invoice_id', sa.Integer, sa.ForeignKey('invoices.id'), comment='关联发票ID'),
        sa.Column('receipt_image_url', sa.String(500), comment='收据图片URL'),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False, index=True,
                  comment='状态: pending/auto_approved/manual_review/approved/rejected'),
        sa.Column('category_code', sa.String(20), comment='成本分类代码（审核时填写）'),
        sa.Column('review_note', sa.Text, comment='审核备注'),
        sa.Column('reviewed_by', sa.Integer, sa.ForeignKey('users.id'), comment='审核人ID'),
        sa.Column('reviewed_at', sa.DateTime, comment='审核时间'),
        sa.Column('amount_diff_pct', sa.Numeric(5, 2), comment='发票金额偏差百分比'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── 成本分类表 ──
    op.create_table(
        'cost_category',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('code', sa.String(20), unique=True, nullable=False, comment='分类代码'),
        sa.Column('name', sa.String(100), nullable=False, comment='分类名称'),
        sa.Column('behavior', sa.String(20), nullable=False, comment='成本性态: variable/fixed'),
        sa.Column('sort_order', sa.Integer, server_default='0', comment='排序'),
        sa.Column('is_active', sa.Boolean, server_default='1', comment='是否启用'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── 管理成本流水表 ──
    op.create_table(
        'management_cost_ledger',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('trade_date', sa.Date, nullable=False, index=True, comment='交易日期'),
        sa.Column('item_name', sa.String(200), nullable=False, comment='明细名称'),
        sa.Column('supplier_name', sa.String(200), comment='供应商'),
        sa.Column('pre_tax_amount', sa.Numeric(12, 2), nullable=False, comment='不含税金额'),
        sa.Column('tax_rate', sa.Numeric(5, 2), server_default='0', comment='税率%'),
        sa.Column('tax_amount', sa.Numeric(12, 2), server_default='0', comment='税额'),
        sa.Column('post_tax_amount', sa.Numeric(12, 2), nullable=False, comment='含税金额'),
        sa.Column('category_code', sa.String(20), sa.ForeignKey('cost_category.code'),
                  nullable=False, index=True, comment='成本分类代码'),
        sa.Column('invoice_status', sa.String(20), server_default='none',
                  comment='发票状态: special_vat/general_vat/none'),
        sa.Column('source_type', sa.String(20), nullable=False,
                  comment='来源: expense_claim/manual/auto'),
        sa.Column('source_id', sa.Integer, comment='来源ID'),
        sa.Column('is_sunk_cost', sa.Boolean, server_default='0', comment='是否沉没成本'),
        sa.Column('created_by', sa.Integer, sa.ForeignKey('users.id'), comment='创建人'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── 欠票台账表 ──
    op.create_table(
        'missing_invoice_ledger',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('trade_date', sa.Date, nullable=False, index=True, comment='交易日期'),
        sa.Column('item_name', sa.String(200), nullable=False, comment='明细名称'),
        sa.Column('supplier_name', sa.String(200), comment='供应商'),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False, comment='欠票金额'),
        sa.Column('responsible_user_id', sa.Integer, sa.ForeignKey('users.id'),
                  nullable=False, index=True, comment='责任人ID'),
        sa.Column('source_type', sa.String(20), nullable=False,
                  comment='来源: expense_claim/manual'),
        sa.Column('source_id', sa.Integer, comment='来源ID'),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False, index=True,
                  comment='状态: pending/reminded/received/written_off'),
        sa.Column('reminder_count', sa.Integer, server_default='0', comment='催票次数'),
        sa.Column('last_reminded_at', sa.DateTime, comment='最后催票时间'),
        sa.Column('matched_invoice_id', sa.Integer, sa.ForeignKey('invoices.id'),
                  comment='匹配发票ID'),
        sa.Column('resolved_at', sa.DateTime, comment='销账时间'),
        sa.Column('resolved_by', sa.Integer, sa.ForeignKey('users.id'), comment='销账人'),
        sa.Column('resolve_note', sa.Text, comment='销账备注'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── 初始化成本分类种子数据 ──
    op.execute("""
        INSERT INTO cost_category (code, name, behavior, sort_order) VALUES
        ('CHEM', '洗涤化料', 'variable', 1),
        ('WATER', '水费', 'variable', 2),
        ('ELEC', '电费', 'variable', 3),
        ('GAS', '燃气/蒸汽', 'variable', 4),
        ('PACK', '包装耗材', 'variable', 5),
        ('MAINT', '设备维修', 'variable', 6),
        ('TRANS', '物流运输', 'variable', 7),
        ('LABOR_V', '临时用工', 'variable', 8),
        ('RENT', '厂房租金', 'fixed', 10),
        ('DEPR', '设备折旧', 'fixed', 11),
        ('SALARY', '固定工资', 'fixed', 12),
        ('SOCIAL', '社保公积金', 'fixed', 13),
        ('INSUR', '保险费', 'fixed', 14),
        ('OFFICE', '办公费', 'fixed', 15),
        ('OTHER_F', '其他固定', 'fixed', 16),
        ('OTHER_V', '其他变动', 'variable', 9)
    """)


def downgrade():
    """回滚 Phase 3B/3C 表"""
    from alembic import op

    op.drop_table('missing_invoice_ledger')
    op.drop_table('management_cost_ledger')
    op.drop_table('cost_category')
    op.drop_table('expense_claims')
    op.drop_table('invoices')
