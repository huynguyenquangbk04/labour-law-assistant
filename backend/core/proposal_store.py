"""
Proposal Store — JSON-file-based storage for conflict proposals.

Each proposal is stored as a JSON object with a unique ID, status (pending/approved/rejected),
and the conflict details from the ConflictAnalyzer.

Staged chunks are stored separately so that ainsert is deferred until human approval.
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional
from backend.config import settings


PROPOSALS_FILE = os.path.join(settings.LIGHTRAG_WORKING_DIR, "proposals.json")
STAGED_DIR = os.path.join(settings.LIGHTRAG_WORKING_DIR, "staged")


def _load_proposals() -> list[dict]:
    """Load all proposals from disk."""
    if not os.path.exists(PROPOSALS_FILE):
        return []
    try:
        with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_proposals(proposals: list[dict]) -> None:
    """Save all proposals to disk."""
    os.makedirs(os.path.dirname(PROPOSALS_FILE), exist_ok=True)
    with open(PROPOSALS_FILE, "w", encoding="utf-8") as f:
        json.dump(proposals, f, ensure_ascii=False, indent=2)


# ── Staged chunks (deferred insert) ───────────────────────────────────

def stage_chunks(
    batch_id: str,
    filename: str,
    chunks: list[str],
    file_paths: list[str],
    paragraphs: list[str] | None = None,
    full_text: str | None = None,
) -> None:
    """Save chunks to a staging file so they can be inserted after human approval."""
    os.makedirs(STAGED_DIR, exist_ok=True)
    staged_file = os.path.join(STAGED_DIR, f"{batch_id}.json")
    with open(staged_file, "w", encoding="utf-8") as f:
        json.dump({
            "batch_id": batch_id,
            "filename": filename,
            "chunks": chunks,
            "file_paths": file_paths,
            "paragraphs": paragraphs or [],
            "full_text": full_text or "",
            "created_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)


def get_staged_chunks(batch_id: str) -> Optional[dict]:
    """Load staged chunks by batch_id."""
    staged_file = os.path.join(STAGED_DIR, f"{batch_id}.json")
    if not os.path.exists(staged_file):
        return None
    try:
        with open(staged_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def delete_staged_chunks(batch_id: str) -> None:
    """Remove staged chunks after they've been inserted or rejected."""
    staged_file = os.path.join(STAGED_DIR, f"{batch_id}.json")
    if os.path.exists(staged_file):
        os.remove(staged_file)


# ── Proposals ─────────────────────────────────────────────────────────

def add_proposals(
    analysis_result,
    source_filename: str,
    batch_id: str,
) -> list[dict]:
    """
    Save proposals from a ConflictAnalysisResult to the store.
    All proposals in a batch share the same batch_id (linked to staged chunks).
    
    Returns the list of newly created proposal dicts (with IDs).
    """
    proposals = _load_proposals()
    new_proposals = []

    for p in analysis_result.proposals:
        proposal = {
            "id": str(uuid.uuid4()),
            "batch_id": batch_id,
            "status": "pending",  # pending | approved | rejected
            "created_at": datetime.now().isoformat(),
            "source_filename": source_filename,
            "proposal_type": p.proposal_type,
            "new_entity_id": p.new_entity_id,
            "existing_entity_id": p.existing_entity_id,
            "reason": p.reason,
            "suggested_tags": p.suggested_tags,
        }
        proposals.append(proposal)
        new_proposals.append(proposal)

    if new_proposals:
        _save_proposals(proposals)

    return new_proposals


def get_proposals(status: Optional[str] = None) -> list[dict]:
    """
    Get proposals, optionally filtered by status.
    
    Args:
        status: "pending", "approved", "rejected", or None for all.
    """
    proposals = _load_proposals()
    if status:
        proposals = [p for p in proposals if p.get("status") == status]
    return proposals


def are_all_resolved(batch_id: str) -> bool:
    """Check if all proposals in a batch have been resolved (approved or rejected)."""
    proposals = _load_proposals()
    batch_proposals = [p for p in proposals if p.get("batch_id") == batch_id]
    if not batch_proposals:
        return True
    return all(p.get("status") in ("approved", "rejected") for p in batch_proposals)


def get_approved_proposals(batch_id: str) -> list[dict]:
    """Get all approved proposals in a batch."""
    proposals = _load_proposals()
    return [p for p in proposals if p.get("batch_id") == batch_id and p.get("status") == "approved"]


def update_proposal_status(proposal_id: str, new_status: str) -> Optional[dict]:
    """
    Update a proposal's status to 'approved' or 'rejected'.
    
    Returns the updated proposal dict, or None if not found.
    """
    proposals = _load_proposals()
    target = None
    for p in proposals:
        if p["id"] == proposal_id:
            p["status"] = new_status
            p["resolved_at"] = datetime.now().isoformat()
            target = p
            break

    if target:
        _save_proposals(proposals)
    return target
