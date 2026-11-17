# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

FastAPI To-Do 앱 (API 5.0.0). DB 없이 `todo.json` 파일에 저장하고, 화면은 `templates/index.html` 한 파일(바닐라 JS)을 `/` 에서 서빙한다.

## 명령어 (모두 `fastapi-app/` 에서)

```powershell
# 설치 — Windows 는 PYTHONUTF8=1 필수 (requirements*.txt 의 한글 주석을 cp949 로 읽다가 실패함)
python -m venv .venv
$env:PYTHONUTF8 = "1"; .venv\Scripts\python.exe -m pip install -r requirements.txt
#   Git Bash: PYTHONUTF8=1 .venv/Scripts/python.exe -m pip install -r requirements.txt

# 테스트
.venv\Scripts\python.exe -m pytest                                   # 전체
.venv\Scripts\python.exe -m pytest tests/test_main.py::test_lifecycle  # 하나만
.venv\Scripts\python.exe -m pytest --cov=. --cov-report=xml            # SonarQube 용 coverage.xml

# UI 테스트 (Playwright, 설치된 Chrome 사용) — 서버를 먼저 띄워야 하고 기본 pytest 에는 포함되지 않는다
$env:PYTHONUTF8 = "1"; .venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.venv\Scripts\python.exe -m pytest ui_tests          # 기본 대상 http://localhost:8000 , 다른 서버는 $env:BASE_URL, 창 보기는 $env:HEADED = "1"
git restore todo.json                                # 로컬 서버로 돌리면 todo.json 이 바뀐다

# 실행
.venv\Scripts\python.exe -m uvicorn main:app --reload    # http://localhost:8000 , 문서 /docs
docker compose up -d --build fastapi-app                 # (저장소 루트) http://localhost:5005
docker compose up -d sonarqube                           # (저장소 루트) http://localhost:9000
docker compose up -d prometheus grafana node-exporter cadvisor  # (저장소 루트) 모니터링: Grafana http://localhost:3000
docker compose up -d influxdb grafana                    # (저장소 루트) JMeter 결과 저장용 InfluxDB 1.x
$env:JMETER_LOOPS = "30"; docker compose run --rm jmeter # 부하 테스트 → InfluxDB. JMETER_THREADS / JMETER_LOOPS / JMETER_RAMP 생략 시 10명·1회·10초
#   리눅스 서버(~/FastApi_Todos-deploy, 도메인 계정): JMETER_LOOPS=30 docker compose run --rm --user "$(id -u):$(id -g)" jmeter
docker exec influxdb influx -database jmeter -execute "SELECT count(*) FROM jmeter"   # 저장 확인
```

## 컨벤션

- 코드 주석·커밋 메시지·문서는 한국어. 주석은 줄 끝에 짧게 "왜"를 적는 스타일.
- 새 기능은 코드 전에 `/intent` 스킬로 `intent/<slug>/intent.md` 를 쓴다. 커밋은 사용자 승인 후.
- 작업 브랜치에서 작업하고 `main` 으로 PR.
- SonarQube 토큰은 파일에 쓰지 않는다 (Jenkins Credentials 로만).

## 구조

- `main.py` 하나에 API 전부. 모델은 `TodoIn`(입력, id 없음) → `TodoItem`(+id) → `TodoStore`(파일 전체: `next_id` + `next_project_id` + `projects` + `todos`). 프로젝트는 `ProjectIn`/`ProjectItem`, 하위 할 일은 `SubtaskIn`(id 없음, 할 일 PUT 으로 목록째 교체).
- 모든 엔드포인트가 `with STORE_LOCK:` 안에서 `load_store()` → 수정 → `save_store()`. 캐시 없음. `save_store()` 는 `todo.json.tmp` 에 쓴 뒤 `os.replace` 로 바꿔치기한다. uvicorn 프로세스 1개 전제(`--workers` 금지).
- 할 일 필드: `title`, `description`, `completed`, `priority`(1~4), `due_date`(`"YYYY-MM-DD"` 또는 `null`), `project_id`(`null` = 수집함), `subtasks`(최대 50), `repeat`(`daily`/`weekly`/`monthly`, 마감일 필수). "기한 지남" 판단은 서버가 아니라 화면이 브라우저 로컬 날짜로 한다.
- 반복: `update_todo` 가 잠금 안에서 "저장된 값은 미완료 → 요청은 완료"일 때만 `next_due()` 로 다음 회차를 새 id 로 만들고, 완료한 쪽의 `repeat` 는 `null` 로 바꾼다. 매월은 말일로 맞추고 원래 날짜를 기억하지 않는다(1/31 → 2/28 → 3/28). 화면의 `nextDue()` 는 알림용 복사본이라 규칙을 바꾸면 둘 다 고친다.
- `GET /todos` 쿼리 `q`, `project_id`(0 = 수집함), `priority`, `status`(open/done), `sort`(created 기본/priority/due/title). 쿼리가 없으면 v4 와 같은 전체 목록. 프로젝트 삭제는 안의 할 일도 함께 지운다.
- 화면(`index.html`): 보기 상태(프로젝트·검색·필터·정렬)는 주소 쿼리에 둔다(`readView`/`writeView`). `load()` 는 `/projects`, 전체 `/todos`(사이드바 개수·진행률), 조건 `/todos` 를 함께 받는다. 열린 폼은 `state.*Form` 에 두어 다시 그려도 새로 만들지 않는다.
- `tests/test_main.py`: API 단위 테스트. autouse fixture 가 `main.TODO_FILE` 을 임시 파일로 바꾼다.
- `ui_tests/`: 실행 중인 서버를 대상으로 하는 Playwright 테스트(`test_due_date_ui.py`, `test_v5_ui.py`). 제목·이름이 `[UI테스트 …]` 인 할 일과 프로젝트만 만들고 지운다. 프로젝트 이름은 30자 제한이라 태그(14자) 뒤에 짧게.
- 기능 문서는 `intent/<slug>/` 에 intent.md → spec.md → plan.md 순서로 쌓는다.
- `GET /metrics`: `prometheus-fastapi-instrumentator` 가 노출하는 Prometheus 메트릭 (Swagger 문서에는 숨김).
- `docker-compose.yml`(루트): 앱(5005→8000) + SonarQube(설정은 `sonar-project.properties`) + 모니터링(Prometheus `127.0.0.1:7070`, Grafana 3000, node-exporter, cadvisor). 수집 대상은 `prometheus/prometheus.yml`.
- InfluxDB 1.x(포트 비공개, DB `jmeter`): JMeter 의 Backend Listener 가 테스트 도중 결과를 밀어 넣는다(Prometheus 와 반대로 push). Grafana 데이터 소스 `InfluxDB-JMeter` 는 `grafana/provisioning/datasources/` 파일로 자동 등록되고, 대시보드는 UI 에서 5496 을 import 한다.

## Claude가 자주 틀리는 것

- **시스템 `python` 으로 pytest 실행** → "No module named pytest". 항상 `.venv` 의 Python 을 쓴다.
- **pip 설치 실패를 패키지 문제로 착각** → 원인은 인코딩. `PYTHONUTF8=1` 을 붙인다. 주석을 지우거나 영어로 바꾸지 말 것.
- **`TODO_FILE` 경로를 고정** (기본 인자, import 시점 상수 복사) → 테스트의 monkeypatch 가 안 먹고 실제 `todo.json` 이 바뀐다. 함수 안에서 매번 `TODO_FILE` 을 참조할 것.
- **PUT 을 부분 수정으로 구현** → PUT 은 전체 교체다. 생략한 필드는 기본값으로 돌아가고, 테스트도 이걸 검사한다.
- **`strict=True` 를 풀거나 우회** → `"2"`, `true`, `"yes"` 같은 값을 422 로 거부하는 것이 의도된 동작이다.
- **`due_date` 를 그냥 `date` 로 선언** → FastAPI 는 요청 본문을 dict 로 검증해서, strict 모드에서는 올바른 `"2026-10-31"` 도 422 가 된다. `parse_iso_date` 검증기(`IsoDate`)가 필요하다. 저장도 `model_dump(mode="json")` 이어야 한다(아니면 `TypeError`).
- **화면에서 날짜를 `Date` 로 파싱하거나 `toISOString()` 사용** → UTC 기준이라 한국에서 오전 9시 전에는 하루가 어긋난다. `"YYYY-MM-DD"` 문자열로 비교한다(`todayLocal`, `isOverdue`).
- **편집 PUT 에서 `due_date` 를 빼먹음** → 전체 교체라 마감일이 지워지거나, 지운 마감일이 남는다. 지울 때도 `null` 을 보낸다.
- **화면에서 할 일 PUT 본문을 직접 만듦** → `subtasks`·`repeat`·`project_id` 하나만 빠져도 사용자가 적은 하위 할 일이 통째로 사라진다. 항상 `todoBody(todo, changes)` 로 만든다. 하위 할 일 체크는 `completed` 를 그대로 보내야 반복 회차가 생기지 않는다.
- **반복 회차 판단을 잠금 밖에서 하거나 완료 쪽 `repeat` 를 남김** → 더블 클릭·완료 해제 후 재완료 때 회차가 중복된다. `test_repeat_concurrent_complete`, `test_repeat_uncheck_and_recheck` 가 잡는다.
- **없는 프로젝트 확인(`check_project`)을 모델 검증기로 옮김** → 저장소를 봐야 해서 엔드포인트의 `STORE_LOCK` 안에서만 할 수 있다. 본문의 `project_id: 0` 은 422 이고, 쿼리의 `project_id=0` 은 수집함이다(의미가 다름).
- **화면 버튼·라벨 이름에 기존 로케이터가 들어감** → Playwright `name=` 은 부분 일치라 "하위 할 일 추가" 같은 이름이 `"할 일 추가"` 를 쓰는 기존 UI 테스트를 strict 위반으로 깨뜨린다. 그래서 "하위 항목 추가", "프로젝트 삭제", "이름 저장" 같은 이름을 쓴다. 폼 선택 상자 라벨 "프로젝트" 와 겹치지 않게 사이드바는 "프로젝트 목록", 좁은 화면 선택 상자는 "프로젝트 보기".
- **`replaceChildren(a, b, null)`** → `make()` 와 달리 `null` 을 걸러 주지 않아 화면에 "null" 글자가 찍힌다. `.filter(Boolean)` 을 붙인다.
- **새 엔드포인트에서 `STORE_LOCK` 없이 `load_store()`/`save_store()` 호출, 또는 `TODO_FILE.write_text()` 로 직접 저장** → 동시 요청 때 빈 파일을 읽어 500, id 중복·누락(v4.1.0 에서 JMeter 3,000건 중 314건 실패). `test_concurrent_requests` 가 잡는다.
- **삭제된 id 재사용 / `max(id)+1` 로 새 id 계산** → 반드시 `store.next_id` 를 쓴다.
- **v3 목록 형식(`[...]`) 읽기 코드 삭제** → `todo.json` 이 아직 옛 형식일 수 있다. 하위 호환을 유지할 것.
- **`httpx` 를 의존성에 추가** → 이 프로젝트는 `httpx2` 를 쓴다.
- **`main.py` 를 고치다 `Instrumentator().instrument(app)...` 줄을 지움** → `/metrics` 가 404 가 되어 Prometheus 수집과 Grafana 대시보드가 빈다. 충돌 해결·리팩터링 때 남아 있는지 확인한다.
- **수동 테스트로 바뀐 `fastapi-app/todo.json` 을 커밋** → git 에 추적되는 파일이라 서버를 돌리면 diff 가 생긴다. 의도한 변경이 아니면 커밋하지 않는다.
- **서버에서 JMeter 가 `jmeter.log (Permission denied)`, `Cannot write to '/jmeter/report'`** → 이미지는 uid 1000 인데 서버 계정은 도메인 uid 라 `./jmeter` 에 못 쓴다. `--user "$(id -u):$(id -g)"` 로 돌린다. `chmod 777` / `chown 1000` 은 하지 않는다.
- **에러율 100% + `UnknownHostException: fastapi-app`** → 앱 컨테이너가 `loadtest-net` 에 없다(네트워크 설정 전에 만든 컨테이너). `docker network connect --alias fastapi-app <프로젝트>_loadtest-net FastApi-app2` 로 연결한다. 앱 컨테이너를 다시 만들면 컨테이너 안의 `todo.json` 이 이미지 것으로 돌아가니 함부로 `up` 으로 재생성하지 않는다.
- **`pytest` 만 돌리고 UI 까지 확인했다고 생각** → `testpaths = ["tests"]` 라 `ui_tests/` 는 따로 `pytest ui_tests` 로 돌려야 한다. `integration_tests/` 는 커밋 33dfed3 에서 삭제됐다.
