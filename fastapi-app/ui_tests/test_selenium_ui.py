from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from conftest import TAG, seed, summary, title

# Selenium 은 자동 대기가 없어 모든 화면 변화를 WebDriverWait 로 명시적으로 기다린다


def wait(driver, timeout=10):                    # 찾은 직후 목록이 다시 그려지면 stale → 다시 찾도록 무시한다
    return WebDriverWait(driver, timeout, ignored_exceptions=[StaleElementReferenceException])


def open_app(driver, base_url):
    driver.get(f"{base_url}/")
    return wait(driver).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".add-trigger")))  # 로딩이 끝나야 생긴다


def open_adder(driver, base_url):
    open_app(driver, base_url).click()
    return wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[aria-label="할 일 이름"]')))


def row_xpath(todo_title):
    return f"//li[contains(@class,'task')][.//div[@class='task-title' and text()='{todo_title}']]"


def wait_row(driver, todo_title):
    return wait(driver).until(EC.presence_of_element_located((By.XPATH, row_xpath(todo_title))))


def css(driver, selector):
    return driver.find_element(By.CSS_SELECTOR, selector)


def submit_button(driver):
    return css(driver, "#adder button[type=submit]")


def prio_button(driver, priority):
    return css(driver, f'.prio-btn[data-priority="{priority}"]')


def wait_focus(driver, selector):                # 다시 그린 뒤 포커스가 selector 로 옮겨질 때까지 기다린다
    wait(driver).until(lambda d: d.switch_to.active_element == css(d, selector))


def hover_click(driver, todo_title, action):    # 편집·삭제 버튼은 opacity:0 → hover 로 보이게 한 뒤 클릭
    row = wait_row(driver, todo_title)
    button = row.find_element(By.CSS_SELECTOR, f'[aria-label="{todo_title} {action}"]')
    ActionChains(driver).move_to_element(row).perform()
    wait(driver).until(EC.element_to_be_clickable(button)).click()
    return button


def test_ui01_page_load(driver, base_url, api, shot):
    open_app(driver, base_url)
    assert driver.title == "Todo"
    assert css(driver, "h1").text == "전체"
    s = summary(api)
    assert css(driver, "#view-count").text == f"{s['total']}개"
    if s["total"] == 0:
        assert "할 일이 없습니다" in css(driver, "#list-area").text
        assert not css(driver, "#progress").is_displayed()
    else:
        assert css(driver, "#progress-text").text == s["text"]
    shot("UI-01-load")


# 콘솔 에러(favicon 404) 확인은 Playwright 에서만 한다 — Selenium 은 브라우저 로그를 받으려면 따로 설정해야 한다


def test_ui02_add_todo(driver, base_url, api, shot):
    t = title("장보기")
    name = open_adder(driver, base_url)
    assert not submit_button(driver).is_enabled()
    name.send_keys("   ")
    assert not submit_button(driver).is_enabled()                       # 공백만 입력해도 제출 불가
    name.send_keys(Keys.CONTROL, "a")
    name.send_keys(t)
    css(driver, 'textarea[aria-label="설명"]').send_keys("우유, 계란")
    prio_button(driver, 2).click()
    assert prio_button(driver, 2).get_attribute("aria-pressed") == "true"
    shot("UI-02-add-form")
    name.send_keys(Keys.ENTER)

    row = wait_row(driver, t)
    assert "우유, 계란" in row.text and "우선순위 2" in row.text
    wait(driver).until(lambda d: prio_button(d, 4).get_attribute("aria-pressed") == "true")  # 연속 등록: 입력 초기화
    name = css(driver, 'input[aria-label="할 일 이름"]')
    assert name.get_property("value") == ""
    assert driver.switch_to.active_element == name
    assert not submit_button(driver).is_enabled()
    saved = [x for x in api.get("/todos").json() if x["title"] == t]
    assert [(x["description"], x["priority"], x["completed"]) for x in saved] == [("우유, 계란", 2, False)]
    shot("UI-02-added")


def test_ui03_priority_sort(driver, base_url, api, shot):
    for name, priority in [("보통", 3), ("급함", 1), ("기본", 4)]:
        seed(api, name, priority=priority)
    open_app(driver, base_url)
    rows = driver.find_elements(By.XPATH, f"//li[contains(@class,'task')][.//div[starts-with(text(), '{TAG}')]]")
    assert [r.find_element(By.CLASS_NAME, "task-title").text for r in rows] == [title("급함"), title("보통"), title("기본")]
    for r, (priority, color) in zip(rows, [("1", "rgba(209, 69, 59, 1)"), ("3", "rgba(36, 111, 224, 1)"), ("4", "rgba(188, 188, 188, 1)")]):
        check = r.find_element(By.CSS_SELECTOR, "[role=checkbox]")
        assert check.get_attribute("data-priority") == priority
        assert check.value_of_css_property("border-top-color") == color    # 릴리즈 노트의 색: 빨강 / 파랑 / 회색
        assert f"우선순위 {priority}" in r.text
    shot("UI-03-sorted")


def test_ui04_complete_and_progress(driver, base_url, api, shot):
    t = seed(api, "빨래")["title"]
    open_app(driver, base_url)
    css(driver, f'[aria-label$="{t} 완료"]').click()

    wait(driver).until(lambda d: d.find_element(By.XPATH, row_xpath(t)).get_attribute("data-done") == "true")
    s = summary(api)
    wait(driver).until(EC.text_to_be_present_in_element((By.ID, "progress-text"), s["text"]))
    assert css(driver, ".done-section .done-count").text == str(s["done"])
    assert css(driver, "[role=progressbar]").get_attribute("aria-valuenow") == str(s["done"])

    css(driver, ".done-section summary").click()                        # 펼치면 취소선과 함께 보인다
    row = wait(driver).until(EC.visibility_of_element_located((By.XPATH, row_xpath(t))))
    assert "line-through" in row.find_element(By.CLASS_NAME, "task-title").value_of_css_property("text-decoration-line")
    shot("UI-04-done-section")

    css(driver, f'[aria-label$="{t} 완료 취소"]').click()
    wait(driver).until(lambda d: d.find_element(By.XPATH, f"//div[@id='list-area']{row_xpath(t)}").get_attribute("data-done") == "false")
    wait(driver).until(EC.text_to_be_present_in_element((By.ID, "progress-text"), summary(api)["text"]))


def test_ui05_edit(driver, base_url, api, shot):
    todo = seed(api, "보고서", description="초안", priority=1)
    t = todo["title"]
    open_app(driver, base_url)
    edit = wait_row(driver, t).find_element(By.CSS_SELECTOR, f'[aria-label="{t} 편집"]')
    assert not edit.is_displayed()                                       # opacity:0 이라 Selenium 은 "안 보임"으로 판단
    hover_click(driver, t, "편집")
    name = wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[aria-label="할 일 이름"]')))
    assert name.get_property("value") == t
    assert css(driver, 'textarea[aria-label="설명"]').get_property("value") == "초안"
    assert prio_button(driver, 1).get_attribute("aria-pressed") == "true"

    name.send_keys(" 바뀜", Keys.ESCAPE)                                 # Escape = 취소, 바뀌지 않는다
    assert wait_row(driver, t).find_element(By.CLASS_NAME, "task-title").text == t

    hover_click(driver, t, "편집")
    new_title = title("보고서 v2")
    name = wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[aria-label="할 일 이름"]')))
    name.send_keys(Keys.CONTROL, "a")
    name.send_keys(new_title)
    prio_button(driver, 3).click()
    shot("UI-05-edit-card")
    driver.find_element(By.XPATH, "//button[text()='저장']").click()

    assert "우선순위 3" in wait_row(driver, new_title).text
    saved = next(x for x in api.get("/todos").json() if x["id"] == todo["id"])
    assert saved == {**todo, "title": new_title, "priority": 3}         # 설명·완료 상태는 PUT 후에도 유지


def test_ui06_delete_with_confirm(driver, base_url, api, shot):
    todo = seed(api, "삭제 대상")
    t = todo["title"]
    open_app(driver, base_url)
    delete = hover_click(driver, t, "삭제")
    dialog = wait(driver).until(EC.visibility_of_element_located((By.ID, "confirm-dialog")))
    assert "할 일을 삭제할까요?" in dialog.text and f'"{t}"' in dialog.text
    shot("UI-06-confirm-dialog")

    css(driver, "#confirm-cancel").click()
    wait(driver).until(EC.invisibility_of_element(dialog))
    wait_row(driver, t)
    assert driver.switch_to.active_element == delete                     # 닫으면 포커스가 삭제 버튼으로 돌아온다

    hover_click(driver, t, "삭제")
    wait(driver).until(EC.element_to_be_clickable((By.ID, "confirm-ok"))).click()
    wait(driver).until(EC.invisibility_of_element_located((By.XPATH, row_xpath(t))))
    wait_focus(driver, ".add-trigger")                                    # 삭제 버튼이 사라지면 "할 일 추가" 로
    assert todo["id"] not in [x["id"] for x in api.get("/todos").json()]


def test_ui07_maxlength_and_xss(driver, base_url, api):
    name = open_adder(driver, base_url)
    name.send_keys("a" * 101)
    assert name.get_property("value") == "a" * 100                       # maxLength=100 이라 101번째 글자는 안 들어간다
    name.send_keys(Keys.ESCAPE)

    xss = title("<img src=x onerror=window.__xss=1>")
    name = open_adder(driver, base_url)
    name.send_keys(xss, Keys.ENTER)
    row = wait(driver).until(EC.presence_of_element_located((By.XPATH, row_xpath(xss))))  # 태그가 아니라 글자 그대로 보인다
    assert row.find_element(By.CLASS_NAME, "task-title").text == xss
    assert driver.find_elements(By.CSS_SELECTOR, "li.task img") == []
    assert driver.execute_script("return window.__xss") is None          # onerror 스크립트가 실행되지 않음


def test_ui08_load_failure_and_retry(driver, base_url, shot):
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*/todos"]})  # Chrome 전용(CDP)으로 서버 장애 흉내
    driver.get(f"{base_url}/")
    wait(driver).until(EC.text_to_be_present_in_element((By.ID, "list-area"), "목록을 불러오지 못했습니다"))
    assert driver.find_elements(By.CSS_SELECTOR, ".add-trigger") == []
    shot("UI-08-load-failed")

    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": []})
    driver.find_element(By.XPATH, "//button[text()='다시 불러오기']").click()
    wait(driver).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".add-trigger")))
    assert "목록을 불러오지 못했습니다" not in css(driver, "#list-area").text


# 저장 실패(POST 500) 토스트는 Selenium 만으로는 응답을 바꿔치기할 수 없어 Playwright 에서만 검증한다


def test_ui09_mobile_layout(driver, base_url, api, shot):
    seed(api, "모바일 화면에서 줄바꿈되는 긴 제목 " + "가나다라마바사" * 7, priority=2)
    driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride",
                           {"width": 375, "height": 812, "deviceScaleFactor": 1, "mobile": True})
    open_app(driver, base_url)
    assert driver.find_element(By.XPATH, f"//div[starts-with(text(), '{TAG}')]").is_displayed()
    assert driver.execute_script("return document.documentElement.scrollWidth <= document.documentElement.clientWidth")  # 가로 스크롤 없음
    row = driver.find_element(By.XPATH, f"//li[contains(@class,'task')][.//div[starts-with(text(), '{TAG}')]]")
    buttons = row.find_elements(By.CSS_SELECTOR, ".icon-btn")
    assert len(buttons) == 2
    for button in buttons:
        assert button.is_displayed()                                      # hover 가 없어도 보인다 (opacity 1)
        assert button.size["width"] >= 44 and button.size["height"] >= 44  # 손가락으로 누르기 쉬운 크기
    shot("UI-09-mobile")


def test_ui10_keyboard_focus(driver, base_url, api):
    t = seed(api, "키보드")["title"]
    open_app(driver, base_url)
    css(driver, f'[aria-label="{t} 완료"]').send_keys(Keys.SPACE)        # 완료 → 접힌 "완료됨" 섹션으로 옮겨진다
    wait_focus(driver, ".done-section summary")                          # 포커스가 body 로 빠지지 않는다

    css(driver, ".done-section summary").send_keys(Keys.ENTER)           # 펼친 뒤 완료 취소
    wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, f'[aria-label="{t} 완료 취소"]'))).send_keys(Keys.SPACE)
    wait_focus(driver, f'[aria-label="{t} 완료"]')                        # 목록으로 돌아온 같은 항목

    hover_click(driver, t, "편집")
    name = wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[aria-label="할 일 이름"]')))
    name.send_keys(" 수정", Keys.ENTER)                                    # 저장 → 같은 항목의 편집 버튼
    wait_focus(driver, f'[aria-label="{t} 수정 편집"]')

    css(driver, ".add-trigger").click()
    name = wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[aria-label="할 일 이름"]')))
    name.send_keys(Keys.ESCAPE)                                            # 추가 폼 닫기 → "할 일 추가" 버튼
    wait_focus(driver, ".add-trigger")


def test_ui11_priority_then_enter(driver, base_url, api):
    name = open_adder(driver, base_url)
    names = [b.accessible_name for b in driver.find_elements(By.CSS_SELECTOR, ".prio-btn")]
    assert names == ["우선순위 1 (가장 높음)", "우선순위 2", "우선순위 3", "우선순위 4 (기본)"]  # 숫자만 읽히지 않는다

    t = title("우선순위 후 Enter")
    name.send_keys(t)
    prio_button(driver, 2).click()                                        # 마우스로 고르면
    assert driver.switch_to.active_element == name                       # 제목칸으로 돌아와서
    ActionChains(driver).send_keys(Keys.ENTER).perform()                 # 바로 Enter 로 제출된다
    assert "우선순위 2" in wait_row(driver, t).text
    assert [x["priority"] for x in api.get("/todos").json() if x["title"] == t] == [2]
