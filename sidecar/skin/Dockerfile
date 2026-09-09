# MCP-сервер зоны скинов (`apps/skin/.mcp` из omnifield/probe-web). Живёт рядом с агентом, как
# любой сосед из сайдкара: чужое окружение заперто здесь, наружу торчит http.
#
# Исходники НЕ лежат в этом репозитории и не копируются контекстом: образ сам клонирует ветку
# probe-web. Так сборка не зависит от того, есть ли у машины клон чужого репозитория рядом,
# а обновление — это пересборка образа, не правка файлов по месту.

FROM node:24-bookworm-slim

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

# Ставятся и собираются только MCP и то, от чего он зависит, — весь монорепозиторий здесь не нужен.
# `...` у pnpm — «пакет и все его зависимости по воркспейсу», сборка идёт в порядке зависимостей.
#
# Скрипты при установке выключены намеренно: хук `prepare` пакета `build` собирает его раньше,
# чем собран `trace`, от которого он зависит, и установка падала на чистом клоне. Порядок
# держит отдельная сборка ниже — она идёт по графу зависимостей.
RUN pnpm install --frozen-lockfile --ignore-scripts --filter "@web-core/skin-mcp..."

# Кит `ui` собирается из порождённых файлов (`src/kit.ts` и соседи лежат под `.gitignore`, их
# пишет шаг `generate`). У авторов порядок держит nx; здесь он назван руками: сначала всё, от чего
# зависит `ui`, потом порождение, потом сборка целиком — повторная сборка уже собранного дешёвая.
RUN pnpm --filter "@web-core/ui^..." run build \
    && pnpm --filter "@web-core/ui" run generate \
    && pnpm --filter "@web-core/skin-mcp..." run build

WORKDIR /src/apps/skin/.mcp

ENV SKIN_MCP_TRANSPORT=http \
    SKIN_MCP_HOST=0.0.0.0 \
    PORT=8788 \
    # АДРЕС СЛУЖБЫ, без пути: зона сама дописывает к нему свой путь запроса. Дай ей путь — она
    # допишет свой поверх и промахнётся мимо службы. Прежнее значение оканчивалось на `/api/presets`
    # и было верным, пока служба говорила REST; с переходом на GraphQL оно стало ловушкой.
    SKIN_MCP_PRESETS_URL=http://presets:8787

EXPOSE 8788

# Тот же запуск, что у авторов (`pnpm serve`): переменные выше и есть serve. Раннер назван путём,
# а не именем `web-core-node`: ссылка на него в node_modules/.bin не создалась — при установке
# раннера ещё не существовало, он появился только на сборке.
CMD ["node", "/src/packages/build/dist/bin.mjs", "src/index.ts"]
