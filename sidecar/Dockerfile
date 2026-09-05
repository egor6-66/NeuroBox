# Окружение чужих тяжёлых штук: node, CLI, позже браузер для тех stdio-серверов, которым он
# нужен. Всё это заперто здесь, чтобы образ сервиса оставался тонким и одинаковым у всех.

FROM node:22-bookworm-slim

# git нужен инструментам, работающим с репозиториями; ca-certificates — для https наружу.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@2.1.261

# A2A-адаптер: снаружи общий протокол, внутри локальный CLI. Собирается отдельным слоем —
# зависимости ставятся раньше кода, чтобы правка адаптера не тянула установку заново.
WORKDIR /agent
COPY agent/package.json agent/package-lock.json* ./
RUN npm install
COPY agent/tsconfig.json ./
COPY agent/src ./src
RUN npm run build

# Каталог авторизации создаётся В ОБРАЗЕ и с правильным владельцем. Свежий именованный том
# докер заполняет содержимым и владельцем того, что лежало в образе на этом месте; если каталога
# там нет, том достаётся root, и CLI под пользователем node в него не пишет.
RUN mkdir -p /home/node/.claude && chown -R node:node /home/node/.claude

USER node
WORKDIR /agent

# Контейнер стал настоящим сервисом: он держит A2A-агента. Войти в CLI по-прежнему можно,
# подменив команду через `docker compose run`.
CMD ["node", "dist/index.js"]
