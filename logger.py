"""사용 기록 로깅.

무엇을 왜 기록하는가
  - 임계값 0.7의 근거를 만들기 위해서다. 실제 질문들의 거리 값이 쌓이면
    "정상 질문은 대체로 얼마, 차단된 질문은 얼마"를 숫자로 말할 수 있다.
  - 어떤 질문이 잘못 차단됐는지(오탐) 찾아 프롬프트와 임계값을 조정하기 위해서다.
  - 응답 시간을 측정해 느린 구간을 찾기 위해서다.

기록 위치: data/usage_log.csv
개인정보가 될 수 있는 질문 원문이 남으므로, 저장소에 커밋하지 않는다(.gitignore).
"""

import csv
import os
from datetime import datetime

LOG_DIR = "data"
LOG_PATH = os.path.join(LOG_DIR, "usage_log.csv")

FIELDS = [
    "시각",
    "사용자",
    "역할",
    "기능",         # 질의응답 / 문항 생성 / 슬라이드 ...
    "질문",
    "재작성",       # 멀티턴으로 다시 쓴 질문 (없으면 빈칸)
    "차단",         # Y / N
    "사유",
    "거리",         # 검색 최상위 거리 값
    "출처수",
    "응답시간",     # 초
]


def log(user_id, role, feature, question, result, elapsed):
    """한 건의 사용 기록을 남긴다. 실패해도 앱 동작을 막지 않는다."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        is_new = not os.path.exists(LOG_PATH)

        score = result.get("best_score")

        row = {
            "시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "사용자": user_id,
            "역할": role,
            "기능": feature,
            "질문": (question or "").replace("\n", " ")[:200],
            "재작성": result.get("rewritten") or "",
            "차단": "Y" if result.get("blocked") else "N",
            "사유": result.get("reason") or "",
            "거리": f"{score:.4f}" if isinstance(score, (int, float)) else "",
            "출처수": len(result.get("sources") or []),
            "응답시간": f"{elapsed:.2f}",
        }

        # newline=""은 윈도우에서 빈 줄이 끼는 것을 막는다.
        with open(LOG_PATH, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)

    except Exception:
        # 로깅 실패로 사용자 요청이 중단되면 안 된다.
        pass


def read_logs():
    """기록을 전부 읽어 리스트로 돌려준다."""
    if not os.path.exists(LOG_PATH):
        return []

    try:
        with open(LOG_PATH, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def summarize(rows):
    """대시보드에 보여줄 지표를 계산한다."""
    total = len(rows)
    if total == 0:
        return None

    blocked = [r for r in rows if r.get("차단") == "Y"]
    passed = [r for r in rows if r.get("차단") == "N"]

    def to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    pass_scores = [s for s in (to_float(r.get("거리")) for r in passed) if s is not None]
    block_scores = [s for s in (to_float(r.get("거리")) for r in blocked) if s is not None]
    times = [t for t in (to_float(r.get("응답시간")) for r in rows) if t is not None]

    def stats(values):
        if not values:
            return None
        return {
            "건수": len(values),
            "최소": min(values),
            "평균": sum(values) / len(values),
            "최대": max(values),
        }

    features = {}
    for r in rows:
        features[r.get("기능", "?")] = features.get(r.get("기능", "?"), 0) + 1

    return {
        "총건수": total,
        "차단건수": len(blocked),
        "차단율": len(blocked) / total * 100,
        "재작성건수": sum(1 for r in rows if r.get("재작성")),
        "평균응답시간": sum(times) / len(times) if times else 0,
        "통과거리": stats(pass_scores),
        "차단거리": stats(block_scores),
        "기능별": features,
    }


def clear():
    """기록을 지운다."""
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
