"""Commit resolved batches through the same document pipeline as ordinary uploads."""

import json
from pathlib import Path

from filelock import FileLock

from backend.config import settings
from backend.core import proposal_store
from backend.core.conflict_analyzer import ConflictProposal
from backend.core.doc_graph_enricher import build_legal_graph
from backend.core.rag_engine import RAGEngine
from backend.services.document_ingestion import ingest_document


async def resolve_proposal(proposal_id: str, status: str) -> dict | None:
    if status not in ('approved', 'rejected'):
        raise ValueError('Invalid proposal decision')
    directory = Path(settings.LIGHTRAG_WORKING_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / '.proposal-review.lock'), timeout=0):
        proposals = proposal_store.get_proposals()
        previous = next((p for p in proposals if p['id'] == proposal_id), None)
        if previous is None:
            return None
        batch_id = previous.get('batch_id')
        staged = None
        if previous['status'] != 'pending':
            if previous['status'] != status or not batch_id:
                return previous
            staged = proposal_store.get_staged_chunks(batch_id)
            if staged is None:
                return previous
        if not batch_id:
            raise ValueError('Legacy proposal has no source batch; re-upload the original DOCX')
        # Keep the final decision pending until its batch is fully committed.
        batch = [{**p, 'status': status} if p['id'] == proposal_id else p
                 for p in proposals if p.get('batch_id') == batch_id]
        approved = [ConflictProposal.model_validate(p).model_dump() for p in batch if p['status'] == 'approved']
        if approved:
            staged = staged or proposal_store.get_staged_chunks(batch_id)
            if not staged or not staged.get('parsed_chunks'):
                raise ValueError('Batch lacks the parsed source snapshot. Re-upload the original DOCX; existing review data is retained.')
            incoming = build_legal_graph(staged['parsed_chunks'], staged['filename'])
            incoming_ids = {node['entity_name'] for node in incoming['entities']}
            rag = RAGEngine.get_instance()
            storage = rag.chunk_entity_relation_graph
            targets = await storage.get_nodes_batch(sorted({p['existing_entity_id'].strip() for p in approved}))
            for decision in approved:
                source = decision['new_entity_id'].strip()
                target = decision['existing_entity_id'].strip()
                if source not in incoming_ids or not targets.get(target) or source == target:
                    raise ValueError('A reviewed entity ID does not match the source or existing graph; batch retained')
        if any(p['status'] == 'pending' for p in batch):
            return proposal_store.update_proposal_status(proposal_id, status)
        if approved:
            await ingest_document(staged['parsed_chunks'], staged['filename'])
            # Apply approved changes after indexing so extraction cannot overwrite them.
            for decision in approved:
                source = decision['new_entity_id'].strip()
                target = decision['existing_entity_id'].strip()
                nodes = await storage.get_nodes_batch([source, target])
                if not nodes.get(source) or not nodes.get(target):
                    raise ValueError('A reviewed entity ID is missing from the graph; batch retained')
                tags = decision.get('suggested_tags', {})
                for node_id, tag_key in ((source, 'new_node'), (target, 'old_node')):
                    nodes[node_id].update(tags.get(tag_key, {}))
                await storage.upsert_nodes_batch(list(nodes.items()))
                relation_type = 'AMENDS' if decision['proposal_type'] == 'MODIFIES' else decision['proposal_type']
                relation = {
                    'src_id': source, 'tgt_id': target, 'keywords': relation_type,
                    'description': decision['reason'], 'evidence': decision['reason'],
                    'source_location': source, 'extraction_method': 'human_review',
                }
                previous_edge = await storage.get_edge(source, target)
                edge = previous_edge or {}
                relations = json.loads(edge.get('legal_relations', '[]'))
                relations = [r for r in relations if (r['src_id'], r['keywords'], r['tgt_id']) != (source, relation_type, target)]
                relations.append(relation)
                edge.update({
                    'keywords': ', '.join(sorted({r['keywords'] for r in relations})),
                    'description': '\n'.join(r['description'] for r in relations),
                    'source_id': nodes[source].get('source_id', ''),
                    'legal_relations': json.dumps(relations, ensure_ascii=False),
                })
                edge['weight'] = max(1.0, len(set(filter(None, edge['source_id'].split('<SEP>')))))
                if previous_edge:
                    await rag.aedit_relation(source, target, edge)
                else:
                    await rag.acreate_relation(source, target, edge)
                # Native edit/create updates vectors but only persists its standard fields.
                await storage.upsert_edge(source, target, edge)
            await storage.index_done_callback()
        proposal = proposal_store.update_proposal_status(proposal_id, status)
        proposal_store.delete_staged_chunks(batch_id)
        return proposal
