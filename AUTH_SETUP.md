# 구글 로그인 설정 가이드

`--allow-unauthenticated`로 배포한 앱은 URL만 알면 누구나 들어옵니다.
구글 로그인을 붙여 로그인한 사용자만 이용하게 하고, **역할과 과목도 계정 기준으로 자동 부여**합니다.

---

## 1. OAuth 클라이언트 발급

1. [Google Cloud 콘솔 → API 및 서비스 → OAuth 동의 화면](https://console.cloud.google.com/apis/credentials/consent)
   - User Type: **외부(External)**
   - 앱 이름, 지원 이메일 입력 후 저장
   - 테스트 사용자에 **본인 계정과 멘토님 계정**을 추가 (게시 전에는 등록된 계정만 로그인됩니다)

2. [사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID](https://console.cloud.google.com/apis/credentials)
   - 유형: **웹 애플리케이션**
   - **승인된 리디렉션 URI** 에 두 개를 등록합니다.

```
http://localhost:8501/oauth2callback
https://배포된-서비스-주소/oauth2callback
```

배포 주소는 아래 명령으로 확인합니다.

```bash
gcloud run services describe ai-learning-assistant --region asia-northeast3 --format='value(status.url)'
```

3. 생성 후 나오는 **클라이언트 ID** 와 **클라이언트 보안 비밀번호** 를 복사해 둡니다.

---

## 2. 로컬 설정

`.streamlit/secrets.toml` 파일을 만듭니다. **`.gitignore`에 이미 등록해 두었습니다.**

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "아무 긴 임의 문자열"

[auth.google]
client_id = "발급받은-클라이언트-ID"
client_secret = "발급받은-보안-비밀번호"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

패키지를 설치하고 실행합니다.

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m streamlit run app.py
```

> `secrets.toml`이 없으면 기존 방식(아이디 직접 입력)의 **개발 모드 로그인**이 뜹니다. 코드가 죽지 않으므로 설정 전에도 개발은 계속할 수 있습니다.

---

## 3. 역할과 과목 지정

로그인한 메일 주소로 서버가 역할을 정합니다. 환경변수로 관리합니다.

| 변수 | 설명 | 예시 |
|---|---|---|
| `ADMIN_EMAILS` | 관리자로 취급할 메일. 쉼표 구분 | `admin@oo.ac.kr` |
| `PROFESSOR_EMAILS` | 교수자로 취급할 메일. 쉼표 구분 | `prof@oo.ac.kr,kim@oo.ac.kr` |
| `COURSE_MAP` | 메일별 과목. JSON | `{"prof@oo.ac.kr":["EE201"]}` |
| `DEFAULT_COURSES` | 목록에 없는 사용자의 기본 과목 | `EE201` |
| `ALLOWED_EMAIL_DOMAIN` | 이 도메인만 허용 (선택) | `oo.ac.kr` |
| `TEST_ACCOUNTS` | 구글 계정 없이 쓸 발급 계정. JSON | 아래 참고 |

**역할 세 가지**

| 역할 | 권한 |
|---|---|
| 관리자 | 모든 자료 열람. 교수자·학습자 화면을 사이드바에서 전환하며 사용 |
| 교수자 | 담당 과목 자료 + 공개 자료. 문항·계획서·요약·슬라이드 생성 |
| 학습자 | 수강 과목의 공개·수강생 자료. 교수자 전용 자료는 차단 |

### 테스트 계정

구글 계정을 새로 만들기 어려운 평가·시연 상황을 위해 아이디/비밀번호 로그인을 함께 제공합니다.
**가입 기능은 없습니다.** 서버가 발급한 계정만 쓸 수 있습니다.

```
TEST_ACCOUNTS={"admin":{"password":"sha256:해시값","role":"관리자","courses":["EE201"]}}
```

비밀번호 해시는 이렇게 만듭니다.

```bash
python -c "import hashlib;print('sha256:'+hashlib.sha256('원하는비밀번호'.encode()).hexdigest())"
```

`sha256:` 없이 평문을 넣어도 동작하지만, 시크릿에 평문이 남으므로 해시를 권장합니다.

로컬에서는 `.env`에 넣으면 됩니다.

```
PROFESSOR_EMAILS=본인메일@gmail.com
COURSE_MAP={"본인메일@gmail.com":["EE201"]}
DEFAULT_COURSES=EE201
```

목록에 없는 사람은 **학습자 + 기본 과목**으로 처리됩니다. 학생이 교수자를 사칭할 수 없습니다.

---

## 4. Cloud Run에 반영

### 4-1. 시크릿 등록

```bash
printf '발급받은-클라이언트-ID' | gcloud secrets create OAUTH_CLIENT_ID --data-file=-
printf '발급받은-보안-비밀번호' | gcloud secrets create OAUTH_CLIENT_SECRET --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create OAUTH_COOKIE_SECRET --data-file=-
```

각 시크릿에 접근 권한을 줍니다.

```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for S in OAUTH_CLIENT_ID OAUTH_CLIENT_SECRET OAUTH_COOKIE_SECRET; do
  gcloud secrets add-iam-policy-binding $S --member="$SA" --role="roles/secretmanager.secretAccessor"
done
```

### 4-2. 재배포

`OAUTH_REDIRECT_URI`에는 **본인 서비스 주소**를 넣으세요.

```bash
gcloud run deploy ai-learning-assistant --source . --region asia-northeast3 --allow-unauthenticated --memory 2Gi --timeout 300 --set-secrets GOOGLE_API_KEY=GOOGLE_API_KEY:latest,OAUTH_CLIENT_ID=OAUTH_CLIENT_ID:latest,OAUTH_CLIENT_SECRET=OAUTH_CLIENT_SECRET:latest,OAUTH_COOKIE_SECRET=OAUTH_COOKIE_SECRET:latest --set-env-vars OAUTH_REDIRECT_URI=https://배포주소/oauth2callback,PROFESSOR_EMAILS=본인메일@gmail.com,DEFAULT_COURSES=EE201
```

`COURSE_MAP`은 JSON에 쉼표가 들어가 `--set-env-vars`와 충돌합니다. 필요하면 이렇게 넣으세요.

```bash
gcloud run services update ai-learning-assistant --region asia-northeast3 --update-env-vars '^@^COURSE_MAP={"메일@gmail.com":["EE201"]}'
```

`^@^`는 구분자를 쉼표 대신 `@`로 쓰겠다는 표시입니다.

---

## 확인

1. 배포 URL 접속 → **Google 계정으로 로그인** 버튼만 보이면 정상
2. 로그인 후 사이드바에 메일 주소와 역할이 표시되는지 확인
3. `PROFESSOR_EMAILS`에 없는 계정으로 로그인하면 **학습자**로 잡히는지 확인

---

## 자주 겪는 문제

| 증상 | 원인 |
|---|---|
| `redirect_uri_mismatch` | 콘솔에 등록한 URI와 `OAUTH_REDIRECT_URI`가 정확히 일치하지 않음. `https`, 끝의 `/oauth2callback`까지 확인 |
| 로그인 후 다시 로그인 화면 | `cookie_secret`이 비어 있거나 재배포마다 바뀜. 시크릿으로 고정했는지 확인 |
| 개발 모드 화면이 뜸 | `secrets.toml`이 생성되지 않음. `OAUTH_CLIENT_ID` 주입 여부 확인 |
| `액세스 차단됨` | OAuth 동의 화면의 테스트 사용자에 해당 계정이 없음 |

---

## 남은 한계

- 구글 계정만 지원합니다. 실제 학내 SSO는 학교 IdP의 `server_metadata_url`로 바꾸면 됩니다. **코드 변경은 없습니다.**
- 역할·과목이 환경변수 기반이라 사람이 늘면 관리가 어렵습니다. 운영 단계에서는 학사 시스템 연동이 필요합니다.
