"""등록한 자료를 디스크에 저장하고 다시 불러오는 기능.

지금까지는 FAISS 인덱스가 메모리에만 있어서 앱을 껐다 켜면 자료가 전부 사라졌다.
매번 다시 업로드하고 임베딩해야 하므로 시간과 API 호출이 낭비되고,
배포 환경에서는 "실사용 가능한 서비스"라고 하기 어렵다.

저장 구조
    data/
      index/          FAISS 인덱스 (벡터 + 청크 본문)
      library.json    등록 자료 목록 (파일명·과목·공개범위·청크 수)
      pdf/            원본 PDF (슬라이드에 넣을 도표를 꺼내는 데 필요)
"""

import json
import os
import shutil

from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

import remote
from rag_module import EMBEDDING_MODEL, load_documents

DATA_DIR = "data"
INDEX_DIR = os.path.join(DATA_DIR, "index")
PDF_DIR = os.path.join(DATA_DIR, "pdf")
LIBRARY_PATH = os.path.join(DATA_DIR, "library.json")


def _embeddings():
    return GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)


def _safe_name(file_name):
    """파일명을 저장용으로 다듬는다. 경로 구분자가 섞이면 엉뚱한 곳에 쓰일 수 있다."""
    return file_name.replace("/", "_").replace("\\", "_")


# ============================================================
# 저장
# ============================================================
def save_all(vectorstore, library, pdf_store):
    """현재 상태를 디스크에 저장한다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    if vectorstore is not None:
        vectorstore.save_local(INDEX_DIR)

    _save_library(library)

    # 원본 파일은 슬라이드에 도표를 넣을 때와 인덱스 재생성에 필요하므로 함께 보관한다.
    for name, data in pdf_store.items():
        path = os.path.join(PDF_DIR, _safe_name(name))
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)

    remote.upload()


# ============================================================
# 불러오기
# ============================================================
def load_all():
    """저장된 자료를 불러온다.

    Cloud Storage가 설정되어 있으면 먼저 버킷에서 내려받는다.
    Cloud Run은 재시작 시 파일이 초기화되므로 이 단계가 없으면 자료가 사라진다.

    반환: (vectorstore, library, pdf_store)
          저장된 것이 없으면 (None, [], {})
    """
    remote.download()

    if not os.path.exists(LIBRARY_PATH) or not os.path.isdir(INDEX_DIR):
        return None, [], {}

    try:
        with open(LIBRARY_PATH, encoding="utf-8") as f:
            library = json.load(f)

        # allow_dangerous_deserialization: FAISS 인덱스는 pickle로 저장된다.
        # 우리가 직접 만든 파일만 읽으므로 안전하다.
        vectorstore = FAISS.load_local(
            INDEX_DIR, _embeddings(), allow_dangerous_deserialization=True
        )

        pdf_store = {}
        for item in library:
            path = os.path.join(PDF_DIR, _safe_name(item["file"]))
            if os.path.exists(path):
                with open(path, "rb") as f:
                    pdf_store[item["file"]] = f.read()

        return vectorstore, library, pdf_store

    except Exception:
        # 저장 형식이 바뀌었거나 파일이 깨진 경우, 빈 상태로 시작한다.
        return None, [], {}


# ============================================================
# 삭제
# ============================================================
def delete_document(vectorstore, file_name, library, pdf_store):
    """자료 하나를 목록과 인덱스에서 제거한다.

    해당 파일의 청크만 골라 지운다. 전체를 다시 만들지 않으므로
    자료가 많아져도 삭제 시간이 늘지 않는다.
    지우지 못한 경우에만 보관된 원본으로 인덱스를 다시 만든다.

    반환: (vectorstore, library, pdf_store)
    """
    library = [item for item in library if item["file"] != file_name]
    pdf_store = {k: v for k, v in pdf_store.items() if k != file_name}

    path = os.path.join(PDF_DIR, _safe_name(file_name))
    if os.path.exists(path):
        os.remove(path)

    # 남은 자료가 없으면 인덱스도 통째로 지운다.
    if not library:
        clear_index()
        remote.upload()
        return None, [], {}

    removed = _remove_file_vectors(vectorstore, file_name)

    if not removed:
        # 부분 삭제가 안 되면 보관된 원본으로 다시 만든다.
        vectorstore = rebuild_index(library, pdf_store)
    else:
        vectorstore.save_local(INDEX_DIR)
        _save_library(library)

    remote.upload()
    return vectorstore, library, pdf_store


def _remove_file_vectors(vectorstore, file_name):
    """벡터스토어에서 해당 파일의 청크만 제거한다. 성공하면 True."""
    if vectorstore is None:
        return False

    try:
        # 저장된 청크를 훑어 해당 파일에서 온 것들의 내부 id를 모은다.
        target_ids = [
            doc_id
            for doc_id in vectorstore.index_to_docstore_id.values()
            if vectorstore.docstore.search(doc_id).metadata.get("file_name") == file_name
        ]

        if not target_ids:
            return False

        vectorstore.delete(target_ids)
        return True

    except Exception:
        return False


def _save_library(library):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def clear_index():
    if os.path.isdir(INDEX_DIR):
        shutil.rmtree(INDEX_DIR)
    if os.path.exists(LIBRARY_PATH):
        os.remove(LIBRARY_PATH)


def rebuild_index(library, pdf_store, progress=None):
    """보관 중인 원본 PDF로 인덱스를 처음부터 다시 만든다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    vectorstore = None
    total = len(library)

    for i, item in enumerate(library, start=1):
        data = pdf_store.get(item["file"])
        if not data:
            continue

        if progress:
            progress(i, total, item["file"])

        # PyMuPDFLoader가 파일 경로를 받으므로 임시 파일로 저장해 사용한다.
        temp_path = os.path.join(DATA_DIR, f"_rebuild_{_safe_name(item['file'])}")
        with open(temp_path, "wb") as f:
            f.write(data)

        try:
            docs = load_documents(temp_path, item["file"],
                                  item["course"], item["visibility"])
            if vectorstore is None:
                vectorstore = FAISS.from_documents(docs, _embeddings())
            else:
                vectorstore.add_documents(docs)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    if vectorstore is not None:
        vectorstore.save_local(INDEX_DIR)

    _save_library(library)
    return vectorstore


def clear_all():
    """저장된 자료를 전부 지운다."""
    if os.path.isdir(DATA_DIR):
        shutil.rmtree(DATA_DIR)
