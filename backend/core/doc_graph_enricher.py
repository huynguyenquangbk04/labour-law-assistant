"""
doc_graph_enricher.py
---------------------
Post-insert graph enrichment after rag.ainsert().

Two jobs:
1. Seed structural nodes (Chương, Điều, Khoản) directly from DOCX parse — 
   LLM won't reliably extract these when each chunk IS one Điều.
2. LLM-extract trang_thai per Điều and patch graph nodes via upsert_node.
"""

import re
import json
import logging
from typing import Optional

import openai

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Regex patterns ─────────────────────────────────────────────────────────────

_CHUONG_RE = re.compile(r"^Chương\s+([IVXLCDM]+|\d+)[.:)]*\s*(.*)$", re.IGNORECASE)
_DIEU_RE   = re.compile(r"^Điều\s+(\d+)[.:)]*\s*(.*)$",              re.IGNORECASE)
_KHOAN_RE  = re.compile(r"^(\d+)\.\s+(.+)$")  # e.g. "1. Người lao động có quyền..."

# ── Structural node extraction ─────────────────────────────────────────────────

def extract_structural_nodes(paragraphs: list[str], source_filename: str) -> list[dict]:
    """
    Parse paragraph list and return node dicts for Chương, Điều, Khoản.
    Node IDs are deterministic: lowercase slug from filename + number.
    """
    nodes: list[dict] = []
    doc_slug = re.sub(r"\s+", "_", source_filename.lower().removesuffix(".docx"))

    current_chuong_id: Optional[str] = None
    current_dieu_id:   Optional[str] = None

    for line in paragraphs:
        stripped = line.strip()

        m_chuong = _CHUONG_RE.match(stripped)
        if m_chuong:
            num, title = m_chuong.group(1), m_chuong.group(2).strip()
            node_id = f"chuong_{num.lower()}_{doc_slug}"
            nodes.append({
                "node_id": node_id,
                "props": {
                    "entity_id":   node_id,
                    "entity_type": "Chương",
                    "description": f"Chương {num}" + (f": {title}" if title else ""),
                    "so_chuong":   num,
                    "source_file": source_filename,
                },
            })
            current_chuong_id = node_id
            current_dieu_id = None
            continue

        m_dieu = _DIEU_RE.match(stripped)
        if m_dieu:
            num, title = m_dieu.group(1), m_dieu.group(2).strip()
            node_id = f"dieu_{num}_{doc_slug}"
            props: dict = {
                "entity_id":   node_id,
                "entity_type": "Điều",
                "description": f"Điều {num}" + (f": {title}" if title else ""),
                "so_dieu":     num,
                "source_file": source_filename,
            }
            if current_chuong_id:
                props["chuong_id"] = current_chuong_id
            nodes.append({"node_id": node_id, "props": props})
            current_dieu_id = node_id
            continue

        m_khoan = _KHOAN_RE.match(stripped)
        if m_khoan and current_dieu_id and len(stripped) > 5:
            num, text = m_khoan.group(1), m_khoan.group(2).strip()
            node_id = f"khoan_{num}_{current_dieu_id}"
            nodes.append({
                "node_id": node_id,
                "props": {
                    "entity_id":   node_id,
                    "entity_type": "Khoản",
                    "description": text[:200],
                    "so_khoan":    num,
                    "dieu_id":     current_dieu_id,
                    "source_file": source_filename,
                },
            })

    return nodes


# ── trang_thai LLM extraction ─────────────────────────────────────────────────

_TRANG_THAI_PROMPT = """\
Bạn là trợ lý pháp lý. Đọc văn bản pháp luật dưới đây và trả về JSON.

Với mỗi Điều được đề cập, xác định:
- "dieu": số Điều (chỉ số nguyên, ví dụ: "10")
- "trang_thai": một trong ["con_hieu_luc", "het_hieu_luc", "chua_co_hieu_luc", "khong_ro"]

Chỉ trả về JSON array, không giải thích. Ví dụ:
[{"dieu": "5", "trang_thai": "con_hieu_luc"}, {"dieu": "12", "trang_thai": "het_hieu_luc"}]

Văn bản:
{text}
"""


async def extract_trang_thai_per_dieu(text: str) -> dict[str, str]:
    """
    LLM call on full doc text. Returns {dieu_number_str: trang_thai_str}.
    Falls back to empty dict on any error.
    """
    client = openai.AsyncOpenAI(
        base_url=settings.BASE_URL,
        api_key=settings.API_KEY,
    )
    prompt = _TRANG_THAI_PROMPT.format(text=text[:12000])  # token budget
    try:
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        # Strip markdown code fences if present
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip().strip("`")
        data = json.loads(raw)
        return {str(item["dieu"]): item["trang_thai"] for item in data if "dieu" in item and "trang_thai" in item}
    except Exception as e:
        logger.warning("trang_thai extraction failed (non-fatal): %s", e)
        return {}


# ── Main enrichment entry point ───────────────────────────────────────────────

async def enrich_graph(
    graph_storage,           # rag.chunk_entity_relation_graph
    paragraphs: list[str],
    full_text: str,
    source_filename: str,
) -> dict:
    """
    1. Upsert structural nodes (Chương, Điều, Khoản).
    2. Extract trang_thai per Điều via LLM and patch matching nodes.

    Returns summary dict for logging.
    """
    doc_slug = re.sub(r"\s+", "_", source_filename.lower().removesuffix(".docx"))

    # ── Step 1: structural nodes ───────────────────────────────────────────────
    structural_nodes = extract_structural_nodes(paragraphs, source_filename)
    upserted = 0
    for item in structural_nodes:
        try:
            await graph_storage.upsert_node(item["node_id"], item["props"])
            upserted += 1
        except Exception as e:
            logger.warning("upsert_node failed for %s: %s", item["node_id"], e)

    # ── Step 2: trang_thai patch ───────────────────────────────────────────────
    trang_thai_map = await extract_trang_thai_per_dieu(full_text)
    patched = 0
    for dieu_num, trang_thai in trang_thai_map.items():
        node_id = f"dieu_{dieu_num}_{doc_slug}"
        try:
            # fetch existing props so we don't overwrite them
            existing = await graph_storage.get_node(node_id)
            if existing:
                existing["trang_thai"] = trang_thai
                await graph_storage.upsert_node(node_id, existing)
                patched += 1
            else:
                # node may not exist yet if LLM didn't extract it — create minimal
                await graph_storage.upsert_node(node_id, {
                    "entity_id":   node_id,
                    "entity_type": "Điều",
                    "description": f"Điều {dieu_num}",
                    "so_dieu":     dieu_num,
                    "trang_thai":  trang_thai,
                    "source_file": source_filename,
                })
                patched += 1
        except Exception as e:
            logger.warning("trang_thai patch failed for dieu_%s: %s", dieu_num, e)

    return {
        "structural_nodes_upserted": upserted,
        "trang_thai_patched": patched,
    }
