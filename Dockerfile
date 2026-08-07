# GCP Cloud Run 배포용 컨테이너
#
# 로컬에서 쓰던 가상환경은 컨테이너 안에서 다시 만들 필요가 없다.
# 컨테이너 자체가 격리된 환경이기 때문이다.

FROM python:3.12-slim

# 파이썬 출력이 버퍼에 갇히지 않게 해, Cloud Run 로그에 바로 찍히도록 한다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 의존성을 먼저 설치한다.
# 코드만 바뀌었을 때 이 층을 다시 만들지 않아 빌드가 빨라진다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run은 PORT 환경변수로 사용할 포트를 알려준다. 그 값을 그대로 써야 한다.
ENV PORT=8080
EXPOSE 8080

# --server.address=0.0.0.0 : 컨테이너 밖에서 접속할 수 있게 한다.
# --server.headless=true   : 실행 시 브라우저를 열려고 시도하지 않는다.
CMD streamlit run app.py \
    --server.port=$PORT \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
