# 小安 · 模拟银行 AI 智能体（全部数据为模拟）
# 只用 Python 标准库，镜像里不需要安装任何第三方包。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINTECH_HOST=0.0.0.0 \
    FINTECH_PORT=8765 \
    FINTECH_DB=/data/demo.db \
    FINTECH_MODEL_BASE_URL=https://api.deepseek.com \
    FINTECH_MODEL_NAME=deepseek-flash

WORKDIR /app
COPY . /app

# 用非 root 用户运行；演示库放在 /data（可挂载卷，重建容器后熔断和审计记录仍在）
RUN useradd --system --uid 10001 --no-create-home xiaoan \
    && mkdir -p /data \
    && chown -R xiaoan /data

USER xiaoan
EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/v2/session', timeout=4).status == 200 else 1)"

CMD ["python", "run.py"]
