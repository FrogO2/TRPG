"""FastAPI app for the local TRPG runtime website."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from web.services import NOTEBOOK_NAMES, RuntimeWebService

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TRPG Runtime Web", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
service = RuntimeWebService()


class InitRequest(BaseModel):
    order: list[str] = Field(default_factory=list)


class SetOrderRequest(BaseModel):
    order: list[str] = Field(default_factory=list)
    reason: str = ""


class HumanTurnRequest(BaseModel):
    message: str
    no_advance: bool = False


class AITurnRequest(BaseModel):
    message: str = ""
    context: str = ""
    no_advance: bool = False


class InterruptRequest(BaseModel):
    actor_id: str
    reason: str = ""


class ApproveInterruptRequest(BaseModel):
    actor_id: str


class NominateNextRequest(BaseModel):
    actor_id: str
    next_speaker: str
    reason: str = ""


class NotebookReadQuery(BaseModel):
    actor_id: str
    owner_id: str
    notebook_name: str


class NotebookSearchRequest(BaseModel):
    actor_id: str
    owner_id: str
    notebook_name: str
    query: str


class NotebookJumpRequest(BaseModel):
    actor_id: str
    owner_id: str
    notebook_name: str
    heading: str


class NotebookUpdateRequest(BaseModel):
    actor_id: str
    owner_id: str
    notebook_name: str
    content: str
    mode: str = "append"
    heading: str = ""


class RuleQueryRequest(BaseModel):
    query: str
    doc_ids: str = ""
    top_k: int = 5


class CompileRulesRequest(BaseModel):
    doc_ids: str = ""
    output_path: str = ""


def _handle_runtime_error(exc: Exception) -> None:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    snapshot = service.snapshot()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "snapshot": snapshot,
            "notebook_names": NOTEBOOK_NAMES,
        },
    )


@app.get("/api/state")
async def get_state():
    return service.snapshot()


@app.post("/api/init")
async def initialize_runtime(payload: InitRequest):
    try:
        return service.initialize(payload.order or None)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/advance")
async def advance():
    try:
        return service.advance()
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/set-order")
async def set_order(payload: SetOrderRequest):
    try:
        return service.set_temporary_order(payload.order, reason=payload.reason)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/turn/human")
async def human_turn(payload: HumanTurnRequest):
    try:
        return service.human_turn(payload.message, no_advance=payload.no_advance)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/turn/player/{actor_id}")
async def player_turn(actor_id: str, payload: AITurnRequest):
    try:
        return service.player_turn(
            actor_id,
            message=payload.message,
            extra_context=payload.context,
            no_advance=payload.no_advance,
        )
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/turn/gm")
async def gm_turn(payload: AITurnRequest):
    try:
        return service.gm_turn(
            payload.message,
            extra_context=payload.context,
            no_advance=payload.no_advance,
        )
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/interrupt/request")
async def interrupt_request(payload: InterruptRequest):
    try:
        return service.request_interrupt(payload.actor_id, reason=payload.reason)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/interrupt/approve")
async def interrupt_approve(payload: ApproveInterruptRequest):
    try:
        return service.approve_interrupt(payload.actor_id)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/nominate-next")
async def nominate_next(payload: NominateNextRequest):
    try:
        return service.nominate_next(payload.actor_id, payload.next_speaker, reason=payload.reason)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.get("/api/history")
async def history(window: int = 20):
    snapshot = service.snapshot(history_window=window)
    return {"history": snapshot["history"]}


@app.get("/api/notebook")
async def read_notebook(actor_id: str, owner_id: str, notebook_name: str):
    try:
        return service.read_notebook(actor_id, owner_id, notebook_name)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/notebook/search")
async def search_notebook(payload: NotebookSearchRequest):
    try:
        return service.search_notebook(payload.actor_id, payload.owner_id, payload.notebook_name, payload.query)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/notebook/jump")
async def jump_notebook(payload: NotebookJumpRequest):
    try:
        return service.jump_notebook(payload.actor_id, payload.owner_id, payload.notebook_name, payload.heading)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/notebook/update")
async def update_notebook(payload: NotebookUpdateRequest):
    try:
        return service.update_notebook(
            payload.actor_id,
            payload.owner_id,
            payload.notebook_name,
            payload.content,
            mode=payload.mode,
            heading=payload.heading,
        )
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/rules/query")
async def rules_query(payload: RuleQueryRequest):
    try:
        return service.rule_query(payload.query, doc_ids=payload.doc_ids, top_k=payload.top_k)
    except Exception as exc:
        _handle_runtime_error(exc)


@app.post("/api/rules/compile")
async def rules_compile(payload: CompileRulesRequest):
    try:
        return service.compile_rules(doc_ids=payload.doc_ids, output_path=payload.output_path)
    except Exception as exc:
        _handle_runtime_error(exc)
