# 환경 생성과 이전

조사·프로파일·계획 초안을 작성하고 생성기로 검토 가능한 환경을 구성한다. 사용자가 계획·제약·검증 기준을 한 번 확인한 뒤 자동 실행을 시작한다.

## 입력 구성

PROFILE.md는 11개 번호 항목을 유지한다. 확인한 Python 실행 경로로 scripts/detect_tools.py --output <temp>/tools.json <tool> ...를 실행한다. Bash에서는 detect_tools.sh를 사용할 수 있다. Python이 없으면 설치·실행 경로 준비부터 안내하고 실제 실행을 확인한다.

intake.json의 필수 항목은 what, done_when, skeleton이다. scope_in, scope_out, interfaces, assumptions, open_questions, never는 문자열 배열이다. research에는 출처·버전·확인한 사실을, plan에는 환경 준비·작업 의존성·예상 시간을 기록한다. sources에는 실제 산출물의 프로젝트 상대 glob을 넣는다.

done_when 항목은 criterion, work, verify, pass_when, requires(도구 명령 배열)와 필요한 경우 prerequisites·fallback을 갖는다. executable에는 [검증 계약](checker-contract.md)의 command, cwd, min_tests, timeout_seconds, checker_files, self_tests와 필요한 metrics·evidence를 넣는다. skeleton도 같은 형식을 사용하며 work는 PROFILE 9번이다. T01/V01은 최소 실행 경로이며 이후 T02/V02부터 done_when 순서로 배정된다. depends_on을 생략하면 후속 작업은 T01에 의존한다.

constraints에는 description과 checks 배열로 PROFILE 제약과 사용자 금칙을 열거한다. 추가 검증기는 extra_checks에 완전한 검증 항목으로 넣는다. executable이 없는 이전 입력도 초안으로 생성할 수 있지만 검증 연결이 비어 있으면 approve가 거부한다.

## 생성

프로젝트 루트에서 확인한 Python으로 실행한다.

```text
python "<skill>/scripts/init_harness.py" --profile harness/PROFILE.md --intake "<temp>/intake.json" --tools "<temp>/tools.json"
```

PROFILE, SPEC, CONSTRAINTS, VERIFICATION, PLAN, RESEARCH, BACKLOG, AGENT, PROTOCOL, REPORT_FORMAT과 STATE·CONTROL·CHECKS 및 runtime.py를 생성한다. 실제 작업용 어댑터와 fixture를 harness/checks/에 작성한다. 검증 연결과 조사·계획 초안 문구를 실제 내용으로 채운 뒤 검토받는다.

기존 규약과 호환되게 루트 AGENTS.md에서 harness/AGENT.md와 PROTOCOL.md를 읽도록 연결한다. Claude Code를 쓰면 CLAUDE.md에서 @AGENTS.md로 가져온다. 기존 지시를 보존한다. 새 에이전트는 harness 폴더의 PROTOCOL.md와 runtime.py로 이어간다.

완성된 파일을 임시 위치에 준비한 뒤 반영한다. 중간 실패 시 .init-journal.json의 해시와 동일한 입력으로 재실행하면 누락 파일을 채운다. 사용자가 바꾼 파일은 덮어쓰지 않는다. 완성된 기존 harness는 종료 코드 3으로 구분한다.

## v1 이전

프로젝트 루트에서 python "<skill>/scripts/init_harness.py" --upgrade를 실행한다. STATE.v1.json에 이전 상태를 보존하고 공통 실행기·인계 규약을 추가한다. 기존 명세를 유지하며 PLAN.md, RESEARCH.md, CHECKS.json과 어댑터를 작성한다. 기존 AGENT.md에 PROTOCOL.md를 읽도록 연결한다.

기존 loop는 last_completed_loop로 옮긴다. running 상태는 파일·보고서와 작업을 대조한 뒤 recover한다. 새 기준을 확인받고 approve 후 start한다.

## 환경 준비

도구가 없으면 환경에 맞는 설치·설정 방법과 준비 확인 명령을 계획에 넣는다. GUI·라이선스·실기 접근 조건도 기록한다. 필수 환경 작업을 상태와 백로그에서 추적하고 승인 후 환경 단계에서 실제 최소 실행을 확인한다. 경로 발견만으로 검증 성공을 표시하지 않는다.
