FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV OLLAMA_HOST=http://ollama:11434
ENV MLFLOW_TRACKING_URI=file:/app/mlruns

EXPOSE 8000

# This image is the backend: the FastAPI REST API that the Next.js frontend
# (web-next) calls. The UI is a separate service — see docker-compose.yml.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
