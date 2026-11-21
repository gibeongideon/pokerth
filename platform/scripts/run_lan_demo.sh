#!/usr/bin/env bash
# Serve the platform to phones on the same Wi-Fi, for the no-login demo APK
# (apps/player: npm run android:demo). LOCAL TESTING ONLY: runs with
# PLATFORM_ENV=local (demo sign-in endpoints on) and listens on the LAN.
#
#   platform/scripts/run_lan_demo.sh [LAN_IP]      (Ctrl-C stops the API)
set -euo pipefail
cd "$(dirname "$0")/.."
IP=${1:-$(ip -4 route get 1.1.1.1 | grep -oP 'src \K[\d.]+')}
echo "LAN IP: $IP  (the APK must be built with VITE_API_BASE_URL=http://$IP:8000)"

docker compose up -d postgres redis mailpit >/dev/null
. .venv/bin/activate
alembic upgrade head >/dev/null
python -m app.seed >/dev/null

# Game server for live hands (WebSocket on :7233).
docker rm -f poker-gs >/dev/null 2>&1 || true
python - <<'PY' > /tmp/fk-seat-key.pem
from app.services.seat_tokens import public_key_pem
print(public_key_pem())
PY
docker run -d --name poker-gs --network host -v poker-server-build-cache:/build:ro \
  -e POKERTH_PLATFORM_MODE=1 -e POKERTH_SEAT_TOKEN_PUBLIC_KEY="$(cat /tmp/fk-seat-key.pem)" \
  -e POKERTH_PLATFORM_URL=http://127.0.0.1:8000 -e POKERTH_PLATFORM_SECRET=dev-only-insecure-game-secret \
  poker-server-build /build/bin/pokerth_dedicated_server --foreground >/dev/null
trap 'docker rm -f poker-gs >/dev/null 2>&1 || true' EXIT

echo "API on http://$IP:8000 - open http://$IP:8000/healthz on the phone to check it can connect."
PLATFORM_ENV=local \
PLATFORM_GAME_WS_URL="ws://$IP:7233" \
PLATFORM_PUBLIC_BASE_URL="http://$IP:8000" \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
