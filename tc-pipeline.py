#!/usr/bin/env python3
"""
테스트 케이스 자동 생성 파이프라인 v1.0
기획서(.md) → 구조 분석 → 케이스 설계 → 우선순위 분류 → 엣지케이스 보완 → CSV + 커버리지 리포트

사용법:
  python generate_tc.py <기획서.md>
  python generate_tc.py <기획서.md> --output <결과.csv>
"""

import sys
import os
import json
import csv
import re
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("[오류] anthropic 패키지가 필요합니다: pip install anthropic")
    sys.exit(1)


# ───────────────────────────────────────────────────────────────
# 1단계: 구조 분석 — 기획서 파싱
# ───────────────────────────────────────────────────────────────
def parse_spec(md_path: str) -> list:
    """기획서 .md를 섹션 > 서브섹션 단위로 파싱합니다."""
    text = Path(md_path).read_text(encoding="utf-8")
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


# ───────────────────────────────────────────────────────────────
# 2~4단계: 케이스 설계 + 우선순위 분류 + 엣지케이스 보완
# ───────────────────────────────────────────────────────────────
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
[테스트 시나리오]
- 구체적인 액션 중심으로 서술
- 예: "512×512px 미만 이미지를 대표 사진으로 업로드 시도"

[기대 결과]
- UI 문구 표시 여부, 화면 이동, 버튼 상태 변화, 데이터 저장 여부를 구체적으로 명시
- 예: '"최대 5마리까지 등록 가능합니다" 안내 토스트 노출 / 등록 진행 불가'

[비고]
- 기획서에 정책이 명시되지 않은 사항, 기획 누락 의심 포인트
- 없으면 빈 문자열 ""

━━━ 출력 형식 ━━━
순수 JSON 배열만 출력. 마크다운 코드블록, 설명 텍스트 없이 [ ... ] 형태로만.

각 케이스 필드:
{
  "케이스 유형": "해피 | 인해피 | 엣지",
  "테스트 시나리오": "...",
  "기대 결과": "...",
  "우선순위": "P0 | P1 | P2",
  "출처": "기획서기반 | AI추가",
  "사전 조건": "...",
  "비고": "..."
}"""


def generate_cases_for_section(client: anthropic.Anthropic, section: dict, verbose: bool = True) -> list:
    """단일 서브섹션에 대한 테스트 케이스를 Claude API로 생성합니다."""
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
        if match:
            try:
                cases = json.loads(match.group())
            except json.JSONDecodeError:
                if verbose:
                    print(f"    [경고] JSON 파싱 실패 — {section['subsection']}")
                cases = []
        else:
            if verbose:
                print(f"    [경고] JSON 파싱 실패 — {section['subsection']}")
            cases = []

    for c in cases:
        c["섹션"] = section["section"]

    return cases


# ───────────────────────────────────────────────────────────────
# 5단계: CSV 생성
# ───────────────────────────────────────────────────────────────
COLUMNS = ["ID", "섹션", "케이스 유형", "테스트 시나리오", "기대 결과",
           "우선순위", "출처", "사전 조건", "비고"]


def write_csv(cases: list, output_path: str):
    """테스트 케이스를 UTF-8 BOM CSV로 저장합니다 (엑셀 한글 지원)."""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for i, c in enumerate(cases, 1):
            writer.writerow({
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


# ───────────────────────────────────────────────────────────────
# 섹션별 커버리지 리포트
# ───────────────────────────────────────────────────────────────
def generate_coverage_report(cases: list, spec_path: str) -> str:
    by_section = defaultdict(lambda: {"해피": 0, "인해피": 0, "엣지": 0})
    by_priority = defaultdict(int)
    by_source = defaultdict(int)

    for c in cases:
        sec = c.get("섹션", "기타")
        typ = c.get("케이스 유형", "")
        pri = c.get("우선순위", "")
        src = c.get("출처", "")

        if typ in ("해피", "인해피", "엣지"):
            by_section[sec][typ] += 1
        by_priority[pri] += 1
        by_source[src] += 1

    total = len(cases)
    happy_total = sum(v["해피"] for v in by_section.values())
    unhappy_total = sum(v["인해피"] for v in by_section.values())
    edge_total = sum(v["엣지"] for v in by_section.values())

    W = 58
    lines = [
        "=" * W,
        "  테스트 케이스 커버리지 리포트".center(W),
        f"  기획서 : {Path(spec_path).name}",
        f"  생성일 : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"  총 케이스 : {total}개",
        "=" * W,
        "",
        "[ 섹션별 케이스 수 ]",
        f"  {'섹션':<26} {'해피':>4} {'인해피':>5} {'엣지':>4} {'합계':>4}",
        "  " + "-" * 46,
    ]

    for sec, counts in by_section.items():
        subtotal = counts["해피"] + counts["인해피"] + counts["엣지"]
        lines.append(
            f"  {sec:<26} {counts['해피']:>4} {counts['인해피']:>5}"
            f" {counts['엣지']:>4} {subtotal:>4}"
        )

    lines += [
        "  " + "-" * 46,
        f"  {'합계':<26} {happy_total:>4} {unhappy_total:>5} {edge_total:>4} {total:>4}",
        "",
        "[ 우선순위 분포 ]",
        f"  P0: {by_priority.get('P0', 0):>3}건"
        f"  P1: {by_priority.get('P1', 0):>3}건"
        f"  P2: {by_priority.get('P2', 0):>3}건",
        "",
        "[ 출처 분포 ]",
        f"  기획서기반: {by_source.get('기획서기반', 0):>3}건"
        f"  AI추가: {by_source.get('AI추가', 0):>3}건",
        "=" * W,
    ]

    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────
# 메인
# ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="기획서(.md) → 테스트 케이스 CSV 자동 생성 파이프라인"
    )
    parser.add_argument("spec", help="기획서 .md 파일 경로")
    parser.add_argument(
        "--output", "-o", default=None,
        help="출력 CSV 파일명 (기본: <기획서명>_tc_YYYYMMDD.csv)"
    )
    args = parser.parse_args()

    spec_path = args.spec
    if not Path(spec_path).exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {spec_path}")
        sys.exit(1)

    today = datetime.now().strftime("%Y%m%d")
    stem = Path(spec_path).stem
    output_path = args.output or f"{stem}_tc_{today}.csv"
    report_path = f"{stem}_coverage_{today}.txt"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[오류] ANTHROPIC_API_KEY 환경변수를 설정해주세요.")
        print("  예) $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # ── 1단계: 구조 분석 ──
    print(f"\n[1/4] 구조 분석 중: {spec_path}")
    sections = parse_spec(spec_path)
    print(f"      → {len(sections)}개 서브섹션 발견")

    # ── 2~4단계: 케이스 설계 + 우선순위 + 엣지케이스 ──
    print(f"\n[2/4] 테스트 케이스 생성 중...")
    all_cases = []
    for i, section in enumerate(sections, 1):
        label = f"{section['section']} > {section['subsection']}"
        print(f"  ({i:02d}/{len(sections):02d}) {label}")
        cases = generate_cases_for_section(client, section)
        all_cases.extend(cases)
        type_counts = {t: sum(1 for c in cases if c.get("케이스 유형") == t)
                       for t in ("해피", "인해피", "엣지")}
        print(f"         → 해피 {type_counts['해피']} / 인해피 {type_counts['인해피']} / 엣지 {type_counts['엣지']}")

    # ── 5단계: CSV 생성 ──
    print(f"\n[3/4] CSV 저장 중: {output_path}")
    write_csv(all_cases, output_path)
    print(f"      → {len(all_cases)}개 케이스 저장 완료")

    # ── 커버리지 리포트 ──
    print(f"\n[4/4] 커버리지 리포트 생성 중: {report_path}")
    report = generate_coverage_report(all_cases, spec_path)
    Path(report_path).write_text(report, encoding="utf-8")

    print()
    print(report)
    print(f"\n✓ 완료")
    print(f"  CSV    : {output_path}")
    print(f"  리포트 : {report_path}")


if __name__ == "__main__":
    main()
