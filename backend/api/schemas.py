from pydantic import BaseModel
from typing import Optional, Any

class ChatRequest(BaseModel):
    message: str
    history: Optional[list[dict]] = []
    stream: Optional[bool] = False
    comparison_mode: Optional[bool] = False

class ChatResponse(BaseModel):
    response: str
    mode: str = "hybrid"
    sources: Optional[list[dict[str, Any]]] = []# List of sources, each source is a dictionary (key = id, name,...) 

class ComparisonResponse(BaseModel):
    naive: ChatResponse # mode = "naive"
    hybrid: ChatResponse

class UploadFileResponse(BaseModel):
    filename: str
    status: str
    message: str