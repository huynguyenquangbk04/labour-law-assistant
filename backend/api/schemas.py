from pydantic import BaseModel
from typing import Optional, Any

class ChatRequest(BaseModel):
    message: str
    history: Optional[list[dict]] = []
    critique: Optional[bool] = False
    comparison_mode: Optional[bool] = False

class ChatResponse(BaseModel):
    response: str
    mode: str = "hybrid"
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