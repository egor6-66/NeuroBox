# Сосед по машине: демка статбордов. Не часть бокса — свой репозиторий и свой цикл выпуска.
#
# Исходников здесь нет и не будет: образ сам клонирует ветку, как и сосед зоны скинов. Так сборка
# не зависит от того, лежит ли рядом с машиной чужой клон, а обновление — это пересборка образа,
# а не правка файлов по месту.

FROM node:24-bookworm-slim AS build

ARG STATBOARD_REPO=https://github.com/egor6-66/statboard-test.git
# Ветку называет компоуз (STATBOARD_REF из .env); умолчание здесь — на случай сборки руками.
ARG STATBOARD_REF=main

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Версию pnpm называет сам репозиторий (`packageManager`), corepack берёт её оттуда.
RUN corepack enable

# Отметка вершины ветки: сдвинулась — слой ниже пересобирается, и клон не залипает на вчерашнем
# коде из кеша докера.
ADD https://api.github.com/repos/egor6-66/statboard-test/commits/${STATBOARD_REF} /tmp/statboard-head.json

WORKDIR /src
RUN git clone --depth 1 --branch ${STATBOARD_REF} ${STATBOARD_REPO} /src

# Пакеты базы приезжают из реестра по адресу из `.npmrc` самого репозитория и читаются анонимно:
# демка ставится ровно так же, как у постороннего потребителя, а не особым способом для нас.
RUN pnpm install --frozen-lockfile
RUN pnpm build


FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html

EXPOSE 80
