from pydantic import BaseModel
from typing import Optional, Any

class ChatRequest(BaseModel):
    message: str
    history: Optional[list[dict]] = []
    critique: Optional[bool] = False
    comparison_mode: Optional[bool] = False
    engine: Optional[str] = "lightrag"  # "lightrag" | "graphrag"
    rag_mode: Optional[str] = "hybrid"  # lightrag: hybrid/naive/local/global/mix; graphrag: drift/local/global/basic
    top_k: Optional[int] = 5
    community_level: Optional[int] = 2
    lightrag_mode: Optional[str] = "hybrid"  # mode for LightRAG in comparison (hybrid/local/global/mix)
    graphrag_method: Optional[str] = "drift"  # method for GraphRAG in comparison (drift/local/global/basic)

class ChatResponse(BaseModel):
    response: str
    mode: str = "hybrid"
    engine: Optional[str] = "lightrag"
    sources: Optional[list[dict[str, Any]]] = []# List of sources, each source is a dictionary (key = id, name,...) 

class ComparisonResponse(BaseModel):
    naive: ChatResponse # mode = "naive"
    hybrid: ChatResponse
    drift: ChatResponse

class UploadFileResponse(BaseModel):
    filename: str
    status: str
    message: str
    proposals: Optional[list[dict]] = None  # populated when conflict proposals require human review


class ProposalResponse(BaseModel):
    id: str
    status: str
    created_at: str
    source_filename: str
    proposal_type: str
    new_entity_id: str
    existing_entity_id: str
    reason: str
    suggested_tags: dict = {}
    resolved_at: Optional[str] = None

class ProposalActionResponse(BaseModel):
    id: str
    status: str
    message: str

class ResumeRequest(BaseModel):
    """Sent by the human after the graph pauses at the reflect interrupt."""
    thread_id: int
    # Human decision: True = force redraft, False = skip redraft and finalize
    human_approve_modify: bool
    # Optional human feedback injected into reflect state before resuming
    feedback: Optional[str] = None