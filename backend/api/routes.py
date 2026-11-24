import os
import json
import uuid
import shutil
import asyncio
import logging
from contextlib import aclosing
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse
from backend.core.rag_engine import RAGEngine
from backend.core.graphrag_engine import GraphRAGEngine
from backend.core.graph import get_critique_result
from backend.core.conflict_analyzer import ConflictAnalyzer, ConflictAnalysisResult, ConflictAnalysisError
from backend.core import proposal_store
from backend.api.schemas import (
    ChatRequest, ChatResponse, ComparisonResponse, UploadFileResponse,
    ProposalResponse, ProposalActionResponse, ResumeRequest,
)
from backend.config import settings
from backend.core.law_parser import parse_docx
from backend.services.document_ingestion import DocumentIdentityConflict, ingest_document, validate_filename
from backend.services.proposal_review import resolve_proposal
from backend.services.graph_view import serialize_graph

router = APIRouter()
logger = logging.getLogger(__name__)

def get_agent(request: Request):
    return request.app.state.agent

thread_id = 1

@router.post("/chat")
async def chat(request: ChatRequest, agent=Depends(get_agent)):
    thread = {"configurable": {"thread_id": thread_id}}
    input = {
        "query": request.message,
        "comparison_mode": request.comparison_mode,
        "critique": request.critique,
        "engine": request.engine or "lightrag",
        "rag_mode": request.rag_mode or "hybrid",
        "lightrag_mode": request.lightrag_mode or "hybrid",
        "graphrag_method": request.graphrag_method or "drift",
        "top_k": request.top_k or 5,
        "community_level": request.community_level or 2,
        "full_query": "",
        "context": {},
        "drift_response": "",
        "references": [],
        "payroll_calculation": None,
        "draft": {},
        "reflect": {},
        "should_modify": {},
        "critique_reviews": {},
        "errors": {},
        "revision_number": 0,
        "max_revisions": 3,
    }

    if request.critique:
        try:
            state = await agent.graph.ainvoke(input=input, config=thread)
            draft = state.get("draft") or {}
            errors = state.get("errors") or {}

            def answer(mode: str, engine: str, rag_mode: str) -> ChatResponse:
                return ChatResponse(
                    response=draft.get(mode) or "", mode=rag_mode, engine=engine,
                    error=errors.get(mode, {}).get("message"),
                    critique=get_critique_result(state, mode),
                )

            if request.comparison_mode:
                payload = ComparisonResponse(
                    naive=answer("naive", "lightrag", "naive"),
                    hybrid=answer("hybrid", "lightrag", request.lightrag_mode or "hybrid"),
                    drift=answer("drift", "graphrag", request.graphrag_method or "drift"),
                )
            else:
                payload = answer("hybrid", request.engine or "lightrag", request.rag_mode or "hybrid")
            response = JSONResponse(content=payload.model_dump())
        except Exception:
            logger.exception("Chat workflow failed")
            raise HTTPException(status_code=500, detail="The chat request could not be completed. Please try again.")
    else:
        async def event_generator():
            try:
                modes = ("naive", "hybrid", "drift") if request.comparison_mode else ("hybrid",)
                for mode in modes:
                    yield f"data: {json.dumps({'type': 'start', 'mode': mode})}\n\n"

                async with aclosing(agent.graph.astream_events(input=input, config=thread, version="v2")) as events:
                    async for event in events:
                        kind = event.get("event")
                        if kind == "on_custom_event" and event.get("name") in ("comparison_chunk", "branch_error"):
                            event_type = "chunk" if event["name"] == "comparison_chunk" else "branch_error"
                            yield f"data: {json.dumps({'type': event_type, **event.get('data', {})})}\n\n"
                        elif kind == "on_chat_model_stream" and "final" in event.get("tags", []):
                            content = event["data"]["chunk"].content
                            if content:
                                for mode in modes:
                                    if mode in event["tags"]:
                                        yield f"data: {json.dumps({'type': 'chunk', 'mode': mode, 'content': content})}\n\n"
                                        break
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            except Exception:
                logger.exception("Chat stream failed")
                yield f"data: {json.dumps({'type': 'error', 'message': 'The chat request could not be completed. Please try again.'})}\n\n"

        response = StreamingResponse(
            event_generator(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return response

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
async def upload_file(file: UploadFile = File(...)):

    try:
        filename = validate_filename(file.filename or '')
        if not filename.lower().endswith('.docx'):
            raise ValueError('Only DOCX files are supported')
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    os.makedirs(settings.WORKING_DIR, exist_ok=True)
    # Distinct uploads must not overwrite the source of a pending review.
    file_path = os.path.join(settings.WORKING_DIR, f'{uuid.uuid4().hex}_{filename}')
    try:
        with open(file_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)
        parsed_chunks = parse_docx(file_path, source_filename=filename)
        lightrag = RAGEngine.get_instance()
        text_chunks = [chunk['text'] for chunk in parsed_chunks]
        chunk_titles = [filename] * len(parsed_chunks)

        # ── Conflict analysis ─────────────────────────────────────────────
        # Fetch existing nodes from LightRAG graph storage
        graph_storage = lightrag.chunk_entity_relation_graph
        existing_nodes = await graph_storage.get_all_nodes()

        # Only run analysis when graph already has nodes (first upload skips)
        if existing_nodes:
            analyzer = ConflictAnalyzer()
            analysis = await analyzer.analyze(
                new_chunks=text_chunks,
                existing_nodes=existing_nodes,
                source_filename=file.filename,
            )

            # Filter to only actionable proposal types
            actionable = [
                p for p in analysis.proposals
                if p.proposal_type in ("REPLACES", "MODIFIES")
            ]

            if actionable:
                # Stage chunks for deferred insert after human review
                batch_id = str(uuid.uuid4())

                proposal_store.stage_chunks(
                    batch_id=batch_id,
                    filename=file.filename,
                    chunks=text_chunks,
                    file_paths=chunk_titles,
                    parsed_chunks=parsed_chunks,
                    full_text="\n\n".join(text_chunks),
                )

                # Persist proposals
                saved = proposal_store.add_proposals(
                    ConflictAnalysisResult(proposals=actionable, summary=analysis.summary),
                    source_filename=file.filename,
                    batch_id=batch_id,
                )

                return UploadFileResponse(
                    filename=file.filename,
                    status="pending_review",
                    message=(
                        f"Phát hiện {len(saved)} xung đột cần xem xét "
                        f"(REPLACES/MODIFIES). Tài liệu chưa được nạp vào graph — "
                        f"hãy duyệt hoặc từ chối các đề xuất bên dưới."
                    ),
                    proposals=saved,
                )
        # ─────────────────────────────────────────────────────────────────

        await ingest_document(parsed_chunks, filename)

        return UploadFileResponse(
            filename=file.filename,
            status="success",
            message="File uploaded and indexed successfully",
        )

    except ConflictAnalysisError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except DocumentIdentityConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to index file: {str(e)}")


@router.get("/health")
async def health():
    return {"status": "healthy"}
    
@router.get("/graph")
async def get_graph(max_nodes: int = Query(5000, ge=1, le=5000)):
    try:
        rag = RAGEngine.get_instance()
        kg = await rag.get_knowledge_graph(node_label="*", max_depth=5, max_nodes=max_nodes)
        
        kg_dict = kg.model_dump() if hasattr(kg, "model_dump") else kg.dict()
        
        return serialize_graph(kg_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Proposal HITL Endpoints ────────────────────────────────────────────

@router.get("/proposals")
async def list_proposals(status: str = None):
    """List conflict proposals, optionally filtered by status (pending/approved/rejected)."""
    try:
        proposals = proposal_store.get_proposals(status=status)
        return proposals
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str):
    try:
        proposal = await resolve_proposal(proposal_id, 'approved')
    except Exception as error:
        logger.exception('Proposal approval failed')
        raise HTTPException(status_code=500, detail=str(error)) from error
    if proposal is None:
        raise HTTPException(status_code=404, detail='Proposal not found')
    return ProposalActionResponse(id=proposal_id, status=proposal['status'],
                                  message='Đã ghi nhận quyết định. Tài liệu được nạp khi toàn bộ đề xuất đã xử lý.')


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    try:
        proposal = await resolve_proposal(proposal_id, 'rejected')
    except Exception as error:
        logger.exception('Proposal rejection failed')
        raise HTTPException(status_code=500, detail=str(error)) from error
    if proposal is None:
        raise HTTPException(status_code=404, detail='Proposal not found')
    return ProposalActionResponse(id=proposal_id, status=proposal['status'],
                                  message='Đã ghi nhận quyết định; chỉ nạp tài liệu nếu batch có đề xuất được duyệt.')













   

        














