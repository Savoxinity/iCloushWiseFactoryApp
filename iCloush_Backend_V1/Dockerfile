# ═══════════════════════════════════════════════════
# iCloush 智慧工厂后端 — Dockerfile
# 适配微信云托管 (WeChat Cloud Run)
# ═══════════════════════════════════════════════════

# ── 基础镜像 ──
# 如果 Docker Hub 拉取超时，依次尝试以下国内镜像源：
#   方案A（推荐）：Docker Desktop → Settings → Docker Engine → 添加：
#     "registry-mirrors": ["https://docker.1ms.run", "https://docker.xuanyuan.me"]
#
#   方案B：直接使用阿里云镜像（取消注释下面一行，注释掉 FROM python:3.11-slim）
# FROM registry.cn-shanghai.aliyuncs.com/library/python:3.11-slim

FROM python:3.11-slim

WORKDIR /app

# 系统依赖（使用清华 apt 源加速）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 升级 pip 避免旧版兼容问题
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip setuptools wheel

# Python 依赖（使用清华 pip 源加速）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 应用代码
COPY . .

# 微信云托管要求监听 80 端口
ENV APP_PORT=80
ENV APP_HOST=0.0.0.0
ENV APP_ENV=production

EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80", "--workers", "2"]
