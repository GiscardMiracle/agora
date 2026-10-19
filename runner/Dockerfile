# Sandbox image used to run students' code. Keep it small: the VPS has a 10 GB disk.
#   docker build -t agora-runner:latest runner/
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential clang valgrind \
      libcriterion-dev libncurses-dev \
      python3 bc diffutils procps file less ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Uncomment for graphical projects (adds ~300 MB):
# RUN apt-get update && apt-get install -y --no-install-recommends libcsfml-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /work
