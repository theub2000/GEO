FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY . .

# uvicorn 실행 포트
EXPOSE 8200

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8200"]
