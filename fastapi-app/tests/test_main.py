import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from main import app, save_store, load_store, TodoIn, TodoItem, TodoStore

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


# ---------- 데이터 모델링 ----------

def test_model_defaults():
    todo = TodoIn(title="Test")
    assert (todo.description, todo.completed, todo.priority) == ("", False, 4)


def test_model_requires_id():
    with pytest.raises(ValidationError):         # TodoItem 은 id 필수
        TodoItem(title="Test")


# ---------- 상태관리 ----------

def test_save_and_load():
    store = TodoStore(todos=[TodoItem(id=1, title="장보기", priority=1)])
    save_store(store)
    assert load_store() == store
    text = main.TODO_FILE.read_text(encoding="utf-8")
    assert "장보기" in text                       # 한글이 \uXXXX 로 바뀌지 않음
    assert '"next_id": 2' in text                # 다음 id 도 함께 저장


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
    assert response.json() == {"id": 1, "title": "Test", "description": "", "completed": False, "priority": 4}
    assert len(stored()) == 1


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


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ---------- 유효성 검사 ----------

@pytest.mark.parametrize("payload", [
    {"title": "a"},                              # 최소 길이
    {"title": "a" * 100},                        # 최대 길이
    {"title": "Test", "priority": 1},
    {"title": "Test", "priority": 4},
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
])
def test_create_todo_invalid(payload):
    assert client.post("/todos", json=payload).status_code == 422
    assert stored() == []                        # 잘못된 요청은 저장되지 않음


def test_invalid_path_id():
    assert client.delete("/todos/abc").status_code == 422

