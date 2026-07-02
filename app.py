import streamlit as st
import os
import json
import csv
import re
import io
from pathlib import Path
from collections import defaultdict
from datetime import datetime

try:
    import anthropic
except ImportError:
    st.error("anthropic 패키지가 필요합니다: pip install anthropic")
    st.stop()

import pandas as pd

# ── 파이프라인 함수 (tc-pipeline.py 재사용) ──────────────────────

def parse_spec_from_text(text: str) -> list:
    sections = []
    current_section = None
    current_subsection = None
    buffer = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_subsection:
                sections.append({
                    "section": current_section,
                    "subsection": current_subsection,
                    "content": "\n".join(buffer).strip()
                })
                buffer = []
            current_section = line[3:].strip()
            current_subsection = None
        elif line.startswith("### "):
            if current_subsection:
                sections.append({
                    "section": current_section,
                    "subsection": current_subsection,
                    "content": "\n".join(buffer).strip()
                })
                buffer = []
            current_subsection = line[4:].strip()
        elif current_subsection:
            buffer.append(line)

    if current_subsection:
        sections.append({
            "section": current_section,
            "subsection": current_subsection,
            "content": "\n".join(buffer).strip()
        })
    return sections


SYSTEM_PROMPT = """당신은 경력 5년의 시니어 QA 엔지니어입니다.
모바일 앱(iOS/Android) 기능 명세서를 받아 실무 품질의 테스트 케이스를 JSON 배열로 생성합니다.

━━━ 케이스 유형 정의 ━━━
• 해피   : 정상 입력 → 의도한 동작 성공 (기능의 핵심 플로우)
• 인해피 : 잘못된 입력, 필수값 누락, 유효성 검사 실패
• 엣지   : 경계값(최솟값/최댓값/경계±1), 네트워크 단절, OS 권한 거부,
           빈 상태(0건), 앱 강제종료, 데이터 동시성, 타임존 불일치

━━━ 우선순위 기준 ━━━
• P0: 핵심 기능 — 실패 시 서비스 전체 장애 또는 데이터 유실
• P1: 주요 기능 — 실패 시 UX 심각 저하, 회피 방법 없음
• P2: 부가 기능 — 실패 시 불편하지만 대안 존재

━━━ 출처 기준 ━━━
• 기획서기반: 명세서에 명시된 조건/동작에서 도출
• AI추가    : 명세서에 없지만 QA 관점에서 반드시 검증해야 하는 케이스

━━━ 작성 규칙 ━━━
[테스트 시나리오] 구체적인 액션 중심으로 서술
[기대 결과] UI 문구, 화면 이동, 버튼 상태, 데이터 저장 여부 구체적으로 명시
[비고] 기획서 정책 미명시 또는 기획 누락 의심 포인트. 없으면 ""

━━━ 출력 형식 ━━━
순수 JSON 배열만 출력. 마크다운 코드블록 없이 [ ... ] 형태로만.

각 케이스 필드:
{"케이스 유형": "해피|인해피|엣지", "테스트 시나리오": "...", "기대 결과": "...",
 "우선순위": "P0|P1|P2", "출처": "기획서기반|AI추가", "사전 조건": "...", "비고": ""}"""


def generate_cases(client, section: dict) -> list:
    user_msg = f"""## 섹션: {section['section']} > {section['subsection']}

명세 내용:
{section['content']}

이 서브섹션의 테스트 케이스를 JSON 배열로 생성하세요.
구성: 해피 1~2개 / 인해피 1~3개 / 엣지 1~3개"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}]
    )
    raw = response.content[0].text.strip()
    try:
        cases = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        cases = json.loads(match.group()) if match else []

    for c in cases:
        c["섹션"] = section["section"]
    return cases


COLUMNS = ["ID", "섹션", "케이스 유형", "테스트 시나리오", "기대 결과",
           "우선순위", "출처", "사전 조건", "비고"]


def cases_to_df(cases: list) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(cases, 1):
        rows.append({
            "ID": f"TC-{i:03d}",
            "섹션": c.get("섹션", ""),
            "케이스 유형": c.get("케이스 유형", ""),
            "테스트 시나리오": c.get("테스트 시나리오", ""),
            "기대 결과": c.get("기대 결과", ""),
            "우선순위": c.get("우선순위", ""),
            "출처": c.get("출처", ""),
            "사전 조건": c.get("사전 조건", ""),
            "비고": c.get("비고", ""),
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue().encode("utf-8-sig")


def build_coverage(cases: list) -> dict:
    by_section = defaultdict(lambda: {"해피": 0, "인해피": 0, "엣지": 0})
    by_priority = defaultdict(int)
    by_source = defaultdict(int)
    for c in cases:
        sec = c.get("섹션", "기타")
        typ = c.get("케이스 유형", "")
        if typ in ("해피", "인해피", "엣지"):
            by_section[sec][typ] += 1
        by_priority[c.get("우선순위", "")] += 1
        by_source[c.get("출처", "")] += 1
    return {"by_section": dict(by_section), "by_priority": dict(by_priority), "by_source": dict(by_source)}


# ── UI ───────────────────────────────────────────────────────────

st.set_page_config(page_title="QA TC 자동 생성", page_icon="🧪", layout="wide")

st.title("🧪 QA 테스트 케이스 자동 생성")
st.caption("기획서 .md 파일을 올리면 테스트 케이스를 자동으로 만들어 드립니다.")

# 사이드바: API 키
with st.sidebar:
    st.header("설정")
    api_key = st.text_input(
        "Anthropic API Key",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
        placeholder="sk-ant-..."
    )
    st.caption("키는 브라우저에만 저장됩니다.")
    st.divider()
    st.markdown("**만든 사람:** 이민서")
    st.markdown("**GitHub:** [QA-Entrecee](https://github.com/lms111414-cmd/QA-Entrecee)")

# 파일 업로드
uploaded = st.file_uploader("기획서 .md 파일을 올려주세요", type=["md"])

if uploaded:
    spec_text = uploaded.read().decode("utf-8")
    sections = parse_spec_from_text(spec_text)

    col1, col2 = st.columns([2, 1])
    with col1:
        st.success(f"**{uploaded.name}** 업로드 완료 — {len(sections)}개 서브섹션 발견")
    with col2:
        run = st.button("▶ TC 생성 시작", type="primary", use_container_width=True)

    if run:
        if not api_key:
            st.error("왼쪽 사이드바에 Anthropic API Key를 입력해주세요.")
            st.stop()

        client = anthropic.Anthropic(api_key=api_key)
        all_cases = []

        progress_bar = st.progress(0)
        status_box = st.empty()

        for i, section in enumerate(sections):
            label = f"{section['section']} > {section['subsection']}"
            status_box.info(f"생성 중... ({i+1}/{len(sections)}) **{label}**")
            try:
                cases = generate_cases(client, section)
                all_cases.extend(cases)
            except Exception as e:
                st.warning(f"[건너뜀] {label} — {e}")
            progress_bar.progress((i + 1) / len(sections))

        status_box.success(f"완료! 총 **{len(all_cases)}건** 생성됨")

        # 결과 저장 (세션)
        st.session_state["cases"] = all_cases
        st.session_state["filename"] = uploaded.name

# 결과 출력
if "cases" in st.session_state:
    cases = st.session_state["cases"]
    fname = st.session_state.get("filename", "spec.md")
    df = cases_to_df(cases)
    cov = build_coverage(cases)

    st.divider()

    # 지표
    total = len(cases)
    p0 = cov["by_priority"].get("P0", 0)
    p1 = cov["by_priority"].get("P1", 0)
    p2 = cov["by_priority"].get("P2", 0)
    spec_based = cov["by_source"].get("기획서기반", 0)
    ai_added = cov["by_source"].get("AI추가", 0)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("전체 TC", f"{total}건")
    m2.metric("P0 (출시 차단)", f"{p0}건")
    m3.metric("P1", f"{p1}건")
    m4.metric("P2", f"{p2}건")
    m5.metric("AI 추가 케이스", f"{ai_added}건")

    # 릴리즈 게이트
    st.subheader("릴리즈 게이트 판정")
    if p0 >= 1:
        st.error(f"🔴 **출시 보류** — P0 미해결 {p0}건. 핫픽스 후 P0 전수 재검증 필수.")
    elif p1 > 5:
        st.warning(f"🟡 **조건부 출시** — P1 미해결 {p1}건. CTO·QA리드 공동 승인 필요.")
    else:
        st.success(f"🟢 **출시 가능** — P0=0, P1={p1}건 (5건 이하). 정상 출시 가능.")

    st.divider()

    # 필터 + 테이블
    st.subheader("테스트 케이스 목록")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_priority = st.multiselect("우선순위 필터", ["P0", "P1", "P2"], default=["P0", "P1", "P2"])
    with col_f2:
        filter_type = st.multiselect("케이스 유형 필터", ["해피", "인해피", "엣지"], default=["해피", "인해피", "엣지"])
    with col_f3:
        filter_source = st.multiselect("출처 필터", ["기획서기반", "AI추가"], default=["기획서기반", "AI추가"])

    filtered = df[
        df["우선순위"].isin(filter_priority) &
        df["케이스 유형"].isin(filter_type) &
        df["출처"].isin(filter_source)
    ]
    st.dataframe(filtered, use_container_width=True, height=420)

    # 섹션별 커버리지
    st.subheader("섹션별 커버리지")
    cov_rows = []
    for sec, counts in cov["by_section"].items():
        subtotal = counts["해피"] + counts["인해피"] + counts["엣지"]
        cov_rows.append({"섹션": sec, "해피": counts["해피"], "인해피": counts["인해피"], "엣지": counts["엣지"], "합계": subtotal})
    st.dataframe(pd.DataFrame(cov_rows), use_container_width=True, hide_index=True)

    # 다운로드
    today = datetime.now().strftime("%Y%m%d")
    stem = Path(fname).stem
    st.download_button(
        label="⬇ CSV 다운로드",
        data=df_to_csv_bytes(df),
        file_name=f"{stem}_tc_{today}.csv",
        mime="text/csv",
        type="primary"
    )
