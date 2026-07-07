from __future__ import annotations

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.agents import CustomerServiceAgent
from app.config import load_llm_config
from app.models import ChatRequest, ChatResponse, ConversationState
from app.services import (
    HandoffService,
    KnowledgeBaseService,
    LLMIntentFallbackService,
    LogisticsService,
    OrderService,
)
from app.store import SessionStore


session_store = SessionStore()
llm_config = load_llm_config()
agent = CustomerServiceAgent(
    store=session_store,
    knowledge_base=KnowledgeBaseService(),
    order_service=OrderService(),
    logistics_service=LogisticsService(),
    handoff_service=HandoffService(),
    llm_fallback_service=LLMIntentFallbackService(llm_config),
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


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            request = ChatRequest(**payload)
            for event in agent.chat_events(request):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json(
            {
                "type": "error",
                "message": str(exc),
            }
        )
        await websocket.close()


@app.get("/session/{session_id}", response_model=ConversationState)
def get_session(session_id: str) -> ConversationState:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
