FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# 复制项目所有文件
COPY . .

# 暴露 Hugging Face 默认端口 7860
EXPOSE 8000

# 启动命令（根据你的后端入口调整，假设你的 FastAPI/Uvicorn 入口在 server.py 或 agent.py）
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
