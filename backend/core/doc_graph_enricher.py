"""Deterministic structure and explicit local citations; semantic rules use LLM extraction."""

import json
import re
from collections import defaultdict


_CLAUSE = re.compile(r'^(\d+)\.\s+(.+)')
_POINT = re.compile(r'^([a-zđ])\)\s+(.+)')
_NUMBERS = r'\d+(?:(?:\s*,\s*|\s+và\s+)\d+)*'
_LETTERS = r'[a-zđ](?:(?:\s*,\s*|\s+và\s+)[a-zđ])*'
_REFERENCE = re.compile(
    rf'(?:(?:các\s+)?điểm\s+(?P<points>{_LETTERS})\s+)?'
    rf'(?:(?:các\s+)?khoản\s+(?P<clauses>{_NUMBERS})\s+)?'
    r'Điều\s+(?P<article>\d+|này)\b', re.IGNORECASE,
)


def build_legal_graph(chunks: list[dict], source_filename: str) -> dict:
    """Build a LightRAG custom KG with resolvable chunk evidence and scoped IDs."""
    if not chunks:
        raise ValueError('Document has no chunks')
    document_id = chunks[0]['document_id']
    if any(c.get('document_id') != document_id for c in chunks):
        raise ValueError('All chunks must belong to one document')
    if len({c['id'] for c in chunks}) != len(chunks):
        raise ValueError('Duplicate provision IDs in document')
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict] = {}
    units: list[tuple[str, str, str, dict]] = []

    def node(node_id, kind, label, text, chunk, location):
        if node_id not in nodes:
            nodes[node_id] = {
                'entity_name': node_id, 'entity_type': kind, 'label': label,
                'description': f'{label}\nNguồn: {source_filename}; {location}\n{text}',
                'source_id': chunk['id'], 'file_path': source_filename,
                'source_location': location, 'evidence': text,
                'extraction_method': 'deterministic',
            }

    def edge(source, target, kind, chunk, evidence):
        if source != target:
            edges[(source, kind, target)] = {
                'src_id': source, 'tgt_id': target, 'keywords': kind,
                'description': f'{kind}: {source} -> {target}\nNguồn: {chunk["id"]}\n{evidence}',
                'source_id': chunk['id'], 'file_path': source_filename, 'weight': 1.0,
                'source_location': target if kind == 'CONTAINS' else source, 'evidence': evidence,
                'extraction_method': 'deterministic',
            }

    first = chunks[0]
    node(document_id, 'VanBanPhapLuat', first['document_number'], first['body'], first, document_id)
    for chunk in chunks:
        if chunk['type'] != 'dieu':
            continue
        article_id = chunk['id']
        chapter_id = f'{document_id}:chuong_{chunk["chuong_so"].lower()}'
        chapter_title = f'Chương {chunk["chuong_so"]}. {chunk["chuong_ten"]}'
        node(chapter_id, 'Chuong', chapter_title, chapter_title, chunk, chapter_id)
        edge(document_id, chapter_id, 'CONTAINS', chunk, chapter_title)
        parent_id = chapter_id
        if chunk['muc_so']:
            parent_id = f'{chapter_id}:muc_{chunk["muc_so"]}'
            title = f'Mục {chunk["muc_so"]}. {chunk["muc_ten"]}'
            node(parent_id, 'Muc', title, title, chunk, parent_id)
            edge(chapter_id, parent_id, 'CONTAINS', chunk, title)
        node(article_id, 'Dieu', chunk['title'], chunk['body'], chunk, article_id)
        edge(parent_id, article_id, 'CONTAINS', chunk, chunk['title'])

        # Accumulate continuation paragraphs before resolving references.
        content: dict[str, list[str]] = {article_id: []}
        parents: dict[str, str] = {}
        kinds: dict[str, str] = {}
        current_clause = article_id
        current_unit = article_id
        for line in chunk['body'].splitlines():
            clause = _CLAUSE.match(line.strip())
            point = _POINT.match(line.strip())
            if clause:
                current_clause = f'{article_id}:khoan_{clause.group(1)}'
                current_unit = current_clause
                parents[current_unit] = article_id
                kinds[current_unit] = 'Khoan'
            elif point:
                current_unit = f'{current_clause}:diem_{point.group(1)}'
                parents[current_unit] = current_clause
                kinds[current_unit] = 'Diem'
            content.setdefault(current_unit, []).append(line)
        for unit_id, lines in content.items():
            own_text = '\n'.join(lines)
            if unit_id != article_id:
                parent = parents[unit_id]
                context = '\n'.join(content[article_id])
                if parent != article_id:
                    context += '\n' + '\n'.join(content[parent])
                location = unit_id.split(':', 1)[1].replace('dieu_', 'Điều ').replace('khoan_', 'Khoản ').replace('diem_', 'Điểm ').replace(':', ' / ')
                node(unit_id, kinds[unit_id], location, f'{context}\n{own_text}'.strip(), chunk, unit_id)
                edge(parent, unit_id, 'CONTAINS', chunk, own_text)
            units.append((unit_id, article_id, own_text, chunk))

    unresolved = []
    for unit_id, article_id, text, chunk in units:
        for match in _REFERENCE.finditer(text):
            tail = text[match.end():]
            scope = re.match(r'\s+(?:của\s+)?((?:Bộ luật|Luật|Nghị định|Thông tư|Nghị quyết)\b[^.;,]*)', tail, re.IGNORECASE)
            if scope and not re.match(r'(?:Bộ luật|Luật)\s+này\b', scope.group(1), re.IGNORECASE):
                unresolved.append({'source': unit_id, 'citation': match.group() + scope.group()})
                continue
            number = match.group('article')
            target = article_id if number.casefold() == 'này' else f'{document_id}:dieu_{number}'
            clauses = re.findall(r'\d+', match.group('clauses') or '')
            points = re.findall(r'\b[a-zđ]\b', match.group('points') or '', re.IGNORECASE)
            targets = [f'{target}:khoan_{n}' for n in clauses] if clauses else [target]
            if points:
                targets = [f'{t}:diem_{p.lower()}' for t in targets for p in points]
            for target in targets:
                if target in nodes:
                    edge(unit_id, target, 'REFERENCES', chunk, text)
                else:
                    unresolved.append({'source': unit_id, 'citation': match.group()})
    return {
        'entities': list(nodes.values()), 'relationships': list(edges.values()),
        'chunks': [{'content': c['text'], 'source_id': c['id'], 'file_path': source_filename} for c in chunks],
        'unresolved_references': unresolved,
    }


async def enrich_graph(rag, chunks: list[dict], source_filename: str) -> dict:
    """Import into graph AND vectors, then preserve directed legal evidence.

    Source JSON is retained by ingestion for idempotent retry after partial failures.
    """
    from lightrag.utils import compute_mdhash_id, sanitize_text_for_encoding
    from lightrag.kg.shared_storage import get_storage_keyed_lock

    graph = build_legal_graph(chunks, source_filename)
    pairs = defaultdict(list)
    for relation in graph['relationships']:
        pairs[tuple(sorted((relation['src_id'], relation['tgt_id'])))].append(relation)
    relationships = [{
        **relations[0], 'src_id': source, 'tgt_id': target,
        'keywords': ', '.join(sorted({r['keywords'] for r in relations})),
        'description': '\n\n'.join(r['description'] for r in relations),
    } for (source, target), relations in pairs.items()]
    # shortcut: the SDK custom-KG path has no recovery journal; retain source snapshots
    # for replay until the SDK supports journaled custom graph imports.
    await rag.ainsert_custom_kg({**graph, 'relationships': relationships})

    storage = rag.chunk_entity_relation_graph
    keys = sorted(n['entity_name'] for n in graph['entities'])
    namespace = f'{rag.workspace}:GraphDB' if rag.workspace else 'GraphDB'
    chunk_ids = {c['id']: compute_mdhash_id(sanitize_text_for_encoding(c['text']), prefix='chunk-') for c in chunks}
    async with get_storage_keyed_lock(keys, namespace=namespace):
        existing_nodes = await storage.get_nodes_batch(keys)
        existing_edges = await storage.get_edges_batch([{'src': s, 'tgt': t} for s, t in pairs])
        node_updates = []
        for item in graph['entities']:
            existing = existing_nodes.get(item['entity_name'])
            if existing is None:
                raise RuntimeError(f'Imported node is missing: {item["entity_name"]}')
            existing.update({k: item[k] for k in ('label', 'source_location', 'evidence', 'extraction_method')})
            node_updates.append((item['entity_name'], existing))
        await storage.upsert_nodes_batch(node_updates)
        edge_updates = []
        for (source, target), relations in pairs.items():
            existing = existing_edges.get((source, target))
            if existing is None:
                raise RuntimeError(f'Imported edge is missing: {source} -> {target}')
            existing['legal_relations'] = json.dumps(relations, ensure_ascii=False)
            evidence_ids = {chunk_ids[r['source_id']] for r in relations}
            existing['source_id'] = '<SEP>'.join(sorted(evidence_ids))
            existing['weight'] = max(float(existing.get('weight', 1.0)), len(evidence_ids))
            edge_updates.append((source, target, existing))
        await storage.upsert_edges_batch(edge_updates)
        await storage.index_done_callback()
    return {'nodes': len(graph['entities']), 'edges': len(graph['relationships']),
            'unresolved_references': graph['unresolved_references']}
