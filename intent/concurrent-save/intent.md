# Intent: 동시 요청에도 할 일이 깨지지 않게 저장하기
Author: songjihwan. Date: 2026-11-07. Status: draft.

## Problem
JMeter로 사용자 10명이 100번씩 요청(총 3,000건)을 보냈더니 314건(10.5%)이 실패했다.
- 앱 로그에 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`가 찍혔다. 한 요청이 `todo.json`을 다시 쓰는 도중에 다른 요청이 그 파일을 읽어 빈 내용을 받았다.
- `POST /todos` 114건과 `GET /todos` 43건이 500을 받았다. 500이 난 연결로 보낸 다음 요청 157건은 `Connection reset`으로 끊겼다.
- 응답 시간은 1~8ms였고 타임아웃은 없었다. 서버 처리 용량이 모자란 문제가 아니다.
- 같은 이유로 두 요청이 동시에 할 일을 추가하면 id가 겹치거나 한쪽 할 일이 사라질 수 있다.

## Proposed outcome
- 여러 사람이 동시에 추가, 수정, 삭제, 조회해도 500 오류가 나지 않는다.
- 동시에 추가한 할 일은 하나도 빠지지 않고 저장되며, id가 겹치지 않는다.
- 저장 도중 앱이 멈추더라도 `todo.json`은 이전 내용이나 새 내용 중 하나로 온전히 남는다.
- 서버에서 지난번과 같은 부하(10명 × 100회)를 다시 걸었을 때 에러율 0%. Grafana에서 수정 전후를 비교해 볼 수 있다.
- v4.2.0으로 릴리즈한다. 릴리즈 노트에는 이 수정과 이미 머지한 InfluxDB 모니터링을 함께 정리한다.

## Out of scope
- DB(SQLite 등)로 저장 방식 바꾸기
- 앱 컨테이너를 다시 만들어도 할 일이 남도록 데이터 볼륨 분리하기
- uvicorn 프로세스를 여러 개(`--workers`)로 늘리기
- 화면(`index.html`)과 API 모양 변경
- 응답 속도 개선 (파일 전체를 다시 쓰는 구조는 그대로)

## Affected users and systems
- 사용자: 여러 명이 동시에 쓰는 경우. 부하 테스트(JMeter)도 여기에 해당한다.
- `fastapi-app/main.py`의 저장과 읽기 부분, `fastapi-app/tests/test_main.py`
- `RELEASE_NOTES.md`, `CLAUDE.md`(버전과 구조 설명), 태그 `version4.2`
- 서버의 `FastApi-app2` 컨테이너: 새 버전을 반영하려면 컨테이너를 다시 만들어야 해서, 컨테이너 안의 `todo.json`이 이미지에 들어 있는 내용으로 돌아간다.

## Constraints
- API 요청과 응답 모양, 상태 코드, 검증 규칙(`strict`, PUT 전체 교체)은 그대로 둔다.
- `todo.json`의 v3 목록 형식과 v4 형식을 계속 읽을 수 있어야 한다.
- 새 id는 계속 `next_id`로 매기고, 지운 id는 다시 쓰지 않는다.
- 테스트가 `TODO_FILE`을 임시 파일로 바꾸는 방식이 계속 동작해야 한다.
- `/metrics`(Prometheus 계측)를 유지한다.
- 새 의존성은 추가하지 않는다.

## Open questions
- 없음
