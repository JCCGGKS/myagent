from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent import CustomerServiceAgent
from app.models import ChatRequest, ChatResponse, ConversationState
from app.services import HandoffService, KnowledgeBaseService, LogisticsService, OrderService
from app.store import SessionStore


session_store = SessionStore()
agent = CustomerServiceAgent(
    store=session_store,
    knowledge_base=KnowledgeBaseService(),
    order_service=OrderService(),
    logistics_service=LogisticsService(),
    handoff_service=HandoffService(),
)

app = FastAPI(title="Customer Service Agent MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return agent.chat(request)


@app.get("/session/{session_id}", response_model=ConversationState)
def get_session(session_id: str) -> ConversationState:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
