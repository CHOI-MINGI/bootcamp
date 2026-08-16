"""배포 전 점검 스크립트.

설정한 모델을 실제로 쓸 수 있는지 확인한다.
공식 문서에 있는 모델명이라도 계정·티어에 따라 호출되지 않는 경우가 있어,
배포 후에 404나 429로 발견하면 늦다.

실행:
    python check_models.py
"""

import os

from dotenv import load_dotenv

load_dotenv()

print("=" * 62)

key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not key:
    print("GOOGLE_API_KEY가 없습니다. .env를 확인하세요.")
    raise SystemExit(1)

print(f"API 키  {key[:6]}...{key[-4:]}")

chat_model = os.getenv("CHAT_MODEL", "gemini-3.6-flash")
embed_model = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")

print(f"설정된 대화 모델  {chat_model}")
print(f"설정된 임베딩 모델  {embed_model}")
print("-" * 62)

# [1] 계정에서 쓸 수 있는 모델 목록
try:
    from google import genai

    client = genai.Client(api_key=key)
    available = [m.name.replace("models/", "") for m in client.models.list()]

    print(f"[1] 사용 가능한 모델 {len(available)}개")

    if chat_model in available:
        print(f"    OK   {chat_model} 목록에 있음")
    else:
        print(f"    주의 {chat_model} 이 목록에 없습니다.")
        similar = [m for m in available if "flash" in m and "image" not in m][:6]
        print("    대안:", ", ".join(similar))

except ImportError:
    print("[1] google-genai 미설치 — 목록 조회를 건너뜁니다.")
except Exception as e:
    print(f"[1] 목록 조회 실패 — {type(e).__name__}: {str(e)[:120]}")

# [2] 실제 호출 확인. 목록에 있어도 티어 때문에 막힐 수 있다.
print("[2] 실제 호출 확인")

try:
    from langchain_google_genai import ChatGoogleGenerativeAI

    ChatGoogleGenerativeAI(model=chat_model, temperature=0).invoke("안녕")
    print(f"    OK   {chat_model} 호출 성공")
except Exception as e:
    msg = str(e).replace("\n", " ")
    print(f"    실패 {chat_model} — {msg[:160]}")
    if "429" in msg:
        print("    할당량 문제입니다. 모델명은 유효합니다.")
    elif "404" in msg:
        print("    모델명이 잘못되었거나 계정에서 사용할 수 없습니다.")

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    dim = len(GoogleGenerativeAIEmbeddings(model=embed_model).embed_query("테스트"))
    print(f"    OK   {embed_model} 호출 성공 (차원 {dim})")
except Exception as e:
    print(f"    실패 {embed_model} — {str(e)[:160]}")

print("=" * 62)
print("현재 한도는 https://aistudio.google.com/rate-limit 에서 확인할 수 있습니다.")
