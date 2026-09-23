# Contexto de build = raíz del proyecto (ver docker-compose.yml)
FROM python:3.12-slim

ARG WITH_XTTS=0
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    MODELS_DIR=/models \
    CONFIG_DIR=/app/config \
    WEB_DIR=/app/web

WORKDIR /app
COPY api/requirements.txt api/requirements-xtts.txt ./
RUN pip install -r requirements.txt \
 && if [ "$WITH_XTTS" = "1" ]; then pip install -r requirements-xtts.txt; fi

COPY api/app ./app
COPY config ./config
COPY web ./web

EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
