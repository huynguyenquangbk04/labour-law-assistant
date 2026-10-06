import os
import json
import uuid
import shutil
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from backend.core.rag_engine import RAGEngine
from backend.core.graphrag_engine import GraphRAGEngine
from backend.core.conflict_analyzer import ConflictAnalyzer, ConflictAnalysisResult
from backend.core import proposal_store
from backend.api.schemas import (
    ChatRequest, ChatResponse, ComparisonResponse, UploadFileResponse,
    ProposalResponse, ProposalActionResponse, ResumeRequest,
)
from backend.config import settings
from backend.core.law_parser import parse_and_save_docx

router = APIRouter()

def get_agent(request: Request):
    return request.app.state.agent

thread_id = 1

@router.post("/chat")
async def chat(request: ChatRequest, agent=Depends(get_agent)): # currently have not considered history in request and sources in responses

    print(f"DEBUG: Chat request received. message='{request.message[:20]}...', comparison_mode={request.comparison_mode}, critique={request.critique}")

    global thread_id    
    thread = {"configurable": {"thread_id": thread_id}}

    input = {
        "query": request.message,
        "comparison_mode": request.comparison_mode,
        "critique": request.critique,
        "full_query": "",
        "context": {},
        "drift_response": "",
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
                drift_response = response.get("drift_messages")[-1].content

                return ComparisonResponse(
                    naive=ChatResponse(response=naive_response, mode="naive"),
                    hybrid=ChatResponse(response=hybrid_response, mode="hybrid"),
                    drift=ChatResponse(response=drift_response, mode="drift")
                )
            
            hybrid_response = response.get("hybrid_messages")[-1].content       
            return ChatResponse(response=hybrid_response, mode="hybrid")
        
        except Exception as e: 
            raise HTTPException(status_code=500, detail=str(e))
    
    async def event_generator(): # a generator to get the chunks from LightRAG streamming response(s) and yield them to chat function
        try:
            if request.comparison_mode:
                yield f"data: {json.dumps({'type': 'start', 'mode': 'naive'})}\n\n"
                yield f"data: {json.dumps({'type': 'start', 'mode': 'drift'})}\n\n"

            yield f"data: {json.dumps({'type': 'start', 'mode': 'hybrid'})}\n\n"

            async for event in agent.graph.astream_events(input=input, config=thread, version="v2"):
                kind = event.get("event")
                tags = event.get("tags", [])

                if kind == "on_custom_event" and event.get("name") == "comparison_chunk":
                    payload = event.get("data", {})
                    yield f"data: {json.dumps({'type': 'chunk', **payload})}\n\n"
                    continue

                if kind == "on_chat_model_stream": 
                    chunk = event["data"]["chunk"].content

                    if not chunk:
                        continue

                    if "final" in tags: 
                        if "naive" in tags: 
                            yield f"data: {json.dumps({'type': 'chunk', 'mode': 'naive', 'content': chunk})}\n\n"
                        elif "hybrid" in tags:
                            yield f"data: {json.dumps({'type': 'chunk', 'mode': 'hybrid', 'content': chunk})}\n\n"
                        elif "drift" in tags:
                            yield f"data: {json.dumps({'type': 'chunk', 'mode': 'drift', 'content': chunk})}\n\n"
                
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
    os.makedirs(settings.WORKING_DIR, exist_ok=True)
    file_path = os.path.join(settings.WORKING_DIR, file.filename)

    with open(file_path, "wb") as buffer: 
        shutil.copyfileobj(file.file, buffer) # copyfileobj() is more safe for heavy files than write(), the binary bytes then become .docx file on disk

    name_only, _ = os.path.splitext(file.filename)

    os.makedirs(settings.LIGHTRAG_WORKING_DIR, exist_ok=True)
    lightrag_file_path = os.path.join(settings.LIGHTRAG_WORKING_DIR, f"{name_only}.json")

    os.makedirs(settings.GRAPHRAG_WORKING_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.GRAPHRAG_WORKING_DIR, "input"), exist_ok=True)
    graphrag_file_path = os.path.join(settings.GRAPHRAG_WORKING_DIR, "input", f"{name_only}.json")

    # save to rag database
    try:
        parse_and_save_docx(file_path, [lightrag_file_path, graphrag_file_path])

        lightrag = RAGEngine.get_instance()

        with open(lightrag_file_path, "r", encoding="utf-8") as f:
            parsed_chunks = json.load(f)

        text_chunks = [chunk["text"] for chunk in parsed_chunks]
        chunk_titles = [chunk["title"] for chunk in parsed_chunks]
        chunk_ids = [chunk["id"] for chunk in parsed_chunks]

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

                # Collect all paragraph texts for enrichment later
                all_paragraphs = []
                for chunk in parsed_chunks:
                    all_paragraphs.append(chunk.get("title", ""))
                    all_paragraphs.append(chunk.get("text", ""))

                proposal_store.stage_chunks(
                    batch_id=batch_id,
                    filename=file.filename,
                    chunks=text_chunks,
                    file_paths=chunk_titles,
                    paragraphs=all_paragraphs,
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

        # No conflicts (or first upload) — insert immediately
        light_rag_task = lightrag.ainsert(
            text_chunks,
            split_by_character="\u241f",    # sentinel hợp lệ trong PostgreSQL JSONB
            split_by_character_only=True,    # ép LightRAG không tự chia nhỏ thêm nữa
            ids=chunk_ids,
            file_paths=chunk_titles,
        )
        graph_rag_task = GraphRAGEngine.build_index()
        await asyncio.gather(light_rag_task, graph_rag_task)

        return UploadFileResponse(
            filename=file.filename,
            status="success",
            message="File uploaded and indexed successfully",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to index file: {str(e)}")


@router.get("/health")
async def health():
    return {"status": "healthy"}
    
@router.get("/graph")
async def get_graph():
    try:
        rag = RAGEngine.get_instance()
        kg = await rag.get_knowledge_graph(node_label="*", max_depth=5)
        
        kg_dict = kg.model_dump() if hasattr(kg, "model_dump") else kg.dict()
        
        nodes = []
        links = []
        valid_node_ids = set()
        
        for n in kg_dict.get("nodes", []):
            node_id = n.get("id")
            properties = n.get("properties", {})
            entity_name = properties.get("entity_id") or (n.get("labels")[0] if n.get("labels") else "Unknown")
            entity_type = properties.get("entity_type", "Unknown")
            
            valid_node_ids.add(node_id)
            nodes.append({
                "id": node_id,
                "label": entity_name,
                "type": entity_type,
                "description": properties.get("description", ""),
                "trang_thai": properties.get("trang_thai", ""),
                "hieu_luc_tu": properties.get("hieu_luc_tu", ""),
                "het_hieu_luc": properties.get("het_hieu_luc", ""),
            })
            
        for e in kg_dict.get("edges", []):
            source = e.get("source")
            target = e.get("target")
            properties = e.get("properties", {})
            if source in valid_node_ids and target in valid_node_ids:
                links.append({
                    "source": source,
                    "target": target,
                    "label": properties.get("keywords", "")
                })
            
        return {"nodes": nodes, "links": links}
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
    """
    Approve a proposal and commit the changes to the Knowledge Graph.
    
    This will:
    1. Update properties on the old node (e.g. trang_thai='het_hieu_luc')
    2. Update properties on the new node (e.g. hieu_luc_tu, trang_thai='con_hieu_luc')
    3. Create an edge between old and new node (REPLACES/MODIFIES/etc.)
    """
    proposal = proposal_store.update_proposal_status(proposal_id, "approved")
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Commit changes to LightRAG graph
    try:
        rag = RAGEngine.get_instance()
        graph_storage = rag.chunk_entity_relation_graph

        tags = proposal.get("suggested_tags", {})
        old_id = proposal["existing_entity_id"].lower().strip()
        new_id = proposal["new_entity_id"].lower().strip()
        relation_type = proposal["proposal_type"]

        # Update old node properties (e.g. mark as expired)
        old_tags = tags.get("old_node", {})
        if old_tags:
            existing = await graph_storage.get_node(old_id)
            if existing:
                existing.update(old_tags)
                await graph_storage.upsert_node(old_id, existing)

        # Update new node properties (e.g. mark as active with effective date)
        new_tags = tags.get("new_node", {})
        if new_tags:
            existing = await graph_storage.get_node(new_id)
            if existing:
                existing.update(new_tags)
                await graph_storage.upsert_node(new_id, existing)

        # Commit edge
        edge_data = {
            "keywords": relation_type,
            "weight": "1.0",
            "description": proposal.get("reason", ""),
            "source_id": proposal.get("source_filename", "conflict_analyzer"),
        }
        await graph_storage.upsert_edge(new_id, old_id, edge_data)

        # Kiểm tra batch: nếu tất cả proposal trong batch đã xử lý -> thực hiện ainsert các staged chunks
        batch_id = proposal.get("batch_id")
        insert_msg = ""
        if batch_id and proposal_store.are_all_resolved(batch_id):
            staged = proposal_store.get_staged_chunks(batch_id)
            if staged:
                chunks = staged.get("chunks", [])
                file_paths = staged.get("file_paths", [])
                staged_paragraphs = staged.get("paragraphs", [])
                staged_full_text = staged.get("full_text", "")
                staged_filename = staged.get("filename", "")
                if chunks:
                    await rag.ainsert(chunks, file_paths=file_paths)
                    try:
                        enrich_summary = await enrich_graph(
                            graph_storage=rag.chunk_entity_relation_graph,
                            paragraphs=staged_paragraphs,
                            full_text=staged_full_text,
                            source_filename=staged_filename,
                        )
                        print(f"Graph enrichment (HITL approve): {enrich_summary}")
                    except Exception as enrich_err:
                        print(f"Graph enrichment warning (non-fatal): {enrich_err}")
                proposal_store.delete_staged_chunks(batch_id)
                insert_msg = " Đã nạp tài liệu vào LightRAG do toàn bộ batch đã giải quyết."

        return ProposalActionResponse(
            id=proposal_id,
            status="approved",
            message=f"Đã cập nhật graph: {new_id} -{relation_type}-> {old_id}.{insert_msg}"
        )

    except Exception as e:
        # Rollback status if graph update fails
        proposal_store.update_proposal_status(proposal_id, "pending")
        raise HTTPException(
            status_code=500,
            detail=f"Approved but failed to update graph: {str(e)}"
        )


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    """Reject a proposal — không thay đổi quan hệ xung đột."""
    proposal = proposal_store.update_proposal_status(proposal_id, "rejected")
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    batch_id = proposal.get("batch_id")
    insert_msg = ""
    if batch_id and proposal_store.are_all_resolved(batch_id):
        # Nếu có ít nhất 1 proposal được duyệt thì insert, nếu tất cả bị reject thì huỷ bỏ chunks
        approved = proposal_store.get_approved_proposals(batch_id)
        if approved:
            staged = proposal_store.get_staged_chunks(batch_id)
            if staged:
                rag = RAGEngine.get_instance()
                chunks = staged.get("chunks", [])
                file_paths = staged.get("file_paths", [])
                staged_paragraphs = staged.get("paragraphs", [])
                staged_full_text = staged.get("full_text", "")
                staged_filename = staged.get("filename", "")
                if chunks:
                    await rag.ainsert(chunks, file_paths=file_paths)
                    try:
                        enrich_summary = await enrich_graph(
                            graph_storage=rag.chunk_entity_relation_graph,
                            paragraphs=staged_paragraphs,
                            full_text=staged_full_text,
                            source_filename=staged_filename,
                        )
                        print(f"Graph enrichment (HITL reject-batch): {enrich_summary}")
                    except Exception as enrich_err:
                        print(f"Graph enrichment warning (non-fatal): {enrich_err}")
                proposal_store.delete_staged_chunks(batch_id)
                insert_msg = " Đã nạp tài liệu vào LightRAG theo các đề xuất được duyệt còn lại."
        else:
            proposal_store.delete_staged_chunks(batch_id)
            insert_msg = " Tất cả đề xuất bị từ chối; huỷ nạp tài liệu vào graph."

    return ProposalActionResponse(
        id=proposal_id,
        status="rejected",
        message=f"Proposal rejected.{insert_msg}"
    )













   

        














