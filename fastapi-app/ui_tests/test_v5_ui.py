import re

from playwright.sync_api import Page, expect

from conftest import TAG, seed, seed_project, title

NOW = "2026-11-17T10:00:00+09:00"


def open_page(page: Page, path="/"):
    page.clock.set_fixed_time(NOW)
    page.goto(path)
    expect(page.get_by_role("button", name="할 일 추가")).to_be_visible()   # 로딩이 끝나야 생긴다


def row(page: Page, todo_title):
    return page.locator("#list-area li.task", has_text=todo_title)


def find(api, todo_title):
    return [t for t in api.get("/todos").json() if t["title"] == todo_title]


def nav(page: Page):
    return page.get_by_role("navigation", name="프로젝트 목록")


def test_project_navigation(page: Page, api):                       # R25, R26, R31, R32
    project = seed_project(api, "업무")
    name, pid = project["name"], project["id"]
    seed(api, "업무 끝", project_id=pid, completed=True)
    other = seed(api, "수집함 일")["title"]
    open_page(page)
    expect(page.locator("#page-title")).not_to_contain_text("null")  # 프로젝트 버튼이 없는 "전체" 제목 (replaceChildren 에 null)

    nav(page).get_by_role("link", name=name).click()
    expect(page.get_by_role("heading", level=1)).to_have_text(name)
    expect(nav(page).get_by_role("link", name=name)).to_have_attribute("aria-current", "page")
    expect(page).to_have_url(re.compile(rf"[?&]project={pid}\b"))
    expect(row(page, other)).to_have_count(0)                        # 다른 프로젝트의 할 일은 안 보인다
    expect(page.locator("#progress-text")).to_have_text("1/1 완료 (100%)")

    t = title("업무 일")
    page.get_by_role("button", name="할 일 추가").click()
    expect(page.get_by_label("프로젝트", exact=True)).to_have_value(str(pid))   # 지금 보는 프로젝트가 골라져 있다
    page.get_by_label("할 일 이름").fill(t)
    page.get_by_label("할 일 이름").press("Enter")
    expect(row(page, t)).to_be_visible()
    assert find(api, t)[0]["project_id"] == pid
    expect(page.locator("#progress-text")).to_have_text("1/2 완료 (50%)")

    page.reload()                                                    # 주소로 같은 화면이 다시 나온다
    expect(page.get_by_role("heading", level=1)).to_have_text(name)
    nav(page).get_by_role("link", name="수집함").click()
    expect(row(page, other)).to_be_visible()
    expect(row(page, t)).to_have_count(0)


def test_project_delete(page: Page, api):                           # R27, R9
    project = seed_project(api, "지울 것")
    for n in ("하나", "둘"):
        seed(api, n, project_id=project["id"])
    open_page(page, f"/?project={project['id']}")

    page.get_by_role("button", name="프로젝트 삭제").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("할 일 2개")
    dialog.get_by_role("button", name="삭제").click()

    expect(page.get_by_role("heading", level=1)).to_have_text("전체")
    expect(nav(page).get_by_role("link", name=project["name"])).to_have_count(0)
    assert all(p["id"] != project["id"] for p in api.get("/projects").json())
    assert all(t["project_id"] != project["id"] for t in api.get("/todos").json())


def test_subtasks(page: Page, api):                                  # R32, R34, R35 · 위험 E
    project = seed_project(api, "하위")
    t = title("이사 준비")
    open_page(page)

    page.get_by_role("button", name="할 일 추가").click()
    page.get_by_label("할 일 이름").fill(t)
    page.get_by_label("마감일", exact=True).fill("2026-11-20")
    page.get_by_label("반복", exact=True).select_option("weekly")
    page.get_by_label("프로젝트", exact=True).select_option(str(project["id"]))
    sub = page.get_by_label("새 하위 할 일")
    sub.fill("짐 싸기")
    sub.press("Enter")                                               # 하위 할 일 칸의 Enter 는 폼 제출이 아니다
    sub.fill("청소")
    page.get_by_role("button", name="하위 항목 추가").click()
    expect(page.get_by_label("새 하위 할 일")).to_have_value("")
    page.get_by_label("할 일 이름").press("Enter")

    r = row(page, t)
    expect(r.locator(".sub-count")).to_have_text("0/2")
    expect(r.locator(".repeat-tag")).to_contain_text("매주")
    expect(r.locator(".project-tag")).to_contain_text(project["name"])  # "전체" 화면에서는 프로젝트 이름도 보인다
    toggle = page.get_by_role("button", name=f"{t} 하위 할 일 보기")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    page.get_by_role("checkbox", name="하위 할 일 짐 싸기 완료").click()

    expect(r.locator(".sub-count")).to_have_text("1/2")
    expect(page.get_by_role("checkbox", name="하위 할 일 청소 완료")).to_be_visible()  # 다시 그려도 펼친 상태 유지
    saved = find(api, t)
    assert len(saved) == 1                                           # 하위 체크가 반복 회차를 만들지 않는다
    todo = saved[0]
    assert [s["completed"] for s in todo["subtasks"]] == [True, False]
    assert (todo["due_date"], todo["repeat"], todo["project_id"], todo["completed"]) == (
        "2026-11-20", "weekly", project["id"], False)


def test_repeat_complete(page: Page, api):                           # R15, R36 · 우려 7
    weekly = seed(api, "주간", due_date="2026-11-20", repeat="weekly")["title"]
    monthly = seed(api, "월말", due_date="2027-01-31", repeat="monthly")["title"]
    open_page(page)

    page.get_by_role("checkbox", name=f"{weekly} 완료").click()
    expect(page.locator("#toast")).to_contain_text("2026년 11월 27일")
    expect(row(page, weekly).locator(".due-tag")).to_contain_text("2026년 11월 27일")
    assert sorted(t["completed"] for t in find(api, weekly)) == [False, True]

    page.get_by_role("checkbox", name=f"{monthly} 완료").click()
    expect(page.locator("#toast")).to_contain_text("2027년 2월 28일")   # 화면 계산이 서버(next_due)와 같다
    upcoming = next(t for t in find(api, monthly) if not t["completed"])
    assert upcoming["due_date"] == "2027-02-28"


def test_repeat_needs_due(page: Page):                               # R33
    open_page(page)
    page.get_by_role("button", name="할 일 추가").click()
    repeat = page.get_by_label("반복", exact=True)
    expect(repeat).to_be_disabled()

    page.get_by_label("마감일", exact=True).fill("2026-11-20")
    expect(repeat).to_be_enabled()
    repeat.select_option("daily")
    page.get_by_role("button", name="마감일 지우기").click()
    expect(repeat).to_be_disabled()
    expect(repeat).to_have_value("")


def test_search_filter_sort(page: Page, api):                        # R28–R31
    late = seed(api, "검색 사과", due_date="2026-11-10")["title"]     # 기한 지남
    urgent = seed(api, "검색 바나나", due_date="2026-11-30", priority=1)["title"]
    other = seed(api, "다른 것")["title"]
    open_page(page)
    titles = page.locator("#list-area li.task .task-title")

    search = page.get_by_role("searchbox", name="검색")
    search.fill(f"{TAG} 검색")
    expect(titles).to_have_text([urgent, late])                      # 기본 정렬은 우선순위
    expect(page).to_have_url(re.compile(r"[?&]q="))

    page.reload()                                                    # 새로고침해도 검색어 유지
    expect(page.get_by_role("searchbox", name="검색")).to_have_value(f"{TAG} 검색")
    expect(titles).to_have_text([urgent, late])

    page.get_by_label("정렬", exact=True).select_option(label="마감일")
    expect(titles).to_have_text([late, urgent])
    page.get_by_label("상태", exact=True).select_option(label="기한 지남")
    expect(titles).to_have_text([late])

    search.fill(f"{TAG} 없는 말")
    expect(page.locator("#list-area")).to_contain_text("조건에 맞는 할 일이 없습니다")
    page.get_by_role("button", name="필터 지우기").first.click()
    expect(page.get_by_role("searchbox", name="검색")).to_have_value("")
    expect(row(page, other)).to_be_visible()
    expect(page).not_to_have_url(re.compile(r"[?&](q|status|sort)="))
