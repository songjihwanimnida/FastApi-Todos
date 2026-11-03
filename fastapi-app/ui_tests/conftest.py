import os
import time
from datetime import datetime

import httpx2
import pytest

# 실행 중인 서버를 대상으로 한다 — 배포 서버는 BASE_URL=http://163.239.77.77:5006 처럼 지정
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
HEADED = os.environ.get("HEADED") == "1"                             # HEADED=1 이면 브라우저 창을 띄운다
TAG_PREFIX = "[UI테스트"
TAG = f"{TAG_PREFIX} {datetime.now():%H%M%S}]"                       # 테스트가 만든 할 일만 골라 지우기 위한 제목 접두어


def title(name):
    return f"{TAG} {name}"


def seed(api, name, **fields):                  # 사전 조건은 화면 대신 API 로 빠르게 만든다
    response = api.post("/todos", json={"title": title(name), **fields})
    assert response.status_code == 201
    return response.json()


def remove_test_todos(api):                      # 다른 사람의 데이터는 건드리지 않는다
    for todo in api.get("/todos").json():
        if todo["title"].startswith(TAG_PREFIX):
            api.delete(f"/todos/{todo['id']}")


@pytest.fixture(scope="session")
def base_url():                                  # pytest-base-url 의 base_url 을 덮어써 page.goto("/") 가 동작하게 한다
    return BASE_URL


@pytest.fixture(scope="session")
def api():
    with httpx2.Client(base_url=BASE_URL, timeout=10) as c:
        for _ in range(30):                      # 서버가 막 뜨는 중일 수 있어 최대 30초 대기
            try:
                if c.get("/todos").status_code == 200:
                    break
            except httpx2.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail(f"{BASE_URL} 에 접속할 수 없음")
        remove_test_todos(c)                     # 이전 실행이 중간에 끊겨 남은 항목 정리
        yield c


@pytest.fixture(autouse=True)
def cleanup(api):
    yield
    remove_test_todos(api)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {"channel": "chrome", "headless": not HEADED, **browser_type_launch_args}  # --browser-channel 등 CLI 옵션이 이긴다


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    # 시간대를 고정해야 "오늘" 계산이 실행하는 PC 와 상관없이 같다
    return {**browser_context_args, "locale": "ko-KR", "timezone_id": "Asia/Seoul", "viewport": {"width": 1280, "height": 900}}
