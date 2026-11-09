# 실행 가능한 검증 계약

CHECKS.json은 schema_version 2이며 sources, requirements, tasks, checks 배열을 가진다. 경로는 프로젝트 루트 기준이다. sources는 산출물 전체를 포함하는 glob 배열이며 생성된 로그·상태 파일을 포함하지 않는다. 결과물이 달라지면 이전 검증 결과는 다시 확인한다.

requirements 항목은 id, kind(goal 또는 constraint), description, checks(검증 ID 배열)를 가진다. 모든 목표와 PROFILE 제약·사용자 금칙을 대응시킨다. tasks 항목은 id, work, checks, depends_on 배열을 가진다. 검증이 없는 요구사항과 순환 의존성은 승인 전에 해소한다.

검증 항목 예시는 다음과 같다.

```json
{
  "id": "V01",
  "command": ["{python}", "harness/checks/check_behavior.py", "--input", "output/result.json"],
  "cwd": ".",
  "min_tests": 2,
  "timeout_seconds": 300,
  "checker_files": ["harness/checks/check_behavior.py", "harness/checks/good.json", "harness/checks/bad.json"],
  "self_tests": [
    {"command": ["{python}", "harness/checks/check_behavior.py", "--input", "harness/checks/good.json"], "expected": "PASS"},
    {"command": ["{python}", "harness/checks/check_behavior.py", "--input", "harness/checks/bad.json"], "expected": "FAIL"}
  ],
  "metrics": {"error_count": "min"}
}
```

어댑터는 실제 도구 실행이나 실제 결과를 읽고 기준과 비교한다. 셸 문자열 대신 인자 배열을 쓴다. 파이프나 리다이렉션은 어댑터 코드에서 처리한다. stdout은 JSON 한 개다.

```json
{"status":"PASS","tests_run":2,"passed":2,"failed":0,"skipped":0,"metrics":{"error_count":0}}
```

tests_run은 passed + failed + skipped와 같아야 한다. 통과는 종료 코드 0, 실제 검증 실패는 1이다. 이외 종료 코드는 ERROR다. 건너뛴 필수 검사나 부족한 검사 수는 UNVERIFIED다. negative fixture는 실제 조건 불충족으로 FAIL을 내야 하며 예외·구문 오류를 검증기 성공으로 사용하지 않는다. self_tests는 같은 어댑터를 정상·실패 fixture로 실행한다. 상수 PASS 어댑터를 작성하지 않는다.

metrics는 선언한 min/max 방향으로 개선을 판단한다. 코드 변경량이나 설명 변경은 진전 지표가 아니다.

## 외부 측정 증거

check의 evidence 배열 항목에는 path, metadata, max_age_seconds, producer, target, settings를 적는다. metadata 파일은 artifact_sha256, sources(현재 결과물 상대 경로와 SHA-256 맵), collected_at(시간대가 있는 ISO 시각), producer, target, settings를 가진다. manifest와 메타데이터의 producer·target·settings가 일치해야 한다.

어댑터에도 해당 증거 경로를 넘겨 내용을 판정한다. 실행기는 해시·시각·대상·설정·결과물 버전 연결을 검사하고, 어댑터는 측정값의 기준 충족을 검사한다. 누락된 증거는 미검증이다.

검증 코드·fixture·요구사항·허용치 수정은 기존 승인을 무효화한다. 오류 수정이 필요하면 영향과 이유를 보여 주고 새 기준을 확인받는다.
