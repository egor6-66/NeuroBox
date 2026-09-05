# Сборка отдельно от отдачи: в готовом образе нет ни node, ни исходников — только статика
# и сервер, который её раздаёт.
FROM node:22-bookworm-slim AS build

WORKDIR /console
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY ./src ./src
RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /console/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
