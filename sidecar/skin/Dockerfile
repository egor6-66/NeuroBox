# Зона скинов из omnifield/web-core: MCP (`apps/studio/.mcp`) и витрина (`apps/studio`). Один файл
# на обоих — общий клон, установка и сборка зависимостей, а расходятся они только в конце, по
# целям сборки: `--target mcp` и `--target web`. Компоуз называет цель у каждого соседа.
#
# Исходники НЕ лежат в этом репозитории и не копируются контекстом: образ сам клонирует ветку
# web-core. Так сборка не зависит от того, есть ли у машины клон чужого репозитория рядом,
# а обновление — это пересборка образа, не правка файлов по месту.

FROM node:24-bookworm-slim AS source

ARG WEB_CORE_REPO=https://github.com/omnifield/web-core.git
# Ветку называет компоуз (WEB_CORE_REF из .env); умолчание здесь — на случай сборки руками.
ARG WEB_CORE_REF=dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Версия pnpm та же, что у авторов (lockfile 9). corepack тянет её сам.
RUN corepack enable && corepack prepare pnpm@10.11.0 --activate

# Отметка вершины ветки: меняется — слой ниже пересобирается, клон не залипает на старом коде
# из кеша докера. Без неё `docker compose build` молча отдавал бы вчерашний образ.
ADD https://api.github.com/repos/omnifield/web-core/commits/${WEB_CORE_REF} /tmp/web-core-head.json

WORKDIR /src
RUN git clone --depth 1 --branch ${WEB_CORE_REF} ${WEB_CORE_REPO} /src

# Ставится и собирается только то, от чего зависят MCP и витрина, — весь монорепозиторий здесь
# не нужен. `...` у pnpm — «пакет и все его зависимости по воркспейсу».
#
# Скрипты при установке выключены намеренно: хук `prepare` пакета `build` собирает его раньше,
# чем собран `trace`, от которого он зависит, и установка падала на чистом клоне. Порядок
# держит отдельная сборка ниже — она идёт по графу зависимостей.
RUN pnpm install --frozen-lockfile --ignore-scripts \
    --filter "@web-core/studio-mcp..." --filter "@web-core/studio..."

# Кит `ui` собирается из порождённых файлов (`src/kit.ts` и соседи лежат под `.gitignore`, их
# пишет шаг `generate`). У авторов порядок держит nx; здесь он назван руками: сначала всё, от чего
# зависит `ui`, потом порождение, потом зависимости обоих соседей — повторная сборка уже
# собранного дешёвая. Сама витрина здесь не собирается: ей нужны адреса, а они у цели `web`.
RUN pnpm --filter "@web-core/ui^..." run build \
    && pnpm --filter "@web-core/ui" run generate \
    && pnpm --filter "@web-core/studio-mcp..." --filter "@web-core/studio^..." run build

# Ссылки на исполняемые файлы своих пакетов создаются ЗАНОВО, уже после сборки.
#
# pnpm кладёт их при установке, а собранного тогда ещё нет: `web-core-vite` появляется только
# после сборки `@web-core/build`, и при установке ссылка молча пропускается — в выводе это одна
# строка WARN среди сотен. Дальше сборка витрины падает на `web-core-vite: not found`, и выглядит
# это как поломка чужого репозитория, хотя дело в порядке шагов у нас.
#
# Повторная установка дешёвая: пакеты уже в кеше, меняются только ссылки.
RUN pnpm install --frozen-lockfile --ignore-scripts \
    --filter "@web-core/studio-mcp..." --filter "@web-core/studio..."


# --- MCP ------------------------------------------------------------------------------------
FROM source AS mcp

WORKDIR /src/apps/studio/.mcp

ENV SKIN_MCP_TRANSPORT=http \
    SKIN_MCP_HOST=0.0.0.0 \
    PORT=8788 \
    # АДРЕС СЛУЖБЫ, без пути: зона сама дописывает к нему свой путь запроса. Дай ей путь — она
    # допишет свой поверх и промахнётся мимо службы. Прежнее значение оканчивалось на
    # `/api/presets` и было верным, пока служба говорила REST; с GraphQL оно стало ловушкой.
    SKIN_MCP_PRESETS_URL=http://presets:8787

EXPOSE 8788

# Тот же запуск, что у авторов (`pnpm serve`): переменные выше и есть serve. Раннер назван путём,
# а не именем: так запуск не зависит от того, успела ли создаться ссылка в node_modules/.bin.
#
# Каталог `web-core/`, а не `packages/`: скоуп переехал в свой каталог верхнего уровня.
CMD ["node", "/src/web-core/build/dist/bin.mjs", "src/index.ts"]


# --- Витрина: сборка ------------------------------------------------------------------------
FROM source AS web-build

# Адреса впечатываются в бандл НА СБОРКЕ — так устроена витрина (`import.meta.env`). По
# умолчанию относительные: витрина и её соседи отдаются с одного источника, а пути разводит
# nginx ниже, и для браузера это одно место.
#
# Имена без префикса `VITE_` пускает сборщик кита: он объявляет `envPrefix` из `VITE_`,
# `PRESETS_` и `NEUROBOX_`. Прежние `VITE_CHAT_*` витрина больше не читает — их здесь нет
# намеренно, чтобы переменная, которую никто не читает, не выглядела рабочей ручкой.
#
# Токен попадает в публичный JS, и это решение авторов витрины, а не наше: личность несёт
# `X-User-Login` поверх него. Имя для этого заголовка — `NEUROBOX_USER`.
ARG PRESETS_URL=/presets
ARG NEUROBOX_URL=/api
ARG NEUROBOX_TOKEN
ARG NEUROBOX_USER=studio
# Витрина дописывает к адресу службы её собственный путь (`/graphql`) — как и MCP. Дай ей
# путь, и она допишет свой поверх. Здесь адрес, а не путь.
ENV PRESETS_URL=${PRESETS_URL} \
    NEUROBOX_URL=${NEUROBOX_URL} \
    NEUROBOX_TOKEN=${NEUROBOX_TOKEN} \
    NEUROBOX_USER=${NEUROBOX_USER}

RUN pnpm --filter "@web-core/studio" run build


# --- Витрина: раздача -----------------------------------------------------------------------
FROM nginx:1.27-alpine AS web

COPY web.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /src/apps/studio/dist /usr/share/nginx/html

EXPOSE 80
