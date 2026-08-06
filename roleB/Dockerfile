# Render는 render.yaml의 python 런타임으로 배포한다. 이 Dockerfile은 백업 경로다.
#   - Render 무료 조건이 바뀌면 Hugging Face Spaces(Docker SDK)로 옮긴다 (PLAN.md §11.2)
#   - 로컬에서 컨테이너로 재현하고 싶을 때
#
#   docker build -t wheretogo-api -f roleB/Dockerfile roleB
#   docker run -p 8000:8000 -e MOCK_MODE=true wheretogo-api

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# $PORT는 Render / HF Spaces가 주입한다.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
