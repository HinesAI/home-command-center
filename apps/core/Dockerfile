FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY apps/core/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && groupadd --system hcc \
    && useradd --system --gid hcc --home-dir /app --shell /usr/sbin/nologin hcc

COPY --chown=hcc:hcc apps/core/ /app/
COPY --chown=hcc:hcc VERSION /app/VERSION

RUN mkdir -p /app/data && chown hcc:hcc /app/data

USER hcc

EXPOSE 8080
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]

CMD ["python", "/app/server.py"]
