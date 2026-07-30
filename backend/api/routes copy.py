import os
import json
import shutil
import docx
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from backend.core.rag_engine import RAGEngine
from backend.api.schemas import ChatRequest, ChatResponse, ComparisonResponse, UploadFileResponse
from backend.config import settings
from backend.core.graph import agent

router = APIRouter()

thread_id = 1

@router.post("/chat")
async def chat(request: ChatRequest): # currently have not considered history in request and sources in responses

    print(f"DEBUG: Chat request received. message='{request.message[:20]}...', comparison_mode={request.comparison_mode}, critique={request.critique}")

    global thread_id    
    thread = {"configurable": {"thread_id": thread_id}}

    input = {
        "query": request.message,
        "comparison_mode": request.comparison_mode,
        "critique": request.critique,
        "full_query": "",
        "context": {},
        "references": [],
        "draft": {},
        "reflect": {},
        "should_modify": {},
        "revision_number": 0,
        "max_revisions": 3
    }

    if request.critique: 
        try: 
            response = await agent.graph.ainvoke(input=input, config=thread)
            if request.comparison_mode: 
                naive_response = response.get("naive_messages")[-1].content
                hybrid_response = response.get("hybrid_messages")[-1].content

                return ComparisonResponse(
                    naive=ChatResponse(response=naive_response, mode="naive"),
                    hybrid=ChatResponse(response=hybrid_response, mode="hybrid")
                )
            
            hybrid_response = response.get("hybrid_messages")[-1].content       
            return ChatResponse(response=hybrid_response, mode="hybrid")
        
        except Exception as e: 
            raise HTTPException(status_code=500, detail=str(e))
    
    async def event_generator(): # a generator to get the chunks from LightRAG streamming response(s) and yield them to chat function
        try:
            if request.comparison_mode:
                yield f"data: {json.dumps({'type': 'start', 'mode': 'naive'})}\n\n"

            yield f"data: {json.dumps({'type': 'start', 'mode': 'hybrid'})}\n\n"

            async for event in agent.graph.astream_events(input=input, config=thread, version="v2"):
                kind = event.get("event")
                tags = event.get("tags", [])

                if kind == "on_chat_model_stream": 
                    chunk = event["data"]["chunk"].content

                    if not chunk:
                        continue

                    if "final" in tags: 
                        if "naive" in tags: 
                            yield f"data: {json.dumps({'type': 'chunk', 'mode': 'naive', 'content': chunk})}\n\n"
                        elif "hybrid" in tags:
                            yield f"data: {json.dumps({'type': 'chunk', 'mode': 'hybrid', 'content': chunk})}\n\n"
                
            yield f"data: {json.dumps({'type': 'done'})}\n\n"                   
                                    
        except Exception as e: 
              yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"    
        
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get("/documents")
async def list_documents():
    try: 
        rag = RAGEngine.get_instance()

        doc_tuple, _ = await rag.doc_status.get_docs_paginated()
        
        result = []

        for doc_id, status_obj in doc_tuple: 
            status_str = ""
            if hasattr(status_obj.status, "value"):
                status_str = status_obj.status.value
            else: 
                status_str = status_obj.status
            
            result.append({
                "id": doc_id, 
                "status": status_str,
                "source": status_obj.file_path if status_obj.file_path else "unknown",
                "content_summary": (status_obj.content_summary[:100] + "...") if status_obj.content_summary else ""
            })          

        return result

    except Exception as e: 
        print(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/upload")
# File helps find the file in form-data sent from frontend, ... mean compulsory. This file is also in UploadFile type, which has attributes like filename, Content-Type besides the file content in binary itself  
async def uplload_file(file: UploadFile = File(...)):

    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only DOCX files are supported")
    
    # save to disk
    os.makedirs(settings.LIGHTRAG_WORKING_DIR, exist_ok=True)
    file_path = os.path.join(settings.LIGHTRAG_WORKING_DIR, file.filename)

    with open(file_path, "wb") as buffer: 
        shutil.copyfileobj(file.file, buffer) # copyfileobj() is more safe for heavy files than write(), the binary bytes then become .docx file on disk

    # save to rag database
    try: 
        rag = RAGEngine.get_instance()

        doc = docx.Document(file_path)
        full_para = []
        for para in doc.paragraphs:
            if para.text.strip():
                full_para.append(para.text)
        
        content = "\n".join(full_para)

        if not content.strip():
            raise ValueError("File is empty or no text could be extracted")

        await rag.ainsert(content, file_paths=[file.filename]) 

        return UploadFileResponse(
            filename=file.filename,
            status="success",
            message=f"File uploaded and indexed ({len(content)} characters)"
        )
        
    except Exception as e: 
        raise HTTPException(status_code=500, detail=f"Failed to index file: {str(e)}")

@router.get("/health")
async def health():
    return {"status": "healthy"}
    

   

        














