# GCP Cloud Run 배포 가이드

로컬 PC에 아무것도 설치하지 않고, 브라우저의 **Cloud Shell** 만으로 배포합니다.

---

## 0. 준비

| 항목 | 내용 |
|---|---|
| Google 계정 | Gemini API 키를 발급받은 계정 그대로 사용 |
| 결제 계정 | **카드 등록 필요.** 무료 한도(월 200만 요청) 안에서는 실제 청구가 거의 발생하지 않음 |
| 소요 시간 | 처음이면 30~40분 |

> 결제를 등록하면 Gemini API도 Tier 1로 올라가, 막혀 있던 이미지 생성 할당량이 열립니다.

---

## 1. GitHub에 코드 올리기

### 1-1. 커밋되면 안 되는 것 확인

```powershell
dir -Force
```

`.env` 는 숨김 파일이라 그냥 `dir` 로는 보이지 않습니다. **반드시 `-Force` 로 확인하세요.**

`.gitignore` 에 다음이 들어 있는지 확인합니다.

```
.env
venv/
data/
```

### 1-2. 업로드

```powershell
git init
git add .
git status          # .env 와 data/ 가 목록에 없어야 합니다
git commit -m "AI 학습 도우미 MVP"
git branch -M main
git remote add origin https://github.com/<사용자명>/<저장소명>.git
git push -u origin main
```

`git status` 에 `.env` 가 보이면 **push 하지 마세요.** `.gitignore` 를 고친 뒤 다시 확인합니다.

> 한 번이라도 키가 올라가면 지워도 소용없습니다. 커밋 기록에 남고, 공개 저장소는 자동 수집 대상입니다. 그런 경우 [AI Studio](https://aistudio.google.com/apikey) 에서 키를 삭제하고 새로 발급받으세요.

---

## 2. Cloud Shell 열기

1. [console.cloud.google.com](https://console.cloud.google.com) 접속
2. 프로젝트 선택 (Gemini 키를 만든 프로젝트)
3. 우측 상단 **터미널 아이콘(>_)** 클릭 → Cloud Shell 실행

브라우저 안에서 리눅스 터미널이 열립니다. `gcloud`, `git`, `docker` 가 모두 설치되어 있습니다.

---

## 3. API 사용 설정

```bash
gcloud services enable run.googleapis.com \
                       cloudbuild.googleapis.com \
                       artifactregistry.googleapis.com \
                       secretmanager.googleapis.com
```

---

## 4. API 키를 Secret Manager에 저장

키를 배포 명령어에 직접 적으면 명령 기록과 로그에 남습니다. 별도 보관소를 씁니다.

```bash
# 실제 키 값을 입력하고 Enter → Ctrl+D
gcloud secrets create GOOGLE_API_KEY --data-file=-
```

Cloud Run이 이 값을 읽을 수 있도록 권한을 줍니다.

```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')

gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## 5. 코드 받아서 배포

```bash
git clone https://github.com/<사용자명>/<저장소명>.git
cd <저장소명>

gcloud run deploy ai-learning-assistant \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --timeout 300 \
  --set-secrets GOOGLE_API_KEY=GOOGLE_API_KEY:latest
```

| 옵션 | 이유 |
|---|---|
| `--source .` | Dockerfile을 알아서 찾아 빌드합니다 |
| `--region asia-northeast3` | 서울 리전 |
| `--allow-unauthenticated` | 로그인 없이 접속 가능하게 (시연용) |
| `--memory 2Gi` | FAISS와 임베딩이 메모리를 쓰므로 기본값 512Mi로는 부족합니다 |
| `--timeout 300` | 슬라이드 생성처럼 오래 걸리는 요청 대비 |

첫 빌드는 5~10분 걸립니다. 끝나면 `https://ai-learning-assistant-xxxxx.a.run.app` 형태의 **URL이 출력됩니다.** 이게 과제 결과물 ③번입니다.

---

## 6. 코드를 고친 뒤 다시 배포

```bash
cd <저장소명>
git pull
gcloud run deploy ai-learning-assistant --source . --region asia-northeast3
```

---

## 알아둘 제약

### 등록한 자료가 재시작 시 사라집니다

Cloud Run은 컨테이너가 꺼지면 파일이 초기화됩니다. `data/` 에 저장한 인덱스도 사라집니다.

- **시연에는 문제없습니다.** 접속 → 자료 등록 → 질의응답까지 한 번에 이어집니다.
- 유지하려면 Cloud Storage 버킷을 볼륨으로 연결하거나, 계획서대로 pgvector로 옮겨야 합니다.

보고서에는 이렇게 적으면 됩니다.

> 컨테이너 파일시스템이 휘발성이므로 인덱스가 재시작 시 소실됩니다. 운영 단계에서는 Cloud Storage 마운트 또는 pgvector 전환이 필요합니다.

### 첫 접속이 느립니다

요청이 없으면 인스턴스가 0으로 줄어듭니다(콜드 스타트). 시연 직전에 한 번 접속해 깨워두세요.

항상 켜두려면 `--min-instances 1` 을 붙이면 되지만, **이 경우 무료 한도를 벗어나 과금됩니다.**

### 비용 관리

```bash
# 시연이 끝난 뒤 서비스 삭제
gcloud run services delete ai-learning-assistant --region asia-northeast3
```

예산 알림도 걸어두세요. 콘솔 → 결제 → 예산 및 알림 → 1,000원 정도로 설정하면 충분합니다.

---

## 문제가 생기면

```bash
# 최근 로그 확인
gcloud run services logs read ai-learning-assistant --region asia-northeast3 --limit 50
```

| 증상 | 원인 |
|---|---|
| 빌드 실패 | `requirements.txt` 의 패키지가 Python 3.12에서 설치되는지 확인 |
| 시작 후 바로 종료 | 포트 문제. Dockerfile의 `$PORT` 사용 여부 확인 |
| 키 오류 | Secret 이름과 `--set-secrets` 값이 일치하는지 확인 |
| 메모리 부족 | `--memory 4Gi` 로 올려서 재배포 |
