FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scanner/ scanner/
COPY config.example.toml .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "scanner", "loop"]
