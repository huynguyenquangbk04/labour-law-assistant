"""Resolve unambiguous statute/article references before semantic retrieval."""

import re


def requested_article_id(query: str) -> str | None:
    documents = set(re.findall(r'(?<!\w)(\d{1,4})\s*/\s*(\d{4})\s*/\s*(QH\d+)(?!\w)', query, re.IGNORECASE))
    articles = set(re.findall(r'\b(?:điều|dieu)\s+(\d+)\b', query, re.IGNORECASE))
    if len(documents) != 1 or len(articles) != 1:
        return None
    document = next(iter(documents))
    return '_'.join(document).lower() + ':dieu_' + next(iter(articles))


def article_context(article_id: str, content: str | None) -> str:
    if content:
        return f'Truy xuất chính xác [{article_id}]:\n{content}'
    return (f'Không tìm thấy điều luật [{article_id}] trong dữ liệu đã được lập chỉ mục của công cụ này. '
            'Chưa đủ căn cứ để tính theo điều luật được yêu cầu; không thay bằng văn bản khác.')


def requested_indexed_article(query: str) -> str | None:
    if re.search(r'\b(?:tài liệu|văn bản|dữ liệu)\s+(?:đã\s+)?(?:nạp|tải lên)\b', query, re.IGNORECASE):
        return requested_article_id(query)
    return None
