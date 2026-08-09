"""강의 슬라이드(PPTX) 생성 기능.

역할 분담:
  - LLM   : 자료를 근거로 "무엇을 넣을지"(제목·내용·출처)를 JSON으로 정한다.
  - 이 파일 : 그 JSON을 받아 "어떻게 배치할지"를 처리해 실제 pptx 파일을 만든다.

그림은 새로 생성하지 않고, 근거가 된 PDF 페이지에서 도표·이미지를 그대로 가져온다.
자료에 없는 그림을 지어내지 않기 위해서다.
"""

import io
import json
import re

import fitz                                  # PyMuPDF
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI

from rag_module import (_search, _build_context, _build_sources,
                        _format_extra, CHAT_MODEL)


# ============================================================
# 1. 색상 / 서체
# ============================================================
NAVY = RGBColor(0x1E, 0x27, 0x61)
NAVY_DARK = RGBColor(0x12, 0x19, 0x3F)
NAVY_MID = RGBColor(0x2A, 0x36, 0x70)
ICE = RGBColor(0xCA, 0xDC, 0xFC)
ICE_LIGHT = RGBColor(0xEA, 0xF1, 0xFC)
AMBER = RGBColor(0xD9, 0x8A, 0x1F)
AMBER_LIGHT = RGBColor(0xFB, 0xF0, 0xDC)
GRAY = RGBColor(0x5A, 0x64, 0x78)
LINE = RGBColor(0xD8, 0xDE, 0xE9)
TEXT = RGBColor(0x1A, 0x21, 0x38)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xF3, 0xF6, 0xFB)

FONT = "맑은 고딕"

SLIDE_W = 13.333
SLIDE_H = 7.5


# ============================================================
# 2. LLM에게 슬라이드 구성을 받아오는 부분
# ============================================================
SLIDE_TEMPLATE = """당신은 OO대학교의 강의자료 작성 AI입니다.

[규칙]
1. 아래 [자료]에 있는 내용만 사용하십시오. 자료에 없는 내용은 절대 지어내지 마십시오.
2. 반드시 JSON 배열만 출력하십시오. 설명 문장, 인사말, 코드블록 표시를 붙이지 마십시오.
3. 각 슬라이드는 다음 형식을 따르십시오.
   {{"title": "슬라이드 제목", "lead": "한 줄 요약", "bullets": ["문장1", "문장2"], "source": "파일명 p.페이지"}}
4. lead는 그 슬라이드의 핵심을 한 문장(35자 이내)으로 요약한 것입니다.
5. bullets는 슬라이드당 3~4개, 각 문장은 45자 이내로 작성하십시오.
6. source에는 그 슬라이드의 근거가 된 출처를 '파일명 p.숫자' 형식으로 정확히 적으십시오.
7. 모든 내용은 한국어로 작성하십시오.

[요청]
주제 '{topic}'에 대한 강의 슬라이드 {count}장을 구성하십시오.
{extra}
[자료]
{context}

[JSON 배열만 출력]"""


def _parse_json(raw):
    """LLM 응답에서 JSON 배열을 꺼낸다.

    지시를 했더라도 앞뒤에 설명이나 ```json 표시가 붙는 경우가 있어,
    가장 바깥쪽 대괄호 구간만 잘라내어 파싱한다.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("JSON 배열을 찾지 못했습니다.")

    data = json.loads(text[start:end + 1])

    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "title": str(item.get("title", "")).strip(),
            "lead": str(item.get("lead", "")).strip(),
            "bullets": [str(b).strip() for b in item.get("bullets", []) if str(b).strip()],
            "source": str(item.get("source", "")).strip(),
        })

    if not cleaned:
        raise ValueError("슬라이드 항목이 비어 있습니다.")

    return cleaned


def generate_slide_data(vectorstore, topic, count=5, role="교수자", courses=(),
                        k=6, extra=""):
    """자료를 근거로 슬라이드 구성(JSON)을 만든다.

    extra : 교수자가 입력한 추가 지시사항 (선택)
    """
    docs, best_score, blocked = _search(vectorstore, topic, role, courses, k)
    if blocked:
        return blocked

    prompt = ChatPromptTemplate.from_template(SLIDE_TEMPLATE)
    llm = ChatGoogleGenerativeAI(model=CHAT_MODEL, temperature=0.2)
    chain = prompt | llm | StrOutputParser()

    raw = chain.invoke({
        "topic": topic,
        "count": count,
        "extra": _format_extra(extra),
        "context": _build_context(docs),
    })

    try:
        slides = _parse_json(raw)
    except Exception as e:
        # JSON 파싱에 실패해도 기능이 통째로 죽지 않도록 원문을 돌려준다.
        return {
            "answer": raw,
            "slides": None,
            "sources": _build_sources(docs),
            "blocked": False,
            "reason": f"JSON 파싱 실패: {e}",
            "best_score": best_score,
        }

    return {
        "answer": None,
        "slides": slides,
        "sources": _build_sources(docs),
        "blocked": False,
        "reason": None,
        "best_score": best_score,
    }


# ============================================================
# 3. 근거 페이지에서 그림 가져오기
# ============================================================
def _parse_source(source):
    """'회로이론.pdf p.12' 형태에서 파일명과 페이지 번호를 분리한다.

    도표를 꺼낼 수 있는 것은 PDF뿐이므로 다른 형식은 처리하지 않는다.
    """
    m = re.search(r"^(.*?\.pdf)\s*p\.\s*(\d+)", source, re.IGNORECASE)
    if not m:
        return None, None
    return m.group(1).strip(), int(m.group(2))


def _ink_ratio(image_bytes):
    """이미지에서 흰색이 아닌 픽셀의 비율을 구한다.

    PDF에는 테두리만 있는 빈 상자나 배경 도형이 이미지로 들어 있는 경우가 많다.
    그런 것을 슬라이드에 넣으면 빈 네모만 보이므로, 내용이 있는지 미리 걸러낸다.
    """
    try:
        pix = fitz.Pixmap(image_bytes)

        # 알파 채널이나 CMYK는 RGB로 변환한다.
        if pix.alpha or pix.colorspace is None or pix.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)

        # 계산을 빠르게 하기 위해 작게 줄인다.
        while pix.width > 80 and pix.height > 80:
            pix.shrink(1)

        data = pix.samples
        n = pix.n
        total = pix.width * pix.height
        if total == 0:
            return 0.0

        ink = 0
        for i in range(0, len(data), n):
            # 세 채널 중 하나라도 어두우면 '내용이 있는 픽셀'로 본다.
            if min(data[i], data[i + 1], data[i + 2]) < 235:
                ink += 1

        return ink / total

    except Exception:
        # 판단할 수 없으면 일단 쓸 만하다고 본다.
        return 1.0


def extract_page_image(pdf_bytes, page_no, min_size=180, min_ink=0.04,
                       allow_page_render=True):
    """근거가 된 페이지에서 그림을 가져온다.

    1순위 : 그 페이지에 삽입된 이미지 중 내용이 있고 가장 큰 것 (도표·사진)
    2순위 : allow_page_render가 True일 때만, 페이지 전체를 렌더링한 썸네일

    페이지 렌더링은 거의 항상 성공하므로, 도표만 먼저 찾고 싶을 때는
    allow_page_render를 False로 두고 단계를 나눠 호출한다.

    반환: (이미지 바이트, 종류) 또는 (None, None)
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None, None

    try:
        if page_no < 1 or page_no > len(doc):
            return None, None

        page = doc[page_no - 1]

        # [1] 페이지에 삽입된 이미지 찾기
        best = None
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue

            # 로고나 아이콘처럼 작은 이미지는 제외한다.
            if info.get("width", 0) < min_size or info.get("height", 0) < min_size:
                continue

            # 테두리만 있는 빈 상자 등 내용이 없는 이미지는 제외한다.
            if _ink_ratio(info["image"]) < min_ink:
                continue

            area = info["width"] * info["height"]
            if best is None or area > best[0]:
                best = (area, info["image"])

        if best:
            return best[1], "그림"

        if not allow_page_render:
            return None, None

        # [2] 쓸 만한 삽입 이미지가 없으면 페이지 자체를 이미지로 렌더링
        pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6))
        png = pix.tobytes("png")

        # 페이지가 거의 비어 있다면 그림을 넣지 않는다.
        if _ink_ratio(png) < 0.01:
            return None, None

        return png, "페이지"

    finally:
        doc.close()


# ============================================================
# 4. pptx 조립 — 공통 도구
# ============================================================
def _text(slide, left, top, width, height, content,
          size=14, bold=False, color=TEXT, align=PP_ALIGN.LEFT,
          anchor=MSO_ANCHOR.TOP, spacing=1.0):
    box = slide.shapes.add_textbox(Inches(left), Inches(top),
                                   Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0

    p = frame.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    run = p.add_run()
    run.text = content
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return frame


def _rect(slide, left, top, width, height, fill,
          line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    shp = slide.shapes.add_shape(shape, Inches(left), Inches(top),
                                 Inches(width), Inches(height))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill

    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)

    # 기본 테마에는 그림자가 켜져 있어 지저분해 보인다. 테마 참조를 떼어내 그림자를 없앤다.
    shp.shadow.inherit = False
    style = shp._element.find(qn("p:style"))
    if style is not None:
        shp._element.remove(style)

    # 모서리 둥글기를 완만하게 (기본값은 지나치게 둥글다)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            shp.adjustments[0] = 0.06
        except Exception:
            pass

    return shp


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _header(slide, index, title, lead):
    """모든 본문 슬라이드 상단에 공통으로 들어가는 제목 영역"""
    _text(slide, 0.62, 0.42, 3, 0.28, f"{index:02d}", size=11, bold=True, color=AMBER)
    _text(slide, 0.62, 0.72, 11.5, 0.62, title, size=25, bold=True, color=NAVY)

    if lead:
        bar = _rect(slide, 0.62, 1.5, 12.1, 0.62, ICE_LIGHT, shape=MSO_SHAPE.RECTANGLE)
        bar.line.fill.background()
        _rect(slide, 0.62, 1.5, 0.05, 0.62, AMBER, shape=MSO_SHAPE.RECTANGLE)
        _text(slide, 0.85, 1.5, 11.7, 0.62, lead, size=13, bold=True,
              color=NAVY, anchor=MSO_ANCHOR.MIDDLE)


# ============================================================
# 5. 슬라이드 종류별 레이아웃
# ============================================================
def _title_slide(prs, topic, subtitle):
    slide = _blank(prs)

    _rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY_DARK, shape=MSO_SHAPE.RECTANGLE)
    _rect(slide, 9.6, -1.5, 5.6, 5.6, NAVY_MID, shape=MSO_SHAPE.OVAL)
    _rect(slide, 11.2, 4.6, 3.2, 3.2, NAVY, shape=MSO_SHAPE.OVAL)

    _text(slide, 0.85, 2.25, 10, 0.32, "OO UNIVERSITY · 강의자료",
          size=12, bold=True, color=AMBER)
    _text(slide, 0.85, 2.7, 10.5, 1.1, topic, size=36, bold=True, color=WHITE)
    _text(slide, 0.85, 3.9, 10.5, 0.5, subtitle, size=15, color=ICE)

    _rect(slide, 0.85, 4.7, 1.6, 0.045, AMBER, shape=MSO_SHAPE.RECTANGLE)


def _agenda_slide(prs, slides):
    """목차 — 본문이 3장 이상일 때만 넣는다."""
    slide = _blank(prs)
    _rect(slide, 0, 0, SLIDE_W, SLIDE_H, LIGHT, shape=MSO_SHAPE.RECTANGLE)

    _text(slide, 0.62, 0.42, 3, 0.28, "CONTENTS", size=11, bold=True, color=AMBER)
    _text(slide, 0.62, 0.72, 11.5, 0.62, "목차", size=25, bold=True, color=NAVY)

    top = 1.75
    for i, s in enumerate(slides, start=1):
        _rect(slide, 0.62, top, 12.1, 0.78, WHITE, line=LINE)
        _rect(slide, 0.62, top, 0.06, 0.78, NAVY, shape=MSO_SHAPE.RECTANGLE)
        _text(slide, 0.95, top, 0.7, 0.78, f"{i:02d}", size=15, bold=True,
              color=ICE, anchor=MSO_ANCHOR.MIDDLE)
        _text(slide, 1.7, top, 10.7, 0.78, s["title"], size=14, bold=True,
              color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
        top += 0.92


def _image_slide(prs, index, data, image_bytes, kind):
    """왼쪽 본문 + 오른쪽 그림 배치"""
    slide = _blank(prs)
    _header(slide, index, data["title"], data["lead"])

    # --- 왼쪽 본문 (그림 높이에 맞춰 세로 가운데로 모은다) ---
    bullets = data["bullets"][:4]
    card_h, gap = 0.92, 0.13
    total = len(bullets) * card_h + max(len(bullets) - 1, 0) * gap
    top = 2.45 + (3.9 - total) / 2

    for bullet in bullets:
        _rect(slide, 0.62, top, 6.5, card_h, WHITE, line=LINE)
        _rect(slide, 0.62, top, 0.055, card_h, AMBER, shape=MSO_SHAPE.RECTANGLE)
        _text(slide, 0.92, top + 0.06, 6.0, card_h - 0.12, bullet, size=12,
              color=TEXT, anchor=MSO_ANCHOR.MIDDLE, spacing=1.15)
        top += card_h + gap

    # --- 오른쪽 그림 ---
    frame_left, frame_top, frame_w, frame_h = 7.35, 2.45, 5.35, 3.9
    _rect(slide, frame_left, frame_top, frame_w, frame_h, WHITE, line=LINE)

    try:
        stream = io.BytesIO(image_bytes)
        pic = slide.shapes.add_picture(stream, Inches(frame_left + 0.18),
                                       Inches(frame_top + 0.18),
                                       width=Inches(frame_w - 0.36))

        # 세로가 넘치면 높이 기준으로 다시 맞춘다.
        max_h = Inches(frame_h - 0.36)
        if pic.height > max_h:
            ratio = pic.width / pic.height
            pic.height = int(max_h)
            pic.width = int(max_h * ratio)

        # 액자 안에서 가운데 정렬
        pic.left = Inches(frame_left) + (Inches(frame_w) - pic.width) // 2
        pic.top = Inches(frame_top) + (Inches(frame_h) - pic.height) // 2

    except Exception:
        _text(slide, frame_left, frame_top + 1.7, frame_w, 0.4,
              "이미지를 불러오지 못했습니다", size=11, color=GRAY,
              align=PP_ALIGN.CENTER)

    label = {
        "그림": "자료에서 가져온 도표",
        "페이지": "근거 페이지 미리보기",
    }.get(kind, "")
    _text(slide, frame_left, frame_top + frame_h + 0.12, frame_w, 0.3,
          label, size=9, color=GRAY, align=PP_ALIGN.CENTER)

    _footer(slide, data["source"])


def _card_slide(prs, index, data):
    """그림이 없을 때 — 본문을 카드 격자로 배치해 여백을 채운다."""
    slide = _blank(prs)
    _header(slide, index, data["title"], data["lead"])

    bullets = data["bullets"][:4]
    if not bullets:
        return

    # 본문에 쓸 수 있는 세로 구간 (머리말 아래 ~ 출처 위)
    area_top, area_bottom = 2.45, 6.6

    if len(bullets) <= 2:
        # 가로로 넓은 카드. 개수가 적으면 세로 가운데로 모아 여백을 줄인다.
        card_h, gap = 1.5, 0.3
        total = len(bullets) * card_h + (len(bullets) - 1) * gap
        top = area_top + (area_bottom - area_top - total) / 2

        for i, bullet in enumerate(bullets, start=1):
            _rect(slide, 0.62, top, 12.1, card_h, WHITE, line=LINE)
            _rect(slide, 0.62, top, 0.06, card_h, NAVY, shape=MSO_SHAPE.RECTANGLE)
            _badge(slide, 0.95, top + (card_h - 0.42) / 2, i)
            _text(slide, 1.75, top + 0.15, 10.6, card_h - 0.3, bullet, size=15,
                  color=TEXT, anchor=MSO_ANCHOR.MIDDLE, spacing=1.3)
            top += card_h + gap

    elif len(bullets) == 3:
        # 3개는 세로로 쌓는다. 2열로 하면 한 칸이 비어 균형이 깨진다.
        card_h, gap = 1.1, 0.25
        total = 3 * card_h + 2 * gap
        top = area_top + (area_bottom - area_top - total) / 2

        for i, bullet in enumerate(bullets, start=1):
            _rect(slide, 0.62, top, 12.1, card_h, WHITE, line=LINE)
            _rect(slide, 0.62, top, 0.06, card_h, AMBER if i % 2 == 0 else NAVY,
                  shape=MSO_SHAPE.RECTANGLE)
            _badge(slide, 0.95, top + (card_h - 0.42) / 2, i)
            _text(slide, 1.75, top + 0.12, 10.6, card_h - 0.24, bullet, size=14,
                  color=TEXT, anchor=MSO_ANCHOR.MIDDLE, spacing=1.3)
            top += card_h + gap

    else:
        # 4개는 2열 격자
        card_h = 1.85
        gap_y = 0.3
        row_top = area_top + (area_bottom - area_top - (2 * card_h + gap_y)) / 2
        positions = [
            (0.62, row_top), (6.85, row_top),
            (0.62, row_top + card_h + gap_y), (6.85, row_top + card_h + gap_y),
        ]
        for i, bullet in enumerate(bullets):
            x, y = positions[i]
            _rect(slide, x, y, 5.87, card_h, WHITE, line=LINE)
            _rect(slide, x, y, 0.06, card_h, AMBER if i % 2 else NAVY,
                  shape=MSO_SHAPE.RECTANGLE)
            _badge(slide, x + 0.33, y + 0.32, i + 1)
            _text(slide, x + 0.33, y + 0.92, 5.2, 0.8, bullet, size=13,
                  color=TEXT, spacing=1.3)

    _footer(slide, data["source"])


def _badge(slide, left, top, number):
    circle = _rect(slide, left, top, 0.42, 0.42, NAVY, shape=MSO_SHAPE.OVAL)
    frame = circle.text_frame
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = str(number)
    run.font.name = FONT
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = WHITE


def _footer(slide, source):
    if not source:
        return
    _rect(slide, 0.62, 6.78, 12.1, 0.02, LINE, shape=MSO_SHAPE.RECTANGLE)
    _text(slide, 0.62, 6.9, 12.1, 0.3, f"출처 · {source}", size=9, color=GRAY)


def _closing_slide(prs, topic):
    slide = _blank(prs)
    _rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY_DARK, shape=MSO_SHAPE.RECTANGLE)
    _rect(slide, 9.9, -1.4, 5.4, 5.4, NAVY_MID, shape=MSO_SHAPE.OVAL)

    _text(slide, 0.85, 3.0, 10, 0.7, "정리", size=30, bold=True, color=WHITE)
    _text(slide, 0.85, 3.8, 10, 0.5,
          f"본 자료는 학내 등록 자료를 근거로 자동 생성된 {topic} 강의 초안입니다.",
          size=13, color=ICE)
    _text(slide, 0.85, 4.25, 10, 0.5,
          "각 슬라이드 하단의 출처에서 원문을 확인하실 수 있습니다.",
          size=13, color=ICE)


# ============================================================
# 6. 전체 조립
# ============================================================
def build_pptx(topic, slides, pdf_store=None, log=None):
    """슬라이드 목록을 pptx 파일(바이트)로 만들어 반환한다.

    pdf_store : {파일명: PDF 바이트} — 근거 페이지의 그림을 가져오는 데 사용한다.
    log       : 슬라이드별 처리 결과를 담을 리스트 (선택).

    그림 우선순위
      1. 자료에 실제로 삽입된 도표
      2. 근거 페이지 썸네일
      3. 둘 다 없으면 카드형 레이아웃

    그림은 모두 자료에서 가져온다. AI로 이미지를 생성하지 않는 이유는
    자료에 없는 그림을 강의자료에 넣으면 '근거 기반'이라는 설계 원칙이 깨지기 때문이다.
    """
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    _title_slide(prs, topic, "학내 자료 기반 강의 슬라이드 · AI 생성 초안")

    if len(slides) >= 3:
        _agenda_slide(prs, slides)

    for i, data in enumerate(slides, start=1):
        image_bytes, kind = None, None
        note = ""

        file_name, page_no = _parse_source(data.get("source", ""))
        has_pdf = bool(pdf_store and file_name and page_no and file_name in pdf_store)

        # [1] 자료에 실제로 삽입된 도표를 먼저 찾는다.
        if has_pdf:
            image_bytes, kind = extract_page_image(
                pdf_store[file_name], page_no, allow_page_render=False
            )
            if image_bytes:
                note = "자료 도표 사용"

        # [2] 도표가 없으면 근거 페이지 썸네일을 쓴다.
        if image_bytes is None and has_pdf:
            image_bytes, kind = extract_page_image(
                pdf_store[file_name], page_no, allow_page_render=True
            )
            if image_bytes:
                note = "페이지 썸네일 사용"

        if log is not None:
            log.append(f"{i}. {data['title']} — {note or '그림 없음 (카드형)'}")

        if image_bytes:
            _image_slide(prs, i, data, image_bytes, kind)
        else:
            _card_slide(prs, i, data)

    _closing_slide(prs, topic)

    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
