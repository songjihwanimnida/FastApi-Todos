# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

FastAPI To-Do 앱 (API 4.0.0). DB 없이 `todo.json` 파일에 저장하고, 화면은 `templates/index.html` 한 파일(바닐라 JS)을 `/` 에서 서빙한다.

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

# 실행
.venv\Scripts\python.exe -m uvicorn main:app --reload    # http://localhost:8000 , 문서 /docs
docker compose up -d --build fastapi-app                 # (저장소 루트) http://localhost:5005
docker compose up -d sonarqube                           # (저장소 루트) http://localhost:9000
```

## 컨벤션

- 코드 주석·커밋 메시지·문서는 한국어. 주석은 줄 끝에 짧게 "왜"를 적는 스타일.
- 새 기능은 코드 전에 `/intent` 스킬로 `intent/<slug>/intent.md` 를 쓴다. 커밋은 사용자 승인 후.
- 작업 브랜치에서 작업하고 `main` 으로 PR.
- SonarQube 토큰은 파일에 쓰지 않는다 (Jenkins Credentials 로만).

## 구조

- `main.py` 하나에 API 전부. 모델은 `TodoIn`(입력, id 없음) → `TodoItem`(+id) → `TodoStore`(파일 전체: `next_id` + `todos`).
- 모든 엔드포인트가 `load_store()` → 수정 → `save_store()`. 캐시·잠금 없음.
- `tests/test_main.py` 가 유일한 테스트. autouse fixture 가 `main.TODO_FILE` 을 임시 파일로 바꾼다.
- `docker-compose.yml`(루트): 앱(5005→8000) + SonarQube. 설정은 `sonar-project.properties`.

## Claude가 자주 틀리는 것

- **시스템 `python` 으로 pytest 실행** → "No module named pytest". 항상 `.venv` 의 Python 을 쓴다.
- **pip 설치 실패를 패키지 문제로 착각** → 원인은 인코딩. `PYTHONUTF8=1` 을 붙인다. 주석을 지우거나 영어로 바꾸지 말 것.
- **`TODO_FILE` 경로를 고정** (기본 인자, import 시점 상수 복사) → 테스트의 monkeypatch 가 안 먹고 실제 `todo.json` 이 바뀐다. 함수 안에서 매번 `TODO_FILE` 을 참조할 것.
- **PUT 을 부분 수정으로 구현** → PUT 은 전체 교체다. 생략한 필드는 기본값으로 돌아가고, 테스트도 이걸 검사한다.
- **`strict=True` 를 풀거나 우회** → `"2"`, `true`, `"yes"` 같은 값을 422 로 거부하는 것이 의도된 동작이다.
- **삭제된 id 재사용 / `max(id)+1` 로 새 id 계산** → 반드시 `store.next_id` 를 쓴다.
- **v3 목록 형식(`[...]`) 읽기 코드 삭제** → `todo.json` 이 아직 옛 형식일 수 있다. 하위 호환을 유지할 것.
- **`httpx` 를 의존성에 추가** → 이 프로젝트는 `httpx2` 를 쓴다.
- **수동 테스트로 바뀐 `fastapi-app/todo.json` 을 커밋** → git 에 추적되는 파일이라 서버를 돌리면 diff 가 생긴다. 의도한 변경이 아니면 커밋하지 않는다.
- **`ui_tests/`, `integration_tests/` 가 있다고 가정** → 커밋 33dfed3 에서 삭제됐다. `requirements-ui.txt` 만 남아 있다.
