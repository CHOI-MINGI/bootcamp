"""Cloud Storage 동기화.

문제
    Cloud Run은 컨테이너가 꺼지면 파일이 초기화된다.
    등록한 자료, 인덱스, 사용자 목록, 로그가 재시작마다 사라진다.

방법
    앱이 시작될 때 버킷에서 data 폴더를 내려받고,
    내용이 바뀔 때마다 버킷으로 올린다.

    데이터베이스를 붙이는 것보다 단순하고, 파일 그대로 다루므로
    기존 코드(storage.py, logger.py)를 거의 바꾸지 않아도 된다.

    다만 여러 인스턴스가 동시에 쓰면 나중에 올린 쪽이 이긴다.
    파일럿 규모에서는 문제되지 않지만, 운영 단계에서는 pgvector 같은
    공유 저장소로 옮겨야 한다.

환경변수
    GCS_BUCKET   사용할 버킷 이름. 없으면 동기화하지 않고 로컬 파일만 쓴다.
    GCS_PREFIX   버킷 안 경로. 기본 'app-data'
"""

import os

DATA_DIR = "data"


def bucket_name():
    return os.getenv("GCS_BUCKET", "").strip()


def enabled():
    return bool(bucket_name())


def _prefix():
    return os.getenv("GCS_PREFIX", "app-data").strip("/")


def _client_bucket():
    from google.cloud import storage as gcs

    client = gcs.Client()
    return client.bucket(bucket_name())


def _blob_path(local_path):
    """로컬 경로를 버킷 안 경로로 바꾼다."""
    rel = os.path.relpath(local_path, DATA_DIR).replace(os.sep, "/")
    return f"{_prefix()}/{rel}"


# ============================================================
# 내려받기 / 올리기
# ============================================================
def download():
    """버킷의 내용을 로컬 data 폴더로 가져온다.

    반환: (가져온 파일 수, 오류 메시지)
    """
    if not enabled():
        return 0, None

    try:
        bucket = _client_bucket()
        count = 0

        for blob in bucket.list_blobs(prefix=_prefix() + "/"):
            if blob.name.endswith("/"):
                continue

            rel = blob.name[len(_prefix()) + 1:]
            local_path = os.path.join(DATA_DIR, *rel.split("/"))

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            blob.download_to_filename(local_path)
            count += 1

        return count, None

    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def upload():
    """로컬 data 폴더의 내용을 버킷으로 올린다.

    반환: (올린 파일 수, 오류 메시지)
    """
    if not enabled():
        return 0, None

    if not os.path.isdir(DATA_DIR):
        return 0, None

    try:
        bucket = _client_bucket()
        count = 0
        local_names = set()

        for root, _dirs, files in os.walk(DATA_DIR):
            for name in files:
                local_path = os.path.join(root, name)
                blob_path = _blob_path(local_path)
                local_names.add(blob_path)

                bucket.blob(blob_path).upload_from_filename(local_path)
                count += 1

        # 로컬에서 지운 파일은 버킷에서도 지운다.
        # 이렇게 하지 않으면 삭제한 자료가 재시작 때 되살아난다.
        for blob in bucket.list_blobs(prefix=_prefix() + "/"):
            if blob.name not in local_names:
                blob.delete()

        return count, None

    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"
