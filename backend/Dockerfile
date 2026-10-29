FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/service \
    DATABASE_PATH=/data/service.sqlite3
WORKDIR /app
COPY backend/requirements.lock /app/backend/requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r backend/requirements.lock \
    && useradd --uid 10001 --create-home service \
    && mkdir /data && chown service:service /data
COPY backend /app/backend
COPY web /app/web
COPY gpt /app/gpt
# Host checkouts may use a restrictive umask; the runtime user must read code.
RUN chmod -R a+rX /app/backend /app/web /app/gpt
USER service
EXPOSE 8000
CMD ["uvicorn", "backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header", "--limit-concurrency", "100", "--proxy-headers", "--forwarded-allow-ips", "*"]
