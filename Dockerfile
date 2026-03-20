FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y default-jdk ffmpeg fonts-nanum && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/default-java

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN ls -la /app/ && ls -la /app/shorts/ || echo "NO SHORTS DIR"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
