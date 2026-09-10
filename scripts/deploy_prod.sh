#!/usr/bin/env bash
# Deploy instabiz to prod. Usage: deploy_prod.sh <git-sha>
# The runner has ALREADY placed the new tree in apps/instabiz (git archive over SSH)
# before calling this. This script: snapshot -> migrate -> build -> restart ->
# health-check, and on any failure restores the snapshot + the pre-deploy DB backup.
set -Eeuo pipefail
SHA="${1:?need a git SHA}"
BENCH=/home/frappe/frappe-bench
SITE=instabizerp.com
APP="$BENCH/apps/instabiz"
URL="https://instabizerp.com/api/method/ping"
LOG=/home/frappe/deploy.log
MYSQL_ROOT="${PROD_MARIADB_ROOT:-}"
exec > >(tee -a "$LOG") 2>&1
echo "──────── $(date -Is)  deploy $SHA ────────"
cd "$BENCH"

SNAP="/home/frappe/.deploy_snap_instabiz.tgz"
echo "snapshot current app tree…"
tar czf "$SNAP" -C "$BENCH/apps" instabiz

echo "backup site…"
bench --site "$SITE" backup --with-files
BK="$BENCH/sites/$SITE/private/backups"
DB=$(ls -t $BK/*-database*.sql.gz 2>/dev/null | head -1 || true)
PUB=$(ls -t $BK/*-files*.tar 2>/dev/null | grep -v private | head -1 || true)
PRIV=$(ls -t $BK/*-private-files*.tar 2>/dev/null | head -1 || true)

rollback() {
  echo "!! DEPLOY FAILED — restoring snapshot"
  rm -rf "$APP" && mkdir -p "$APP" && tar xzf "$SNAP" -C "$BENCH/apps"
  if [ -n "$DB" ] && [ -n "$MYSQL_ROOT" ]; then
    bench --site "$SITE" --force restore "$DB" \
      ${PUB:+--with-public-files "$PUB"} ${PRIV:+--with-private-files "$PRIV"} \
      --mariadb-root-password "$MYSQL_ROOT" || true
  fi
  bench --site "$SITE" migrate || true
  bench build --app instabiz || true
  sudo supervisorctl restart all || true
  bench --site "$SITE" set-maintenance-mode off || true
  echo "rolled back to pre-deploy state."
  exit 1
}
trap rollback ERR

bench --site "$SITE" set-maintenance-mode on
echo "record deployed sha…"; echo "$SHA" > "$APP/.deployed_sha"
echo "pip -e (in case deps changed)…"; "$BENCH/env/bin/pip" install --quiet -e "$APP" || true
echo "migrate…";  bench --site "$SITE" migrate
echo "build…";    bench build --app instabiz
echo "restart…";  sudo supervisorctl restart all
sleep 6
echo "health check…"
ok=0
for i in $(seq 1 12); do
  c=$(curl -s -o /dev/null -w '%{http_code}' --resolve instabizerp.com:443:127.0.0.1 "$URL" || true)
  [ "$c" = "200" ] && { echo "healthy"; ok=1; break; }
  sleep 3
done
[ "$ok" = 1 ] || { echo "unhealthy"; false; }
bench --site "$SITE" set-maintenance-mode off
trap - ERR
rm -f "$SNAP"
echo "✅ deployed $SHA  ($(date -Is))"
ls -t $BK/*-database*.sql.gz 2>/dev/null | tail -n +11 | sed 's/-database.*//' | while read -r p; do rm -f "${p}"*; done || true
