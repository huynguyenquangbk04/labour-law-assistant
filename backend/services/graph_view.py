"""Expose directed legal facts without inventing direction for legacy edges."""

import json
import re

from backend.config import settings
from backend.core.legal_schema import CONFLICT_TYPES, validate_relation_semantics


def serialize_graph(graph: dict) -> dict:
    def canonical_key(value) -> str:
        return str(value).strip().casefold()

    def canonical_type(value) -> str:
        raw = str(value or 'Unknown').strip()
        return next((name for name in settings.APP_ENTITY_TYPES
                     if name.casefold() == raw.casefold()), raw)

    def canonical_relation(value) -> str:
        raw = str(value or '').strip()
        candidates = [*settings.APP_EDGE_TYPES, *CONFLICT_TYPES]
        return next((name for name in candidates
                     if name.casefold() == raw.casefold()), raw)

    nodes = []
    aliases = {}
    names = {}
    types = {}
    for node in graph.get('nodes', []):
        properties = node.get('properties', {})
        name = properties.get('entity_id') or next(iter(node.get('labels', [])), str(node['id']))
        aliases[name] = node['id']
        aliases[canonical_key(name)] = node['id']
        names[node['id']] = name
        types[node['id']] = canonical_type(properties.get('entity_type', 'Unknown'))
        nodes.append({
            'id': node['id'], 'label': properties.get('label') or name,
            'type': types[node['id']],
            **{key: properties.get(key, '') for key in (
                'description', 'trang_thai', 'hieu_luc_tu', 'het_hieu_luc',
                'source_location', 'evidence', 'extraction_method', 'file_path',
            )},
        })
    links = []
    for edge in graph.get('edges', []):
        source, target = edge.get('source'), edge.get('target')
        if source not in names or target not in names:
            continue
        properties = edge.get('properties', {})
        try:
            relations = json.loads(properties.get('legal_relations', '[]'))
        except (json.JSONDecodeError, TypeError):
            relations = []
        if not isinstance(relations, list):
            relations = []
        # Native semantic extraction carries direction in its evidence description.
        if not relations:
            match = re.search(r'([A-Z_]+):\s*([^\s;\\]+)\s*->\s*([^\s;\\]+)',
                              properties.get('description', ''), re.IGNORECASE)
            if match:
                relations = [{'keywords': match.group(1), 'src_id': match.group(2).strip(),
                              'tgt_id': match.group(3).strip(),
                              'description': properties['description'], 'extraction_method': 'llm'}]
        # PGGraphStorage retains native direction on the edge even when the
        # richer legal_relations payload is absent.
        if not relations and str(edge.get('type', '')).upper() == 'DIRECTED' and properties.get('keywords'):
            relations = [{'keywords': properties['keywords'], 'src_id': names[source],
                          'tgt_id': names[target], 'description': properties.get('description', ''),
                          'evidence': properties.get('evidence', ''),
                          'extraction_method': 'storage'}]
        valid = []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            src_id = aliases.get(canonical_key(relation.get('src_id', '')))
            tgt_id = aliases.get(canonical_key(relation.get('tgt_id', '')))
            relation_type = canonical_relation(relation.get('keywords'))
            if (src_id is None or tgt_id is None or
                    {src_id, tgt_id} != {source, target} or
                    relation_type not in settings.APP_EDGE_TYPE_DESCRIPTIONS and
                    relation_type not in CONFLICT_TYPES):
                continue
            evidence = f"{relation.get('description', '')}\n{relation.get('evidence', '')}"
            if validate_relation_semantics(types.get(src_id, 'Unknown'), types.get(tgt_id, 'Unknown'),
                                           relation_type, evidence=evidence) is None:
                valid.append((relation, src_id, tgt_id, relation_type))
        if valid:
            for relation, src_id, tgt_id, relation_type in valid:
                links.append({
                    'source': src_id, 'target': tgt_id,
                    'label': relation_type, 'directed': True,
                    **{key: relation.get(key, '') for key in ('description', 'evidence', 'source_location', 'extraction_method')},
                })
        else:
            links.append({'source': source, 'target': target, 'label': properties.get('keywords', ''),
                          'description': properties.get('description', ''), 'directed': False})
    return {'nodes': nodes, 'links': links, 'is_truncated': bool(graph.get('is_truncated', False))}
