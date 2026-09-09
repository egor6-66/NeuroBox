# Зона скинов из omnifield/probe-web: MCP (`apps/skin/.mcp`) и витрина (`apps/skin`). Один файл
# на обоих — общий клон, установка и сборка зависимостей, а расходятся они только в конце, по
# целям сборки: `--target mcp` и `--target web`. Компоуз называет цель у каждого соседа.
#
# Исходники НЕ лежат в этом репозитории и не копируются контекстом: образ сам клонирует ветку
# probe-web. Так сборка не зависит от того, есть ли у машины клон чужого репозитория рядом,
# а обновление — это пересборка образа, не правка файлов по месту.

FROM node:24-bookworm-slim AS source

ARG PROBE_WEB_REPO=https://github.com/omnifield/probe-web.git
# Ветку называет компоуз (PROBE_WEB_REF из .env); умолчание здесь — на случай сборки руками.
ARG PROBE_WEB_REF=dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Версия pnpm та же, что у авторов (lockfile 9). corepack тянет её сам.
RUN corepack enable && corepack prepare pnpm@10.11.0 --activate

# Отметка вершины ветки: меняется — слой ниже пересобирается, клон не залипает на старом коде
# из кеша докера. Без неё `docker compose build` молча отдавал бы вчерашний образ.
ADD https://api.github.com/repos/omnifield/probe-web/commits/${PROBE_WEB_REF} /tmp/probe-web-head.json

WORKDIR /src
RUN git clone --depth 1 --branch ${PROBE_WEB_REF} ${PROBE_WEB_REPO} /src

# Ставится и собирается только то, от чего зависят MCP и витрина, — весь монорепозиторий здесь
# не нужен. `...` у pnpm — «пакет и все его зависимости по воркспейсу».
#
# Скрипты при установке выключены намеренно: хук `prepare` пакета `build` собирает его раньше,
# чем собран `trace`, от которого он зависит, и установка падала на чистом клоне. Порядок
# держит отдельная сборка ниже — она идёт по графу зависимостей.
RUN pnpm install --frozen-lockfile --ignore-scripts \
    --filter "@web-core/skin-mcp..." --filter "@web-core/skin-app..."

# Кит `ui` собирается из порождённых файлов (`src/kit.ts` и соседи лежат под `.gitignore`, их
# пишет шаг `generate`). У авторов порядок держит nx; здесь он назван руками: сначала всё, от чего
# зависит `ui`, потом порождение, потом зависимости обоих соседей — повторная сборка уже
# собранного дешёвая. Сама витрина здесь не собирается: ей нужны адреса, а они у цели `web`.
RUN pnpm --filter "@web-core/ui^..." run build \
    && pnpm --filter "@web-core/ui" run generate \
    && pnpm --filter "@web-core/skin-mcp..." --filter "@web-core/skin-app^..." run build


# --- MCP ------------------------------------------------------------------------------------
FROM source AS mcp

WORKDIR /src/apps/skin/.mcp

ENV SKIN_MCP_TRANSPORT=http \
    SKIN_MCP_HOST=0.0.0.0 \
    PORT=8788 \
    SKIN_MCP_PRESETS_URL=http://presets:8787/api/presets

EXPOSE 8788

# Тот же запуск, что у авторов (`pnpm serve`): переменные выше и есть serve. Раннер назван путём,
# а не именем `web-core-node`: ссылка на него в node_modules/.bin не создалась — при установке
# раннера ещё не существовало, он появился только на сборке.
CMD ["node", "/src/packages/build/dist/bin.mjs", "src/index.ts"]


# --- Витрина: сборка ------------------------------------------------------------------------
FROM source AS web-build

# Адреса впечатываются в бандл на сборке — так устроена витрина (`import.meta.env`). Все три
# относительные: витрина и её соседи отдаются с одного источника, а пути разводит nginx ниже.
# Токен чата — общий токен бокса; он попадает в публичный JS, и это решение авторов витрины
# (личность несёт `X-User-Login` поверх него), а не наше.
ARG VITE_CHAT_TOKEN
ENV VITE_PRESETS_URL=/presets/api/presets \
    VITE_CHAT_URL=/api \
    VITE_CHAT_TOKEN=${VITE_CHAT_TOKEN}

RUN pnpm --filter "@web-core/skin-app" run build


# --- Витрина: раздача -----------------------------------------------------------------------
FROM nginx:1.27-alpine AS web

COPY web.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /src/apps/skin/dist /usr/share/nginx/html

EXPOSE 80
