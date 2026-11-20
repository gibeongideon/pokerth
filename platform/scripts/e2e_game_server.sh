#!/usr/bin/env bash
# End-to-end check of platform <-> C++ game server (Phase 2b):
# seats alice/bob/carol at a fast 3-player table, starts the real game server
# in platform mode, lets three bots play it out with their seat tokens, and
# waits until the platform has settled the table.
#
# Needs: the compose Postgres/Redis, the seeded dev DB, the API on :8000, and
# the server built with docker/server/Dockerfile.build (poker-server-build-cache).
#
# WEB_CLIENTS=N plays the first N seats through the TypeScript GameClient
# (packages/protocol, the code the web and phone app use) over WebSocket :7233;
# the remaining seats are C++ bots. Default 0 = bots only.
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
WORK=$(mktemp -d)

python - "$WORK" <<'PY'
import json, sys, httpx
c = httpx.Client(base_url="http://localhost:8000", timeout=10)
auth = lambda u: {"Authorization": "Bearer " + c.post(f"/dev/token/{u}").json()["access_token"]}
def call(m, u, p, b=None):
    r = c.request(m, p, json=b, headers=auth(u)); r.raise_for_status(); return r.json()
tier = call("POST", "admin", "/admin/stake-tiers", {
    "name": "E2E fast", "buy_in_cents": 500, "seats": 3, "min_players": 2,
    "payout_bps": [6500, 3500], "starting_chips": 200, "first_small_blind": 20,
    "blind_level_minutes": 1, "sort_order": 99})
players = ["alice", "bob", "carol"]
for p in players: t = call("POST", p, "/lobby/quick-play", {"tier_id": tier["id"]})
for p in players: t = call("POST", p, f"/tables/{t['id']}/ready")
tokens = [call("GET", p, f"/tables/{t['id']}/seat-token")["token"] for p in players]
json.dump({"table": t["id"], "tokens": ",".join(tokens),
           "pubkey": c.get("/internal/seat-token-key").text}, open(sys.argv[1] + "/e2e.json", "w"))
PY
TABLE=$(python -c "import json;print(json.load(open('$WORK/e2e.json'))['table'])")
TOKENS=$(python -c "import json;print(json.load(open('$WORK/e2e.json'))['tokens'])")
PUB=$(python -c "import json;print(json.load(open('$WORK/e2e.json'))['pubkey'])")

docker rm -f poker-gs poker-bots >/dev/null 2>&1 || true
trap 'docker rm -f poker-gs poker-bots >/dev/null 2>&1 || true' EXIT
docker run -d --name poker-gs --network host -v poker-server-build-cache:/build:ro \
  -e POKERTH_PLATFORM_MODE=1 -e POKERTH_SEAT_TOKEN_PUBLIC_KEY="$PUB" \
  -e POKERTH_PLATFORM_URL=http://127.0.0.1:8000 -e POKERTH_PLATFORM_SECRET=dev-only-insecure-game-secret \
  poker-server-build /build/bin/pokerth_dedicated_server --foreground >/dev/null
sleep 4
WEB_CLIENTS=${WEB_CLIENTS:-0}
IFS=, read -ra ALL <<< "$TOKENS"
WEB_TOKENS=("${ALL[@]:0:$WEB_CLIENTS}")
BOT_TOKENS=$(IFS=,; echo "${ALL[*]:$WEB_CLIENTS}")
if [ -n "$BOT_TOKENS" ]; then
  docker run -d --name poker-bots --network host -v poker-server-build-cache:/build:ro \
    poker-server-build /build/bin/pokerth_bot -s 127.0.0.1 --no-tls --platform-tokens "$BOT_TOKENS" >/dev/null
fi
if [ "$WEB_CLIENTS" -gt 0 ]; then
  echo "web clients: ${#WEB_TOKENS[@]} over ws://127.0.0.1:7233"
  (cd ../packages/protocol && npm run --silent live -- ws://127.0.0.1:7233 "${WEB_TOKENS[@]}")
fi

echo "table $TABLE: game running, waiting for the result (up to 10 min)..."
for _ in $(seq 1 120); do
  STATUS=$(docker compose exec -T postgres psql -U platform -tAc "select status from game_tables where id='$TABLE'")
  [ "$STATUS" = "finished" ] && { echo "OK: table settled by the game server"; exit 0; }
  sleep 5
done
echo "FAIL: table still $STATUS"; exit 1
