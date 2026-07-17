import os
import json
import asyncio
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from lightrag import QueryParam
from backend.core.rag_engine import RAGEngine
from backend.core.llm_services import parse_pdf
from backend.api.schemas import ChatRequest, ChatResponse, ComparisonResponse, UploadFileResponse
from backend.config import settings


router = APIRouter()

@router.post("/chat")
async def chat(request: ChatRequest): # currently have not considered history in request and sources in responses
    rag = RAGEngine.get_instance()

    print(f"DEBUG: Chat request received. message='{request.message[:20]}...', comparison_mode={request.comparison_mode}, stream={request.stream}")

    system_prompt = (
        "STRICT INSTRUCTION: Output ONLY the relevant information. "
        "DO NOT use introductory phrases like 'Dựa trên thông tin được cung cấp...', 'Dưới đây là...', etc. "
        "Directly provide the answer based on the context."
    )

    full_query = f"{request.message} \n\n {system_prompt}" 

    if not request.stream: 
        try: 
            if request.comparison_mode: 
                naive_response = await rag.aquery(full_query, param=QueryParam(mode="naive"))
                hybrid_response = await rag.aquery(full_query, param=QueryParam(mode="hybrid"))
                # can improve by using create_task()
                return ComparisonResponse(
                    naive=ChatResponse(response=naive_response, mode="naive"),
                    hybrid=ChatResponse(response=hybrid_response, mode="hybrid")
                )
            
            hybrid_response = await rag.aquery(full_query, param=QueryParam(mode="hybrid"))
            return ChatResponse(response=hybrid_response, mode="hybrid")
        except Exception as e: 
            raise HTTPException(status_code=500, detail=str(e))
    
    async def event_generator(): # a generator to get the chunks from LightRAG streamming response(s) and yield them to chat function
        try:
            if request.comparison_mode: 
                queue = asyncio.Queue() # to handle the async chunks from both naive and hybrid responses
                pending_tasks = set() # contains naive and hybrid response tasks, to track when those tasks done

                async def stream_wrapper(gen_func, mode): # chunk is put in SSE format, so that frontend can extract and handle later
                    try: 
                        await queue.put(f"data: {json.dumps({'type': 'start', 'mode': mode})}\n\n")

                        response = await gen_func

                        if hasattr(response, "__aiter__"): # check if reponse is a generator, normally when streaming, LightRAG should returns a generator
                            async for chunk in response: 
                                await queue.put(f"data: {json.dumps({'type': 'chunk', 'mode': mode, 'content': chunk})}\n\n")
                    
                    except Exception as e: 
                        print(f"STREAM ERROR ({mode}): {str(e)}")
                        await queue.put(f"data: {json.dumps({'type': 'error', 'mode': mode, 'message': str(e)})}\n\n")

                # Use create_task() to create underground tasks, serving parallelism 
                t1 = asyncio.create_task(stream_wrapper(rag.aquery(full_query, param=QueryParam(mode="naive", stream=True)), mode="naive"))
                t2 = asyncio.create_task(stream_wrapper(rag.aquery(full_query, param=QueryParam(mode="hybrid", stream=True)), mode="hybrid"))
                pending_tasks.update([t1, t2])

                while pending_tasks: 
                    while not queue.empty():
                        yield await queue.get()

                    # instead of asking for empty queue continuously, which wastes CPU, make it sleep and give space to chunk-listening tasks themselves, only wake up after one completed or 0.1s 
                    done, pending_tasks = await asyncio.wait(pending_tasks, timeout=0.1, return_when=asyncio.FIRST_COMPLETED) # if one reponse done, it will be moved from "pending_task" to "done" list

                    while not queue.empty():
                        yield await queue.get()

                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
            else: 
                response = await rag.aquery(full_query, param=QueryParam(mode="hybrid", stream=True))

                if hasattr(response, "__aiter__"): # check if reponse is a generator, normally when streaming, LightRAG should returns a generator
                    async for chunk in response: 
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

    if not file.filename.endswith(".pdf") and not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are supported")
    
    # save to disk
    os.makedirs(settings.LIGHTRAG_WORKING_DIR, exist_ok=True)
    file_path = os.path.join(settings.LIGHTRAG_WORKING_DIR, file.filename)

    with open(file_path, "wb") as buffer: 
        shutil.copyfileobj(file.file, buffer) # copyfileobj() is more safe for heavy files than write(), the binary bytes then become .pdf or .txt file on disk

    # save to rag database
    try: 
        rag = RAGEngine.get_instance()

        content = ""
        if file.filename.endswith(".pdf"):
            content = await parse_pdf(file_path=file_path)

        else: # assume .txt
            with open(file_path, "r", encoding="utf-8", errors="ignore") as txt_file:
                content = txt_file.read()

        if not content.strip():
            raise ValueError("File is empty or no text could be extracted")

        await rag.ainsert(content, file_paths=[file.filename]) 

        return UploadFileResponse(
            filename=file.filename,
            status="success",
            message=f"File uploaded and indexed ({len(content)} characters)"
        )
        
    except Exception as e: 
        return UploadFileResponse(
            filename=file.filename,
            status="error",
            message=f"Failed to index file: {str(e)}"
        )

@router.get("/health")
async def health():
    return {"status": "healthy"}
    

   

        














