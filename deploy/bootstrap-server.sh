#!/usr/bin/env bash
# One-time setup of a Felt Kings server (Ubuntu 24.04), run as root:
#   ssh root@SERVER 'bash -s' < deploy/bootstrap-server.sh  SITE_DOMAIN ENV "DEPLOY_PUBKEY"
#
# - Docker + Compose, firewall (22/80/443 only), automatic security updates, fail2ban
# - a `deploy` user (docker group) for GitHub Actions, with only that key
# - /opt/feltkings with a generated .env (secrets never leave the server) and
#   the seat-token signing keys
# Safe to run again: existing secrets and keys are kept.
set -euo pipefail
SITE_DOMAIN=${1:?site domain}
PLATFORM_ENV=${2:-staging}
DEPLOY_PUBKEY=${3:?public key of the GitHub Actions deploy key}
DIR=/opt/feltkings

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 ufw fail2ban unattended-upgrades openssl >/dev/null
systemctl enable --now docker >/dev/null

ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null

id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
grep -qxF "$DEPLOY_PUBKEY" /home/deploy/.ssh/authorized_keys 2>/dev/null || echo "$DEPLOY_PUBKEY" >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

install -d -m 750 -o deploy -g deploy "$DIR" "$DIR/keys"
cd "$DIR"
if [ ! -f keys/seat-token.key ]; then
  openssl genpkey -algorithm ed25519 -out keys/seat-token.key
  openssl pkey -in keys/seat-token.key -pubout -out keys/seat-token.pub
fi
# API container runs as uid 10001 and reads the private key; the game server
# only needs the public one.
chown 10001:deploy keys/seat-token.key && chmod 640 keys/seat-token.key
chmod 644 keys/seat-token.pub

if [ ! -f .env ]; then
  rand() { openssl rand -hex "$1"; }
  cat > .env <<ENV
# Generated $(date -u +%F) by deploy/bootstrap-server.sh. Secrets: keep on this server only.
PLATFORM_ENV=$PLATFORM_ENV
SITE_DOMAIN=$SITE_DOMAIN
POSTGRES_PASSWORD=$(rand 24)
PLATFORM_JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')
PLATFORM_GAME_INTERNAL_SECRET=$(rand 32)

# Email: staging catches sign-in emails in Mailpit (https://$SITE_DOMAIN/mail).
# For real users put an SMTP provider here (host/port/username/password/starttls).
PLATFORM_SMTP_HOST=mailpit
PLATFORM_SMTP_PORT=1025
PLATFORM_SMTP_FROM=Felt Kings <no-reply@$SITE_DOMAIN>
MAIL_UI_USER=tester
MAIL_UI_PASSWORD=$(rand 12)

# Paystack (empty = payments off). Test keys first: sk_test_... / pk_test_...
PLATFORM_PAYSTACK_SECRET_KEY=
PLATFORM_PAYSTACK_PUBLIC_KEY=
ENV
fi
chown deploy:deploy .env && chmod 600 .env
echo "server ready: $DIR (env $PLATFORM_ENV, site $SITE_DOMAIN)"
