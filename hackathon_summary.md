# Petbbi QA 자동화 포트폴리오 — 작업 요약

**작성자**: 이민서  
**작업일**: 2026-07-01  
**레포지토리**: https://github.com/lms111414-cmd/QA-Entrecee  
**라이브 사이트**: https://lms111414-cmd.github.io/QA-Entrecee/

---

## 1. 프로젝트 개요

반려동물 AI 다이어리 앱 **Petbbi**를 대상으로, PM 부트캠프 QA 자동화 과제를 수행했다.  
단순 테스트 케이스 작성을 넘어 **AI 기반 TC 자동 생성 파이프라인**과 **CI/CD 자동화**까지 구축했다.

### 목표
- 기획서(.md) 한 장으로 테스트 케이스 CSV를 자동 생성
- 릴리즈 게이트 기준을 직접 설계해 출시 판단 근거를 수치화
- GitHub Actions로 코드 push 시 파이프라인이 서버에서 자동 구동

---

## 2. 과제 단계별 산출물

### Basic — 기초 TC 설계
| 산출물 | 파일 | 내용 |
|---|---|---|
| 분석 기획서 | `data/petbbi-spec-v1-before-ac.md` | AC 없는 원본 기획서 |
| TC 체크리스트 | `output/qa-checklist-petbbi.csv` | 78건, 9컬럼 |
| 커버리지 리포트 | `output/coverage-report-petbbi-v1.txt` | 섹션별 케이스 수·우선순위 분포 |

### Standard — 파이프라인 구축
| 산출물 | 파일 | 내용 |
|---|---|---|
| 보완 기획서 | `data/petbbi-spec-v2-with-ac.md` | AC·화면 상태 추가, 마일스톤 부록 포함 |
| Python 파이프라인 | `tc-pipeline.py` | 기획서 → TC CSV 자동 생성 (Claude API) |
| 패키지 목록 | `requirements.txt` | `anthropic>=0.115.0` |
| 슬래시 커맨드 | `.claude/commands/gen-tc.md` | `/gen-tc` 커맨드 정의 |
| 재현성 검증 | `output/qa-checklist-petbbi-v2-replication.csv` | v2 기획서 기준 82건 재현 |

### Challenge — 직접 설계 + 자동화
| 산출물 | 파일 | 내용 |
|---|---|---|
| 최종 리포트 | `README.md` | Standard + Challenge 통합 리포트 |
| QA 대시보드 | `output/petbbi_challenge_report_v2_20260701.html` | 시각화 리포트 (릴리즈 게이트·실행 플랜) |
| GitHub Pages | `index.html` | 라이브 웹사이트로 배포 |
| CI/CD 파이프라인 | `.github/workflows/qa-pipeline.yml` | GitHub Actions 자동화 |

---

## 3. 핵심 기술 — TC 자동 생성 파이프라인

```
기획서(.md)
    ↓ [1단계] 구조 분석 — ## / ### 섹션 파싱
    ↓ [2단계] Claude API 호출 — 서브섹션별 TC 설계
    ↓ [3단계] 우선순위 분류 — P0 / P1 / P2
    ↓ [4단계] 엣지케이스 보완 — 경계값·네트워크·권한·빈 상태
    ↓ [5단계] CSV 저장 — UTF-8 BOM, 9컬럼
    ↓ [6단계] 커버리지 리포트 — 섹션별·우선순위·출처 분포
```

**사용 모델**: Claude Sonnet (claude-sonnet-4-6)  
**케이스 구성**: 서브섹션당 해피 1~2 / 인해피 1~3 / 엣지 1~3

---

## 4. Challenge — 직접 설계한 QA 방법론

### 우선순위 점수화 공식 (본인 설계)

```
Risk Score = (영향도 × 3) + (발생 가능성 × 2) + (발견 난이도 × 1)
최대 18점

14~18점 = P0  |  8~13점 = P1  |  6~7점 = P2
```

> 영향도 만점 + 전체 사용자 영향 + 비가역 3가지가 겹치면 점수 무관 P0 즉시 승격

### 릴리즈 게이트 3단 기준 (본인 설계)

| 단계 | 조건 | 결정 |
|---|---|---|
| 출시 보류 | P0 ≥ 1건 | 핫픽스 후 P0 전수 재검증 |
| 조건부 출시 | P0=0 & P1 ≤ 5건 | CTO·QA리드 공동 승인 + 2주 패치 로드맵 |
| 출시 가능 | P0=0 & P1 ≤ 5건 완료 | P2는 다음 스프린트 백로그 이관 |

### P0 주범 케이스 (릴리즈 게이트 차단)

| TC ID | 시나리오 | 점수 |
|---|---|---|
| TC-038 | 동일 이메일 소셜 로그인 충돌 → 계정 접근 영구 불가 | 16점 |
| TC-011 | 캐릭터 생성 중 네트워크 차단 → 재생성 횟수 부당 차감 | 16점 |
| TC-040 | 계정 삭제 트랜잭션 중 앱 강제종료 → 데이터 정합성 붕괴 | 14점 |

### 테스트 실행 플랜

**실행 플랜 01 — P0 (D+1 오전)**  
계정·인증 → 프로필 → AI 캐릭터 → AI 일기 → 커뮤니티 (의존성 순서)  
→ 1건 FAIL 시 즉시 출시 보류, 개발팀 긴급 알림

**실행 플랜 02 — P1 (D+1 오후)**  
타임존·OS 권한 + Empty State 5건 (P2→P1 상향 재분류)  
→ 미해결 5건 초과 시 HOLD, 버그픽스 로드맵 제출 후 재검증

---

## 5. CI/CD 파이프라인 구조

```yaml
트리거: main 브랜치 push 또는 수동 실행(workflow_dispatch)

Steps:
  1. 레포 체크아웃
  2. Python 3.11 환경 세팅
  3. pip install -r requirements.txt
  4. tc-pipeline.py 실행 → TC CSV + 커버리지 리포트 생성
  5. output/ 결과 파일 자동 커밋·push [skip ci]
```

- GitHub Secret `ANTHROPIC_API_KEY` 등록 완료
- `[skip ci]` 태그로 봇 커밋의 무한 루프 방지
- `permissions: contents: write`로 봇 push 권한 부여

---

## 6. 스프린트 마일스톤 (10 Sprint Days)

| Sprint Day | 목표 | 주요 산출물 |
|---|---|---|
| D1~D2 | 기획서 분석 + AC 보완 | petbbi-spec-v2-with-ac.md |
| D3~D4 | Basic TC 설계 (78건) | qa-checklist-petbbi.csv |
| D5~D6 | 파이프라인 개발 | tc-pipeline.py |
| D7 | Challenge 방법론 설계 | 점수화 공식·릴리즈 게이트 |
| D8 | 대시보드 제작 | petbbi_challenge_report_v2.html |
| D9 | CI/CD 구축 | qa-pipeline.yml |
| D10 | GitHub Pages 배포 + 최종 검수 | index.html + README.md |

---

## 7. 링크 모음 (발표 자료용)

| 항목 | URL |
|---|---|
| GitHub 레포 | https://github.com/lms111414-cmd/QA-Entrecee |
| 라이브 대시보드 | https://lms111414-cmd.github.io/QA-Entrecee/ |
| TC CSV | https://github.com/lms111414-cmd/QA-Entrecee/blob/main/output/qa-checklist-petbbi.csv |
| CI/CD 워크플로우 | https://github.com/lms111414-cmd/QA-Entrecee/actions |
