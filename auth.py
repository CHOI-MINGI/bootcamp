"""로그인 및 역할 판정.

두 가지 로그인 방식을 함께 제공한다.

  1) 구글 로그인 (OIDC)
     학내 SSO도 대부분 OAuth2/OIDC 기반이므로, 실제 도입 시에는
     provider 설정만 학교 것으로 바꾸면 코드는 그대로 쓸 수 있다.

  2) 테스트 계정 (아이디/비밀번호)
     시연이나 평가처럼 구글 계정을 새로 만들기 어려운 상황을 위해 남겨둔다.
     계정은 서버가 미리 발급한 것만 쓸 수 있고 가입 기능은 없다.
     실제 대학 시스템도 학생이 가입하는 것이 아니라 학교가 계정을 발급한다.

역할
    교수자 / 학습자 / 관리자
    사용자가 직접 고르게 하면 학생이 교수자를 선택해 비공개 자료를 볼 수 있으므로,
    서버가 계정 정보를 기준으로 정한다.

환경변수 (모두 선택)
    ALLOWED_EMAIL_DOMAIN  허용할 메일 도메인. 예) oo.ac.kr
    ADMIN_EMAILS          관리자 메일 목록. 쉼표 구분
    PROFESSOR_EMAILS      교수자 메일 목록. 쉼표 구분
    COURSE_MAP            메일별 과목. JSON. 예) {"a@x.com": ["EE201"]}
    DEFAULT_COURSES       위 목록에 없는 사용자에게 줄 기본 과목
    TEST_ACCOUNTS         테스트 계정. JSON.
        {"prof01": {"password": "1234", "role": "교수자", "courses": ["EE201"]}}
        비밀번호는 "sha256:<해시>" 형식도 지원한다.
"""

import hashlib
import hmac
import json
import os

import streamlit as st

ROLES = ("관리자", "교수자", "학습자")


def _env_list(name):
    return [v.strip().lower() for v in os.getenv(name, "").split(",") if v.strip()]


def _json_env(name):
    try:
        return json.loads(os.getenv(name, "{}"))
    except Exception:
        return {}


def _default_courses():
    return [c.strip() for c in os.getenv("DEFAULT_COURSES", "").split(",") if c.strip()]


# ============================================================
# 역할 판정
# ============================================================
def resolve_role(email):
    """메일 주소로 역할과 과목을 결정한다.

    판단 근거는 사용자 명부(users.json)다.
    환경변수는 명부가 비어 있을 때 초기값을 만드는 데만 쓰인다.
    """
    import users
    return users.resolve(email)


def is_domain_allowed(email):
    """허용 도메인이 지정된 경우 그 도메인만 통과시킨다."""
    domain = os.getenv("ALLOWED_EMAIL_DOMAIN", "").strip().lower()
    if not domain:
        return True
    return (email or "").lower().endswith("@" + domain)


# ============================================================
# 테스트 계정
# ============================================================
def _check_password(stored, entered):
    """비밀번호를 확인한다.

    'sha256:<해시>' 형식이면 해시로 비교하고, 아니면 그대로 비교한다.
    비교 시간이 입력값에 따라 달라지지 않도록 compare_digest를 쓴다.
    """
    stored = str(stored)

    if stored.startswith("sha256:"):
        digest = hashlib.sha256(entered.encode()).hexdigest()
        return hmac.compare_digest(stored[7:], digest)

    return hmac.compare_digest(stored, entered)


def verify_test_account(user_id, password):
    """테스트 계정을 확인한다. 성공하면 (역할, 과목), 실패하면 None."""
    account = _json_env("TEST_ACCOUNTS").get(user_id)
    if not account:
        return None

    if not _check_password(account.get("password", ""), password):
        return None

    role = account.get("role", "학습자")
    if role not in ROLES:
        role = "학습자"

    return role, account.get("courses", _default_courses())


def _test_accounts_enabled():
    return bool(_json_env("TEST_ACCOUNTS"))


# ============================================================
# 로그인 화면
# ============================================================
def _oidc_configured():
    """구글 로그인 설정이 되어 있는지 확인한다.

    설정이 없으면 st.user 접근 자체가 예외를 내므로 미리 확인한다.
    """
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def _test_login_form():
    with st.form("test_login"):
        user_id = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if not submitted:
        return

    result = verify_test_account(user_id.strip(), password)
    if not result:
        st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
        return

    role, courses = result
    st.session_state.user_id = user_id.strip()
    st.session_state.role = role
    st.session_state.courses = courses
    st.session_state.auth_mode = "테스트"
    st.rerun()


def _login_screen(oidc_ready):
    import ui

    left, center, right = st.columns([1, 1.4, 1])

    with center:
        ui.hero("OO UNIVERSITY",
                "AI 학습 도우미",
                "학내 자료를 근거로 답하는 교수·학습 지원 서비스")

        if oidc_ready:
            st.button("Google 계정으로 로그인", type="primary",
                      use_container_width=True,
                      on_click=st.login, args=("google",))

            domain = os.getenv("ALLOWED_EMAIL_DOMAIN", "").strip()
            if domain:
                st.caption(f"{domain} 계정만 이용할 수 있습니다.")

        if _test_accounts_enabled():
            if oidc_ready:
                st.divider()
                with st.expander("테스트 계정으로 로그인"):
                    _test_login_form()
            else:
                st.caption("발급받은 계정으로 로그인하세요.")
                _test_login_form()

        if not oidc_ready and not _test_accounts_enabled():
            st.error("로그인 수단이 설정되지 않았습니다.")
            st.caption("secrets.toml의 구글 로그인 설정 또는 "
                       "TEST_ACCOUNTS 환경변수가 필요합니다.")

        st.markdown(
            '<div class="login-note">'
            '역할과 수강 과목은 계정 정보를 기준으로 자동 부여됩니다.'
            '</div>',
            unsafe_allow_html=True,
        )


# ============================================================
# 진입점
# ============================================================
def require_login():
    """로그인되어 있지 않으면 로그인 화면을 띄우고 실행을 멈춘다.

    로그인 성공 시 session_state에 user_id / role / courses를 채운다.
    """
    if st.session_state.get("user_id"):
        return

    oidc_ready = _oidc_configured()

    # 구글 로그인을 이미 마친 상태라면 그 정보로 세션을 채운다.
    if oidc_ready and st.user.is_logged_in:
        email = st.user.email

        if not is_domain_allowed(email):
            st.error(f"허용되지 않은 계정입니다 — {email}")
            st.caption(f"{os.getenv('ALLOWED_EMAIL_DOMAIN')} 계정으로 다시 로그인해 주세요.")
            st.button("로그아웃", on_click=st.logout)
            st.stop()

        role, courses = resolve_role(email)
        st.session_state.user_id = email
        st.session_state.role = role
        st.session_state.courses = courses
        st.session_state.auth_mode = "구글"
        return

    _login_screen(oidc_ready)
    st.stop()


def logout():
    """로그아웃한다.

    세션을 비운 뒤에도 스크립트가 계속 실행되면 이미 지워진 값을 읽다가 오류가 난다.
    st.rerun()은 즉시 실행을 중단하지만 st.logout()은 그렇지 않아, 뒤에 st.stop()을 둔다.
    """
    mode = st.session_state.get("auth_mode")
    st.session_state.clear()

    if mode == "구글":
        st.logout()
        st.stop()
    else:
        st.rerun()
