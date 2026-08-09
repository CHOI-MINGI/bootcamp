"""사용자 명부.

역할과 과목을 환경변수로만 관리하면 인원이 늘 때 재배포 없이는 바꿀 수 없다.
명부를 파일로 두고 관리자가 화면에서 수정하도록 한다.

저장 위치: data/users.json  (Cloud Storage 동기화 대상)

형식
    {
      "prof@oo.ac.kr": {"role": "교수자", "courses": ["EE201"]},
      "stu@oo.ac.kr":  {"role": "학습자", "courses": ["EE201"]}
    }

환경변수(ADMIN_EMAILS, PROFESSOR_EMAILS, COURSE_MAP)는 명부가 비어 있을 때
초기값을 만드는 용도로만 쓴다. 첫 실행 시 한 번 명부로 옮겨진다.
"""

import json
import os

import remote

DATA_DIR = "data"
USERS_PATH = os.path.join(DATA_DIR, "users.json")

ROLES = ("관리자", "교수자", "학습자")


def _env_list(name):
    return [v.strip().lower() for v in os.getenv(name, "").split(",") if v.strip()]


def _default_courses():
    return [c.strip() for c in os.getenv("DEFAULT_COURSES", "").split(",") if c.strip()]


# ============================================================
# 읽기 / 쓰기
# ============================================================
def load():
    """명부를 읽는다. 없으면 환경변수로 초기 명부를 만든다."""
    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return _seed_from_env()


def save(users):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    remote.upload()


def _seed_from_env():
    """첫 실행 시 환경변수 설정을 명부로 옮긴다."""
    try:
        course_map = {k.lower(): v for k, v in
                      json.loads(os.getenv("COURSE_MAP", "{}")).items()}
    except Exception:
        course_map = {}

    users = {}

    for email in _env_list("PROFESSOR_EMAILS"):
        users[email] = {"role": "교수자",
                        "courses": course_map.get(email, _default_courses())}

    # 관리자를 나중에 넣어 교수자 목록과 겹칠 경우 관리자가 이긴다.
    for email in _env_list("ADMIN_EMAILS"):
        users[email] = {"role": "관리자",
                        "courses": course_map.get(email, _default_courses())}

    if users:
        save(users)

    return users


# ============================================================
# 조회 / 수정
# ============================================================
def resolve(email):
    """메일 주소로 역할과 과목을 찾는다. 명부에 없으면 학습자."""
    email = (email or "").lower()
    entry = load().get(email)

    if not entry:
        return "학습자", _default_courses()

    role = entry.get("role", "학습자")
    if role not in ROLES:
        role = "학습자"

    return role, entry.get("courses", _default_courses())


def upsert(email, role, courses):
    """사용자를 추가하거나 수정한다."""
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("메일 주소를 입력해 주세요.")
    if role not in ROLES:
        raise ValueError("역할이 올바르지 않습니다.")

    users = load()
    users[email] = {"role": role, "courses": courses}
    save(users)
    return users


def remove(email, actor_email):
    """사용자를 삭제한다. 마지막 관리자와 본인은 지울 수 없다."""
    email = (email or "").lower()
    users = load()

    if email not in users:
        return users

    if email == (actor_email or "").lower():
        raise ValueError("본인 계정은 삭제할 수 없습니다.")

    admins = [e for e, v in users.items() if v.get("role") == "관리자"]
    if users[email].get("role") == "관리자" and len(admins) <= 1:
        raise ValueError("마지막 관리자는 삭제할 수 없습니다.")

    del users[email]
    save(users)
    return users
