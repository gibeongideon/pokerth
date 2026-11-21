# Deploying Draely (GitHub Actions → server)

| Target | Branch | Server | URL |
|---|---|---|---|
| staging (test) | `dev` | 209.38.120.140 | https://draely.dafeapp.com |
| production | `prod` (later) | its own server | tbd |

Every push to `dev` runs `.github/workflows/deploy.yml`:
1. **test** – ruff, mypy, pytest against Postgres/Redis
2. **build** – three images to GHCR: `feltkings-api` (API + worker + beat), `feltkings-web` (player app + Caddy), `feltkings-gameserver`
3. **deploy** – copies `deploy/docker-compose.yml` to `/opt/feltkings`, pulls the images, runs `alembic upgrade head`, restarts the stack
4. **health check** – `https://<domain>/api/readyz`

The server holds all secrets in `/opt/feltkings/.env` (generated there, never in git or GitHub).

## One-time setup

### 1. Server (done for staging on 2026-11-21)
```bash
ssh-keygen -t ed25519 -N "" -C github-actions-deploy@draely -f ~/.ssh/draely_deploy
ssh root@SERVER "bash -s -- draely.dafeapp.com staging '$(cat ~/.ssh/draely_deploy.pub)'" < deploy/bootstrap-server.sh
```
Installs Docker, firewall (22/80/443), automatic security updates and fail2ban; creates the `deploy`
user (key-only, docker group), `/opt/feltkings/.env` with random secrets and the seat-token keys.

### 2. DNS (Cloudflare, dafeapp.com)
Add an **A record**: name `draely`, content `209.38.120.140`, proxy status **DNS only** (grey cloud).
Caddy then gets the Let's Encrypt certificate by itself. (Cloudflare's proxy can be turned on later;
WebSockets work through it on 443.)

### 3. GitHub (repository → Settings)
- **Environments → New environment → `staging`**
  - Deployment branches: *Selected branches* → `dev`
  - Secrets:
    - `SSH_HOST` = `209.38.120.140`
    - `SSH_USER` = `deploy`
    - `SSH_PRIVATE_KEY` = the whole content of `~/.ssh/draely_deploy` (private key, including the BEGIN/END lines)
  - Variables:
    - `SITE_DOMAIN` = `draely.dafeapp.com`
- **Actions → General → Workflow permissions**: the workflow asks for `packages: write` itself; nothing to change unless your org restricts it.
- Later, for production: environment `production` (branch `prod`) with the production server's values, and add `prod` to the `branches:` list in `deploy.yml`.

### 4. First deploy
Push `dev` (or *Actions → Deploy → Run workflow*). The first build takes ~15–25 min (game server compile);
later builds use the cache.

### 5. After the first deploy
```bash
ssh -i ~/.ssh/draely_deploy deploy@209.38.120.140
cd /opt/feltkings
dc() { docker compose --env-file .env --env-file image.env "$@"; }
dc run --rm api python -m app.bootstrap --admin you@example.com   # stake levels + admin (safe to re-run: adds new default levels)
grep MAIL_UI_PASSWORD .env                                         # password for /mail
```
- Sign in at https://draely.dafeapp.com with that email; read the sign-in email at
  https://draely.dafeapp.com/mail (user `tester`).
- Real money stays off (`real_money_enabled=false`). Paystack **test** keys go into `.env`, then `dc up -d`.
- Real email: the staging droplet (DigitalOcean) **blocks outgoing SMTP ports 25/465/587**, so Gmail SMTP
  (DafeApp's settings, already in `.env`, commented out) can't connect. Staging uses Mailpit (`/mail`).
  Options later: ask DigitalOcean support to unblock SMTP and uncomment the Gmail block, or switch to an
  email API over HTTPS (e.g. Brevo/Resend) - needs a small HTTP mailer in `app/services/mailer.py`.

## Everyday
- Logs: `dc logs -f api` (also `worker`, `gameserver`, `web`)
- Status: `dc ps`
- Roll back: re-run an older successful *Deploy* run, or on the server `IMAGE_TAG=<old sha>` in `image.env` and `dc up -d`
- Backups (to add before real players): nightly `pg_dump` of the `pgdata` volume off the server.

## Phone app for staging
`.github/workflows/player-android.yml` with repository variables
`PLAYER_API_BASE_URL=https://draely.dafeapp.com/api` and `PLAYER_PUBLIC_URL=https://draely.dafeapp.com`.
