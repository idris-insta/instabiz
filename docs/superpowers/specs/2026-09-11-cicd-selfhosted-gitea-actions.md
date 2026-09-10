# Self-Hosted CI/CD — Gitea Actions → build gate → deploy to prod

**Date:** 2026-09-11
**Goal:** push to `develop` → CI builds + tests → on green, deploy to `instabizerp.com` automatically, with backup + health-check + auto-rollback.
**Stack:** 100% open source, self-hosted. Gitea (already running) + Gitea Actions + `act_runner`. No SaaS.

---

## PART 0 — What already exists

| Piece | State |
|---|---|
| **Gitea** | running on the dev box, `http://localhost:3100`, repo `dev/instabiz`. The `gitea` git remote already points here. |
| **GitHub** | `origin` = `git@github.com:viktorvaughn-ai/instabiz.git` (mirror / backup) |
| **dev** | Ubuntu 22.04, `bench start`, site `frontend` |
| **prod** | BigRock VPS `66.116.255.198`, supervisor-managed, `/home/frappe/frappe-bench`, site `instabizerp.com`, user `frappe` (has NOPASSWD sudo) |
| **branches** | `develop` = integration/mainline. Feature work on `feature/*`, merged to `develop` via PR. |

**Gitea is LAN-only** (`localhost:3100`) — prod cannot reach it. So: **the CI runner deploys to prod over SSH**; prod never pulls from Gitea. (Alternative — put prod on the dev box's Tailscale net and let prod `git pull` from Gitea — noted at the end, not the default.)

---

## PART 1 — Architecture

```
 dev laptop ── git push gitea develop ──▶ Gitea (localhost:3100)
                                             │  fires Gitea Actions
                                             ▼
                                   act_runner  (Docker executor, on the dev box)
                                     │
                         ┌───────────┴────────────┐
                         ▼                        ▼
                   job: test                 job: deploy   (needs test✓ AND ref==develop)
              ruff · node -c · bench build      SSH ─▶ frappe@66.116.255.198
              bench migrate (throwaway DB)             run scripts/deploy_prod.sh <SHA>
              bench run-tests --app instabiz             ├─ maintenance on
              services: mariadb:10.6                     ├─ bench backup --with-files
                         │                               ├─ git reset --hard <SHA>
                    ✓ / ✗ on the commit                  ├─ pip -e (if pyproject changed)
                    (shown in Gitea + PR checks)         ├─ bench migrate
                                                         ├─ bench build --app instabiz
                                                         ├─ supervisorctl restart all
                                                         ├─ health check (curl /api/method/ping)
                                                         ├─ FAIL ⇒ restore backup + git reset <PREV> + restart
                                                         └─ maintenance off
```

**Two jobs, one workflow file.** `deploy` is gated on `test` passing **and** `github.ref == refs/heads/develop`, so pushing a `feature/*` branch runs only `test` (fast feedback, no deploy). Merging to `develop` runs both.

---

## PART 2 — One-time setup (numbered, copy-paste)

### 2.1 Enable Gitea Actions

On the box running Gitea, edit its `app.ini` (`/etc/gitea/app.ini` or `~gitea/custom/conf/app.ini`):

```ini
[actions]
ENABLED = true
DEFAULT_ACTIONS_URL = github        ; lets `uses: actions/checkout@v4` resolve from github.com
```

Restart Gitea (`sudo systemctl restart gitea`, or however it's run).
Then in the repo: **Settings → Actions → Enable**.

### 2.2 Install `act_runner` (Docker executor, on the dev box)

```bash
# get the binary
curl -sL https://gitea.com/gitea/act_runner/releases/download/v0.2.11/act_runner-0.2.11-linux-amd64 \
  -o /usr/local/bin/act_runner && chmod +x /usr/local/bin/act_runner

# a registration token: Gitea → Site Administration → Actions → Runners → Create registration token
# (or repo-level: repo Settings → Actions → Runners)
sudo useradd -m -s /bin/bash gitea-runner && sudo usermod -aG docker gitea-runner
sudo -u gitea-runner -H bash -c '
  cd ~ &&
  act_runner register --no-interactive \
    --instance http://localhost:3100 \
    --token <REGISTRATION_TOKEN> \
    --name dev-runner \
    --labels ubuntu-latest:docker://catthehacker/ubuntu:act-22.04
'
```

Run it as a service (`/etc/systemd/system/act_runner.service`):

```ini
[Unit]
Description=Gitea act_runner
After=docker.service
Requires=docker.service

[Service]
User=gitea-runner
WorkingDirectory=/home/gitea-runner
ExecStart=/usr/local/bin/act_runner daemon
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now act_runner
```

Confirm it shows **Idle** under Gitea → Actions → Runners.

### 2.3 Deploy key: runner → prod

On the **dev box** (any user — the key just needs to end up as a Gitea secret):

```bash
ssh-keygen -t ed25519 -f /tmp/ib_deploy_key -N '' -C 'gitea-ci-deploy'
cat /tmp/ib_deploy_key.pub
```

On **prod**, append that pubkey to `frappe`'s authorized_keys, restricted to the deploy script:

```bash
# as root on prod
sudo -u frappe bash -c '
cmd="/home/frappe/frappe-bench/apps/instabiz/scripts/deploy_prod.sh"
echo "command=\"$cmd \${SSH_ORIGINAL_COMMAND#* }\",no-agent-forwarding,no-port-forwarding,no-pty,no-X11-forwarding <PUBKEY LINE>" >> ~/.ssh/authorized_keys
'
```

(Or, simpler for v1: add the bare pubkey with no `command=` restriction and just trust the runner. Tighten later.)

In **Gitea → repo → Settings → Secrets**, add:

| Secret | Value |
|---|---|
| `PROD_SSH_KEY` | contents of `/tmp/ib_deploy_key` (the private key) |
| `PROD_HOST` | `66.116.255.198` |
| `PROD_USER` | `frappe` |

Then `shred -u /tmp/ib_deploy_key*` on the dev box.

### 2.4 `frappe` user on prod — sudo for supervisor

Already has NOPASSWD sudo from the initial deploy. If you tightened it, ensure at least:

```
frappe ALL=(root) NOPASSWD: /usr/bin/supervisorctl, /usr/sbin/nginx, /bin/systemctl reload nginx
```

### 2.5 Prod repo hygiene (one time)

```bash
# as frappe on prod
cd /home/frappe/frappe-bench/apps/instabiz
git remote -v          # should have a fetchable origin. If it's the old local rsync path, repoint:
git remote set-url origin git@github.com:viktorvaughn-ai/instabiz.git   # needs a read deploy key on GitHub
git fetch origin
git checkout develop && git branch --set-upstream-to=origin/develop
```

**GitHub read access from prod:** add prod's `frappe@` SSH pubkey as a **read-only Deploy Key** on the GitHub repo (Settings → Deploy keys). `develop` must be pushed to GitHub too (use a multi-push remote so one `git push` hits gitea + github — see 2.7).

Deploy pulls from **GitHub** (public-internet reachable) even though the CI trigger is **Gitea**. The runner passes the exact SHA it built, so gitea and github can't drift the deploy.

### 2.6 Add the deploy script to the repo

`scripts/deploy_prod.sh` — see PART 3. `chmod +x`, commit it.

### 2.7 Push to both remotes with one command (optional but recommended)

```bash
git remote set-url --add --push origin git@github.com:viktorvaughn-ai/instabiz.git
git remote set-url --add --push origin http://dev:beefveggies@localhost:3100/dev/instabiz.git
# now `git push origin develop` writes to BOTH; Gitea fires Actions, GitHub has the SHA for prod to pull
```

---

## PART 3 — `scripts/deploy_prod.sh` (runs ON prod, invoked by the runner over SSH)

```bash
#!/usr/bin/env bash
# Usage: deploy_prod.sh <git-sha>
# Idempotent. Backs up, deploys, health-checks, auto-rolls-back on failure.
set -Eeuo pipefail

SHA="${1:?need a git SHA}"
BENCH=/home/frappe/frappe-bench
SITE=instabizerp.com
APP=$BENCH/apps/instabiz
URL=https://instabizerp.com/api/method/ping
LOG=/home/frappe/deploy.log
exec > >(tee -a "$LOG") 2>&1
echo "──────── $(date -Is)  deploy $SHA ────────"

cd "$APP"
PREV_SHA=$(git rev-parse HEAD)
echo "current: $PREV_SHA   target: $SHA"
[ "$PREV_SHA" = "$SHA" ] && { echo "already at target, nothing to do"; exit 0; }

cd "$BENCH"
PYPROJECT_CHANGED=$(git -C "$APP" diff --name-only "$PREV_SHA" "$SHA" -- pyproject.toml | wc -l)

rollback() {
  echo "!! DEPLOY FAILED — rolling back to $PREV_SHA"
  git -C "$APP" reset --hard "$PREV_SHA" || true
  [ -f "$LATEST_DB" ] && bench --site "$SITE" --force restore "$LATEST_DB" \
     --with-public-files "$LATEST_PUB" --with-private-files "$LATEST_PRIV" \
     --mariadb-root-password "$(grep -oP '"mariadb_root_password":\s*"\K[^"]+' $BENCH/sites/common_site_config.json || true)" || true
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
BK=$BENCH/sites/$SITE/private/backups
LATEST_DB=$(ls -t $BK/*-database.sql.gz $BK/*-database-enc.sql.gz 2>/dev/null | head -1)
LATEST_PUB=$(ls -t $BK/*-files*.tar 2>/dev/null | grep -v private | head -1)
LATEST_PRIV=$(ls -t $BK/*-private-files*.tar 2>/dev/null | head -1)

echo "fetch + checkout $SHA…"
git -C "$APP" fetch origin --tags --prune
git -C "$APP" reset --hard "$SHA"

if [ "$PYPROJECT_CHANGED" -gt 0 ]; then
  echo "pyproject changed — reinstalling app deps"
  "$BENCH/env/bin/pip" install --quiet -e "$APP"
fi

echo "migrate…"
bench --site "$SITE" migrate
echo "build…"
bench build --app instabiz
echo "restart…"
sudo supervisorctl restart all
sleep 6

echo "health check…"
for i in $(seq 1 10); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --resolve instabizerp.com:443:127.0.0.1 "$URL" || true)
  [ "$code" = "200" ] && { echo "healthy ($code)"; break; }
  [ "$i" = "10" ] && { echo "unhealthy after 10 tries (last=$code)"; false; }
  sleep 3
done

bench --site "$SITE" set-maintenance-mode off
trap - ERR
echo "✅ deployed $SHA  ($(date -Is))"
# prune old backups — keep 10
ls -t $BK/*-database*.sql.gz 2>/dev/null | tail -n +11 | sed 's/-database.*//' | while read p; do rm -f "${p}"*; done
```

Notes:
- `bench migrate` is the one risky step; the pre-backup + `rollback()` cover it.
- Keep it on prod at `apps/instabiz/scripts/deploy_prod.sh` so it version-controls itself — but the runner invokes the **currently-checked-out** copy, i.e. `PREV_SHA`'s version, which then checks out `SHA`. A breaking change to the script itself takes one deploy to land. Acceptable.

---

## PART 4 — `.gitea/workflows/deploy.yml`

```yaml
name: CI + Deploy
on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      mariadb:
        image: mariadb:10.6
        env:
          MARIADB_ROOT_PASSWORD: root
          MARIADB_DATABASE: ci
        ports: ["3306:3306"]
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4

      - name: System deps
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y python3.10-venv python3-dev libmariadb-dev \
            redis-tools mariadb-client build-essential libffi-dev wkhtmltopdf
          curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
          sudo apt-get install -y nodejs
          npm i -g yarn

      - name: Lint (ruff)
        run: |
          pip install ruff
          ruff check instabiz
          ruff format --check instabiz

      - name: JS syntax
        run: |
          find instabiz -name '*.js' -not -path '*/node_modules/*' -not -path '*/dist/*' \
            -exec node --check {} \;

      - name: Bench init + install app + migrate + build + tests
        run: |
          pip install frappe-bench
          bench init --skip-redis-config-generation --frappe-branch version-15 --python python3.10 ci-bench
          cd ci-bench
          bench get-app "$GITHUB_WORKSPACE"
          bench new-site ci.test --db-root-password root --admin-password admin \
            --mariadb-host 127.0.0.1 --no-mariadb-socket --install-app instabiz
          bench --site ci.test migrate
          bench build --app instabiz
          bench --site ci.test run-tests --app instabiz || true   # make blocking once a suite exists

  deploy:
    needs: test
    if: gitea.ref == 'refs/heads/develop'
    runs-on: ubuntu-latest
    concurrency: deploy-prod            # never two deploys at once
    steps:
      - name: SSH deploy
        run: |
          mkdir -p ~/.ssh && chmod 700 ~/.ssh
          echo "${{ secrets.PROD_SSH_KEY }}" > ~/.ssh/id_ed25519
          chmod 600 ~/.ssh/id_ed25519
          ssh-keyscan -H "${{ secrets.PROD_HOST }}" >> ~/.ssh/known_hosts 2>/dev/null
          ssh -i ~/.ssh/id_ed25519 "${{ secrets.PROD_USER }}@${{ secrets.PROD_HOST }}" \
            "bash /home/frappe/frappe-bench/apps/instabiz/scripts/deploy_prod.sh ${{ gitea.sha }}"
```

- `branches: ["**"]` + `if:` gate = every branch/PR runs `test`; only `develop` deploys.
- `${{ gitea.sha }}` — Gitea Actions exposes `gitea.*` (and mirrors `github.*`); use whichever your Gitea version supports (`gitea.sha` on 1.21+, else `github.sha`).
- Add `workflow_dispatch:` to the `on:` block for a manual "deploy this ref now" button (hotfixes).

---

## PART 5 — Recommendations / decisions to make

| Question | Recommendation |
|---|---|
| **Auto-deploy every green `develop` push, or gate?** | Start gated: deploy job has `if: gitea.ref == 'refs/heads/develop'` **and** you merge to `develop` deliberately (PR review). That *is* the gate. If you want a harder gate, deploy only on tags (`refs/tags/v*`) and cut a tag when ready. |
| **Runner: host or Docker executor?** | Docker (`catthehacker/ubuntu:act-22.04`) — isolated, doesn't pollute the dev bench, `services:` gives you MariaDB/Redis for free. |
| **Staging site first?** | v2: add a `staging.instabizerp.com` site on the same VPS; deploy job promotes dev→staging, a manual approval promotes staging→prod. For now, backup+rollback on direct-to-prod is enough. |
| **Migrations downtime** | `set-maintenance-mode on` during deploy (script does it). Typical instabiz migrate is 1–3 min. Communicate a nightly deploy window if it matters. |
| **DB backup size** | ~46 MB compressed today — cheap. Script keeps last 10; add off-box copy (rsync to dev / S3-compatible MinIO) in v2. |
| **Secrets rotation** | Rotate `PROD_SSH_KEY` if the dev box is ever compromised; it's the keys to prod. |
| **`bench update`** | This pipeline deploys **instabiz only**. Frappe/ERPNext/etc stay pinned. Upgrading them is a separate, manual, tested operation — never wire it into auto-deploy. |

---

## PART 6 — First run / verification

1. Land 2.1–2.7.
2. Commit `scripts/deploy_prod.sh` + `.gitea/workflows/deploy.yml` on a `feature/ci` branch, push to gitea → watch **only `test`** run (green).
3. Open a PR `feature/ci` → `develop`, merge.
4. Push to `develop` → watch `test` then `deploy` run. `deploy` SSHes to prod, you see `deploy.log` fill, health check 200, `✅ deployed <sha>`.
5. Break something on purpose (a syntax error in a `.py`), push to `develop` → `test` goes red, `deploy` never runs. Fix, push, green.
6. Simulate a bad migrate (temporarily add a failing patch), push → deploy runs, health check fails, script restores the backup + resets git, prod stays up on the old SHA, job exits red.

---

## Alternative: prod pulls from Gitea over Tailscale

The dev box already has Tailscale (`*.tail0712a3.ts.net`). If prod joins the same tailnet:
- prod reaches Gitea at `http://<dev-tailscale-ip>:3100` → prod's `origin` = Gitea, no GitHub deploy key needed
- the deploy step becomes `ssh prod 'cd apps/instabiz && git fetch && git checkout <sha> && ...'` pulling straight from Gitea
- one less moving part (no GitHub in the deploy path), but adds Tailscale as a prod dependency

Either works. The SSH-push-from-runner model in PART 1 is the default because it needs nothing new on prod.
