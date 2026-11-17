import calendar
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

BASE_DIR = Path(__file__).resolve().parent       # main.py 가 있는 폴더
TODO_FILE = BASE_DIR / "todo.json"
INDEX_FILE = BASE_DIR / "templates" / "index.html"

if not TODO_FILE.exists():                       # 없으면 빈 목록으로 만들어 둔다
    TODO_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="To-Do List API", version="5.0.0")

# 요청은 스레드풀에서 동시에 돈다 → 읽기·수정·저장을 한 번에 하나씩 (uvicorn 프로세스 1개 기준, --workers 를 늘리면 부족함)
STORE_LOCK = threading.Lock()

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)  # Prometheus 계측

# 액세스 로그를 stdout 으로 → Docker 컨테이너 로그 → Alloy 가 읽어 Loki 로 보낸다
access_logger = logging.getLogger("todo.access")
access_logger.setLevel(logging.INFO)
if not access_logger.handlers:                   # 모듈을 다시 import 해도 핸들러가 겹쳐 두 줄씩 찍히지 않게
    access_logger.addHandler(logging.StreamHandler(sys.stdout))
access_logger.propagate = False                  # 상위 로거로 넘기면 같은 줄이 두 번 찍힌다

# uvicorn 기본 액세스 로그는 끈다 (켜 두면 요청 1번에 2줄 → 대시보드 카운트가 2배)
logging.getLogger("uvicorn.access").disabled = True


@app.middleware("http")                          # 모든 요청을 한 줄씩 기록
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    client = request.client.host if request.client else "-"
    # 형식: IP - "METHOD PATH HTTP/1.1" 상태코드 응답시간 → Grafana LogQL 쿼리가 이 형식으로 파싱
    access_logger.info(
        f'{client} - "{request.method} {request.url.path} HTTP/1.1" '
        f'{response.status_code} {duration:.3f}s'
    )
    return response

ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_iso_date(value):
    # FastAPI 는 요청 본문을 dict 로 검증해서 strict 모드가 "2026-10-31" 문자열을 거부한다
    # → "YYYY-MM-DD" 모양 문자열만 date 로 바꾼다. 다른 문자열은 여기서, 숫자 등은 strict 검증에서 422
    if isinstance(value, str):
        if not ISO_DATE.fullmatch(value):
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
        return date.fromisoformat(value)         # 없는 날짜(2026-02-30)는 ValueError → 422
    return value


IsoDate = Annotated[date, BeforeValidator(parse_iso_date)]
Repeat = Literal["daily", "weekly", "monthly"]

# strict: "2"→2, "yes"→True 같은 자동 변환을 하지 않는다 / 앞뒤 공백을 지운 뒤 길이를 검사한다
STRICT = ConfigDict(strict=True, str_strip_whitespace=True)


class SubtaskIn(BaseModel):                      # 하위 할 일 — id 없이 할 일 PUT 으로 목록째 바꾼다
    model_config = STRICT

    title: str = Field(min_length=1, max_length=100)
    completed: bool = False


class TodoIn(BaseModel):                         # 클라이언트가 보내는 데이터 (id 없음)
    model_config = STRICT

    title: str = Field(min_length=1, max_length=100)
    description: str = ""
    completed: bool = False
    priority: int = Field(default=4, ge=1, le=4)  # 1 이 가장 높다
    due_date: IsoDate | None = None              # 마감일 (날짜만, "YYYY-MM-DD") — 기한 지남 판단은 화면이 한다
    project_id: int | None = None                # null 은 수집함 — 있는지는 엔드포인트가 저장소를 보고 확인
    subtasks: list[SubtaskIn] = Field(default_factory=list, max_length=50)
    repeat: Repeat | None = None                 # 완료하면 다음 회차를 만든다 (update_todo)

    @model_validator(mode="after")
    def repeat_needs_due_date(self) -> "TodoIn":  # 다음 회차 날짜를 계산할 기준이 없다
        if self.repeat and self.due_date is None:
            raise ValueError("반복하려면 마감일이 있어야 합니다")
        return self


class TodoItem(TodoIn):                          # 서버가 돌려주는 데이터 (id 있음)
    id: int


class ProjectIn(BaseModel):
    model_config = STRICT

    name: str = Field(min_length=1, max_length=30)


class ProjectItem(ProjectIn):
    id: int


class TodoStore(BaseModel):                      # todo.json 전체 — 다음 id 를 따로 저장해 지운 id 를 다시 쓰지 않는다
    next_id: int = 1
    next_project_id: int = 1
    projects: list[ProjectItem] = []
    todos: list[TodoItem] = []

    @model_validator(mode="after")
    def next_id_after_max(self) -> "TodoStore":  # 옛 형식·직접 고친 파일에서도 id 가 겹치지 않게
        self.next_id = max(self.next_id, max((t.id for t in self.todos), default=0) + 1)
        self.next_project_id = max(self.next_project_id, max((p.id for p in self.projects), default=0) + 1)
        return self


def next_due(due: date, repeat: Repeat) -> date | None:
    # 반복 할 일의 다음 마감일 — 원래 마감일 기준. date 범위(9999-12-31)를 넘으면 None
    if repeat == "monthly":
        year, month = (due.year + 1, 1) if due.month == 12 else (due.year, due.month + 1)
        if year > date.max.year:
            return None
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(due.day, last_day))  # 1/31 → 2/28 (원래 31일이었는지는 기억하지 않는다)
    step = timedelta(days=1 if repeat == "daily" else 7)
    return due + step if date.max - due >= step else None


def load_store() -> TodoStore:
    raw = TODO_FILE.read_text(encoding="utf-8") if TODO_FILE.exists() else "[]"
    data = json.loads(raw)
    if isinstance(data, list):                   # v3 이하 형식: 할 일 목록만 저장했다
        data = {"todos": data}
    return TodoStore(**data)                     # 저장된 "YYYY-MM-DD" 는 parse_iso_date 가 date 로 바꾼다


def save_store(store: TodoStore) -> None:
    data = json.dumps(store.model_dump(mode="json"), indent=2, ensure_ascii=False)  # date → "YYYY-MM-DD"
    tmp = TODO_FILE.with_name(TODO_FILE.name + ".tmp")  # 같은 폴더에 다 쓴 뒤 한 번에 바꿔치기
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, TODO_FILE)                   # 쓰는 도중 멈춰도 todo.json 은 이전 내용 그대로 (빈 파일이 안 생김)


NOT_FOUND = {404: {"description": "To-Do item not found"}}  # find_index 가 던지는 404
PROJECT_NOT_FOUND = {404: {"description": "Project not found"}}
NAME_TAKEN = {409: {"description": "Project name already exists"}}


def find_index(todos: list[TodoItem], todo_id: int) -> int:
    for i, todo in enumerate(todos):
        if todo.id == todo_id:
            return i
    raise HTTPException(404, "To-Do item not found")


def find_project_index(projects: list[ProjectItem], project_id: int) -> int:
    for i, project in enumerate(projects):
        if project.id == project_id:
            return i
    raise HTTPException(404, "Project not found")


def check_project(store: TodoStore, project_id: int | None) -> None:
    # 저장소를 봐야 알 수 있어 모델 검증이 아니라 여기서 한다 — 모양은 FastAPI 검증 오류(422)와 맞춘다
    if project_id is not None and all(p.id != project_id for p in store.projects):
        raise HTTPException(422, [{"loc": ["body", "project_id"], "msg": "프로젝트가 없습니다", "type": "project_not_found"}])


def check_name_free(store: TodoStore, name: str, except_id: int | None = None) -> None:
    # 대소문자만 다른 이름도 같은 이름으로 본다 / 자기 이름을 다시 저장하는 것은 허용
    if any(p.name.casefold() == name.casefold() and p.id != except_id for p in store.projects):
        raise HTTPException(409, "Project name already exists")


SORT_KEYS = {
    "created": lambda t: t.id,
    "priority": lambda t: (t.priority, t.id),
    "due": lambda t: (t.due_date is None, t.due_date or date.min, t.priority, t.id),  # 마감일 없는 할 일은 뒤로
    "title": lambda t: (t.title.casefold(), t.id),
}


@app.get("/todos")                               # 목록 조회 — 쿼리가 없으면 v4 와 같이 전체를 id 순으로
def get_todos(
    q: Annotated[str | None, Query(description="제목이나 설명에 포함된 글자 (대소문자 무시)")] = None,
    project_id: Annotated[int | None, Query(ge=0, description="프로젝트 id. 0 은 수집함(프로젝트 없음)")] = None,
    priority: Annotated[int | None, Query(ge=1, le=4)] = None,
    status: Annotated[Literal["open", "done"] | None, Query(description="open: 미완료, done: 완료")] = None,
    sort: Annotated[Literal["created", "priority", "due", "title"], Query(description="created 는 id 순")] = "created",
) -> list[TodoItem]:
    with STORE_LOCK:                             # Windows 에서는 읽는 중인 파일을 os.replace 할 수 없다
        todos = load_store().todos
    keyword = (q or "").strip().casefold()
    if keyword:
        todos = [t for t in todos if keyword in t.title.casefold() or keyword in t.description.casefold()]
    if project_id is not None:
        wanted = project_id or None              # 쿼리의 0 → 저장된 null(수집함)
        todos = [t for t in todos if t.project_id == wanted]
    if priority is not None:
        todos = [t for t in todos if t.priority == priority]
    if status:
        todos = [t for t in todos if t.completed == (status == "done")]
    return sorted(todos, key=SORT_KEYS[sort])


@app.post("/todos", status_code=201)             # 추가 — id 는 서버가 매긴다
def create_todo(payload: TodoIn) -> TodoItem:
    with STORE_LOCK:                             # 두 요청이 같은 next_id 를 읽으면 id 가 겹치고 한쪽이 사라진다
        store = load_store()
        check_project(store, payload.project_id)
        todo = TodoItem(id=store.next_id, **payload.model_dump())
        store.todos.append(todo)
        store.next_id += 1
        save_store(store)
    return todo


@app.put("/todos/{todo_id}", responses=NOT_FOUND)  # 수정
def update_todo(todo_id: int, payload: TodoIn) -> TodoItem:
    with STORE_LOCK:
        store = load_store()
        index = find_index(store.todos, todo_id)
        check_project(store, payload.project_id)
        was_done = store.todos[index].completed  # 잠금 안에서 읽어야 동시 완료 요청이 회차를 두 번 만들지 않는다
        todo = TodoItem(id=todo_id, **payload.model_dump())
        upcoming_due = next_due(todo.due_date, todo.repeat) if todo.repeat and todo.completed and not was_done else None
        if upcoming_due:                         # 반복 할 일을 완료 → 다음 회차를 새로 만든다
            data = todo.model_dump()
            store.todos.append(TodoItem(**{
                **data, "id": store.next_id, "completed": False, "due_date": upcoming_due,
                "subtasks": [{**s, "completed": False} for s in data["subtasks"]],
            }))
            store.next_id += 1
            todo = todo.model_copy(update={"repeat": None})  # 반복은 새 회차가 이어받는다 → 완료 해제·재완료해도 회차가 또 생기지 않음
        store.todos[index] = todo
        save_store(store)
    return todo


@app.delete("/todos/{todo_id}", status_code=204, responses=NOT_FOUND)  # 삭제
def delete_todo(todo_id: int) -> None:
    with STORE_LOCK:
        store = load_store()
        del store.todos[find_index(store.todos, todo_id)]
        save_store(store)


@app.get("/projects")                            # 프로젝트 목록 (id 순)
def get_projects() -> list[ProjectItem]:
    with STORE_LOCK:
        return load_store().projects


@app.post("/projects", status_code=201, responses=NAME_TAKEN)  # 프로젝트 추가
def create_project(payload: ProjectIn) -> ProjectItem:
    with STORE_LOCK:
        store = load_store()
        check_name_free(store, payload.name)
        project = ProjectItem(id=store.next_project_id, **payload.model_dump())
        store.projects.append(project)
        store.next_project_id += 1
        save_store(store)
    return project


@app.put("/projects/{project_id}", responses={**PROJECT_NOT_FOUND, **NAME_TAKEN})  # 이름 변경
def update_project(project_id: int, payload: ProjectIn) -> ProjectItem:
    with STORE_LOCK:
        store = load_store()
        index = find_project_index(store.projects, project_id)
        check_name_free(store, payload.name, except_id=project_id)
        project = ProjectItem(id=project_id, **payload.model_dump())
        store.projects[index] = project
        save_store(store)
    return project


@app.delete("/projects/{project_id}", status_code=204, responses=PROJECT_NOT_FOUND)  # 삭제 — 안의 할 일도 함께
def delete_project(project_id: int) -> None:
    with STORE_LOCK:
        store = load_store()
        del store.projects[find_project_index(store.projects, project_id)]
        store.todos = [t for t in store.todos if t.project_id != project_id]
        save_store(store)


@app.get("/", include_in_schema=False)           # 화면 서빙
def read_root() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html")