# Phase 106 reproducibility image: re-runs the project's own verification suite against pinned dependencies.
# Build from the repo root:  docker build -f repro/Dockerfile -t netscope-repro .
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "scripts.run_reproducibility_check", "--out", "repro_out"]
