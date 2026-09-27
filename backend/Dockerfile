# Phase 06 development image, originally for the placeholder FastAPI app (backend/app/main.py).
# The real API (Phase 09+) reads/writes artifacts through experiments/artifacts/ (paths.py, io.py) and
# experiments/matrix_runner.py (POST /experiments), so that package must ship in the image too -- found
# during the Docker validation pass (backend container crash-looped with
# ModuleNotFoundError: No module named 'experiments' before this line was added).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY experiments/ experiments/
# experiments/synthetic_traffic.py imports simulator.scenarios.topologies (found during the same pass).
COPY simulator/ simulator/

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
