# Architecture

## Components
| Component | Path | Tech | Role |
|---|---|---|---|
| Game server | `src/` (existing) | C++23, Boost.Asio, protobuf, websocketpp | Runs hands only. In-memory game state. Ports 7234 (TCP) and 7233 (WebSocket). |
| Platform API | `platform/` (new) | FastAPI, SQLAlchemy 2, Alembic, Postgres | Users, auth, wallet ledger, payments, tables, tournaments, config. Source of truth for money. |
| Workers | `platform/` (new) | Celery + Redis, beat | Timeouts, scheduled starts, payouts, reconciliation, expiry jobs. |
| Player app | `apps/player/` (new) | Vite, React, TS, Tailwind, PixiJS, Capacitor | The only player-facing app: sign-in, wallet, lobby, tournaments and the poker table. Web/PWA plus Android and iOS from the same code. |
| Site | `apps/site/` (new) | Next.js | Landing page, SEO, legal pages, admin back office. |
| Shared packages | `packages/` (new) | TypeScript, pnpm workspace | `api-client` (from OpenAPI), `protocol` (ts-proto from `pokerth.proto`), `ui` (design tokens, components). |
| Deployment | `deploy/` (new) | Helm, Argo CD | Kubernetes manifests. |

## Flow diagram
```
 Web / Android / iOS ──► player app ──REST──► platform-api ◄── Paystack webhooks
    │                                   │  Postgres · Redis · Celery workers
    └──► (table screen) ──WSS protobuf──► game-server pod N
                                        ▲
         platform-api ◄──HMAC internal HTTP──┘ (create table / results)
```

## Joining a staked table
1. The user picks a table in the portal. The platform moves buy-in + fee from `user:available` to `user:escrow`.
2. When the table starts, the platform asks a game-server pod to create the table and receives its address.
3. The platform issues each seated player a short-lived Ed25519 seat token (user id, table id, seat, expiry).
4. The table client connects to the pod over WSS and sends the token in `InitMessage.platformToken`.
5. The game server checks the token signature and expiry, then seats the player.
6. At game end the server posts the finishing order. The platform pays prizes and rake in one ledger transaction.

## Money rules
- Integer minor units only. No floats anywhere in money paths.
- Every movement is a balanced journal entry with an idempotency key.
- Settling a Paystack charge requires: valid webhook signature (or server-side verify), matching reference, **matching amount and currency**, and status `success`.

## Known code facts (game server)
- Card RNG: `src/engine/local_engine/tools.cpp` uses OpenSSL `RAND_bytes` (CSPRNG), with a fallback to `std::random_device` on failure. In real-money mode the fallback must be replaced by refusing to deal.
- Lobby and sessions: `src/net/serverlobbythread.cpp`, `src/net/sessionmanager.cpp`.
- Game state machine: `src/net/servergame.cpp`, `src/net/servergamestate.cpp`.
- WebSocket listener: `src/net/serveracceptwebhelper.cpp`.
- Protocol: `pokerth.proto` (`InitMessage`, `JoinNewGameMessage`, `JoinExistingGameMessage`, `NetGameInfo`).
- Official-server MySQL code (`src/dbofficial/`) is not used in managed mode.
