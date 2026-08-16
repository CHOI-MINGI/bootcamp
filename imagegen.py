"""강의 슬라이드용 개념 삽화 생성.

여기서 만든 이미지는 '근거'가 아니라 '장식'이다.
자료에 실제로 있는 도표는 slides.extract_page_image()로 가져오고,
이 파일은 도표가 없는 슬라이드의 시각적 여백을 채우는 용도로만 쓴다.
그래서 슬라이드에는 'AI 생성'이라는 표시를 함께 넣는다.

두 단계로 나눈 이유
    슬라이드 문장을 이미지 모델에 그대로 넣으면 엉뚱한 그림이 나온다.
    텍스트 모델에게 먼저 "어떤 그림을 그릴지"를 영어 한 문장으로 정리하게 한 뒤,
    그 문장으로 이미지 모델을 부른다.

환경변수
    IMAGE_MODEL    사용할 이미지 모델. 기본 gemini-2.5-flash-image
    IMAGE_ENABLED  0으로 두면 기능 자체를 끈다
"""

import base64
import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from rag_module import get_llm

# 이미지 모델 중 가장 빠르고 저렴한 것을 기본으로 둔다.
# 슬라이드 장식용이라 최고 품질이 필요하지 않다.
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-3.1-flash-lite-image")

FALLBACK_MODELS = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
]


def enabled():
    return os.getenv("IMAGE_ENABLED", "1").strip() not in ("0", "false", "False")


def use_vertex():
    """Vertex AI로 호출할지 여부.

    AI Studio는 API 키로 인증하고 무료 티어 한도가 걸린다.
    Vertex AI는 서비스 계정으로 인증하고 GCP 결제 계정으로 청구되므로,
    무료 체험 크레딧을 쓸 수 있고 일일 한도도 다르다.
    Cloud Run에서는 별도 키 없이 인스턴스의 서비스 계정이 그대로 쓰인다.
    """
    return os.getenv("USE_VERTEX", "0").strip() not in ("0", "false", "False")


def _make_client(genai):
    """설정에 맞는 클라이언트를 만든다. 없으면 (None, 사유)."""
    if use_vertex():
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        # 이 이미지 모델은 global 엔드포인트로 제공된다.
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip()

        if not project:
            return None, "GOOGLE_CLOUD_PROJECT가 설정되어 있지 않습니다."

        # 콘솔 개편으로 인자 이름이 vertexai에서 enterprise로 바뀌었다.
        # 설치된 SDK 버전에 따라 둘 중 하나만 받으므로 차례로 시도한다.
        for kwargs in ({"enterprise": True}, {"vertexai": True}):
            try:
                return genai.Client(project=project, location=location, **kwargs), None
            except TypeError:
                continue

        return None, "설치된 google-genai가 Vertex 호출을 지원하지 않습니다."

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "GOOGLE_API_KEY가 설정되어 있지 않습니다."

    return genai.Client(api_key=api_key), None


# ============================================================
# 1. 슬라이드 내용 → 그림 지시문
# ============================================================
PROMPT_TEMPLATE = """You write short prompts for an image generation model.

The image will be used as a decorative illustration on a university lecture slide.

Slide title: {title}
Slide content: {bullets}

Write ONE English sentence describing a clean, minimal, flat vector illustration
that visually represents this topic.

Rules:
- No text, no letters, no numbers, no labels in the image.
- No charts with fake data, no diagrams with made-up structure.
- Use a simple metaphor or object, not a detailed technical diagram.
- Navy blue and amber color palette, white background, plenty of empty space.
- Output only the sentence. No quotes, no explanation."""


def build_image_prompt(title, bullets):
    """슬라이드 내용을 이미지 생성용 영어 프롬프트 한 문장으로 바꾼다."""
    chain = (ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
             | get_llm(0.4)
             | StrOutputParser())

    text = chain.invoke({"title": title, "bullets": " / ".join(bullets[:4])})
    return text.strip().strip('"')


# ============================================================
# 2. 이미지 생성
# ============================================================
def _extract_image(response):
    """응답에서 이미지 바이트를 꺼낸다. SDK 버전마다 구조가 달라 여러 경우를 본다."""
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)

        for part in getattr(content, "parts", None) or []:
            # 모델의 사고 과정이 함께 올 수 있다. 그림이 아니므로 건너뛴다.
            if getattr(part, "thought", None):
                continue

            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                data = inline.data
                return data if isinstance(data, bytes) else base64.b64decode(data)

    # 최신 Interactions API 응답 형태
    image = getattr(response, "output_image", None)
    if image is not None and getattr(image, "data", None):
        return base64.b64decode(image.data)

    return None


def _stop_reason(response):
    """정상 종료가 아니면 사유를 돌려준다. 안전 필터에 걸린 경우 등."""
    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        if reason is not None and str(reason).upper().endswith("STOP") is False:
            return str(reason)
    return None


def _call_variants(client, model, prompt):
    """통하는 호출 방식이 SDK·모델마다 달라 순서대로 시도한다."""
    variants = []

    # 이미지 모델은 응답 유형을 명시해야 그림을 돌려준다.
    # 공식 예제가 TEXT와 IMAGE를 함께 요청하므로 그 방식을 먼저 쓴다.
    try:
        from google.genai import types

        # 슬라이드의 그림 자리가 가로로 조금 긴 사각형이라 4:3이 잘 맞는다.
        ratio = os.getenv("IMAGE_ASPECT_RATIO", "4:3")

        def with_config(modalities, image_config=None):
            kwargs = {"response_modalities": modalities}
            if image_config is not None:
                kwargs["image_config"] = image_config
            return lambda: client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(**kwargs),
            )

        # 비율·크기까지 지정하는 방식을 먼저 시도한다.
        try:
            cfg = types.ImageConfig(aspect_ratio=ratio, image_size="1K")
            variants.append(("비율 지정", with_config(["IMAGE", "TEXT"], cfg)))
        except Exception:
            pass

        variants.append(("TEXT+IMAGE", with_config(["TEXT", "IMAGE"])))
        variants.append(("IMAGE", with_config(["IMAGE"])))

    except Exception:
        pass

    variants.append((
        "기본",
        lambda: client.models.generate_content(model=model, contents=prompt),
    ))

    if hasattr(client, "interactions"):
        variants.append((
            "interactions",
            lambda: client.interactions.create(model=model, input=prompt),
        ))

    return variants


def generate_illustration(title, bullets, model=None):
    """개념 삽화를 만들어 (PNG 바이트, 오류 메시지)로 반환한다.

    삽화는 없어도 되는 요소다. 실패해도 전체 생성이 중단되지 않도록
    예외를 밖으로 던지지 않고 사유만 돌려준다.
    """
    if not enabled():
        return None, "삽화 기능이 꺼져 있습니다."

    try:
        from google import genai
    except ImportError:
        return None, "google-genai 패키지가 설치되어 있지 않습니다."

    client, error = _make_client(genai)
    if client is None:
        return None, error

    try:
        instruction = build_image_prompt(title, bullets)
    except Exception as e:
        return None, f"그림 지시문 생성 실패: {type(e).__name__}"

    model = model or IMAGE_MODEL
    last_error = ""

    for name in [model] + [m for m in FALLBACK_MODELS if m != model]:
        for label, call in _call_variants(client, name, instruction):
            try:
                response = call()
                data = _extract_image(response)
                if data:
                    return data, None

                stop = _stop_reason(response)
                last_error = (f"{name}: 생성 거부됨 ({stop})" if stop
                              else f"{name}: 응답에 이미지가 없음")

            except Exception as e:
                message = str(e).replace("\n", " ")
                if "429" in message or "RESOURCE_EXHAUSTED" in message:
                    # 할당량 문제면 같은 모델의 다른 호출 방식도 막혀 있다.
                    last_error = f"{name}: 이미지 생성 할당량 초과"
                    break
                if "404" in message or "not found" in message:
                    last_error = f"{name}: 계정에서 사용할 수 없는 모델"
                    break
                last_error = f"{name}: {type(e).__name__}"

    return None, last_error or "이미지 생성 실패"
