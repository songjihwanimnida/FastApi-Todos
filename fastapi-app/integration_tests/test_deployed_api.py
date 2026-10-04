import os
import time

import httpx2
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://163.239.77.77:5006")  # 배포 서버 주소 (환경변수로 덮어쓰기 가능)


@pytest.fixture(scope="module")
def client():
    with httpx2.Client(base_url=BASE_URL, timeout=10) as c:
        for _ in range(30):                      # 배포 직후엔 서버가 아직 안 떴을 수 있어 최대 30초 대기
            try:
                if c.get("/todos").status_code == 200:
                    break
            except httpx2.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail(f"{BASE_URL} 에 접속할 수 없음")
        yield c


@pytest.fixture
def created_ids(client):                         # 테스트가 중간에 실패해 남은 할 일만 지운다 (운영 데이터 보호)
    ids = []
    yield ids
    for todo_id in ids:
        client.delete(f"/todos/{todo_id}")


def todo_ids(client):
    return [t["id"] for t in client.get("/todos").json()]


def test_crud_flow(client, created_ids):         # 추가(201) → 조회(200) → 수정(200) → 삭제(204)
    response = client.post("/todos", json={"title": "[통합 테스트] 할 일", "priority": 2})
    assert response.status_code == 201
    todo = response.json()
    created_ids.append(todo["id"])
    assert todo == {"id": todo["id"], "title": "[통합 테스트] 할 일", "description": "",
                    "completed": False, "priority": 2}

    response = client.get("/todos")
    assert response.status_code == 200
    assert todo in response.json()

    response = client.put(f"/todos/{todo['id']}", json={"title": "[통합 테스트] 수정됨", "completed": True})
    assert response.status_code == 200
    assert response.json() == {**todo, "title": "[통합 테스트] 수정됨", "completed": True, "priority": 4}

    response = client.delete(f"/todos/{todo['id']}")
    assert response.status_code == 204
    created_ids.remove(todo["id"])
    assert todo["id"] not in todo_ids(client)


def test_create_without_title_returns_422(client):
    response = client.post("/todos", json={"description": "제목 없음"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "title"]


@pytest.mark.parametrize("payload", [
    {"title": "   "},                                     # 공백만 있는 제목
    {"title": "[통합 테스트] 타입", "priority": "2"},       # 문자열 → 정수 자동 변환 안 함
])
def test_invalid_payload_returns_422(client, created_ids, payload):  # v4.0.0
    response = client.post("/todos", json=payload)
    if response.status_code == 201:                      # 잘못 저장됐다면 운영 데이터에서 지운다
        created_ids.append(response.json()["id"])
    assert response.status_code == 422


def test_deleted_id_is_not_reused(client, created_ids):  # v4.0.0: 지운 id 를 다시 쓰지 않음
    first = client.post("/todos", json={"title": "[통합 테스트] 첫 번째"}).json()["id"]
    assert client.delete(f"/todos/{first}").status_code == 204
    second = client.post("/todos", json={"title": "[통합 테스트] 두 번째"}).json()["id"]
    created_ids.append(second)
    assert second > first


def test_delete_missing_id_returns_404(client):
    missing_id = max(todo_ids(client), default=0) + 1
    response = client.delete(f"/todos/{missing_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "To-Do item not found"
