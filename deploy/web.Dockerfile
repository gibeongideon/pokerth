# Player web app + reverse proxy (Caddy: HTTPS, /api -> API, /ws -> game server).
#   docker build -f deploy/web.Dockerfile .
# (Web builds use their own origin for shared links; PUBLIC_URL is only for app builds.)
FROM node:20-slim AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/player/package.json apps/player/
COPY packages/api-client/package.json packages/api-client/
COPY packages/protocol/package.json packages/protocol/
RUN npm ci --no-audit --no-fund
COPY apps/player apps/player
COPY packages packages
RUN npm run build -w apps/player

FROM caddy:2.8.4-alpine
COPY --from=build /repo/apps/player/dist /srv/www
COPY deploy/Caddyfile /etc/caddy/Caddyfile
