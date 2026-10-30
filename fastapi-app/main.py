import json
import re
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

BASE_DIR = Path(__file__).resolve().parent       # main.py 가 있는 폴더
TODO_FILE = BASE_DIR / "todo.json"
INDEX_FILE = BASE_DIR / "templates" / "index.html"

if not TODO_FILE.exists():                       # 없으면 빈 목록으로 만들어 둔다
    TODO_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="To-Do List API", version="4.1.0")

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


class TodoIn(BaseModel):                         # 클라이언트가 보내는 데이터 (id 없음)
    # strict: "2"→2, "yes"→True 같은 자동 변환을 하지 않는다 / 앞뒤 공백을 지운 뒤 길이를 검사한다
    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=100)
    description: str = ""
    completed: bool = False
    priority: int = Field(default=4, ge=1, le=4)  # 1 이 가장 높다
    due_date: IsoDate | None = None              # 마감일 (날짜만, "YYYY-MM-DD") — 기한 지남 판단은 화면이 한다


class TodoItem(TodoIn):                          # 서버가 돌려주는 데이터 (id 있음)
    id: int


class TodoStore(BaseModel):                      # todo.json 전체 — 다음 id 를 따로 저장해 지운 id 를 다시 쓰지 않는다
    next_id: int = 1
    todos: list[TodoItem] = []

    @model_validator(mode="after")
    def next_id_after_max(self) -> "TodoStore":  # 옛 형식·직접 고친 파일에서도 id 가 겹치지 않게
        self.next_id = max(self.next_id, max((t.id for t in self.todos), default=0) + 1)
        return self


def load_store() -> TodoStore:
    raw = TODO_FILE.read_text(encoding="utf-8") if TODO_FILE.exists() else "[]"
    data = json.loads(raw)
    if isinstance(data, list):                   # v3 이하 형식: 할 일 목록만 저장했다
        data = {"todos": data}
    return TodoStore(**data)                     # 저장된 "YYYY-MM-DD" 는 parse_iso_date 가 date 로 바꾼다


def save_store(store: TodoStore) -> None:
    data = json.dumps(store.model_dump(mode="json"), indent=2, ensure_ascii=False)  # date → "YYYY-MM-DD"
    TODO_FILE.write_text(data, encoding="utf-8")


NOT_FOUND = {404: {"description": "To-Do item not found"}}  # find_index 가 던지는 404


def find_index(todos: list[TodoItem], todo_id: int) -> int:
    for i, todo in enumerate(todos):
        if todo.id == todo_id:
            return i
    raise HTTPException(404, "To-Do item not found")


@app.get("/todos")                               # 목록 조회
def get_todos() -> list[TodoItem]:
    return load_store().todos


@app.post("/todos", status_code=201)             # 추가 — id 는 서버가 매긴다
def create_todo(payload: TodoIn) -> TodoItem:
    store = load_store()
    todo = TodoItem(id=store.next_id, **payload.model_dump())
    store.todos.append(todo)
    store.next_id += 1
    save_store(store)
    return todo


@app.put("/todos/{todo_id}", responses=NOT_FOUND)  # 수정
def update_todo(todo_id: int, payload: TodoIn) -> TodoItem:
    store = load_store()
    todo = TodoItem(id=todo_id, **payload.model_dump())
    store.todos[find_index(store.todos, todo_id)] = todo
    save_store(store)
    return todo


@app.delete("/todos/{todo_id}", status_code=204, responses=NOT_FOUND)  # 삭제
def delete_todo(todo_id: int) -> None:
    store = load_store()
    del store.todos[find_index(store.todos, todo_id)]
    save_store(store)


@app.get("/", include_in_schema=False)           # 화면 서빙
def read_root() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html")