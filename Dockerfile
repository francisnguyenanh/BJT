FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bjt_app ./bjt_app
COPY ai_module ./ai_module
COPY BJT-Wiki ./BJT-Wiki

# Secrets (Kaggle proxy creds, Vertex service-account.json) are deliberately
# NOT copied into the image — see .dockerignore. Cloud Run supplies them via
# --set-secrets (Kaggle) and the attached service account / ADC (Vertex AI).

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "120", "bjt_app.app:app"]
