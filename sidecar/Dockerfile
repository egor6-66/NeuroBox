# Окружение чужих тяжёлых штук: node, CLI, позже браузер для тех stdio-серверов, которым он
# нужен. Всё это заперто здесь, чтобы образ сервиса оставался тонким и одинаковым у всех.

FROM node:22-bookworm-slim

# git нужен инструментам, работающим с репозиториями; ca-certificates — для https наружу.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@2.1.261

# Каталог авторизации создаётся В ОБРАЗЕ и с правильным владельцем. Свежий именованный том
# докер заполняет содержимым и владельцем того, что лежало в образе на этом месте; если каталога
# там нет, том достаётся root, и CLI под пользователем node в него не пишет.
RUN mkdir -p /home/node/.claude && chown -R node:node /home/node/.claude

USER node
WORKDIR /work

# Контейнер не сервис: он поднимается по требованию под конкретную команду. Простой сон нужен
# только чтобы `compose up` не считал его упавшим, если его когда-нибудь поднимут фоном.
CMD ["sleep", "infinity"]
