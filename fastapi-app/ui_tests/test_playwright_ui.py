from playwright.sync_api import Page, expect

from conftest import TAG, seed, summary, title

# 로케이터는 화면에 보이는 이름(역할·aria-label) 기준 — 사용자가 화면을 읽는 방식과 같다


def open_adder(page: Page):
    page.goto("/")
    page.get_by_role("button", name="할 일 추가").click()
    return page.get_by_label("할 일 이름")


def row(page: Page, todo_title):
    return page.locator("li.task", has_text=todo_title)


def test_ui01_page_load(page: Page, api, shot):
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto("/")
    expect(page).to_have_title("Todo")
    expect(page.get_by_role("heading", level=1)).to_have_text("전체")
    expect(page.get_by_role("button", name="할 일 추가")).to_be_visible()   # 로딩이 끝나야 생긴다
    s = summary(api)
    expect(page.locator("#view-count")).to_have_text(f"{s['total']}개")
    if s["total"] == 0:
        expect(page.get_by_text("할 일이 없습니다")).to_be_visible()
        expect(page.locator("#progress")).to_be_hidden()
    else:
        expect(page.locator("#progress-text")).to_have_text(s["text"])
    assert errors == []                                                  # favicon.ico 404 같은 콘솔 에러가 없다
    shot("UI-01-load")


def test_ui02_add_todo(page: Page, api, shot):
    t = title("장보기")
    name = open_adder(page)
    submit = page.get_by_role("button", name="할 일 추가")             # 폼이 열리면 같은 이름의 제출 버튼이 된다
    expect(submit).to_be_disabled()
    name.fill("   ")
    expect(submit).to_be_disabled()                                     # 공백만 입력해도 제출 불가
    name.fill(t)
    page.get_by_label("설명", exact=True).fill("우유, 계란")
    page.get_by_title("우선순위 2").click()
    expect(page.get_by_title("우선순위 2")).to_have_attribute("aria-pressed", "true")
    shot("UI-02-add-form")
    name.press("Enter")

    expect(row(page, t)).to_contain_text("우유, 계란")
    expect(row(page, t)).to_contain_text("우선순위 2")
    expect(name).to_have_value("")                                      # 연속 등록: 폼은 열린 채 입력만 비운다
    expect(name).to_be_focused()
    expect(page.get_by_title("우선순위 4")).to_have_attribute("aria-pressed", "true")
    expect(submit).to_be_disabled()
    saved = [x for x in api.get("/todos").json() if x["title"] == t]
    assert [(x["description"], x["priority"], x["completed"]) for x in saved] == [("우유, 계란", 2, False)]
    shot("UI-02-added")


def test_ui03_priority_sort(page: Page, api, shot):
    for name, priority in [("보통", 3), ("급함", 1), ("기본", 4)]:   # 일부러 섞어서 등록
        seed(api, name, priority=priority)
    page.goto("/")
    rows = row(page, TAG)
    expect(rows.locator(".task-title")).to_have_text([title("급함"), title("보통"), title("기본")])
    for i, (priority, color) in enumerate([("1", "rgb(209, 69, 59)"), ("3", "rgb(36, 111, 224)"), ("4", "rgb(188, 188, 188)")]):
        check = rows.nth(i).get_by_role("checkbox")
        expect(check).to_have_attribute("data-priority", priority)
        expect(check).to_have_css("border-top-color", color)            # 릴리즈 노트의 색: 빨강 / 파랑 / 회색
        expect(rows.nth(i)).to_contain_text(f"우선순위 {priority}")
    shot("UI-03-sorted")


def test_ui04_complete_and_progress(page: Page, api, shot):
    t = seed(api, "빨래")["title"]
    page.goto("/")
    page.get_by_role("checkbox", name=f"{t} 완료").click()

    expect(row(page, t)).to_have_attribute("data-done", "true")         # 접힌 "완료됨" 섹션으로 이동
    s = summary(api)
    expect(page.locator(".done-section .done-count")).to_have_text(str(s["done"]))
    expect(page.locator("#progress-text")).to_have_text(s["text"])
    expect(page.get_by_role("progressbar")).to_have_attribute("aria-valuenow", str(s["done"]))

    page.locator(".done-section summary").click()                       # 펼치면 취소선과 함께 보인다
    expect(row(page, t)).to_be_visible()
    expect(row(page, t).locator(".task-title")).to_have_css("text-decoration-line", "line-through")
    shot("UI-04-done-section")

    page.get_by_role("checkbox", name=f"{t} 완료 취소").click()
    expect(page.locator("#list-area").locator("li.task", has_text=t)).to_have_attribute("data-done", "false")
    expect(page.locator("#progress-text")).to_have_text(summary(api)["text"])


def test_ui05_edit(page: Page, api, shot):
    todo = seed(api, "보고서", description="초안", priority=1)
    t = todo["title"]
    page.goto("/")
    page.get_by_role("button", name=f"{t} 편집").click()                # hover 해야 보이는 버튼(opacity:0)도 바로 클릭된다
    name = page.get_by_label("할 일 이름")
    expect(name).to_have_value(t)
    expect(page.get_by_label("설명", exact=True)).to_have_value("초안")
    expect(page.get_by_title("우선순위 1")).to_have_attribute("aria-pressed", "true")

    name.fill(f"{t} 바뀜")
    name.press("Escape")                                                 # Escape = 취소, 바뀌지 않는다
    expect(row(page, t).locator(".task-title")).to_have_text(t)

    page.get_by_role("button", name=f"{t} 편집").click()
    new_title = title("보고서 v2")
    name.fill(new_title)
    page.get_by_title("우선순위 3").click()
    shot("UI-05-edit-card")
    page.get_by_role("button", name="저장").click()

    expect(row(page, new_title)).to_contain_text("우선순위 3")
    saved = next(x for x in api.get("/todos").json() if x["id"] == todo["id"])
    assert saved == {**todo, "title": new_title, "priority": 3}         # 설명·완료 상태는 PUT 후에도 유지


def test_ui06_delete_with_confirm(page: Page, api, shot):
    todo = seed(api, "삭제 대상")
    t = todo["title"]
    page.goto("/")
    delete = page.get_by_role("button", name=f"{t} 삭제")
    delete.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("할 일을 삭제할까요?")
    expect(dialog).to_contain_text(f'"{t}"')
    shot("UI-06-confirm-dialog")

    dialog.get_by_role("button", name="취소").click()
    expect(dialog).to_be_hidden()
    expect(row(page, t)).to_be_visible()
    expect(delete).to_be_focused()                                       # 닫으면 포커스가 삭제 버튼으로 돌아온다

    delete.click()
    dialog.get_by_role("button", name="삭제", exact=True).click()
    expect(row(page, t)).to_have_count(0)
    expect(page.get_by_role("button", name="할 일 추가")).to_be_focused()  # 삭제 버튼이 사라지면 "할 일 추가" 로
    assert todo["id"] not in [x["id"] for x in api.get("/todos").json()]


def test_ui07_maxlength_and_xss(page: Page, api):
    name = open_adder(page)
    name.press_sequentially("a" * 101)
    expect(name).to_have_value("a" * 100)                               # maxLength=100 이라 101번째 글자는 안 들어간다
    name.press("Escape")

    xss = title("<img src=x onerror=window.__xss=1>")
    name = open_adder(page)
    name.fill(xss)
    name.press("Enter")
    expect(row(page, xss).locator(".task-title")).to_have_text(xss)     # 태그가 아니라 글자 그대로 보인다
    expect(page.locator("li.task img")).to_have_count(0)
    assert page.evaluate("window.__xss") is None                         # onerror 스크립트가 실행되지 않음


def test_ui08_load_failure_and_retry(page: Page, shot):
    page.route("**/todos", lambda route: route.abort())                 # 서버가 죽은 상황을 흉내
    page.goto("/")
    expect(page.get_by_text("목록을 불러오지 못했습니다")).to_be_visible()
    expect(page.get_by_role("button", name="할 일 추가")).to_have_count(0)
    shot("UI-08-load-failed")

    page.unroute("**/todos")
    page.get_by_role("button", name="다시 불러오기").click()
    expect(page.get_by_role("button", name="할 일 추가")).to_be_visible()
    expect(page.get_by_text("목록을 불러오지 못했습니다")).to_have_count(0)


def test_ui08_save_failure_toast(page: Page, api, shot):
    page.route("**/todos", lambda route: route.fulfill(status=500, body="error")
               if route.request.method == "POST" else route.continue_())  # 추가(POST)만 500 응답
    t = title("저장 실패")
    name = open_adder(page)
    name.fill(t)
    name.press("Enter")
    expect(page.get_by_role("status")).to_have_text("추가에 실패했습니다. (500)")
    expect(name).to_have_value(t)                                        # 실패하면 입력값을 지우지 않는다
    shot("UI-08-save-failed-toast")
    assert t not in [x["title"] for x in api.get("/todos").json()]


def test_ui09_mobile_layout(page: Page, api, shot):
    seed(api, "모바일 화면에서 줄바꿈되는 긴 제목 " + "가나다라마바사" * 7, priority=2)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto("/")
    expect(row(page, TAG)).to_be_visible()
    expect(page.get_by_role("button", name="할 일 추가")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")  # 가로 스크롤 없음
    expect(row(page, TAG).locator(".task-actions")).to_have_css("opacity", "1")  # hover 가 없어도 편집·삭제가 보인다
    for button in row(page, TAG).locator(".icon-btn").all():
        box = button.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44                # 손가락으로 누르기 쉬운 크기
    shot("UI-09-mobile")


def test_ui10_keyboard_focus(page: Page, api, shot):
    t = seed(api, "키보드")["title"]
    page.goto("/")
    page.get_by_role("checkbox", name=f"{t} 완료", exact=True).focus()
    page.keyboard.press("Space")                                         # 완료 → 접힌 "완료됨" 섹션으로 옮겨진다
    expect(page.locator(".done-section summary")).to_be_focused()        # 포커스가 body 로 빠지지 않고 섹션 제목에 남는다
    page.keyboard.press("Enter")                                         # 펼친 뒤
    page.get_by_role("checkbox", name=f"{t} 완료 취소").focus()
    page.keyboard.press("Space")                                         # 완료 취소 → 목록으로 돌아온 같은 항목
    expect(page.get_by_role("checkbox", name=f"{t} 완료", exact=True)).to_be_focused()

    page.get_by_role("button", name=f"{t} 편집").focus()
    page.keyboard.press("Enter")
    expect(page.get_by_label("할 일 이름")).to_be_focused()
    page.keyboard.type(" 수정")
    page.keyboard.press("Enter")                                         # 저장 → 같은 항목의 편집 버튼
    expect(page.get_by_role("button", name=f"{t} 수정 편집")).to_be_focused()
    shot("UI-10-focus-after-save")

    page.get_by_role("button", name="할 일 추가").click()
    page.keyboard.press("Escape")                                        # 추가 폼 닫기 → "할 일 추가" 버튼
    expect(page.get_by_role("button", name="할 일 추가")).to_be_focused()


def test_ui11_priority_buttons(page: Page, api):
    name = open_adder(page)
    group = page.get_by_role("group", name="우선순위 (1이 가장 높음)")
    expect(group.get_by_role("button")).to_have_count(4)                # .all() 은 기다리지 않으므로 먼저 확인
    for button, label in zip(group.get_by_role("button").all(),
                             ["우선순위 1 (가장 높음)", "우선순위 2", "우선순위 3", "우선순위 4 (기본)"]):
        expect(button).to_have_accessible_name(label)                    # 화면 낭독기가 숫자만 읽지 않는다

    t = title("우선순위 후 Enter")
    name.fill(t)
    group.get_by_role("button", name="우선순위 2", exact=True).click()   # 마우스로 고르면
    expect(name).to_be_focused()                                         # 제목칸으로 돌아와서
    page.keyboard.press("Enter")                                         # 바로 Enter 로 제출된다
    expect(row(page, t)).to_contain_text("우선순위 2")
    assert [x["priority"] for x in api.get("/todos").json() if x["title"] == t] == [2]

    prio3 = group.get_by_role("button", name="우선순위 3", exact=True)
    prio3.focus()
    page.keyboard.press("Space")                                         # 키보드로 고르면
    expect(prio3).to_have_attribute("aria-pressed", "true")
    expect(prio3).to_be_focused()                                        # 포커스는 버튼에 남아 Tab 이동을 이어 간다
