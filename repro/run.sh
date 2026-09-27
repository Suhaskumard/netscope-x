#!/bin/sh
# One command: build the reproducibility image and run every verification gate. Report lands in ./repro_out
set -e
cd "$(dirname "$0")/.."
docker build -f repro/Dockerfile -t netscope-repro .
mkdir -p repro_out
docker run --rm -v "$(pwd)/repro_out:/app/repro_out" netscope-repro
