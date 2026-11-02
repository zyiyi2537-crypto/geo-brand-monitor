FROM python:3.11-slim

# 最小工具链:lxml 需要,curl 用于 healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖,利用 layer cache
COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
        "fastapi>=0.110.0" \
        "uvicorn[standard]>=0.27.0" \
        "pydantic>=2.5.0" \
        "openai>=1.50.0" \
        "ddgs>=9.0.0" \
        "requests>=2.31.0" \
        "beautifulsoup4>=4.12.0" \
        "lxml>=5.0.0"

# 再 copy 源码
COPY . /app/

# 数据目录(volume mount 进来)
RUN mkdir -p /app/data
ENV SENTINEL_DATA_DIR=/app/data \
    SENTINEL_PORT=8090 \
    PYTHONUNBUFFERED=1

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8090"]
