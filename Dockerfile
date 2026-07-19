# 后端服务镜像 —— Python 3.10（与本地 miniconda `myagent` 环境对齐）
FROM python:3.10-slim

# 编译期依赖 + OpenMP（fastembed / onnxruntime 的 CPU 推理需要 libgomp）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 日志不缓冲、禁止写 __pycache__、pip 不落缓存
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖以利用层缓存（requirements.txt 不含任何密钥）
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 再拷源码（.dockerignore 已排除前端 / 测试 / 评估 / 密钥配置等大目录）
COPY . .

# 对外暴露端口
EXPOSE 8000

# 配置与密钥通过 compose 以只读卷挂载（config/llm_config.local.yml 为 gitignore 文件，
# 不烘焙进镜像）；APP_ENV / REDIS_URL / HF_ENDPOINT 等由 compose 注入。
CMD ["uvicorn", "app.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
