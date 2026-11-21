# Game server image for deployment (platform mode).
#   docker build -t feltkings-gameserver -f docker/server/Dockerfile .
# Build stage = docker/server/Dockerfile.build; the runtime stage only carries
# the shared libraries the server links against.
FROM ubuntu:25.10 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build pkg-config ca-certificates \
        libprotobuf-dev protobuf-compiler libwebsocketpp-dev libssl-dev \
        libboost-iostreams-dev libboost-random-dev libboost-thread-dev \
        libboost-filesystem-dev libboost-program-options-dev libboost-json-dev \
        qt6-base-dev \
    && rm -rf /var/lib/apt/lists/*
COPY . /src
RUN cmake -S /src -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPOKERTH_SERVER_ONLY=ON \
    && cmake --build /build --target pokerth_dedicated_server -j"$(nproc)" \
    && strip /build/bin/pokerth_dedicated_server

FROM ubuntu:25.10
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libqt6core6t64 libqt6network6 libqt6sql6 libqt6xml6 \
        libboost-filesystem1.88.0 libboost-iostreams1.88.0 libboost-program-options1.88.0 \
        libboost-thread1.88.0 libprotobuf32t64 libssl3t64 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10002 --create-home poker \
    && mkdir -p /home/poker/results && chown poker:poker /home/poker/results
COPY --from=build /build/bin/pokerth_dedicated_server /usr/local/bin/pokerth_dedicated_server
USER poker
WORKDIR /home/poker
# 7233 = WebSocket (behind Caddy at /ws), 7234 = legacy TCP (not exposed).
EXPOSE 7233
# Unsent results survive restarts here (mount a volume).
ENV POKERTH_PLATFORM_MODE=1 POKERTH_PLATFORM_SPOOL_DIR=/home/poker/results
CMD ["pokerth_dedicated_server", "--foreground"]
