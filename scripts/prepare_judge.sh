#!/bin/sh
set -eu

image=${1:-scu-judge:1}

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker CLI is required for isolated code execution.' >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  printf '%s\n' 'Docker Engine is not running. Start Docker Desktop, then run this command again.' >&2
  exit 1
fi

if docker image inspect --format '{{index .Config.Labels "scu.coding.languages"}}' "$image" 2>/dev/null | grep -Fx 'cpp11,c,python3' >/dev/null; then
  printf 'Ready: %s (C++11, C, Python 3)\n' "$image"
  exit 0
fi

docker build -t "$image" judge
docker image inspect --format '{{index .Config.Labels "scu.coding.languages"}}' "$image" | grep -Fx 'cpp11,c,python3' >/dev/null
printf 'Ready: %s (C++11, C, Python 3)\n' "$image"
