FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gtm_engine/ ./gtm_engine/
COPY reportingCharts/ ./reportingCharts/
COPY run_plan.py .
COPY config.yaml .
COPY app.py .

RUN mkdir -p data/raw versions

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0

EXPOSE 8000

CMD ["python", "app.py"]
