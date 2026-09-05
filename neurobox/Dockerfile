# Образ только сервиса. Пульт живёт в своей зоне и собирается отдельно — в отличие от шаблона,
# у которого фронт вшит в образ бэкенда одной сборкой.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# Зависимости отдельным слоем: правка кода не заставляет ставить их заново.
# --frozen: локфайл лежит в репозитории, и сборка обязана совпасть с ним точь-в-точь.
# Разошёлся с pyproject — падаем здесь, а не собираем молча что-то другое.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY ./src ./src
# Миграции едут в образ: применять их обязан тот же образ, что и работает, иначе схема и код
# расходятся в момент раскатки.
COPY alembic.ini ./
COPY ./alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["fastapi", "run", "src/neurobox/main.py", "--host", "0.0.0.0", "--port", "8000"]
