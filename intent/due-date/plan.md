# Plan: 할 일 마감일 구현
Author: songjihwan. Date: 2026-10-27. Status: approved.
Intent: [intent.md](./intent.md) · Spec: [spec.md](./spec.md)

## Context
과제처럼 날짜가 정해진 일을 설명 칸에 따로 적어야 하고, 기한이 지난 미완료 일이 눈에 안 띈다(intent.md). spec.md 는 선택 필드 `due_date` 와 화면의 "기한 지남" 표시를 R1–R17 로 정했다. 그리고 지금 코드에 필드만 추가하면 불러오기와 저장이 깨진다는 것을 확인했다(우려 1, 2). 이 계획은 **테스트를 먼저 쓰고(red) → 구현(green)** 하는 순서를 API, UI 두 층에 한 번씩 적용한다.

우려 번호는 spec.md 의 "Areas of concern" 1–9 이고, A–D 는 이번에 새로 찾은 위험이다.

## 바뀌는 파일
| 파일 | 변경 |
|---|---|
| `fastapi-app/tests/test_main.py` | 마감일 API 테스트 추가, `test_create_todo` 기대값에 `due_date: None` 추가 |
| `fastapi-app/main.py` | `due_date` 필드와 날짜 문자열 검증기, 저장을 JSON 모드로, 버전 4.1.0 |
| `fastapi-app/ui_tests/conftest.py` (새로, 복원) | 커밋 33dfed3 이전 파일에서 Playwright 와 API 부분만 가져옴 |
| `fastapi-app/ui_tests/test_due_date_ui.py` (새로) | 마감일 UI 테스트 |
| `fastapi-app/templates/index.html` | 날짜 입력·표시·기한 지남·탭 복귀 시 다시 그리기 |
| `CLAUDE.md` | "ui_tests 는 삭제됐다"는 문장이 틀리게 되므로 고침, UI 테스트 명령 추가 |
| `intent/due-date/plan.md` (새로) | 이 계획 |

바꾸지 않는 것: `todo.json`(테스트 흔적은 되돌림, 우려 8), `requirements*.txt`(playwright 1.64.1, pytest-playwright 0.10.0 이 이미 `.venv` 에 있다), Dockerfile.

## 작업 순서

### 0단계 — 계획 저장
이 내용을 `intent/due-date/plan.md` 로 저장한다.

### 1단계 — API 테스트 먼저 (red) · R1–R8 · 우려 1, 2, 3
`tests/test_main.py` 의 기존 패턴(`seed`, `stored`, autouse 임시 파일 fixture, parametrize)을 그대로 쓴다. Python 쪽에서 모델을 만들 때는 `datetime.date(2026, 10, 31)` 을 쓴다.
- `test_model_defaults` 에 `due_date is None` 추가 (R1)
- `test_create_todo` 의 기대 dict 에 `"due_date": None` 추가 (R4)
- 새 테스트 `test_due_date_roundtrip`: POST `"2026-10-31"` → 201, 응답 일치 → GET 에도 같은 값 → 파일 텍스트에 `"due_date": "2026-10-31"` (R2, R4, R5). **우려 1, 2 를 잡는 핵심 테스트**다. 저장한 뒤 다시 읽는 경로를 지나간다.
- `test_save_and_load` 에 `due_date=date(...)` 항목을 넣어 저장·불러오기 왕복 (R5, 우려 2)
- `test_create_todo_boundary` 에 추가: `"2000-01-01"`(지난 날짜), `"0001-01-01"`, `"9999-12-31"`, `None` (R3)
- `test_create_todo_invalid` 에 추가: `"2026-02-30"`, `"2026-1-5"`, `"20261031"`, `"2026-10-31T00:00:00"`, `""`, `1793404800` (R3)
- 새 테스트 `test_v4_file_without_due_date`: `{"next_id": 3, "todos": [{"id": 1, "title": "a"}]}` 를 읽으면 `due_date is None` (R6). 기존 `test_legacy_list_format` 은 v3 를 그대로 맡는다.
- 새 테스트 `test_update_due_date`: PUT 으로 날짜 설정 → `null` 로 지우기 → 생략해도 `null`(전체 교체) (R2, R7, 우려 3)
- 새 테스트 `test_api_version`: `/openapi.json` 의 `info.version == "4.1.0"` (R8)

**확인**: `.venv\Scripts\python.exe -m pytest` → 새 테스트와 바꾼 테스트만 실패하고 기존 31개 중 나머지는 통과. 지금은 모르는 필드를 무시하고 201 을 돌려주므로 응답에 `due_date` 가 없어 실패하고, 잘못된 날짜도 422 가 아니라 201 이라 실패한다.

### 2단계 — API 구현 (green) · R1–R8 · 우려 1, 2
`fastapi-app/main.py` 만 바꾼다.
- `TodoIn` 에 `due_date: IsoDate | None = None`. `IsoDate` 는 `date` 에 `BeforeValidator(parse_iso_date)` 를 붙인 타입이다. `strict=True` 는 그대로 두고, `strict=False` 로 우회하지 않는다 (R3, 우려 1).
  - *구현 중 수정*: 처음 계획은 "JSON 요청은 자동으로 충족, 불러오기만 `model_validate_json`" 이었다. 그런데 1단계 테스트에서 FastAPI 가 요청 본문을 dict 로 검증해 올바른 `"2026-10-31"` 도 422 로 거부하는 것이 드러났다. 검증기 하나로 요청과 불러오기가 함께 해결되므로 `load_store()` 는 바꾸지 않는다.
- `save_store()`: `store.model_dump(mode="json")` (우려 2). `indent=2`, `ensure_ascii=False` 는 그대로 둔다.
- `FastAPI(..., version="4.1.0")` (R8)

**확인**: 전체 `pytest` 통과. `pytest --cov=. --cov-report=term-missing` 에서 `main.py` 에 새로 덮이지 않은 줄이 없다.
**커밋 ①**: `feat(api): 할 일 마감일 due_date 추가` (1·2단계를 함께)

### 3단계 — UI 테스트 먼저 (red) · R9–R15 · 우려 4, 5
- `ui_tests/conftest.py`: `git show 33dfed3^:fastapi-app/ui_tests/conftest.py` 에서 다음을 가져온다.
  - `BASE_URL`(**기본값을 `http://localhost:8000` 으로 바꿈**, spec 질문 5), `TAG`/`title`/`seed`/`remove_test_todos`
  - `base_url`/`api`/`cleanup` 픽스처, `browser_type_launch_args`(channel chrome, `HEADED`)
  - `browser_context_args` 에 `"timezone_id": "Asia/Seoul"` 추가
  - Selenium 픽스처, 스크린샷 훅, `shot` 은 가져오지 않는다.
- `ui_tests/test_due_date_ui.py`: 매 테스트에서 `page.goto` 전에 `page.clock.set_fixed_time("2026-10-31T08:30:00+09:00")` 를 건다. 오전 9시 전이라 UTC 로 계산하면 하루가 어긋나는 시각이다(우려 5). 예전 테스트의 `row()`, `get_by_role("checkbox", name=...)` 패턴을 그대로 쓴다.
  1. `test_due_display_and_overdue` — 다음 항목을 seed 한다: 어제 마감 미완료, 오늘 마감 미완료, 마감 없음, 어제 마감 완료.
     - 어제 마감 미완료: "기한 지남"과 `2026년 10월 30일` 이 보이고, `data-overdue="true"` 이며, 체크 버튼 이름에 "기한 지남"이 들어간다 (R12–R14)
     - 오늘 마감: 날짜만 보이고 "기한 지남"은 없다 (R13)
     - 마감 없음: `.due-tag` 가 없다
     - 완료 항목: 완료됨 섹션을 펼쳐도 `.due-tag` 가 없다 (R15)
  2. `test_complete_keeps_due_date` — 완료 → 완료 취소 뒤 API 의 `due_date` 가 그대로다. 행에 날짜가 다시 보인다 (R9, R15, 우려 3)
  3. `test_add_and_edit_due_date` — 추가 폼에서 `get_by_label("마감일", exact=True).fill("2026-11-05")` 로 등록하면 API 에 저장되고, 연속 등록 폼의 날짜가 비워진다. 편집하면 기존 값이 채워져 있고, "마감일 지우기"를 누른 뒤 저장하면 API 값이 `null` 이다 (R9, R10, 우려 3)

**확인**: 서버를 띄우고 `pytest ui_tests` → 3개 모두 실패한다(화면에 아직 마감일이 없음). 실행한 뒤 `git restore todo.json` (우려 8).

### 4단계 — UI 구현 (green) · R9–R17 · 우려 3, 5, 6, 7
`templates/index.html` 만 바꾼다. 기존 헬퍼 `make()`, `icon()`, `ICONS`, `editorCard()`, `taskRow()`, `render()` 를 확장하고, 새 구조는 만들지 않는다.
- **날짜 순수 함수** (우려 5): `todayLocal()` 은 `getFullYear/getMonth/getDate` 로 `"YYYY-MM-DD"` 를 만든다. `isOverdue(todo, today)` 는 `!todo.completed && todo.due_date && todo.due_date < today`. `formatDue(s)` 는 `-` 로 나눠 `2026년 10월 31일` 로 조립한다. `Date` 파싱이나 `toISOString` 은 쓰지 않는다.
- **`taskRow()`**:
  - 미완료이고 `due_date` 가 있을 때만 `due-tag` 를 만든다. 달력 아이콘과 날짜를 넣고, 기한이 지났으면 앞에 "기한 지남"을 붙이고 `data-overdue="true"` 를 단다 (R12, R13, R15).
  - 체크 버튼 `aria-label` 의 `prioLabel` 뒤에 `"기한 지남 "` 을 넣는다 (R14).
  - `prioTag` 와 `due-tag` 를 감싸는 `.task-meta`(flex, wrap) 줄을 둔다.
- **CSS**: `.due-tag` 는 `.prio-tag` 와 같은 크기와 muted 색이다. `[data-overdue="true"]` 는 `var(--danger)` 와 굵은 글씨로 한다. `--danger` 와 `--p1` 은 둘 다 `#d1453b` 라 색으로는 구분되지 않으므로 글자가 필수다 (우려 7).
- **`editorCard()`**:
  - `dueDate` 인자를 받는다. `<input type="date">` 의 `aria-label` 은 "마감일"이고, `aria-label` 이 "마감일 지우기"인 작은 버튼을 둔다. 폼 아래쪽 우선순위 옆에 배치한다 (R10).
  - 제출할 때 `validity.badInput` 이면 날짜 칸에 포커스를 주고 중단한다 (R11, 우려 6). 그렇지 않으면 `due_date: input.value || null` 을 보낸다 (우려 6).
  - `keepOpen` 이면 연속 등록 뒤 날짜를 비운다 (R10).
- **PUT 에 담을 값**: 편집은 `{ ...todo, ...values }` 이고 `values` 에 항상 `due_date` 가 들어간다(지웠으면 `null`). 완료 체크는 기존 `{ ...todo, completed }` 그대로 둔다 (R9, 우려 3).
- **R17**: `document` 에 `visibilitychange` 리스너를 단다. 보이게 되었고 `!state.adding && state.editingId === null` 일 때만 `render()` 한다 (**새 위험 A**).
- 목록 순서(`byPriority`)와 진행률은 건드리지 않는다 (R16).

**확인**: `pytest ui_tests` 3개 통과, `pytest` 전체 통과, `git restore todo.json`.
**커밋 ②**: `feat(ui): 마감일 입력과 기한 지남 표시` (3·4단계를 함께, `ui_tests/` 포함)

### 5단계 — 문서와 마무리
- `CLAUDE.md`:
  - "`ui_tests/` 가 있다고 가정" 항목을 고친다. 이제 `ui_tests/` 는 있고, 기본 `pytest` 에는 포함되지 않는다.
  - UI 테스트 실행 명령을 추가한다.
  - "자주 틀리는 것"에 다음을 추가한다: `parse_iso_date` 를 빼거나 저장을 `mode="json"` 없이 하면 날짜가 깨진다, `strict=False` 로 풀지 않는다.
- 수동 체크리스트(spec 검증 계획): 덜 입력한 날짜는 제출이 막힘(R11), 실제 스크린리더로 읽기(R14), 자정을 넘겨 켜 둔 탭에 돌아오면 갱신(R17). 추가로 폼을 연 채 탭을 전환해도 입력이 남아 있는지 확인한다(위험 A).
- **커밋 ③**: `docs: 마감일 반영해 CLAUDE.md 갱신`. 커밋 ①–③ 은 사용자 승인 후에 하고, push 는 따로 요청받으면 한다.

## 위험 요소
| # | 위험 | 대응 단계 |
|---|---|---|
| 우려 1·2 | 불러오기의 엄격 모드와 저장 직렬화 때문에 마감일이 들어가면 500 | 1단계 왕복 테스트로 먼저 드러내고 2단계에서 날짜 검증기와 JSON 저장으로 고침 |
| 우려 3 | PUT 전체 교체로 마감일이 지워짐. 탭 두 개 문제는 고치지 않음(범위 밖) | 편집 시 `null` 을 명시, UI 테스트 2·3 |
| 우려 4 | UI 테스트는 서버와 Chrome 이 필요해 기본 `pytest` 에서 빠짐 | CLAUDE.md 에 실행 명령, 커밋 ② 전에 반드시 실행 |
| 우려 5 | UTC 날짜 함정 | 문자열로만 처리, 시계를 08:30 KST 로 고정한 테스트 |
| 우려 6 | 빈 날짜, 덜 입력한 날짜 | `badInput` 이면 막고 `""` 는 `null`, 수동 확인 |
| 우려 7 | `--danger` 와 `--p1` 이 같은 색 | "기한 지남" 글자 필수, UI 테스트가 글자를 확인 |
| 우려 8 | 로컬 UI 테스트가 추적 중인 `todo.json` 을 바꿈 | 실행할 때마다 `git restore todo.json`, 커밋 전 `git status` |
| 우려 9 | 손으로 잘못 고친 날짜 → 500 | 바꾸지 않음(기존 동작 유지) |
| A (새) | R17 의 다시 그리기가 열린 폼의 입력을 지움 | 폼이 열려 있으면 다시 그리지 않음 |
| B (새) | `get_by_label("마감일")` 이 "마감일 지우기" 버튼과 겹쳐 strict 위반 | `exact=True` |
| C (새) | 기존 `test_create_todo` 가 응답 dict 를 정확히 비교 | 1단계에서 기대값을 먼저 고침 |
| D (새) | CLAUDE.md 의 "ui_tests 삭제됨" 안내가 틀리게 됨 | 5단계 |

## 검증 방법 (모두 `fastapi-app/` 에서)
```powershell
.venv\Scripts\python.exe -m pytest                                    # API 단위 테스트 (1·2단계)
.venv\Scripts\python.exe -m pytest --cov=. --cov-report=term-missing  # main.py 커버리지
# UI: 터미널 하나에서 서버 실행
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
# 다른 터미널에서 (Chrome 설치 필요, HEADED=1 이면 창이 보임)
.venv\Scripts\python.exe -m pytest ui_tests
git restore todo.json                                                  # 우려 8
```
마지막으로 `docker compose up -d --build fastapi-app` 로 띄우고, `http://localhost:5005` 에서 마감일 추가와 기한 지남 표시를 한 번 직접 확인한다.
