# Engineering Environment Everything

An agent skill for turning an engineering request into a researched plan, a project-specific environment, and executable acceptance checks. The planning model defines the checks before approval. The implementation model starts after environment preparation and checker calibration.

Maintained by [mango-leo on GitHub](https://github.com/mango-leo?tab=repositories).

> 엔지니어링 작업 요청을 **조사 → 계획 → 실행 가능한 검증 코드**로 바꾸고, 사용자가 계획을 한 번 확인하면 **구현과 검증을 자동으로 반복**하는 에이전트 스킬입니다.

"그럴듯해 보이는 결과"가 아니라 **실제로 실행해서 통과한 증거**로 완료를 판단합니다. 최종 PASS는 공통 실행기(`runtime.py`)가 전체 검증을 돌린 결과로만 인정됩니다.

Codex와 Claude Code가 같은 `harness/` 상태와 실행기를 사용하도록 구성했습니다. Codex에서는 CSV 예제로 실패 감지, 코드 수정, 최종 PASS까지 확인했습니다. Claude Code는 [진입점](.claude/skills/engineering-environment-everything/SKILL.md)의 형식과 경로를 확인했으며 실제 실행은 미검증입니다.

---

## 왜 필요한가

AI 에이전트에게 개발을 맡길 때 흔한 문제는 다음과 같습니다.

- 무엇이 "완료"인지 정해지지 않아 에이전트가 스스로 "다 됐다"고 선언한다.
- 테스트가 실패하면 기대값을 낮추거나 예외를 삼켜서 통과시킨다.
- 대화가 길어지거나 에이전트가 바뀌면 진행 상태를 잃는다.
- 막혔을 때 같은 시도를 반복하며 시간만 쓴다.

이 스킬은 **완료 기준을 먼저 코드로 고정**하고, 상태·시간·진전을 파일과 실행기가 관리하게 해서 이 문제들을 막습니다.

## 핵심 기능

| 기능 | 설명 |
|---|---|
| 요청 조사 | 사용자 요청과 기존 파일·도구를 먼저 파악하고, 필요한 분야의 공식 문서를 검색해 `RESEARCH.md`에 출처와 함께 기록 |
| 11축 프로파일 | 작업의 성격, 산출물, 실행 환경, 완료 증거, 금칙, 관례, 도구, 대안, 첫 루프 목표, 인접 분야, 확신도를 정리 |
| 실행 가능한 검증 | 요구사항마다 검증 어댑터와 정상(good)·실패(bad) 예제를 만들고, 상수 PASS를 내는 가짜 검증기를 차단 |
| 계획과 구현 모델 배정 | 높은 추론 수준의 모델이 계획과 판정 코드를 작성하고 낮은 추론 수준의 모델이 구현 |
| 1회 승인 | 사용자가 계획을 확인하면 `approve`로 준비 명령과 판정 기준을 고정 |
| 별도 환경 준비 | 실제 준비 검사와 필요한 설치를 끝내고 검증기를 교정한 뒤 구현 시작 |
| 자동 실행 루프 | 작은 구현 → 검증 → 보강을 사용자 응답 없이 반복 |
| 시간·진전 감시 | 기본 60분 제한, 3회 연속 무진전 시 재계획, 이후 2회 더 무진전이면 중단 |
| 인계 가능한 상태 | 상태·회차 기록·실행 로그가 `harness/`에 남아 크래시 후 `recover`, 에이전트 교체 후 이어하기 가능 |
| 완료/중단 보고 | 완료 시 전체 검증 증거를, 중단 시 완료한 것·남은 검증·재개 지점을 보고 |

분야별 고정 분류표(예: "웹은 이렇게, 임베디드는 이렇게")는 두지 않습니다. 작업마다 조사한 근거로 환경을 구성합니다.

## 동작 흐름

```
사용자 요청
   │
   ▼
1. 조사        파일·도구 확인, 분야 문서 검색, 질문은 최대 3개
   │
   ▼
2. 계획 모델   환경 준비 명령 · 제약 · PASS/FAIL 코드와 정상/실패 예제
   ▼
   [ 사용자 확인 1회 ]   계획 · 가정 · 금칙 · 완료 기준 · 예상 시간
   │
   ▼
3. 환경 준비   approve → prepare → calibrate
   ▼
4. 구현 모델   start → begin → 구현 → check → record  (반복)
   ▼
5. 보고        check --final의 PASS 증거 또는 중단 사유와 재개 지점
```

## 요구 사항

- Python 3.9 이상 (외부 패키지 불필요, 표준 라이브러리만 사용)
- Claude Code 또는 `.agents/skills`를 읽는 에이전트(예: Codex)
- 프로젝트에서 사용할 대상 도구는 작업마다 다르며, 스킬이 `detect_tools`로 확인하고 계획에 설치 방법을 넣습니다.

## 설치

이 저장소를 내려받아 저장소 루트에서 실행합니다. 대상 경로를 작업할 프로젝트 폴더로 바꿉니다.

**Windows PowerShell**

```powershell
$target = 'C:\path\to\your-project'
New-Item -ItemType Directory -Force "$target\.agents\skills", "$target\.claude\skills" | Out-Null
Copy-Item -Recurse '.agents\skills\engineering-environment-everything' "$target\.agents\skills\"
Copy-Item -Recurse '.claude\skills\engineering-environment-everything' "$target\.claude\skills\"
```

**Bash**

```bash
target=/path/to/your-project
mkdir -p "$target/.agents/skills" "$target/.claude/skills"
cp -R .agents/skills/engineering-environment-everything "$target/.agents/skills/"
cp -R .claude/skills/engineering-environment-everything "$target/.claude/skills/"
```

- `.agents/skills/engineering-environment-everything/` : 스킬 본체 (절차, 참조 문서, 스크립트, 템플릿)
- `.claude/skills/engineering-environment-everything/` : Claude Code용 진입점. 본체 `SKILL.md`를 상대 경로로 가리키므로 **두 폴더를 함께 복사**해야 합니다.

Codex만 쓴다면 `.agents/skills/engineering-environment-everything/`만 복사하면 됩니다.

## 사용법

대상 프로젝트 루트에서 Codex는 `$engineering-environment-everything`, Claude Code는 `/engineering-environment-everything`으로 스킬을 불러옵니다. 예를 들어 다음처럼 작업을 요청할 수 있습니다.

```text
센서 CSV의 시간대별 평균을 계산하는 CLI를 만들고 싶어. 정상 데이터와 잘못된 행이 섞인 데이터를 검증할 환경부터 구성해 줘.
```

진행 순서는 다음과 같습니다.

1. 에이전트가 요청과 프로젝트를 조사하고, 결과를 바꿀 질문만 최대 3개 묻습니다.
2. 계획·가정·금칙·완료 기준·예상 시간을 보여 줍니다. **여기서 한 번 확인해 주세요.**
3. 승인하면 환경 준비와 검증기 교정을 먼저 진행합니다. 교정을 통과하면 구현 모델이 구현과 검증을 반복합니다.
4. 완료(전체 검증 PASS) 또는 중단 시 증거와 함께 보고합니다.
5. 시간 제한은 언제든 "30분으로 줄여 줘"처럼 요청해 바꿀 수 있습니다. 중단 후 재개는 사용자 승인이 있을 때만 새 예산으로 시작합니다.

## 생성되는 `harness/` 구조

작업 대상 프로젝트 루트에 만들어지며, 작업과 상태의 원본입니다.

| 파일 | 역할 |
|---|---|
| `PROFILE.md` | 11축 작업 프로파일 |
| `RESEARCH.md` | 조사한 근거, 출처, 조회일, 미확인 가정 |
| `SPEC.md` | 목표, 산출물, 범위, 완료 조건, 가정, 미결 사항 |
| `CONSTRAINTS.md` | 제약과 사용자 금칙 |
| `PLAN.md` / `BACKLOG.md` | 작업 순서, 의존성, 예상 시간 |
| `VERIFICATION.md` / `CHECKS.json` | 요구사항별 검증 연결과 실행 정의 |
| `checks/` | 검증 어댑터와 good/bad fixture |
| `BASELINE.json` | 승인된 기준과 검증 코드의 해시 |
| `STATE.json` / `CONTROL.json` | 현재 상태, 시간 제한 등 제어값 |
| `loops/` / `activities/` | 회차별 완료 기록과 명령 실행 로그 |
| `AGENT.md` / `PROTOCOL.md` / `REPORT_FORMAT.md` | 어떤 에이전트든 이어받을 수 있는 규약 |
| `runtime.py` | 상태·검증·시간을 관리하는 공통 실행기 |

환경을 구성하는 에이전트는 기존 프로젝트 지시를 보존하면서 `harness/AGENT.md`와 `PROTOCOL.md`를 읽도록 연결할 수 있습니다. 구체적인 절차는 [환경 생성과 이전](.agents/skills/engineering-environment-everything/references/harness-generation.md)을 참고하세요.

## 공통 실행기 명령

프로젝트 루트에서 `python harness/runtime.py <명령>`으로 실행합니다. 보통은 에이전트가 호출합니다.

| 명령 | 용도 |
|---|---|
| `approve` | 사용자 확인 후 준비 명령과 판정 코드를 고정하고 기본 60분 예산 시작 |
| `prepare E01` | 승인된 준비 검사 실행, 필요하면 설치·설정 후 재검사 |
| `calibrate` | 계획에서 만든 정상·실패 예제로 검증기 확인 |
| `start` | 교정 성공 후 구현 시작. 첫 실행의 마감은 준비 단계에서 이어받음 |
| `status` | 현재 상태, 회차, 남은 시간 확인 |
| `begin --tasks T01` | 구현 회차 예약 |
| `exec --timeout-seconds 300 -- <명령>` | 시간 제한과 로그가 있는 명령 실행 |
| `check --ids V01` / `check --final` | 개별 검증 / 전체 최종 검증 |
| `record` | 회차 완료 기록 |
| `replan` / `pause` / `block` | 접근 변경, 일시 중지, 외부 차단 기록 (`--reason` 필수) |
| `monitor` | 경량 감시 모델의 판단 기록 |
| `recover` / `migrate` | 중단 복구 / v1 환경 이전 |

## 검증 계약

검증은 "설명"이 아니라 **실행 결과**입니다.

- 검증 어댑터는 실제 도구를 실행하거나 실제 결과를 읽어 기준과 비교하고, stdout에 JSON 한 개를 출력합니다.
- 상태는 `PASS` / `FAIL` / `UNVERIFIED` / `ERROR` 중 하나입니다. 테스트 0건, 건너뜀, 증거 누락, 오래된 증거는 완료로 인정하지 않습니다.
- 각 검증은 정상 fixture에서 PASS, 실패 fixture에서 FAIL을 내야 하며, 예외나 구문 오류를 "검증 성공"으로 쓰지 않습니다.
- 외부 측정 로그는 결과물 해시, 수집 시각, 생성 도구, 대상, 설정이 현재 결과물과 연결되어야 합니다.

## 에이전트가 하지 않는 일

- 실패 은폐, 필수 검사 생략, 테스트 기대값 하향
- 실제 연동을 가짜 결과로 대체하고 완료로 보고
- 예외를 삼키고 성공 처리
- 사용자 승인 없이 `baseline` 재생성, 검증 코드 수정, 시간 제한 연장, 재개

승인 이후 검증 기준 변경이 필요하면 영향과 이유를 설명하고 사용자에게 새 기준을 확인받습니다.

## 알려진 한계

- 외부 증거를 만든 주체를 암호학적으로 인증하지는 않습니다. 신뢰할 실행 경로에서 수집했는지와 제공자를 `RESEARCH.md`에 기록하는 방식입니다.
- 계획·구현·감시 모델의 분리 호출은 호스트의 모델 선택과 위임 기능에 따릅니다. 선택 기능이 없으면 역할과 편집 범위를 구분해 진행하고 실제 배정을 보고합니다.
- 실장비, GUI, 라이선스가 필요한 환경은 에이전트가 직접 접근할 수 없을 수 있습니다. 이 경우 사용자 환경에서 수집한 로그를 받아 검증하고, 미검증 범위는 보고서에 남깁니다.

## 개발과 테스트

```bash
cd .agents/skills/engineering-environment-everything
python -m unittest discover -s tests
```

증거 검증, 시간 제한 실행, 크래시 복구 등 동작 회귀 테스트가 포함되어 있습니다.

```text
.agents/skills/engineering-environment-everything/
├── SKILL.md                  # 스킬 정의와 절차
├── references/               # 입력·조사·합성·생성·검증·실행·보고 규약
├── assets/
│   ├── profile-schema.md     # 11축 프로파일 양식
│   └── harness-template/     # 대상 프로젝트로 복사되는 템플릿
├── scripts/
│   ├── init_harness.py       # harness 생성기
│   ├── runtime.py            # 공통 실행기
│   └── detect_tools.py|sh    # 도구 존재 확인
└── tests/test_harness.py
```

## 라이선스

[MIT License](LICENSE)
