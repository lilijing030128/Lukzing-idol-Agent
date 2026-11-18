# 使用官方 Python 3.10 精简版镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区为北京时间（防止定时任务 APScheduler 时间错乱）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 1. 更新源并安装基础编译工具（gcc 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. 复制 requirements 并安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 核心修复：安装 Chromium 及其运行所需的全部底层系统依赖 (如 libnss3 等)
RUN playwright install --with-deps chromium

# 4. 复制项目所有文件
COPY . .

# 5. 暴露端口（虽然 Render 会自己分配，写上是个好习惯）
EXPOSE 8000

# 6. 启动命令：使用动态分配的 $PORT，如果没有则默认 8000
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}