FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV OLLAMA_HOST=http://ollama:11434
ENV MLFLOW_TRACKING_URI=file:/app/mlruns

EXPOSE 8501 8000

# Default: run the Streamlit UI. Override CMD to run the API instead, e.g.:
#   docker run ... uvicorn api:app --host 0.0.0.0 --port 8000
CMD ["streamlit", "run", "receipt_processor.py", "--server.port=8501", "--server.address=0.0.0.0"]
