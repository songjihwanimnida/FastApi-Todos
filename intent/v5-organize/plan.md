# Plan: v5.0.0 구현 — 프로젝트, 하위 할 일, 반복, 검색·필터·정렬
Author: songjihwan. Date: 2026-11-17. Status: approved.
Intent: [intent.md](./intent.md) · Spec: [spec.md](./spec.md)

## Context
할 일이 한 목록에 섞여 있어 나누고 찾기 어렵고, 단계와 반복을 표현할 수 없다(intent.md). spec.md 는 이를 R1–R37 로 정했다. 매월 반복은 spec 대로 필드 추가 없이 1/31 → 2/28 → 3/28 로 한다(2026-11-17 확정). 이 계획은 마감일 때와 같이 **테스트 먼저(red) → 구현(green)** 을 API, UI 두 층에 적용한다. API 는 범위가 커서 두 번에 나눈다(프로젝트·필드 → 반복·검색).

우려 번호는 spec.md 의 "Areas of concern" 1–9, A–F 는 이번에 새로 찾은 위험이다.

## 바뀌는 파일
| 파일 | 변경 |
|---|---|
| `fastapi-app/tests/test_main.py` | 새 테스트 추가, `test_create_todo` 기대값·`test_api_version` 수정 |
| `fastapi-app/main.py` | 모델 3개 추가, 프로젝트 엔드포인트, 반복 회차, `GET /todos` 쿼리, 버전 5.0.0 |
| `fastapi-app/ui_tests/conftest.py` | 테스트 프로젝트 정리(`[UI테스트` 로 시작하는 프로젝트 삭제), `seed_project` |
| `fastapi-app/ui_tests/test_v5_ui.py` (새로) | v5 화면 테스트 |
| `fastapi-app/templates/index.html` | 사이드바, 도구 막대, 폼·행 확장, 주소 쿼리 |
| `CLAUDE.md`, `RELEASE_NOTES.md` | 버전·구조·자주 틀리는 것, v5.0.0 섹션 |

바꾸지 않는 것: `requirements*.txt`(표준 라이브러리 `calendar` 만 씀), `Dockerfile`, `docker-compose.yml`, `jmeter/fastapi_test_plan.jmx`(그대로 통과해야 함, R1), `todo.json`(테스트 흔적은 되돌림, 우려 9).

## 작업 순서

### 0단계 — 계획 저장
이 내용을 `intent/v5-organize/plan.md` 로 저장한다.

### 1단계 — API 테스트 ① (red) · 호환·프로젝트·새 필드 · R1–R14, R5
- 바꿀 기존 테스트: `test_create_todo` 기대 dict 에 `"project_id": None, "subtasks": [], "repeat": None`(**새 위험 A** — 응답 dict 정확 비교), `test_api_version` → `"5.0.0"`, `test_model_defaults` 에 새 필드 기본값.
- 헬퍼: `make_project(name)` → `client.post("/projects", ...)` 의 id.
- 호환: `test_v42_file_reads`(v4.2 형식 → 프로젝트 0개, 새 필드 기본값), `test_get_todos_default_order`(id 순, R1)
- 프로젝트:
  - `test_project_crud` — 생성 201·조회·이름 변경 200·삭제 204, 없는 id 404 (R7)
  - `test_project_duplicate_name` — 생성·변경 409, `"업무"` vs `" 업무 "`, `"Work"` vs `"work"`, 자기 이름 다시 저장·대소문자만 변경은 200 (R8)
  - `test_project_name_invalid` parametrize — `""`, `"   "`, 31자, `123` → 422 (R6)
  - `test_delete_project_deletes_todos` — 다른 프로젝트·수집함 할 일은 남음, 한 번 저장 (R9)
  - `test_project_id_not_reused` (R3)
- 할 일 새 필드:
  - `test_todo_fields_roundtrip` — POST → GET → 파일 텍스트 (R10–R12, R14)
  - `test_unknown_project_id` — POST·PUT 422, 저장 안 됨, `detail[0]["loc"] == ["body", "project_id"]` (R10)
  - `test_put_omitted_fields_reset` — 생략하면 `project_id`/`subtasks`/`repeat` 기본값 (R12)
  - `test_create_todo_invalid` 에 추가: 하위 할 일 51개, 빈 제목 하위 할 일, `{"title": "a", "completed": "yes"}`, `repeat: "yearly"`, `repeat: "weekly"`+마감일 없음, `project_id: "1"` (R11, R14)
  - `test_create_todo_boundary` 에 추가: 하위 할 일 50개, `repeat` + 마감일

**확인**: `pytest` → 새·바뀐 테스트만 실패, 나머지 통과.

### 2단계 — API 구현 ① (green)
`main.py`:
- `SubtaskIn`, `ProjectIn`/`ProjectItem`, `Repeat`, `TodoIn` 새 필드 + `repeat_needs_due_date` 검증기 (R11, R14)
- `TodoStore` 에 `next_project_id`, `projects`. `next_id_after_max` 에 프로젝트도 같은 계산 (R3)
- `check_project(store, project_id)` — 없으면 `HTTPException(422, [{"loc": ["body", "project_id"], "msg": "프로젝트가 없습니다", "type": "project_not_found"}])` (R10)
- `find_project_index`, `name_taken(store, name, except_id)`(`casefold()` 비교) (R8)
- `/projects` 4개 엔드포인트, 모두 `with STORE_LOCK:` (R4, R7, R9)
- `create_todo`/`update_todo` 에 `check_project` 호출
- 버전 `5.0.0`

**확인**: `pytest` 전체 통과.

### 3단계 — API 테스트 ② (red) · 반복·검색 · R15–R24
- `next_due` 단위 테스트 parametrize: 매일·매주, 매월 1/15→2/15, 1/31→2/28, 2028-01-31→2028-02-29, 3/31→4/30, 12/31→다음 해 1/31, 9999-12-31 매일 → `None` (R16)
- `test_repeat_creates_next` — 매주 할 일(하위 할 일 하나 체크됨) 완료 PUT → 응답 `repeat: None`, 새 할 일 id = 이전 `next_id`, 필드 복사·하위 할 일 체크 해제·마감일 +7 (R15, R17)
- `test_repeat_uncheck_and_recheck` — 해제 → 재완료해도 할 일 2개 그대로 (R17)
- `test_repeat_no_spawn` — POST 완료 상태, 완료→완료 PUT, 9999-12-31 → 회차 없음 (R16, R18)
- `test_repeat_concurrent_complete` — 같은 할 일에 완료 PUT 8개 동시 → 회차 정확히 1개 (우려 2)
- `test_filter_*`: `q`(제목·설명, 대소문자, 공백만은 무시), `project_id`(0=수집함, 없는 id → `[]`), `priority`, `status`, 조합 AND (R19–R22, R24)
- `test_sort` parametrize: 4가지, 마감일 없는 항목 뒤로 (R23)
- `test_query_invalid` parametrize: `priority=0/5/abc`, `status=all`, `sort=random`, `project_id=-1` → 422

### 4단계 — API 구현 ② (green)
- `next_due(due, repeat)` — `calendar.monthrange`, 9999년 넘으면 `None` (`OverflowError`·`ValueError` 를 잡지 않고 미리 비교)
- `update_todo`: 잠금 안에서 `was_done = store.todos[i].completed` 를 읽고, `not was_done and payload.completed and payload.repeat` 이고 `next_due(...)` 가 있으면 새 회차 추가, 완료 쪽 `repeat=None` (R15–R18)
- `get_todos(q, project_id, priority, status, sort)` — `Annotated[..., Query(description=...)]`, `sort`·`status` 는 `Literal`, 거르기 → 정렬. 키 함수는 `SORT_KEYS` 딕셔너리 (R19–R24)

**확인**: `pytest` 전체 통과, `pytest --cov=. --cov-report=term-missing` 에서 `main.py` 새 줄 미커버 없음.
**커밋 ①**: `feat(api): 프로젝트, 하위 할 일, 반복, 검색·필터·정렬 (v5.0.0)` (1–4단계)

### 5단계 — UI 테스트 (red) · R25–R37
- `conftest.py`: `seed_project(api, name)` (이름에 `TAG`), `remove_test_todos` 에서 `[UI테스트` 프로젝트도 삭제(그 안 할 일도 함께 지워짐). 정리 순서: 할 일 → 프로젝트.
- `test_v5_ui.py` (시계는 `2026-11-17T10:00:00+09:00` 고정, `open_page`/`row` 패턴 재사용):
  1. `test_project_navigation` — seed 프로젝트 → 사이드바 링크 클릭 → 제목·`aria-current`·주소 `?project=` → "할 일 추가"로 만든 할 일의 API `project_id` 확인 (R25, R26, R31, R32)
  2. `test_project_delete` — 할 일 2개 든 프로젝트 → 삭제 → 확인 창 "할 일 2개" → API 에서 할 일 사라짐 (R27, R9)
  3. `test_subtasks` — 폼에서 하위 할 일 2개 추가해 등록 → 행 `0/2` → 펼침 → 하나 체크 → `1/2`, API 의 `due_date`·`repeat`·`project_id` 유지 (R32, R34, R35)
  4. `test_repeat_complete` — 매주 반복(11-20) 완료 → 토스트 "2026년 11월 27일", 새 행 보임. 매월 1/31 → 토스트 "2027년 2월 28일" (R15, R36, 우려 7)
  5. `test_repeat_needs_due` — 폼에서 마감일 없으면 반복 비활성, 마감일 넣으면 활성, 지우면 "안 함" (R33)
  6. `test_search_filter_sort` — 검색어 입력 → 목록 줄어듦·주소 `q` → 새로고침 유지 → 상태 "기한 지남" → 정렬 "마감일" 순서 → "필터 지우기" (R28–R31)
- `test_due_date_ui.py` 는 수정하지 않는다(R37).

**확인**: 서버 실행 후 `pytest ui_tests` → `test_v5_ui.py` 실패, `test_due_date_ui.py` 통과. `git restore todo.json`.

### 6단계 — UI 구현 (green)
`index.html`. 기존 헬퍼(`make`, `icon`, `run`, `api`, `editorCard`, `taskRow`)를 확장하고 프레임워크는 넣지 않는다.
- **레이아웃**: `.app` 그리드(사이드바 220px + 본문), 767px 이하에서 사이드바 숨기고 `<select aria-label="프로젝트">` 표시 (R25)
- **상태·통신**: `state.projects/all/todos/view/expanded`, `load()` 는 `Promise.all`, 요청 번호로 최신 응답만 반영, `todoBody(todo, changes)` 로 PUT 본문 생성(R35, 우려 1). 주소 ↔ `view` 는 `readView()`/`writeView()`(`history.replaceState`), 알 수 없는 값은 기본값 (R31, 우려 8)
- **사이드바**: 전체·수집함·프로젝트(이름 + 미완료 수), "프로젝트 추가" 인라인 입력, 409 토스트 (R25, R27)
- **제목 영역**: 프로젝트 화면이면 "이름 바꾸기"(인라인 입력)·"프로젝트 삭제" 버튼. 삭제 대화상자는 기존 `confirm-dialog` 를 제목·문구 인자로 일반화 (R27)
- **도구 막대**: 검색(250ms 디바운스), 우선순위·상태·정렬 `<select>`, "필터 지우기" (R28–R30)
- **폼**: 프로젝트·반복 `<select>`, 반복은 마감일 빈 값이면 `disabled` + "안 함"(`dueInput` 의 `input` 이벤트), 하위 할 일 편집 목록. 추가 입력칸 라벨 "새 하위 할 일", 버튼 이름 "하위 항목 추가"(**새 위험 B**) (R32, R33)
- **행**: 반복 태그(아이콘 + "매일/매주/매월"), "전체" 화면이면 프로젝트 태그, 하위 진행 `n/m` + 펼치기 버튼(`aria-expanded`), 하위 체크 버튼 (R34)
- **반복 완료 토스트**: `nextDue(due, repeat)` 문자열 계산 (R36)
- 마감일 관련 코드(`todayLocal`, `isOverdue`, `formatDue`, `badInput`, `visibilitychange`)는 그대로 둔다 (R37)

**확인**: `pytest ui_tests` 전체 통과, `pytest` 전체 통과, `git restore todo.json`.
**커밋 ②**: `feat(ui): 프로젝트 사이드바, 검색·필터·정렬, 하위 할 일, 반복` (5·6단계, `ui_tests/` 포함)

### 7단계 — 문서와 마무리
- `CLAUDE.md`: API 버전 5.0.0, 구조(모델·`/projects`·쿼리·반복 회차 규칙), "자주 틀리는 것"에 추가:
  - 화면에서 PUT 본문을 `todoBody` 없이 만들어 하위 할 일·반복·프로젝트가 지워짐
  - 반복 회차 판단을 잠금 밖에서 하거나 완료 쪽 `repeat` 를 남겨 회차가 중복됨
  - UI 버튼 이름에 "할 일 추가"가 들어가면 기존 UI 테스트가 strict 위반
- `RELEASE_NOTES.md` 맨 위 v5.0.0 섹션: 새 기능 → API 변경(개발자용) → 업그레이드 참고(이미지 재빌드, **업데이트 후 새로고침**(우려 1), **되돌리기 전 `todo.json` 백업**(우려 5)).
- 수동 체크리스트: 767px 이하 화면, 스크린리더(사이드바 현재 위치, 하위 체크 이름), Docker 로 띄워 JMeter 기본 계획 1회(로컬 Docker 가 없으면 서버에서, [[server-compose]]).
- **커밋 ③**: `docs: v5.0.0 릴리즈 노트와 CLAUDE.md`
- 릴리즈(사용자 요청 시): `main` 에 `--no-ff` 머지, 태그 `version5.0`, 푸시하면 배포 파이프라인이 돈다.

커밋 ①–③ 은 각 단계 확인 결과를 보고하고 사용자 승인을 받은 뒤 한다.

## 위험 요소
| # | 위험 | 대응 단계 |
|---|---|---|
| 우려 1 | PUT 전체 교체로 하위 할 일·반복·프로젝트 소실 | `todoBody` 한 곳, UI 테스트 3, 릴리즈 노트 |
| 우려 2 | 반복 완료 동시 요청으로 회차 중복 | 잠금 안 판단, `test_repeat_concurrent_complete` |
| 우려 3 | 프로젝트 삭제 개수가 다른 탭 변경을 모름 | 서버는 파일 기준, 그대로 둠 |
| 우려 4 | 화면 GET 이 3번으로 늘어남 | 디바운스, 최신 응답만 반영 |
| 우려 5 | v4.2 로 되돌리면 새 데이터 소실 | 릴리즈 노트 |
| 우려 6 | 기존 UI 테스트 깨짐 | `test_due_date_ui.py` 수정 금지, 이름 겹침 점검(B, C) |
| 우려 7 | 화면·서버 다음 날짜 불일치 | UI 테스트 4 의 1/31 매월 |
| 우려 8 | 주소 쿼리의 잘못된 값 → 422 | `readView` 가 기본값으로 정리 |
| 우려 9 | 추적 중인 `todo.json` 변경 | 실행마다 `git restore todo.json` |
| A (새) | `test_create_todo` 가 응답 dict 를 정확 비교 | 1단계에서 기대값 먼저 수정 |
| B (새) | Playwright `name=` 은 부분 일치 → "하위 할 일 추가" 버튼이 기존 `"할 일 추가"` 로케이터와 겹쳐 strict 위반 | 버튼 이름 "하위 항목 추가", 입력칸 라벨 "새 하위 할 일" |
| C (새) | 프로젝트 "삭제"·이름 변경 "저장"·"취소" 버튼이 기존 `"저장"`/`"취소"` 로케이터와 겹침 | 프로젝트 버튼은 "프로젝트 삭제", 이름 변경 폼은 열려 있을 때만 존재하고 버튼 이름 "이름 저장"/"이름 변경 취소" |
| D (새) | `GET /todos` 의 `project_id` 쿼리와 본문 `project_id` 의 0 의미가 다름 | Swagger 설명에 명시, 본문 0 은 없는 프로젝트라 422 |
| E (새) | 하위 할 일 체크가 PUT 이라 반복 할 일의 하위 체크도 `completed` 를 그대로 보내야 회차가 안 생김 | `todoBody` 가 `completed` 를 기존 값으로 유지, UI 테스트 3 에서 반복 + 하위 체크 |
| F (새) | 사이드바·도구 막대 추가로 화면 코드가 커져(657줄 → 약 1,100줄) 리뷰가 어려움 | 섹션 주석 유지, 렌더 함수를 영역별로 나눔 |

## 검증 방법 (모두 `fastapi-app/` 에서)
```powershell
.venv\Scripts\python.exe -m pytest                                    # API (1–4단계)
.venv\Scripts\python.exe -m pytest --cov=. --cov-report=term-missing  # main.py 커버리지
.venv\Scripts\python.exe -m uvicorn main:app --port 8000              # 터미널 1
.venv\Scripts\python.exe -m pytest ui_tests                           # 터미널 2 (5·6단계)
git restore todo.json
```
