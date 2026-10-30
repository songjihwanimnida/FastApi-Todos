from playwright.sync_api import Page, expect

from conftest import seed, title

# 오전 9시 전: UTC 로 "오늘"을 계산하면 10-30 이 되어 하루 어긋나는 시각 (spec 우려 5)
NOW = "2026-10-31T08:30:00+09:00"
RED = "rgb(209, 69, 59)"                                             # --danger


def open_page(page: Page):
    page.clock.set_fixed_time(NOW)
    page.goto("/")
    expect(page.get_by_role("button", name="할 일 추가")).to_be_visible()   # 로딩이 끝나야 생긴다


def row(page: Page, todo_title):
    return page.locator("li.task", has_text=todo_title)


def due_of(api, todo_id):
    return next(x for x in api.get("/todos").json() if x["id"] == todo_id)["due_date"]


def test_due_display_and_overdue(page: Page, api):                  # R12–R15
    late = seed(api, "어제 마감", due_date="2026-10-30")["title"]
    today = seed(api, "오늘 마감", due_date="2026-10-31")["title"]
    none = seed(api, "마감 없음")["title"]
    done = seed(api, "끝낸 일", due_date="2026-10-30", completed=True)["title"]
    open_page(page)

    late_tag = row(page, late).locator(".due-tag")
    expect(late_tag).to_contain_text("기한 지남")
    expect(late_tag).to_contain_text("2026년 10월 30일")
    expect(late_tag).to_have_attribute("data-overdue", "true")
    expect(late_tag).to_have_css("color", RED)
    expect(page.get_by_role("checkbox", name=f"기한 지남 {late} 완료")).to_be_visible()   # 스크린리더 이름 (R14)

    today_tag = row(page, today).locator(".due-tag")                 # 마감일 당일은 기한 지남이 아니다
    expect(today_tag).to_contain_text("2026년 10월 31일")
    expect(today_tag).not_to_contain_text("기한 지남")
    expect(today_tag).not_to_have_attribute("data-overdue", "true")

    expect(row(page, none).locator(".due-tag")).to_have_count(0)

    page.locator(".done-section summary").click()                    # 완료됨 섹션에서는 마감일을 숨긴다 (R15)
    expect(row(page, done)).to_be_visible()
    expect(row(page, done).locator(".due-tag")).to_have_count(0)


def test_complete_keeps_due_date(page: Page, api):                  # R9 — PUT 전체 교체에도 마감일 유지 (우려 3)
    todo = seed(api, "과제", due_date="2026-10-30")
    t = todo["title"]
    open_page(page)

    page.get_by_role("checkbox", name=f"{t} 완료").click()
    expect(row(page, t)).to_have_attribute("data-done", "true")
    assert due_of(api, todo["id"]) == "2026-10-30"

    page.locator(".done-section summary").click()
    page.get_by_role("checkbox", name=f"{t} 완료 취소").click()
    expect(page.locator("#list-area").locator("li.task", has_text=t).locator(".due-tag")).to_contain_text("2026년 10월 30일")
    assert due_of(api, todo["id"]) == "2026-10-30"


def test_add_and_edit_due_date(page: Page, api):                    # R9, R10
    t = title("새 과제")
    open_page(page)
    page.get_by_role("button", name="할 일 추가").click()
    name = page.get_by_label("할 일 이름")
    due = page.get_by_label("마감일", exact=True)                   # "마감일 지우기" 버튼과 겹치지 않게 exact
    name.fill(t)
    due.fill("2026-11-05")
    name.press("Enter")

    expect(row(page, t).locator(".due-tag")).to_contain_text("2026년 11월 5일")
    expect(due).to_have_value("")                                    # 연속 등록: 날짜도 비운다
    todo = next(x for x in api.get("/todos").json() if x["title"] == t)
    assert todo["due_date"] == "2026-11-05"
    page.get_by_role("button", name="취소").click()

    page.get_by_role("button", name=f"{t} 편집").click()
    expect(due).to_have_value("2026-11-05")                          # 편집하면 기존 값이 채워져 있다
    page.get_by_role("button", name="마감일 지우기").click()
    expect(due).to_have_value("")
    page.get_by_role("button", name="저장").click()

    expect(row(page, t).locator(".due-tag")).to_have_count(0)
    assert due_of(api, todo["id"]) is None
