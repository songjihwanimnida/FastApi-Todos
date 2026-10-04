import os
import time
from datetime import datetime
from pathlib import Path

import httpx2
import pytest
from selenium import webdriver

BASE_URL = os.environ.get("BASE_URL", "http://163.239.77.77:5006")  # 배포 서버 주소 (환경변수로 덮어쓰기 가능)
HEADED = os.environ.get("HEADED") == "1"                             # HEADED=1 이면 브라우저 창을 띄운다
TAG_PREFIX = "[UI테스트"
TAG = f"{TAG_PREFIX} {datetime.now():%H%M%S}]"                       # 테스트가 만든 할 일만 골라 지우기 위한 제목 접두어
SHOT_DIR = Path(__file__).resolve().parent.parent / "reports" / "screenshots"


def title(name):
    return f"{TAG} {name}"


def seed(api, name, **fields):                  # 사전 조건은 화면 대신 API 로 빠르게 만든다
    response = api.post("/todos", json={"title": title(name), **fields})
    assert response.status_code == 201
    return response.json()


def summary(api):                                # 화면이 보여줘야 할 개수·진행률을 API 기준으로 계산
    todos = api.get("/todos").json()
    done = sum(t["completed"] for t in todos)
    total = len(todos)
    pct = round(done / total * 100) if total else 0
    return {"total": total, "done": done, "text": f"{done}/{total} 완료 ({pct}%)"}


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
        for _ in range(30):                      # 배포 직후엔 서버가 아직 안 떴을 수 있어 최대 30초 대기
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


# ---------- Playwright ----------

@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {"channel": "chrome", "headless": not HEADED, **browser_type_launch_args}  # --browser-channel 등 CLI 옵션이 이긴다


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "locale": "ko-KR", "viewport": {"width": 1280, "height": 900}}


# ---------- Selenium ----------

@pytest.fixture
def driver():
    options = webdriver.ChromeOptions()
    if not HEADED:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--lang=ko-KR")
    d = webdriver.Chrome(options=options)       # chromedriver 는 Selenium Manager 가 Chrome 버전에 맞춰 받는다
    yield d
    d.quit()


# ---------- 스크린샷 ----------

@pytest.fixture
def shot(request):                               # 보고서용 화면 캡처: shot("UI-02-추가")
    def take(name):
        if "page" in request.fixturenames:
            folder, target = "playwright", request.getfixturevalue("page")
        else:
            folder, target = "selenium", request.getfixturevalue("driver")
        path = SHOT_DIR / folder / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if folder == "playwright":
            target.screenshot(path=path, animations="disabled")  # 진행률 바·화살표 전환 효과가 끝난 모습으로 찍는다
        else:
            target.save_screenshot(str(path))
    return take


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):      # Selenium 테스트가 실패하면 그 순간 화면을 남긴다 (Playwright 는 --screenshot 옵션)
    report = yield
    d = item.funcargs.get("driver")
    if report.when == "call" and report.failed and d:
        path = SHOT_DIR / "selenium" / f"FAILED-{item.name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        d.save_screenshot(str(path))
    return report
