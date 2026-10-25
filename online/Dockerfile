FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/service \
    DATABASE_PATH=/data/service.sqlite3 RESOURCE_HUB_CACHE=/data/cache
WORKDIR /app
COPY online/requirements.txt /app/online/requirements.txt
RUN pip install --no-cache-dir -r online/requirements.txt \
    && useradd --uid 10001 --create-home service \
    && mkdir /data && chown service:service /data
COPY online /app/online
COPY skills/resource-hub/scripts /app/skills/resource-hub/scripts
USER service
EXPOSE 8000
CMD ["uvicorn", "online.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
