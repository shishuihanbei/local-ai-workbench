# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKBENCH_DATA=/data \
    WORKBENCH_MODELS=/models \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# 国内网络可加 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY run.py ./
COPY docs ./docs

RUN mkdir -p /data /models /llama
VOLUME ["/data"]

EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:9100/api/health',timeout=3); raise SystemExit(0 if json.load(r).get('status')=='ok' else 1)"

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "9100"]
