FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/service \
    DATABASE_PATH=/data/service.sqlite3 RESOURCE_HUB_CACHE=/data/cache
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && useradd --uid 10001 --create-home service \
    && mkdir /data && chown service:service /data
COPY backend /app/backend
COPY web /app/web
COPY gpt /app/gpt
COPY skills/resource-hub/scripts /app/skills/resource-hub/scripts
# Host checkouts may use a restrictive umask; the runtime user must read code.
RUN chmod -R a+rX /app/backend /app/web /app/gpt /app/skills
USER service
EXPOSE 8000
CMD ["uvicorn", "backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
