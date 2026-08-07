import streamlit as st
import os
import re
import time
import uuid

# 배포 환경에서는 .env 파일이 없고 API 키를 플랫폼이 따로 관리한다.
# Streamlit Secrets에 키가 있으면 환경변수로 옮겨, 로컬(.env)과 같은 방식으로 읽히게 한다.
# 다른 모듈을 불러오기 전에 처리해야 한다.
try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except Exception:
    # Secrets가 설정되지 않은 로컬 환경에서는 그냥 넘어간다.
    pass

import ui
import storage
import logger
from rag_module import (load_documents, add_documents, create_rag_chain,
                        ask, generate, TASK_PROMPTS, SIMILARITY_THRESHOLD)
from slides import generate_slide_data, build_pptx

st.set_page_config(
    page_title="OO대학교 AI 학습 도우미",
    page_icon="🎓",
    layout="wide",
)
ui.inject_css()


# ============================================================
# 0. 로그인 (3주차에 학내 SSO로 대체 예정)
# ============================================================
def login_screen():
    left, center, right = st.columns([1, 1.4, 1])

    with center:
        ui.hero(
            "OO UNIVERSITY",
            "AI 학습 도우미",
            "학내 자료를 근거로 답하는 교수·학습 지원 서비스",
        )

        with st.form("login"):
            user_id = st.text_input("아이디", placeholder="학번 또는 교번")
            role = st.radio("구분", ["학습자", "교수자"], horizontal=True)
            courses = st.text_input(
                "수강(담당) 과목 코드",
                placeholder="예: EE201, EE305",
                help="쉼표로 구분해 입력하세요. 실제 서비스에서는 학사 시스템에서 자동으로 가져옵니다.",
            )
            submitted = st.form_submit_button("로그인", use_container_width=True)

        if submitted:
            if not user_id.strip():
                st.error("아이디를 입력해 주세요.")
            else:
                st.session_state.user_id = user_id.strip()
                st.session_state.role = role
                st.session_state.courses = [
                    c.strip() for c in courses.split(",") if c.strip()
                ]
                st.rerun()

        st.markdown(
            '<div class="login-note">'
            '프로토타입 단계이므로 비밀번호 확인은 생략했습니다.<br>'
            '실제 서비스에서는 학내 SSO(OAuth2)로 로그인하고, 수강 과목은 학사 시스템과 연동됩니다.'
            '</div>',
            unsafe_allow_html=True,
        )


if "user_id" not in st.session_state:
    login_screen()
    st.stop()


# 세션 상태 초기화
st.session_state.setdefault("messages", [])

# 디스크에 저장된 자료를 불러온다. 앱을 다시 켜도 등록 자료가 유지된다.
if "vectorstore" not in st.session_state:
    with st.spinner("저장된 자료를 불러오는 중입니다..."):
        vs, library, pdf_store = storage.load_all()

    st.session_state.vectorstore = vs
    st.session_state.library = library
    st.session_state.pdf_store = pdf_store   # 슬라이드 도표 추출에 원본이 필요하다

if "rag_chain" not in st.session_state:
    st.session_state.rag_chain = create_rag_chain()

ROLE = st.session_state.role
COURSES = st.session_state.courses


# ============================================================
# 1. 사이드바 : 사용자 정보 + 자료 등록
# ============================================================
with st.sidebar:
    ui.user_card(st.session_state.user_id, ROLE, COURSES)

    if st.button("로그아웃", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.header("자료 등록")

    uploaded_files = st.file_uploader(
        "PDF 파일 (여러 개 선택 가능)", type=["pdf"], accept_multiple_files=True
    )
    course_id = st.text_input("과목 코드", value="공통",
                              help="'공통'으로 두면 전교 공개 자료가 됩니다.")

    # 교수자만 비공개 자료를 올릴 수 있다.
    if ROLE == "교수자":
        visibility = st.selectbox("공개 범위", ["공개", "수강생", "교수자"])
    else:
        visibility = "공개"
        st.caption("학습자는 공개 자료만 등록할 수 있습니다.")

    if st.button("자료 등록", type="primary", use_container_width=True,
                 disabled=not uploaded_files):
        if "session_id" not in st.session_state:
            st.session_state.session_id = uuid.uuid4().hex[:8]

        for uploaded_file in uploaded_files:
            # 이미 등록된 파일은 건너뛴다.
            if any(item["file"] == uploaded_file.name
                   for item in st.session_state.library):
                st.warning(f"{uploaded_file.name} — 이미 등록됨")
                continue

            pdf_bytes = uploaded_file.getbuffer().tobytes()
            temp_path = f"temp_{st.session_state.session_id}_{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(pdf_bytes)

            try:
                with st.spinner(f"{uploaded_file.name} 분석 중..."):
                    docs = load_documents(
                        temp_path, uploaded_file.name, course_id, visibility
                    )
                    st.session_state.vectorstore = add_documents(
                        st.session_state.vectorstore, docs
                    )

                st.session_state.library.append({
                    "file": uploaded_file.name,
                    "course": course_id,
                    "visibility": visibility,
                    "chunks": len(docs),
                })
                # 슬라이드 생성 시 근거 페이지의 도표를 가져오기 위해 원본을 보관한다.
                st.session_state.pdf_store[uploaded_file.name] = pdf_bytes
                st.success(f"{uploaded_file.name} — {len(docs)}개 청크")

            except Exception as e:
                st.error(f"{uploaded_file.name} 분석 실패. "
                         "스캔 이미지 PDF이거나 파일이 손상되었을 수 있습니다.")
                st.caption(f"원인: {type(e).__name__} - {e}")

            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        # 등록이 끝나면 디스크에 저장해 다음 실행에서도 쓸 수 있게 한다.
        storage.save_all(st.session_state.vectorstore,
                         st.session_state.library,
                         st.session_state.pdf_store)

    # 등록된 자료 목록
    if st.session_state.library:
        st.divider()
        st.caption(f"등록된 자료 {len(st.session_state.library)}건")

        for item in st.session_state.library:
            ui.doc_item(item["file"], item["course"],
                        item["visibility"], item["chunks"])

            # 교수자만 자료를 지울 수 있다.
            if ROLE == "교수자":
                if st.button("삭제", key=f"del_{item['file']}",
                             use_container_width=True):
                    with st.spinner(f"{item['file']} 삭제 후 인덱스를 다시 만드는 중..."):
                        vs, library, pdf_store = storage.delete_document(
                            item["file"],
                            st.session_state.library,
                            st.session_state.pdf_store,
                        )
                    st.session_state.vectorstore = vs
                    st.session_state.library = library
                    st.session_state.pdf_store = pdf_store
                    st.rerun()


# ============================================================
# 2. 상단 배너
# ============================================================
ui.hero(
    f"OO UNIVERSITY · {ROLE} 모드",
    "AI 학습 도우미",
    "등록된 학내 자료만을 근거로 답변하며, 근거가 없으면 답하지 않습니다.",
)

if st.session_state.vectorstore is None:
    st.info("왼쪽 사이드바에서 PDF 자료를 등록하면 시작됩니다.")
    st.stop()


# ============================================================
# 3. 공통 함수
# ============================================================
def show_result(result):
    """생성 결과를 화면에 출력한다. 차단된 경우 경고로 표시한다."""
    if result["blocked"]:
        st.warning(f"⚠️ {result['answer']}")
        return

    with st.container(border=True):
        st.markdown(result["answer"])

    if result["sources"]:
        ui.sources(result["sources"])


def recent_history(limit=2):
    """후속 질문 재작성에 넘길 최근 대화를 (질문, 답변) 쌍으로 만든다."""
    messages = st.session_state.messages
    pairs = []

    for i in range(len(messages) - 1):
        if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
            pairs.append((messages[i]["content"], messages[i + 1]["content"]))

    return pairs[-limit:]


def chat_tab():
    """질의응답 탭 — 교수자·학습자 공통"""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("질문을 입력하세요"):
        history = recent_history()          # 질문을 기록하기 전에 가져온다

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("답변 생성 중..."):
                started = time.time()
                result = ask(
                    st.session_state.vectorstore,
                    st.session_state.rag_chain,
                    prompt,
                    role=ROLE,
                    courses=COURSES,
                    history=history,
                )
                logger.log(st.session_state.user_id, ROLE, "질의응답",
                           prompt, result, time.time() - started)

            # 후속 질문을 다시 쓴 경우, 무엇으로 검색했는지 보여준다.
            if result.get("rewritten"):
                st.caption(f"이전 대화를 반영해 다음으로 검색했습니다 — "
                           f"「{result['rewritten']}」")

            if result["blocked"]:
                response = f"⚠️ {result['answer']}"
            else:
                response = result["answer"]
                if result["sources"]:
                    response += "\n\n---\n\n**참조한 자료**\n\n"
                    response += "\n".join(f"- {s}" for s in result["sources"])

            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})


EXAMPLE_HINTS = {
    "quiz": "예: 계산 문제 위주로 / 각 문항에 실무 사례를 덧붙여 주세요",
    "syllabus": "예: 매 주차에 과제를 하나씩 넣어 주세요 / 중간고사를 8주차에 배치",
    "summary": "예: 전공 용어는 영어를 함께 표기해 주세요",
    "practice": "예: 계산 과정을 단계별로 보여 주세요",
    "review": "예: 비슷한 유형의 문제를 하나 더 제시해 주세요",
    "slide": "예: 도입부에 학습 목표 슬라이드를 넣어 주세요 / 문장을 더 짧게",
}


def prompt_controls(task):
    """생성 방향을 교수자가 조정할 수 있는 영역.

    두 가지 방법을 제공한다.
      1) 추가 지시사항 — 기본 지시문은 그대로 두고 요청만 덧붙인다. (권장)
      2) 지시문 직접 편집 — 기본 지시문 자체를 바꾼다. (고급)
    """
    extra_key = f"{task}_extra"
    tpl_key = f"{task}_tpl"

    with st.expander("생성 방향 조정"):
        extra = st.text_area(
            "추가 지시사항",
            key=extra_key,
            placeholder=EXAMPLE_HINTS.get(task, ""),
            height=80,
            help="기본 지시문에 덧붙일 요청을 자유롭게 적으세요. "
                 "단, 자료에 없는 내용을 만들라는 요청은 규칙상 반영되지 않습니다.",
        )

        # 슬라이드 생성은 JSON 형식을 지켜야 해서 지시문 편집을 제공하지 않는다.
        if task == "slide":
            return extra, None

        st.divider()
        st.caption("기본 지시문 직접 편집 (고급)")

        default = TASK_PROMPTS[task]
        current = st.session_state.get(tpl_key, default)

        edited = st.text_area(
            "지시문",
            value=current,
            key=f"{tpl_key}_input",
            height=150,
            label_visibility="collapsed",
        )

        # 중괄호 항목은 화면 입력값이 채워지는 자리이므로 지우면 안 된다.
        placeholders = re.findall(r"\{(\w+)\}", default)
        st.caption("중괄호 항목은 유지해야 합니다 · " +
                   " ".join(f"`{{{p}}}`" for p in placeholders))

        c1, c2 = st.columns(2)

        if c1.button("지시문 저장", key=f"{tpl_key}_save", use_container_width=True):
            missing = [p for p in placeholders if f"{{{p}}}" not in edited]
            if missing:
                st.error("다음 항목이 빠졌습니다: " +
                         ", ".join(f"{{{m}}}" for m in missing))
            else:
                st.session_state[tpl_key] = edited
                st.success("저장되었습니다. 이 세션 동안 적용됩니다.")

        if c2.button("기본값으로 되돌리기", key=f"{tpl_key}_reset",
                     use_container_width=True):
            st.session_state.pop(tpl_key, None)
            st.rerun()

        if tpl_key in st.session_state:
            st.info("사용자 지시문이 적용 중입니다.")

    return extra, st.session_state.get(tpl_key)


FEATURE_NAMES = {
    "quiz": "문항 생성",
    "syllabus": "강의계획서",
    "summary": "핵심 요약",
    "practice": "예상 문제",
    "review": "오답 설명",
}


def run_generation(task, spinner_text, extra="", template=None, **params):
    """생성 버튼을 눌렀을 때 공통으로 수행되는 처리"""
    if not params.get("topic", "").strip():
        st.error("주제를 입력해 주세요.")
        return

    with st.spinner(spinner_text):
        started = time.time()
        result = generate(
            st.session_state.vectorstore, task,
            role=ROLE, courses=COURSES,
            extra=extra, template=template, **params
        )
        logger.log(st.session_state.user_id, ROLE,
                   FEATURE_NAMES.get(task, task),
                   params.get("topic", ""), result, time.time() - started)

    show_result(result)


# ============================================================
# 4. 역할별 화면
# ============================================================
def dashboard_tab():
    """로그를 바탕으로 운영 지표를 보여준다."""
    ui.section("이용 현황",
               "기록된 사용 로그를 집계합니다. 임계값 조정과 성능 점검에 사용합니다.")

    rows = logger.read_logs()
    summary = logger.summarize(rows)

    if not summary:
        st.info("아직 기록이 없습니다. 질의응답이나 생성 기능을 사용하면 쌓입니다.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 요청", f"{summary['총건수']}건")
    c2.metric("차단", f"{summary['차단건수']}건",
              f"{summary['차단율']:.1f}%")
    c3.metric("평균 응답시간", f"{summary['평균응답시간']:.2f}초")
    c4.metric("후속 질문 재작성", f"{summary['재작성건수']}건")

    st.divider()

    # 임계값의 근거가 되는 부분이다.
    st.markdown("**유사도 거리 분포**")
    st.caption(f"현재 임계값 {SIMILARITY_THRESHOLD} · "
               "통과 구간과 차단 구간이 뚜렷이 갈릴수록 임계값이 적절하다는 뜻입니다.")

    dist = []
    for label, key in [("통과", "통과거리"), ("차단", "차단거리")]:
        s = summary[key]
        if s:
            dist.append({
                "구분": label,
                "건수": s["건수"],
                "최소": round(s["최소"], 3),
                "평균": round(s["평균"], 3),
                "최대": round(s["최대"], 3),
            })

    if dist:
        st.dataframe(dist, use_container_width=True, hide_index=True)
    else:
        st.caption("거리 값이 기록된 요청이 아직 없습니다.")

    st.divider()

    st.markdown("**기능별 사용 횟수**")
    st.dataframe(
        [{"기능": k, "횟수": v} for k, v in summary["기능별"].items()],
        use_container_width=True, hide_index=True,
    )

    st.divider()

    st.markdown("**최근 기록**")
    st.dataframe(list(reversed(rows))[:30], use_container_width=True,
                 hide_index=True)

    c1, c2 = st.columns([3, 1])

    if os.path.exists(logger.LOG_PATH):
        with open(logger.LOG_PATH, "rb") as f:
            c1.download_button("전체 로그 내려받기 (CSV)", f.read(),
                               file_name="usage_log.csv", mime="text/csv")

    if c2.button("기록 지우기", use_container_width=True):
        logger.clear()
        st.rerun()


if ROLE == "교수자":
    tabs = st.tabs(["질의응답", "문항 생성", "강의계획서", "핵심 요약",
                    "강의 슬라이드", "이용 현황"])

    with tabs[0]:
        ui.section("자료 기반 질의응답",
                   "담당 과목 자료와 공개 자료에서 근거를 찾아 답변합니다.")
        chat_tab()

    with tabs[1]:
        ui.section("퀴즈·과제 문항 생성",
                   "등록된 자료를 근거로 문항과 해설을 만듭니다.")
        topic = st.text_input("주제", key="quiz_topic", placeholder="예: 옴의 법칙")
        c1, c2, c3 = st.columns(3)
        count = c1.number_input("문항 수", 1, 10, 5, key="quiz_count")
        qtype = c2.selectbox("유형", ["객관식", "서술형"], key="quiz_type")
        level = c3.selectbox("난이도", ["하", "중", "상"], key="quiz_level")
        extra, template = prompt_controls("quiz")

        if st.button("문항 생성", key="quiz_btn", type="primary"):
            run_generation("quiz", "문항을 만드는 중입니다...",
                           extra=extra, template=template,
                           topic=topic, count=count, qtype=qtype, level=level)

    with tabs[2]:
        ui.section("강의계획서 초안",
                   "자료에서 주차별 주제를 뽑아 계획서 표를 만듭니다.")
        topic = st.text_input("과목명", key="syl_topic", placeholder="예: 회로이론")
        count = st.number_input("주차 수", 1, 16, 8, key="syl_count")
        extra, template = prompt_controls("syllabus")

        if st.button("계획서 생성", key="syl_btn", type="primary"):
            run_generation("syllabus", "강의계획서를 작성하는 중입니다...",
                           extra=extra, template=template,
                           topic=topic, count=count)

    with tabs[3]:
        ui.section("강의용 핵심 요약 자료",
                   "핵심 개념을 뽑아 설명과 출처를 정리합니다.")
        topic = st.text_input("주제", key="sum_topic", placeholder="예: 3주차 전체 내용")
        count = st.number_input("핵심 개념 수", 1, 10, 5, key="sum_count")
        extra, template = prompt_controls("summary")

        if st.button("요약 생성", key="sum_btn", type="primary"):
            run_generation("summary", "요약 자료를 만드는 중입니다...",
                           extra=extra, template=template,
                           topic=topic, count=count)

    with tabs[4]:
        ui.section("강의 슬라이드 생성",
                   "자료를 근거로 슬라이드를 구성하고 PPTX 파일로 내려받습니다.")
        topic = st.text_input("주제", key="slide_topic", placeholder="예: 옴의 법칙")
        count = st.number_input("슬라이드 수", 1, 10, 5, key="slide_count")
        st.caption("슬라이드의 그림은 업로드한 자료의 도표와 페이지에서 가져옵니다.")
        extra, _ = prompt_controls("slide")

        if st.button("슬라이드 생성", key="slide_btn", type="primary"):
            if not topic.strip():
                st.error("주제를 입력해 주세요.")
            else:
                with st.spinner("슬라이드를 구성하는 중입니다..."):
                    started = time.time()
                    result = generate_slide_data(
                        st.session_state.vectorstore, topic, count,
                        role=ROLE, courses=COURSES, extra=extra,
                    )
                    logger.log(st.session_state.user_id, ROLE, "강의 슬라이드",
                               topic, result, time.time() - started)

                # 다시 그려도 결과가 유지되도록 세션에 보관한다.
                st.session_state.slide_result = result
                st.session_state.slide_topic_used = topic
                st.session_state.pptx_bytes = None      # 새로 만들 파일 초기화

                # PPTX는 여기서 한 번만 만든다.
                # 다운로드 버튼 안에서 만들면 화면이 갱신될 때마다 파일이 다시 만들어진다.
                if not result["blocked"] and result.get("slides"):
                    build_log = []

                    with st.spinner("PPTX 파일을 만드는 중입니다..."):
                        st.session_state.pptx_bytes = build_pptx(
                            topic, result["slides"],
                            st.session_state.pdf_store,
                            log=build_log,
                        )
                    st.session_state.slide_log = build_log

        result = st.session_state.get("slide_result")

        if result:
            if result["blocked"]:
                st.warning(f"⚠️ {result['answer']}")

            elif result.get("slides"):
                used_topic = st.session_state.get("slide_topic_used", "강의자료")

                if st.session_state.get("pptx_bytes"):
                    st.download_button(
                        "📥 PPTX 파일 내려받기",
                        data=st.session_state.pptx_bytes,
                        file_name=f"{used_topic}_강의슬라이드.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        type="primary",
                    )

                if st.session_state.get("slide_log"):
                    with st.expander("슬라이드별 그림 처리 결과"):
                        for line in st.session_state.slide_log:
                            st.text(line)

                st.caption("생성된 구성 미리보기")
                for i, s in enumerate(result["slides"], start=1):
                    with st.container(border=True):
                        st.markdown(f"**{i:02d}. {s['title']}**")
                        for b in s["bullets"]:
                            st.markdown(f"- {b}")
                        if s["source"]:
                            st.caption(f"출처 · {s['source']}")

                if result["sources"]:
                    ui.sources(result["sources"])

            else:
                # JSON 파싱에 실패한 경우 원문을 그대로 보여준다.
                st.warning("슬라이드 형식으로 정리하지 못해 원문을 표시합니다.")
                st.caption(result.get("reason", ""))
                st.markdown(result["answer"])

    with tabs[5]:
        dashboard_tab()

else:
    tabs = st.tabs(["질의응답", "예상 문제", "오답 설명"])

    with tabs[0]:
        ui.section("자료 기반 질의응답",
                   "수강 과목 자료와 공개 자료에서 근거를 찾아 답변합니다.")
        chat_tab()

    with tabs[1]:
        ui.section("예상 문제 풀어보기",
                   "자료를 근거로 연습 문제와 해설을 만듭니다.")
        topic = st.text_input("주제", key="prac_topic", placeholder="예: 키르히호프 법칙")
        count = st.number_input("문항 수", 1, 10, 3, key="prac_count")
        extra, template = prompt_controls("practice")

        if st.button("문제 생성", key="prac_btn", type="primary"):
            run_generation("practice", "예상 문제를 만드는 중입니다...",
                           extra=extra, template=template,
                           topic=topic, count=count)

    with tabs[2]:
        ui.section("틀린 문제 설명 듣기",
                   "왜 틀렸는지와 복습할 개념을 자료에서 찾아 설명합니다.")
        topic = st.text_area("틀린 문제", key="rev_topic",
                             placeholder="문제 내용을 그대로 붙여넣으세요")
        answer = st.text_input("내가 적은 답", key="rev_answer")
        extra, template = prompt_controls("review")

        if st.button("설명 요청", key="rev_btn", type="primary"):
            run_generation("review", "설명을 준비하는 중입니다...",
                           extra=extra, template=template,
                           topic=topic, answer=answer)
