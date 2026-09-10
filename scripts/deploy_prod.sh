#!/usr/bin/env bash
# Deploy instabiz to production. Usage: deploy_prod.sh <git-sha>
# Idempotent. Backs up, deploys, health-checks, auto-rolls-back on failure.
set -Eeuo pipefail

SHA="${1:?need a git SHA}"
BENCH=/home/frappe/frappe-bench
SITE=instabizerp.com
APP="$BENCH/apps/instabiz"
URL="https://instabizerp.com/api/method/ping"
LOG=/home/frappe/deploy.log
exec > >(tee -a "$LOG") 2>&1
echo "──────── $(date -Is)  deploy $SHA ────────"

cd "$APP"
PREV_SHA=$(git rev-parse HEAD)
echo "current: $PREV_SHA   target: $SHA"
[ "$PREV_SHA" = "$SHA" ] && { echo "already at target, nothing to do"; exit 0; }

cd "$BENCH"
PYPROJECT_CHANGED=$(git -C "$APP" diff --name-only "$PREV_SHA" "$SHA" -- pyproject.toml | wc -l || echo 0)
LATEST_DB=""; LATEST_PUB=""; LATEST_PRIV=""

rollback() {
  echo "!! DEPLOY FAILED — rolling back to $PREV_SHA"
  git -C "$APP" reset --hard "$PREV_SHA" || true
  if [ -n "$LATEST_DB" ] && [ -f "$LATEST_DB" ]; then
    bench --site "$SITE" --force restore "$LATEST_DB" \
      ${LATEST_PUB:+--with-public-files "$LATEST_PUB"} \
      ${LATEST_PRIV:+--with-private-files "$LATEST_PRIV"} || true
  fi
  bench --site "$SITE" migrate || true
  bench build --app instabiz || true
  sudo supervisorctl restart all || true
  bench --site "$SITE" set-maintenance-mode off || true
  echo "rolled back."
  exit 1
}
trap rollback ERR

bench --site "$SITE" set-maintenance-mode on

echo "backup…"
bench --site "$SITE" backup --with-files
BK="$BENCH/sites/$SITE/private/backups"
LATEST_DB=$(ls -t $BK/*-database*.sql.gz 2>/dev/null | head -1 || true)
LATEST_PUB=$(ls -t $BK/*-files*.tar 2>/dev/null | grep -v private | head -1 || true)
LATEST_PRIV=$(ls -t $BK/*-private-files*.tar 2>/dev/null | head -1 || true)

echo "checkout $SHA…"
git -C "$APP" fetch origin --tags --prune
git -C "$APP" reset --hard "$SHA"

if [ "$PYPROJECT_CHANGED" -gt 0 ]; then
  echo "pyproject changed — reinstalling app deps"
  "$BENCH/env/bin/pip" install --quiet -e "$APP"
fi

echo "migrate…"; bench --site "$SITE" migrate
echo "build…";   bench build --app instabiz
echo "restart…"; sudo supervisorctl restart all
sleep 6

echo "health check…"
ok=0
for i in $(seq 1 10); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --resolve instabizerp.com:443:127.0.0.1 "$URL" || true)
  if [ "$code" = "200" ]; then echo "healthy ($code)"; ok=1; break; fi
  sleep 3
done
[ "$ok" = "1" ] || { echo "unhealthy after 10 tries"; false; }

bench --site "$SITE" set-maintenance-mode off
trap - ERR
echo "✅ deployed $SHA  ($(date -Is))"
ls -t $BK/*-database*.sql.gz 2>/dev/null | tail -n +11 | sed 's/-database.*//' | while read -r p; do rm -f "${p}"*; done || true
