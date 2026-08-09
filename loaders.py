"""문서 포맷별 텍스트 추출.

PDF 외에 PPTX·DOCX·TXT를 지원한다. 1주차 기획서에 명시된 포맷이다.

출처 표기를 유지하기 위해 포맷마다 '위치'를 페이지 번호처럼 다룬다.
    PDF   페이지 번호
    PPTX  슬라이드 번호
    DOCX  문단 묶음 번호 (문서에 페이지 개념이 없음)
    TXT   줄 묶음 번호
"""

import os

from langchain_core.documents import Document

SUPPORTED = ["pdf", "pptx", "docx", "txt", "md"]

# DOCX·TXT는 페이지가 없어 일정 분량마다 위치 번호를 올린다.
CHARS_PER_UNIT = 1500


def _pdf(path):
    import fitz

    docs = []
    with fitz.open(path) as pdf:
        for i, page in enumerate(pdf):
            text = page.get_text().strip()
            if text:
                docs.append(Document(page_content=text, metadata={"page": i}))
    return docs


def _pptx(path):
    from pptx import Presentation

    docs = []
    prs = Presentation(path)

    for i, slide in enumerate(prs.slides):
        parts = []

        for shape in slide.shapes:
            # 도형 안의 글자
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(text)

            # 표는 셀을 줄 단위로 붙인다.
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))

        # 발표자 노트도 강의 내용이므로 함께 담는다.
        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text.strip()
            if note:
                parts.append(f"[발표자 노트] {note}")

        if parts:
            docs.append(Document(page_content="\n".join(parts),
                                 metadata={"page": i}))
    return docs


def _docx(path):
    import docx

    document = docx.Document(path)
    blocks = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    # 표 내용도 포함한다.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))

    return _group(blocks)


def _txt(path):
    for encoding in ("utf-8", "utf-8-sig", "cp949"):
        try:
            with open(path, encoding=encoding) as f:
                blocks = [line.strip() for line in f if line.strip()]
            return _group(blocks)
        except UnicodeDecodeError:
            continue

    raise ValueError("텍스트 인코딩을 인식하지 못했습니다.")


def _group(blocks):
    """페이지가 없는 문서를 일정 분량 단위로 묶어 위치 번호를 붙인다."""
    docs = []
    buffer = []
    length = 0

    for block in blocks:
        buffer.append(block)
        length += len(block)

        if length >= CHARS_PER_UNIT:
            docs.append(Document(page_content="\n".join(buffer),
                                 metadata={"page": len(docs)}))
            buffer, length = [], 0

    if buffer:
        docs.append(Document(page_content="\n".join(buffer),
                             metadata={"page": len(docs)}))

    return docs


LOADERS = {
    "pdf": _pdf,
    "pptx": _pptx,
    "docx": _docx,
    "txt": _txt,
    "md": _txt,
}


def extension(file_name):
    return os.path.splitext(file_name)[1].lower().lstrip(".")


def load(path, file_name):
    """파일에서 텍스트를 추출해 Document 목록으로 돌려준다."""
    ext = extension(file_name)

    loader = LOADERS.get(ext)
    if loader is None:
        raise ValueError(f"지원하지 않는 형식입니다 — .{ext}")

    docs = loader(path)

    if not docs:
        raise ValueError("문서에서 텍스트를 찾지 못했습니다. "
                         "스캔 이미지로만 이루어진 파일일 수 있습니다.")

    return docs


def location_label(file_name):
    """출처에 쓸 위치 표기. 포맷마다 부르는 이름이 다르다."""
    return {
        "pdf": "p.",
        "pptx": "슬라이드 ",
        "docx": "구간 ",
        "txt": "구간 ",
        "md": "구간 ",
    }.get(extension(file_name), "p.")
