from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as api_router
from backend.core.rag_engine import RAGEngine

@asynccontextmanager
async def lifespan(app: FastAPI):
    await RAGEngine.initialize()
    yield
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