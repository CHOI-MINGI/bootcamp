"""화면 디자인 관련 코드를 모아둔 파일.

기능 로직(app.py)과 보여주는 방식(ui.py)을 분리해 두면
디자인을 바꿔도 기능 코드를 건드리지 않아도 된다.
"""

import streamlit as st

NAVY = "#1E2761"
NAVY_DARK = "#12193F"
ICE = "#CADCFC"
ICE_LIGHT = "#EAF1FC"
AMBER = "#D98A1F"
GRAY = "#5A6478"
LINE = "#D8DEE9"


CSS = f"""
<style>
/* ---------- 전체 ---------- */
.block-container {{
    padding-top: 1.6rem;
    max-width: 1180px;
}}
#MainMenu, footer {{ visibility: hidden; }}

/* ---------- 상단 배너 ---------- */
.hero {{
    background: linear-gradient(110deg, {NAVY_DARK} 0%, {NAVY} 65%, #2A3670 100%);
    border-radius: 10px;
    padding: 1.5rem 1.8rem;
    margin-bottom: 1.6rem;
    color: white;
}}
.hero-tag {{
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    color: {AMBER};
    font-weight: 700;
    margin-bottom: 0.35rem;
}}
.hero-title {{
    font-size: 1.65rem;
    font-weight: 700;
    line-height: 1.25;
    margin-bottom: 0.3rem;
}}
.hero-sub {{
    font-size: 0.9rem;
    color: {ICE};
}}

/* ---------- 사이드바 ---------- */
[data-testid="stSidebar"] {{
    background-color: #FAFBFD;
    border-right: 1px solid {LINE};
}}
[data-testid="stSidebar"] h2 {{
    font-size: 0.95rem !important;
    color: {NAVY};
    letter-spacing: 0.02em;
}}

/* 사용자 정보 카드 */
.user-card {{
    background: {NAVY};
    border-radius: 8px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.8rem;
    color: white;
}}
.user-card .name {{ font-size: 1rem; font-weight: 700; }}
.user-card .meta {{ font-size: 0.76rem; color: {ICE}; margin-top: 0.15rem; }}

/* 등록된 자료 항목 */
.doc-item {{
    border: 1px solid {LINE};
    border-left: 3px solid {NAVY};
    border-radius: 6px;
    padding: 0.5rem 0.7rem;
    margin-bottom: 0.45rem;
    background: white;
}}
.doc-name {{ font-size: 0.82rem; font-weight: 600; color: #1A2138; word-break: break-all; }}
.doc-meta {{ font-size: 0.7rem; color: {GRAY}; margin-top: 0.2rem; }}
.badge {{
    display: inline-block;
    font-size: 0.66rem;
    font-weight: 700;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    margin-right: 0.3rem;
}}
.badge-open   {{ background: {ICE_LIGHT}; color: {NAVY}; }}
.badge-course {{ background: #FBF0DC; color: #8A5A0B; }}
.badge-prof   {{ background: #FBEAE8; color: #B03A2E; }}

/* ---------- 탭 ---------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0.2rem;
    border-bottom: 1px solid {LINE};
}}
.stTabs [data-baseweb="tab"] {{
    height: 2.7rem;
    padding: 0 1.1rem;
    font-size: 0.92rem;
    font-weight: 600;
    color: {GRAY};
}}
.stTabs [aria-selected="true"] {{ color: {NAVY} !important; }}

/* ---------- 버튼 ---------- */
.stButton button {{
    border-radius: 6px;
    font-weight: 600;
    border: 1px solid {NAVY};
}}
.stButton button[kind="primary"],
.stFormSubmitButton button {{
    background: {NAVY};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 600;
}}

/* ---------- 섹션 제목 ---------- */
.section-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: {NAVY};
    margin: 0.6rem 0 0.15rem 0;
}}
.section-desc {{
    font-size: 0.82rem;
    color: {GRAY};
    margin-bottom: 1rem;
}}

/* ---------- 결과 영역 ---------- */
.result-box {{
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 1.1rem 1.3rem;
    background: white;
    margin-top: 1rem;
}}
.source-title {{
    font-size: 0.8rem;
    font-weight: 700;
    color: {NAVY};
    margin-bottom: 0.35rem;
}}
.source-chip {{
    display: inline-block;
    background: {ICE_LIGHT};
    color: {NAVY};
    border: 1px solid {ICE};
    border-radius: 12px;
    padding: 0.15rem 0.6rem;
    font-size: 0.74rem;
    margin: 0.12rem 0.25rem 0.12rem 0;
}}

/* ---------- 로그인 ---------- */
.login-note {{
    font-size: 0.8rem;
    color: {GRAY};
    text-align: center;
    margin-top: 1rem;
    line-height: 1.6;
}}
</style>
"""

BADGE_CLASS = {"공개": "badge-open", "수강생": "badge-course", "교수자": "badge-prof"}


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(tag, title, subtitle):
    st.markdown(
        f'<div class="hero">'
        f'<div class="hero-tag">{tag}</div>'
        f'<div class="hero-title">{title}</div>'
        f'<div class="hero-sub">{subtitle}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def user_card(name, role, courses):
    course_text = ", ".join(courses) if courses else "등록된 과목 없음"
    st.markdown(
        f'<div class="user-card">'
        f'<div class="name">{name}</div>'
        f'<div class="meta">{role} · {course_text}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def doc_item(file_name, course_id, visibility, chunks):
    badge = BADGE_CLASS.get(visibility, "badge-open")
    st.markdown(
        f'<div class="doc-item">'
        f'<div class="doc-name">{file_name}</div>'
        f'<div class="doc-meta">'
        f'<span class="badge {badge}">{visibility}</span>'
        f'{course_id} · {chunks}개 청크'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def section(title, description):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-desc">{description}</div>', unsafe_allow_html=True)


def sources(source_list):
    chips = "".join(f'<span class="source-chip">{s}</span>' for s in source_list)
    st.markdown(
        f'<div class="source-title">참조한 자료</div><div>{chips}</div>',
        unsafe_allow_html=True,
    )
