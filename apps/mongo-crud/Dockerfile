FROM python:3.12-slim

WORKDIR /app

# 의존성만 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8080

CMD ["python", "main.py"]
