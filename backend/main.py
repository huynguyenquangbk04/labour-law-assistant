from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as api_router
from backend.core.rag_engine import RAGEngine
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from backend.core.graph import model, tavily, Agent

@asynccontextmanager
async def lifespan(app: FastAPI):
    await RAGEngine.initialize()

    async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as memory:
        app.state.agent = Agent(model, tavily, memory)

        yield # keep the memory alive for the entire lifespan

    # post logic

app = FastAPI(
    title="Labour Law Assistant", 
    lifespan=lifespan # rag initialize -> app -> post logic (if needed)
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)