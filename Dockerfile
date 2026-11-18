# 使用官方 Python 3.10 精简版镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区为北京时间（防止定时任务APScheduler时间错乱）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装基础编译工具（某些 Python 库可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制 requirements 并安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 核心修复：安装 Playwright 以及 Chromium 运行所需的全部系统级依赖
# 加上 --with-deps 会自动帮你下载缺失的底层 C 库
RUN playwright install --with-deps chromium

# 复制项目所有文件
COPY . .

# 暴露端口（Render 会扫描这个）
EXPOSE 8000

# 启动命令：兼容 Render 动态分配的 $PORT，如果没有则默认 8000
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}