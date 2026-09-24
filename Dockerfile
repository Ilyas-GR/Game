# Базовый образ можно подменить: BASE_IMAGE=... docker compose build
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
# Своя папка и сброс ENTRYPOINT — на случай, если базовый образ от другого проекта.
WORKDIR /gamebot
ENTRYPOINT []
ENV PYTHONUNBUFFERED=1 DB_PATH=/data/game.db
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
COPY game ./game
VOLUME /data
CMD ["python", "bot.py"]
