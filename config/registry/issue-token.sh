#!/bin/sh
# Завести учётку реестра или выпустить ей новый токен.
#
# Почему отдельным скриптом, а не `npm login`: в реестре закрыта самостоятельная регистрация
# (`max_users: -1`), а npm ходит за токеном в ту же ручку, что и за регистрацией, — значит вход
# ею недоступен. Учётку заводит хозяин машины, вот этим.
#
# Работает одноразовым контейнером на том же томе: боевой реестр не трогается, его конфиг
# остаётся тем, что лежит в репозитории.
#
#   sh issue-token.sh <имя> <пароль>
set -e

USER_NAME="${1:?имя учётки первым аргументом}"
PASSWORD="${2:?пароль вторым аргументом}"
VOLUME="${REGISTRY_VOLUME:-neurobox_registry-data}"
PORT="${BOOTSTRAP_PORT:-4899}"

CONF=$(mktemp)
cat > "$CONF" <<'YAML'
storage: /verdaccio/storage/data
auth:
  htpasswd:
    file: /verdaccio/storage/htpasswd
    max_users: 1000
uplinks:
  npmjs: { url: https://registry.npmjs.org/ }
packages:
  '**': { access: $all, publish: $authenticated, proxy: npmjs }
log: { type: stdout, format: pretty, level: warn }
listen: 0.0.0.0:4873
YAML

docker run -d --name registry-bootstrap -p "127.0.0.1:${PORT}:4873" \
  -v "${VOLUME}:/verdaccio/storage" -v "${CONF}:/verdaccio/conf/config.yaml:ro" \
  verdaccio/verdaccio:6 >/dev/null
# Реестру нужно время подняться; без ожидания первый же запрос уходит в закрытую дверь.
sleep 8

RESPONSE=$(curl -s --max-time 30 -X PUT \
  "http://127.0.0.1:${PORT}/-/user/org.couchdb.user:${USER_NAME}" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"${USER_NAME}\",\"password\":\"${PASSWORD}\",\"type\":\"user\",\"roles\":[],\"date\":\"$(date -Iseconds)\"}")

docker rm -f registry-bootstrap >/dev/null
rm -f "$CONF"

echo "$RESPONSE"
