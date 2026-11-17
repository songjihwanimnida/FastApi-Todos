from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from main import app, save_store, load_store, next_due, TodoIn, TodoItem, TodoStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_and_teardown(tmp_path, monkeypatch):
    # 실제 todo.json 대신 테스트마다 새 임시 파일 사용 (데이터 보호 + 테스트 간 격리)
    monkeypatch.setattr(main, "TODO_FILE", tmp_path / "todo.json")
    save_store(TodoStore())


def seed(*ids):                                  # 주어진 id 로 할 일을 미리 저장
    save_store(TodoStore(todos=[TodoItem(id=i, title=f"할 일 {i}") for i in ids]))


def stored():                                    # 파일에 저장된 할 일 목록
    return load_store().todos


def make_project(name="업무"):                    # 프로젝트를 만들고 id 를 돌려준다
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


# ---------- 데이터 모델링 ----------

def test_model_defaults():
    todo = TodoIn(title="Test")
    assert (todo.description, todo.completed, todo.priority, todo.due_date) == ("", False, 4, None)
    assert (todo.project_id, todo.subtasks, todo.repeat) == (None, [], None)


def test_model_requires_id():
    with pytest.raises(ValidationError):         # TodoItem 은 id 필수
        TodoItem(title="Test")


# ---------- 상태관리 ----------

def test_save_and_load():
    store = TodoStore(todos=[TodoItem(id=1, title="장보기", priority=1, due_date=date(2026, 10, 31))])
    save_store(store)
    assert load_store() == store
    text = main.TODO_FILE.read_text(encoding="utf-8")
    assert "장보기" in text                       # 한글이 \uXXXX 로 바뀌지 않음
    assert '"next_id": 2' in text                # 다음 id 도 함께 저장
    assert '"due_date": "2026-10-31"' in text    # 날짜는 문자열로 저장


def test_v4_file_without_due_date():             # 마감일 이전(v4) 형식도 읽힘
    main.TODO_FILE.write_text('{"next_id": 3, "todos": [{"id": 1, "title": "옛 할 일"}]}', encoding="utf-8")
    store = load_store()
    assert store.todos[0].due_date is None
    assert store.next_id == 3


def test_v42_file_reads():                       # v4.2 형식(프로젝트·새 필드 없음)도 읽힘
    main.TODO_FILE.write_text('{"next_id": 2, "todos": [{"id": 1, "title": "옛 할 일", "due_date": "2026-10-31"}]}', encoding="utf-8")
    store = load_store()
    assert (store.projects, store.next_project_id) == ([], 1)
    todo = store.todos[0]
    assert (todo.project_id, todo.subtasks, todo.repeat) == (None, [], None)


def test_legacy_list_format():                   # v3 이하 형식(목록만, priority 없음)도 읽힘
    main.TODO_FILE.write_text('[{"id": 1, "title": "옛 할 일"}, {"id": 3, "title": "옛 할 일 2"}]', encoding="utf-8")
    store = load_store()
    assert store.todos[0].priority == 4
    assert store.next_id == 4                    # 가장 큰 id + 1 부터 이어 쓴다


def test_new_id_is_max_plus_one():
    seed(2, 3)
    assert client.post("/todos", json={"title": "Test"}).json()["id"] == 4


def test_deleted_id_is_not_reused():             # 가장 큰 id 를 지워도 그 id 는 다시 쓰지 않음
    seed(1, 2)
    client.delete("/todos/2")
    assert client.post("/todos", json={"title": "Test"}).json()["id"] == 3


def test_lifecycle():                            # 생성 → 수정 → 삭제 동안 파일 상태 확인
    todo_id = client.post("/todos", json={"title": "Test"}).json()["id"]
    client.put(f"/todos/{todo_id}", json={"title": "Test", "completed": True})
    assert stored()[0].completed is True
    client.delete(f"/todos/{todo_id}")
    assert stored() == []
    assert load_store().next_id == todo_id + 1


# ---------- CRUD ----------

def test_get_todos_empty():
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []


def test_get_todos_with_items():
    seed(1, 2)
    response = client.get("/todos")
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [1, 2]


def test_create_todo():
    response = client.post("/todos", json={"title": "Test", "id": 999})  # 보낸 id 는 무시됨
    assert response.status_code == 201
    assert response.json() == {"id": 1, "title": "Test", "description": "", "completed": False, "priority": 4, "due_date": None,
                               "project_id": None, "subtasks": [], "repeat": None}
    assert len(stored()) == 1


def test_due_date_roundtrip():                   # 저장 → 다시 읽기 경로를 지나야 load/save 문제가 드러난다
    response = client.post("/todos", json={"title": "과제", "due_date": "2026-10-31"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-10-31"
    assert client.get("/todos").json()[0]["due_date"] == "2026-10-31"
    assert '"due_date": "2026-10-31"' in main.TODO_FILE.read_text(encoding="utf-8")


def test_update_due_date():
    seed(1)
    assert client.put("/todos/1", json={"title": "과제", "due_date": "2026-10-31"}).json()["due_date"] == "2026-10-31"
    assert client.put("/todos/1", json={"title": "과제", "due_date": None}).json()["due_date"] is None
    client.put("/todos/1", json={"title": "과제", "due_date": "2026-10-31"})
    assert client.put("/todos/1", json={"title": "과제"}).json()["due_date"] is None  # PUT 은 전체 교체 → 생략하면 지워짐
    assert stored()[0].due_date is None


def test_get_todos_default_order():             # 쿼리가 없으면 v4 와 같이 id 순 (우선순위로 정렬하지 않음)
    for p in (4, 1, 2):
        client.post("/todos", json={"title": "Test", "priority": p})
    assert [t["priority"] for t in client.get("/todos").json()] == [4, 1, 2]


def test_create_todo_strips_whitespace():
    response = client.post("/todos", json={"title": "  장보기  ", "description": " 우유 \n"})
    assert (response.json()["title"], response.json()["description"]) == ("장보기", "우유")


def test_update_todo():
    save_store(TodoStore(todos=[TodoItem(id=1, title="Test", priority=1)]))
    response = client.put("/todos/1", json={"title": "Updated"})
    assert response.status_code == 200
    assert response.json()["title"] == "Updated"
    assert response.json()["priority"] == 4      # PUT 은 전체 교체 → 생략한 값은 기본값


def test_delete_todo():
    seed(1, 2)
    response = client.delete("/todos/1")
    assert response.status_code == 204           # 응답 본문 없음
    assert [t.id for t in stored()] == [2]


def test_update_and_delete_not_found():
    assert client.put("/todos/1", json={"title": "Test"}).status_code == 404
    assert client.delete("/todos/1").status_code == 404


def test_concurrent_requests():                  # JMeter 에서 나온 문제: 동시 요청 때 빈 파일을 읽어 500, id 중복·누락
    threads, rounds = 8, 25
    quiet = TestClient(app, raise_server_exceptions=False)  # 500 을 예외 대신 상태 코드로 받는다

    def user(n):
        codes = []
        for i in range(rounds):
            codes.append(quiet.post("/todos", json={"title": f"동시 {n}-{i}"}).status_code)
            codes.append(quiet.get("/todos").status_code)
        return codes

    with ThreadPoolExecutor(threads) as pool:
        codes = [c for result in pool.map(user, range(threads)) for c in result]

    assert set(codes) == {200, 201}              # 500 없음
    ids = [t.id for t in stored()]
    assert sorted(ids) == list(range(1, threads * rounds + 1))  # 빠진 할 일·겹친 id 없음
    assert load_store().next_id == threads * rounds + 1


# ---------- 프로젝트 ----------

def test_project_crud():
    assert client.get("/projects").json() == []
    response = client.post("/projects", json={"name": " 업무 "})
    assert response.status_code == 201
    assert response.json() == {"id": 1, "name": "업무"}
    assert client.put("/projects/1", json={"name": "회사"}).json() == {"id": 1, "name": "회사"}
    assert client.get("/projects").json() == [{"id": 1, "name": "회사"}]
    assert client.delete("/projects/1").status_code == 204
    assert client.get("/projects").json() == []
    assert client.put("/projects/1", json={"name": "회사"}).status_code == 404
    assert client.delete("/projects/1").status_code == 404


def test_project_duplicate_name():               # 앞뒤 공백·대소문자를 무시하고 같은 이름이면 409
    make_project("업무")
    make_project("Work")
    assert client.post("/projects", json={"name": " 업무 "}).status_code == 409
    assert client.post("/projects", json={"name": "work"}).status_code == 409
    assert client.put("/projects/2", json={"name": "업무"}).status_code == 409
    assert client.put("/projects/1", json={"name": "업무"}).status_code == 200      # 자기 이름 그대로 저장
    assert client.put("/projects/2", json={"name": "WORK"}).json()["name"] == "WORK"  # 대소문자만 변경
    assert [p["name"] for p in client.get("/projects").json()] == ["업무", "WORK"]


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}, {"name": "a" * 31}, {"name": 123}])
def test_project_name_invalid(payload):
    assert client.post("/projects", json=payload).status_code == 422
    assert load_store().projects == []


def test_project_name_max_length():
    assert client.post("/projects", json={"name": "a" * 30}).status_code == 201


def test_delete_project_deletes_todos():         # 프로젝트를 지우면 그 안의 할 일만 함께 지운다
    work, home = make_project("업무"), make_project("집")
    for pid in (work, home, work, None):
        client.post("/todos", json={"title": "할 일", "project_id": pid})
    assert client.delete(f"/projects/{work}").status_code == 204
    assert [t.project_id for t in stored()] == [home, None]
    assert [p.id for p in load_store().projects] == [home]


def test_project_id_not_reused():
    make_project("a")
    make_project("b")
    client.delete("/projects/2")
    assert make_project("c") == 3


# ---------- 할 일 새 필드 (프로젝트·하위 할 일·반복) ----------

def test_todo_fields_roundtrip():
    pid = make_project()
    created = client.post("/todos", json={
        "title": "주간 보고", "project_id": pid, "due_date": "2026-11-20", "repeat": "weekly",
        "subtasks": [{"title": " 숫자 정리 "}, {"title": "메일", "completed": True}],
    }).json()
    assert created["subtasks"] == [{"title": "숫자 정리", "completed": False}, {"title": "메일", "completed": True}]
    assert (created["project_id"], created["repeat"]) == (pid, "weekly")
    assert client.get("/todos").json() == [created]
    text = main.TODO_FILE.read_text(encoding="utf-8")
    assert '"next_project_id": 2' in text
    assert '"repeat": "weekly"' in text


def test_unknown_project_id():                   # 없는 프로젝트는 422, 저장하지 않음
    seed(1)
    response = client.post("/todos", json={"title": "a", "project_id": 99})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "project_id"]
    assert client.put("/todos/1", json={"title": "a", "project_id": 99}).status_code == 422
    assert [t.title for t in stored()] == ["할 일 1"]


def test_put_omitted_fields_reset():             # PUT 은 전체 교체 → 생략한 새 필드도 기본값
    pid = make_project()
    todo_id = client.post("/todos", json={
        "title": "a", "project_id": pid, "due_date": "2026-11-20", "repeat": "daily", "subtasks": [{"title": "s"}],
    }).json()["id"]
    body = client.put(f"/todos/{todo_id}", json={"title": "a"}).json()
    assert (body["project_id"], body["subtasks"], body["repeat"]) == (None, [], None)


# ---------- 반복 할 일 ----------

@pytest.mark.parametrize("due, repeat, expected", [
    (date(2026, 11, 17), "daily", date(2026, 11, 18)),
    (date(2026, 12, 31), "daily", date(2027, 1, 1)),
    (date(2026, 11, 17), "weekly", date(2026, 11, 24)),
    (date(2026, 1, 15), "monthly", date(2026, 2, 15)),
    (date(2026, 1, 31), "monthly", date(2026, 2, 28)),    # 없는 날은 말일로
    (date(2028, 1, 31), "monthly", date(2028, 2, 29)),    # 윤년
    (date(2026, 2, 28), "monthly", date(2026, 3, 28)),    # 원래 31일이었는지 기억하지 않는다 (spec Open question 1)
    (date(2026, 3, 31), "monthly", date(2026, 4, 30)),
    (date(2026, 12, 31), "monthly", date(2027, 1, 31)),   # 해 넘김
    (date(9999, 12, 31), "daily", None),                  # date 범위를 넘으면 회차 없음
    (date(9999, 12, 25), "weekly", None),
    (date(9999, 12, 1), "monthly", None),
])
def test_next_due(due, repeat, expected):
    assert next_due(due, repeat) == expected


def weekly_todo(**fields):                       # 하위 할 일 하나가 체크된 매주 반복 할 일
    return client.post("/todos", json={
        "title": "주간 보고", "description": "메모", "priority": 2, "due_date": "2026-11-20", "repeat": "weekly",
        "subtasks": [{"title": "숫자 정리", "completed": True}, {"title": "메일"}], **fields,
    }).json()


def complete(todo, completed=True):              # 화면처럼 다른 필드는 그대로 두고 completed 만 바꿔 PUT
    body = {k: v for k, v in todo.items() if k != "id"}
    return client.put(f"/todos/{todo['id']}", json={**body, "completed": completed})


def test_repeat_creates_next():
    todo = weekly_todo(project_id=make_project())
    response = complete(todo)
    assert response.status_code == 200
    assert (response.json()["completed"], response.json()["repeat"]) == (True, None)  # 반복은 새 회차가 이어받는다
    done, upcoming = client.get("/todos").json()
    assert done["id"] == todo["id"]
    assert upcoming == {**todo, "id": todo["id"] + 1, "due_date": "2026-11-27",
                        "subtasks": [{"title": "숫자 정리", "completed": False}, {"title": "메일", "completed": False}]}
    assert load_store().next_id == todo["id"] + 2


def test_repeat_uncheck_and_recheck():           # 완료 해제 → 다시 완료해도 회차가 또 생기지 않는다
    done = complete(weekly_todo()).json()
    complete(done, False)
    complete(done, True)
    assert len(stored()) == 2


def test_repeat_no_spawn():
    client.post("/todos", json={"title": "a", "due_date": "2026-11-20", "repeat": "daily", "completed": True})  # POST 는 만들지 않음
    client.put("/todos/1", json={"title": "a", "due_date": "2026-11-20", "repeat": "daily", "completed": True})  # 완료 → 완료
    last = weekly_todo(due_date="9999-12-31")
    assert complete(last).json()["repeat"] == "weekly"  # 다음 날짜가 없으면 반복을 넘겨줄 곳도 없다
    assert len(stored()) == 2


def test_repeat_concurrent_complete():           # 더블 클릭·탭 두 개: 같은 완료가 동시에 와도 회차는 1개
    todo = weekly_todo()
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: complete(todo).status_code, range(8)))
    assert codes == [200] * 8
    assert len(stored()) == 2


# ---------- 검색·필터·정렬 ----------

def query(**params):                             # GET /todos 결과의 제목 목록
    response = client.get("/todos", params=params)
    assert response.status_code == 200
    return [t["title"] for t in response.json()]


@pytest.fixture
def sample():
    work, home = make_project("업무"), make_project("집")
    for body in [
        {"title": "보고서 작성", "priority": 1, "project_id": work, "due_date": "2026-11-20"},
        {"title": "장보기", "description": "우유, 계란", "priority": 3, "project_id": home},
        {"title": "Report 검토", "priority": 2, "project_id": work, "completed": True, "due_date": "2026-11-18"},
        {"title": "운동", "priority": 2, "due_date": "2026-11-19"},
    ]:
        client.post("/todos", json=body)
    return work, home


def test_filter_q(sample):
    assert query(q="보고") == ["보고서 작성"]
    assert query(q="REPORT") == ["Report 검토"]  # 대소문자 무시
    assert query(q=" 계란 ") == ["장보기"]        # 설명도 찾는다, 앞뒤 공백 무시
    assert query(q="   ") == query()             # 공백만은 거르지 않음
    assert query(q="없는 말") == []


def test_filter_project(sample):
    work, _ = sample
    assert query(project_id=work) == ["보고서 작성", "Report 검토"]
    assert query(project_id=0) == ["운동"]        # 0 = 수집함
    assert query(project_id=99) == []            # 없는 프로젝트는 빈 목록


def test_filter_priority_status(sample):
    assert query(priority=2) == ["Report 검토", "운동"]
    assert query(status="open") == ["보고서 작성", "장보기", "운동"]
    assert query(status="done") == ["Report 검토"]
    assert query(priority=2, status="open", project_id=0, q="운") == ["운동"]  # 모두 AND


@pytest.mark.parametrize("sort, expected", [
    ("created", ["보고서 작성", "장보기", "Report 검토", "운동"]),
    ("priority", ["보고서 작성", "Report 검토", "운동", "장보기"]),
    ("due", ["Report 검토", "운동", "보고서 작성", "장보기"]),  # 마감일 없는 장보기가 뒤로
    ("title", ["Report 검토", "보고서 작성", "운동", "장보기"]),
])
def test_sort(sample, sort, expected):
    assert query(sort=sort) == expected


@pytest.mark.parametrize("params", [
    {"priority": 0}, {"priority": 5}, {"priority": "abc"},
    {"status": "all"}, {"sort": "random"}, {"project_id": -1}, {"project_id": "x"},
])
def test_query_invalid(params):
    assert client.get("/todos", params=params).status_code == 422


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_version():
    assert client.get("/openapi.json").json()["info"]["version"] == "5.0.0"


def test_metrics_endpoint():                     # Prometheus 가 수집하는 /metrics 가 살아 있고 문서에는 숨겨져 있다
    client.get("/todos")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


# ---------- 유효성 검사 ----------

@pytest.mark.parametrize("payload", [
    {"title": "a"},                              # 최소 길이
    {"title": "a" * 100},                        # 최대 길이
    {"title": "Test", "priority": 1},
    {"title": "Test", "priority": 4},
    {"title": "Test", "due_date": "2000-01-01"},  # 지난 날짜 허용
    {"title": "Test", "due_date": "0001-01-01"},  # 연도 범위는 제한하지 않음
    {"title": "Test", "due_date": "9999-12-31"},
    {"title": "Test", "due_date": None},
    {"title": "Test", "subtasks": [{"title": "s"}] * 50},  # 하위 할 일 최대 개수
    {"title": "Test", "due_date": "2026-11-20", "repeat": "monthly"},
    {"title": "Test", "project_id": None},
])
def test_create_todo_boundary(payload):
    assert client.post("/todos", json=payload).status_code == 201


@pytest.mark.parametrize("payload", [
    {"description": "Test"},                     # title 누락
    {"title": ""},                               # 너무 짧음
    {"title": "   "},                            # 공백만 → 앞뒤 공백을 지우면 빈 문자열
    {"title": "a" * 101},                        # 너무 김
    {"title": 123},                              # 문자열 아님
    {"title": "Test", "priority": 0},            # 범위(1~4) 밖
    {"title": "Test", "priority": 5},
    {"title": "Test", "completed": "abc"},       # bool 아님
    {"title": "Test", "priority": True},         # 자동 타입 변환 안 함 (true→1)
    {"title": "Test", "priority": "2"},          # ("2"→2)
    {"title": "Test", "completed": "yes"},       # ("yes"→true)
    {"title": "Test", "due_date": "2026-02-30"},  # 없는 날짜
    {"title": "Test", "due_date": "2026-1-5"},    # YYYY-MM-DD 아님
    {"title": "Test", "due_date": "20261031"},
    {"title": "Test", "due_date": "2026-10-31T00:00:00"},  # 시간 포함
    {"title": "Test", "due_date": ""},            # 빈 문자열 (화면은 null 로 보낸다)
    {"title": "Test", "due_date": 1793404800},    # 타임스탬프
    {"title": "Test", "subtasks": [{"title": "s"}] * 51},  # 하위 할 일 너무 많음
    {"title": "Test", "subtasks": [{"title": " "}]},        # 하위 할 일 제목 없음
    {"title": "Test", "subtasks": [{"title": "s", "completed": "yes"}]},
    {"title": "Test", "subtasks": ["s"]},                   # 객체가 아님
    {"title": "Test", "due_date": "2026-11-20", "repeat": "yearly"},  # 없는 반복 주기
    {"title": "Test", "repeat": "weekly"},                  # 마감일 없는 반복
    {"title": "Test", "project_id": 0},                     # 없는 프로젝트 (쿼리의 0=수집함과 다름)
    {"title": "Test", "project_id": "1"},                   # 자동 타입 변환 안 함
])
def test_create_todo_invalid(payload):
    assert client.post("/todos", json=payload).status_code == 422
    assert stored() == []                        # 잘못된 요청은 저장되지 않음


def test_invalid_path_id():
    assert client.delete("/todos/abc").status_code == 422

