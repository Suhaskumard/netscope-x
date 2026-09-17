# Phase 06 development image. Runs the placeholder FastAPI app (backend/app/main.py)
# so the container can be built and started end-to-end before the real API (Phase 09) exists.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
