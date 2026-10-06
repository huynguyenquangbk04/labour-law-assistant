"""
Conflict Analyzer — detects when newly uploaded legal documents
modify, replace, or overlap with entities already in the Knowledge Graph.

Uses the same LLM (via OpenRouter) that powers the rest of the system.
Produces structured proposals that are stored for human review (HITL).
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from backend.core.llm_services import get_openai_client
from backend.config import settings

# ── Pydantic models for LLM structured output ──────────────────────────

class ConflictProposal(BaseModel):
    """A single proposed change detected by the LLM."""
    proposal_type: str = Field(
        ...,
        description="One of: REPLACES, MODIFIES, SUPPLEMENTS, OVERLAPS"
    )
    new_entity_id: str = Field(
        ...,
        description="The entity_id of the new node (from the uploaded document)"
    )
    existing_entity_id: str = Field(
        ...,
        description="The entity_id of the existing node in the graph that is affected"
    )
    reason: str = Field(
        ...,
        description="Brief explanation of why this conflict was detected (in Vietnamese)"
    )
    suggested_tags: dict = Field(
        default_factory=dict,
        description=(
            "Suggested property updates for nodes, e.g. "
            "{'old_node': {'trang_thai': 'het_hieu_luc', 'het_hieu_luc': '2025-01-01'}, "
            " 'new_node': {'hieu_luc_tu': '2025-01-01', 'trang_thai': 'con_hieu_luc'}"
        )
    )

class ConflictAnalysisResult(BaseModel):
    """Full result from the LLM conflict analysis."""
    proposals: list[ConflictProposal] = Field(default_factory=list)
    summary: str = Field(
        default="",
        description="Brief summary of findings (in Vietnamese)"
    )

# ── The system prompt sent to the LLM ──────────────────────────────────

def _build_conflict_prompt() -> str:
    """Build the conflict analysis system prompt from settings.edge_types_guidance."""
    return (
        "Bạn là chuyên gia phân tích pháp luật Việt Nam. Nhiệm vụ: so sánh các đoạn văn bản "
        "MỚI được upload với các thực thể ĐÃ CÓ trong Knowledge Graph, để phát hiện các trường hợp:\n\n"
        f"{settings.edge_types_guidance}\n\n"
        "Quy tắc:\n"
        "- Mỗi đoạn văn mới bắt đầu bằng \"[Nguồn: <tên_file>]\" — đây là tên file tài liệu mới. "
        "Hãy dùng tên file này (đặc biệt năm ban hành trong tên file, vd \"BLLĐ_2019.docx\" vs "
        "\"BLLĐ_2012.docx\") để suy luận xem tài liệu mới CÓ KHẢ NĂNG sửa đổi tài liệu cũ không.\n"
        "- Các thực thể cũ có trường \"nguồn\" cho biết chúng đến từ file nào. Nếu cùng tên Điều "
        "nhưng khác năm/nguồn, rất có khả năng là MODIFIES hoặc REPLACES.\n"
        "- Chỉ báo cáo khi thực sự có bằng chứng từ nội dung HOẶC từ sự khác biệt năm trong tên file/Điều. KHÔNG được đoán tuỳ tiện.\n"
        "- Nếu không phát hiện xung đột nào, trả về danh sách proposals rỗng.\n"
        "- suggested_tags cho old_node nên bao gồm: trang_thai, het_hieu_luc (nếu biết).\n"
        "- suggested_tags cho new_node nên bao gồm: hieu_luc_tu, trang_thai.\n"
        "- Tất cả giải thích bằng tiếng Việt.\n\n"
        "Trả về JSON hợp lệ ĐÚNG theo schema sau (không được thêm key khác):\n"
        "```json\n"
        "{\n"
        "  \"proposals\": [\n"
        "    {\n"
        "      \"proposal_type\": \"REPLACES\",\n"
        "      \"new_entity_id\": \"điều 5 bộ luật lao động 2019\",\n"
        "      \"existing_entity_id\": \"điều 5 bộ luật lao động 2012\",\n"
        "      \"reason\": \"Điều 5 BLLĐ 2019 thay thế hoàn toàn Điều 5 BLLĐ 2012.\",\n"
        "      \"suggested_tags\": {\n"
        "        \"old_node\": {\"trang_thai\": \"het_hieu_luc\", \"het_hieu_luc\": \"2021-01-01\"},\n"
        "        \"new_node\": {\"trang_thai\": \"con_hieu_luc\", \"hieu_luc_tu\": \"2021-01-01\"}\n"
        "      }\n"
        "    }\n"
        "  ],\n"
        "  \"summary\": \"Phát hiện 1 xung đột.\"\n"
        "}\n"
        "```\n"
        "Nếu không có xung đột: trả về `{\"proposals\": [], \"summary\": \"Không phát hiện xung đột.\"}`."
    )


class ConflictAnalyzer:
    """
    Compares newly extracted entities against existing graph nodes
    using LLM reasoning to detect legal conflicts/amendments.
    """

    def __init__(self):
        self.client = get_openai_client()

    async def analyze(
        self,
        new_chunks: list[str],
        existing_nodes: list[dict],
        source_filename: str,
    ) -> ConflictAnalysisResult:
        """
        Run conflict analysis between new document chunks and existing nodes.
        
        Args:
            new_chunks: The text chunks from the newly uploaded document.
            existing_nodes: List of node dicts from get_all_nodes().
            source_filename: Name of the uploaded file (for context).
            
        Returns:
            ConflictAnalysisResult with proposals (may be empty).
        """
        if not existing_nodes:
            return ConflictAnalysisResult(
                proposals=[],
                summary="Không có thực thể nào trong graph hiện tại để so sánh."
            )

        # Summarise existing nodes for the prompt (keep token usage manageable)
        existing_summary = self._summarize_existing_nodes(existing_nodes)

        # Combine new chunks (truncate to ~6000 chars to stay within context)
        new_text = "\n---\n".join(new_chunks)
        if len(new_text) > 6000:
            new_text = new_text[:6000] + "\n... (truncated)"

        user_prompt = (
            f"## Tài liệu mới: {source_filename}\n\n"
            f"### Nội dung các đoạn trích:\n{new_text}\n\n"
            f"### Các thực thể ĐÃ CÓ trong Knowledge Graph:\n{existing_summary}\n\n"
            "Hãy phân tích và trả về JSON theo schema ConflictAnalysisResult."
        )

        try:
            response = await self.client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": _build_conflict_prompt()},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                timeout=120,
                extra_headers={"X-Title": "Labour Law Assistant - Conflict Analyzer"},
            )

            raw = response.choices[0].message.content
            if not raw or not raw.strip():
                return ConflictAnalysisResult(
                    proposals=[],
                    summary="LLM trả về kết quả rỗng."
                )

            # Try to extract JSON from the response (LLM may wrap it in markdown ```json ... ```)
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group())
            else:
                parsed = json.loads(raw)

            return ConflictAnalysisResult.model_validate(parsed)

        except Exception as e:
            print(f"ConflictAnalyzer error: {e}")
            return ConflictAnalysisResult(
                proposals=[],
                summary=f"Lỗi khi phân tích xung đột: {str(e)}"
            )

    def _summarize_existing_nodes(self, nodes: list[dict], max_nodes: int = 80) -> str:
        """
        Create a compact text summary of existing nodes for the LLM prompt.
        Includes entity_id, entity_type, source (file origin), and description snippet.
        """
        lines = []
        for node in nodes[:max_nodes]:
            eid = (node.get("entity_id") or node.get("id") or "?").lower().strip()
            etype = node.get("entity_type", "?")
            desc = (node.get("description") or "")[:150]
            trang_thai = node.get("trang_thai", "")
            # source_id tells LLM which document this node came from (e.g. BLLĐ_2012.docx)
            source_id = node.get("source_id", node.get("source", ""))
            status_str = f" [trạng thái: {trang_thai}]" if trang_thai else ""
            source_str = f" [nguồn: {source_id}]" if source_id else ""
            lines.append(f"- {eid} ({etype}){status_str}{source_str}: {desc}")

        result = "\n".join(lines)
        if len(nodes) > max_nodes:
            result += f"\n... và {len(nodes) - max_nodes} thực thể khác"
        return result
