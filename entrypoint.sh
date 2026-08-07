#!/bin/sh
# 컨테이너가 시작될 때 실행되는 스크립트.
#
# Streamlit의 구글 로그인 설정은 .streamlit/secrets.toml 파일에서만 읽는다.
# 그런데 그 파일에는 클라이언트 시크릿이 들어가므로 이미지에 넣을 수 없다.
# 그래서 실행 시점에 환경변수를 받아 파일을 만들어 준다.
#
# 필요한 환경변수 (Cloud Run에서 Secret으로 주입)
#   OAUTH_CLIENT_ID
#   OAUTH_CLIENT_SECRET
#   OAUTH_REDIRECT_URI   예) https://서비스주소/oauth2callback
#   OAUTH_COOKIE_SECRET  로그인 쿠키 서명용 임의 문자열

set -e

if [ -n "$OAUTH_CLIENT_ID" ] && [ -n "$OAUTH_CLIENT_SECRET" ]; then
  mkdir -p /app/.streamlit

  cat > /app/.streamlit/secrets.toml <<EOF
[auth]
redirect_uri = "${OAUTH_REDIRECT_URI}"
cookie_secret = "${OAUTH_COOKIE_SECRET}"

[auth.google]
client_id = "${OAUTH_CLIENT_ID}"
client_secret = "${OAUTH_CLIENT_SECRET}"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
EOF

  echo "구글 로그인 설정을 적용했습니다."
else
  echo "OAuth 환경변수가 없어 개발 모드 로그인으로 시작합니다."
fi

exec streamlit run app.py \
  --server.port="${PORT:-8080}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
