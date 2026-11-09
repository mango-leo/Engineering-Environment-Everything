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

PROFILE, SPEC, CONSTRAINTS, VERIFICATION, PLAN, RESEARCH, BACKLOG, AGENT, PROTOCOL, REPORT_FORMAT과 STATE·CONTROL·CHECKS 및 runtime.py를 생성한다. 계획 모델이 실제 작업용 어댑터와 fixture를 harness/checks/에 작성한다. 설치 전이라 실행할 수 없는 판정 코드도 계획 확인 전에 완성한다. 검증 연결과 조사·계획 초안 문구를 실제 내용으로 채운 뒤 검토받는다.

생성기가 harness/checks/를 만들기 전에 어댑터를 작성한다면 임시 위치에 두고, 생성이 끝난 뒤 해당 폴더로 옮긴다.

기존 규약과 호환되게 루트 AGENTS.md에서 harness/AGENT.md와 PROTOCOL.md를 읽도록 연결한다. Claude Code를 쓰면 CLAUDE.md에서 @AGENTS.md로 가져온다. 기존 지시를 보존한다. 새 에이전트는 harness 폴더의 PROTOCOL.md와 runtime.py로 이어간다.

완성된 파일을 임시 위치에 준비한 뒤 반영한다. 중간 실패 시 .init-journal.json의 해시와 동일한 입력으로 재실행하면 누락 파일을 채운다. 사용자가 바꾼 파일은 덮어쓰지 않는다. 완성된 기존 harness는 종료 코드 3으로 구분한다.

## v1 이전

프로젝트 루트에서 python "<skill>/scripts/init_harness.py" --upgrade를 실행한다. STATE.v1.json에 이전 상태를 보존하고 공통 실행기·인계 규약을 추가한다. 기존 명세를 유지하며 PLAN.md, RESEARCH.md, CHECKS.json과 어댑터를 작성한다. 기존 AGENT.md에 PROTOCOL.md를 읽도록 연결한다.

기존 loop는 last_completed_loop로 옮긴다. running 상태는 파일·보고서와 작업을 대조한 뒤 recover한다. 새 기준과 준비 단계를 작성해 확인받고 실행 규약을 따른다.

기존 v2 프로젝트에서 새 준비 흐름을 사용하려면 진행 중인 회차를 정리하고, 기존 수정 사항을 보존하면서 runtime.py와 PROTOCOL.md 및 REPORT_FORMAT.md를 이 스킬의 버전으로 갱신한다. `--upgrade`는 기존 파일을 덮어쓰지 않는다. environment를 추가하고 변경된 계획과 기준을 확인받는다.

## 환경 준비

새 계획의 intake.json에 `environment` 배열을 실행 순서대로 넣는다. 이 배열은 CHECKS.json에 복사된다. 준비가 필요 없는 경우에도 빈 배열을 명시한다.

```json
{
  "environment": [
    {
      "id": "E01",
      "setup": ["{python}", "harness/checks/setup_tool.py"],
      "probe": ["{python}", "harness/checks/probe_tool.py"],
      "files": ["harness/checks/setup_tool.py", "harness/checks/probe_tool.py"],
      "cwd": ".",
      "timeout_seconds": 300
    }
  ]
}
```

각 항목은 고유한 `id`와 준비를 확인하는 `probe` 인자 배열이 필수다. `setup`은 첫 probe 실패 때만 실행하므로 재실행 가능한 명령으로 작성한다. 외부에서 준비할 항목은 setup을 생략한다. `files`에는 승인 시 고정해야 할 로컬 준비·검사 스크립트와 설정 파일을 포함한다. `cwd`는 프로젝트 기준이며 기본값은 루트다. 각 명령의 제한은 `timeout_seconds`와 남은 전체 시간 중 짧은 값이다.

PLAN에 도구 버전, 설치 범위, 실행 순서, 각 ID의 준비 완료 조건과 필요한 사용자 조치를 적는다. 준비 검사에는 대표적인 실제 도구 실행을 사용한다. GUI·라이선스·실기 접근 조건이 있으면 확인 가능한 실제 동작이나 증거를 검사한다. 준비 검사 종료 코드 0은 해당 환경 항목의 준비를 뜻하며 제품 완료 판정은 별도 어댑터가 수행한다.

준비 명령과 판정 명령은 별도 프로세스로 실행된다. 가상환경이나 SDK는 설치 경로의 실행 파일을 명시하거나 각 명령에서 필요한 환경을 불러온다.
