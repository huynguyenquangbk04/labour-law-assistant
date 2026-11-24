"""
Conflict Analyzer — detects when newly uploaded legal documents
modify, replace, or overlap with entities already in the Knowledge Graph.

Uses the same LLM (via OpenRouter) that powers the rest of the system.
Produces structured proposals that are stored for human review (HITL).
"""

import json
import logging
import re
import uuid
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from backend.core.llm_services import llm_reasoning_func
from backend.config import settings

logger = logging.getLogger(__name__)


class ConflictAnalysisError(RuntimeError):
    """The model could not complete a valid conflict assessment."""

# ── Pydantic models for LLM structured output ──────────────────────────

class ConflictProposal(BaseModel):
    """A single proposed change detected by the LLM."""
    proposal_type: Literal['REPLACES', 'MODIFIES', 'SUPPLEMENTS', 'OVERLAPS'] = Field(
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
    suggested_tags: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Suggested property updates for nodes, e.g. "
            "{'old_node': {'trang_thai': 'het_hieu_luc', 'het_hieu_luc': '2025-01-01'}, "
            " 'new_node': {'hieu_luc_tu': '2025-01-01', 'trang_thai': 'con_hieu_luc'}"
        )
    )

    @field_validator('suggested_tags')
    @classmethod
    def validate_tags(cls, tags):
        if set(tags) - {'old_node', 'new_node'}:
            raise ValueError('Unknown proposal target')
        for properties in tags.values():
            if set(properties) - {'trang_thai', 'hieu_luc_tu', 'het_hieu_luc'}:
                raise ValueError('Only legal validity properties may be reviewed')
            for key, value in properties.items():
                if key == 'trang_thai':
                    if value not in {'con_hieu_luc', 'het_hieu_luc', 'chua_co_hieu_luc', 'khong_ro'}:
                        raise ValueError('Unknown validity status')
                elif value:
                    date.fromisoformat(value)
        return tags

class ConflictAnalysisResult(BaseModel):
    """Full result from the LLM conflict analysis."""
    proposals: list[ConflictProposal]
    summary: str = Field(
        default="",
        description="Brief summary of findings (in Vietnamese)"
    )

# ── The system prompt sent to the LLM ──────────────────────────────────

def _build_conflict_prompt() -> str:
    """Keep review proposals separate from ordinary legal relations."""
    return (
        "Bạn là chuyên gia phân tích pháp luật Việt Nam. Nhiệm vụ: so sánh các đoạn văn bản "
        "MỚI được upload với các thực thể ĐÃ CÓ trong Knowledge Graph, để phát hiện các trường hợp:\n\n"
        f"{settings.conflict_types_guidance}\n\n"
        "Quy tắc:\n"
        "- Mỗi đoạn văn mới bắt đầu bằng \"[Nguồn: <tên_file>]\" — đây là tên file tài liệu mới. "
        "Chỉ dùng tên file để xác định nguồn, không suy luận sửa đổi hoặc hiệu lực từ năm trong tên.\n"
        "- Chỉ báo cáo khi nội dung có bằng chứng cụ thể, trích nguyên văn và ghi Điều/Khoản/Điểm trong reason.\n"
        "- Sao chép ID chuẩn từ [ID: ...]; cùng số Điều ở hai văn bản không chứng minh thay thế.\n"
        "- Không suy ra còn hiệu lực từ ngày ban hành. Sửa đổi một phần không làm hết hiệu lực toàn bộ văn bản.\n"
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
        existing_summary = self._summarize_existing_nodes(existing_nodes, '\n'.join(new_chunks))

        batches = self._new_text_batches(new_chunks, max_chars=6000)
        results: list[ConflictAnalysisResult] = []
        try:
            for new_text in batches:
                user_prompt = (
                    f"## Tài liệu mới: {source_filename}\n\n"
                    f"### Nội dung các đoạn trích (phần {len(results) + 1}/{len(batches)}):\n{new_text}\n\n"
                    f"### Các thực thể ĐÃ CÓ trong Knowledge Graph:\n{existing_summary}\n\n"
                    "Hãy phân tích và trả về JSON theo schema ConflictAnalysisResult. "
                    "Chỉ đề xuất thay đổi được chứng minh trong phần trích này."
                )
                raw = await llm_reasoning_func(
                    user_prompt,
                    system_prompt=_build_conflict_prompt(),
                    response_format={"type": "json_object"},
                    timeout=120,
                )
                if not raw or not raw.strip():
                    raise ValueError('Conflict analysis returned no result')
                json_match = re.search(r'\{[\s\S]*\}', raw)
                parsed = json.loads(json_match.group() if json_match else raw)
                results.append(ConflictAnalysisResult.model_validate(parsed))

            proposals = []
            seen = set()
            for result in results:
                for proposal in result.proposals:
                    key = (proposal.proposal_type, proposal.new_entity_id, proposal.existing_entity_id)
                    if key not in seen:
                        seen.add(key)
                        proposals.append(proposal)
            summaries = [result.summary.strip() for result in results if result.summary.strip()]
            return ConflictAnalysisResult(
                proposals=proposals,
                summary=' '.join(dict.fromkeys(summaries)),
            )
        except Exception as error:
            reason = 'the model returned an invalid result' if isinstance(error, ValueError) else 'the upstream model request failed'
            status = getattr(error, 'status_code', None)
            if status is not None:
                reason += f' (HTTP {status})'
            logger.warning('Conflict analysis failed for %r: type=%s status=%s',
                           source_filename, type(error).__name__, status)
            raise ConflictAnalysisError(
                f'Conflict analysis failed: {reason}; document was not indexed. Please try again.'
            ) from error

    @staticmethod
    def _new_text_batches(chunks: list[str], *, max_chars: int) -> list[str]:
        """Split on chunk boundaries so an article is never cut mid-text."""
        batches: list[str] = []
        current: list[str] = []
        size = 0
        for chunk in chunks:
            text = str(chunk)
            extra = len(text) + (5 if current else 0)
            if current and size + extra > max_chars:
                batches.append('\n---\n'.join(current))
                current, size = [], 0
            current.append(text)
            size += len(text) + (5 if len(current) > 1 else 0)
        if current:
            batches.append('\n---\n'.join(current))
        return batches or ['']

    def _summarize_existing_nodes(self, nodes: list[dict], focus_text: str = '', max_nodes: int = 80) -> str:
        """
        Create a compact text summary of existing nodes for the LLM prompt.
        Includes entity_id, entity_type, source (file origin), and description snippet.
        """
        article_numbers = set(re.findall(r'(?:Điều|dieu)\s+(\d+)\b', focus_text, re.IGNORECASE))
        article_numbers.update(re.findall(r':dieu_(\d+)(?::|\b)', focus_text, re.IGNORECASE))
        focused = []
        other = []
        for node in nodes:
            entity_id = str(node.get('entity_id') or node.get('id') or '').casefold()
            (focused if any(re.search(rf':dieu_{re.escape(number)}(?::|$)', entity_id) for number in article_numbers) else other).append(node)
        selected = (focused + other)[:max_nodes]
        lines = []
        for node in selected:
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
            result += f"\n... và {len(nodes) - max_nodes} thực thể khác (đã ưu tiên các Điều được nhắc trong tài liệu mới)"
        return result
