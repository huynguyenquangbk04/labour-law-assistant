"""
Parse Bộ luật Lao động (.docx) thành các chunk theo Điều.
"""

import json
import re
from hashlib import sha256
from pathlib import Path
import docx
from docx.text.paragraph import Paragraph


CHUONG_RE = re.compile(r"^Chương\s+([IVXLCDM]+|\d+)(?:[.:]\s*(.*))?\s*$", re.IGNORECASE)
MUC_RE = re.compile(r"^Mục\s+(\d+)(?:[.:]\s*(.*))?\s*$", re.IGNORECASE)
DIEU_RE = re.compile(r"^Điều\s+(\d+)\.\s*(.*)$")
DIEU_BOOKMARK_RE = re.compile(r'w:name="dieu_(\d+)"')


def has_dieu_bookmark(p):
    """
    Trả về số Điều nếu paragraph chứa bookmark 'dieu_<n>', ngược lại None.
    Có logic này là vì các nguồn dữ liệu hiện tại chứa bookmarks tại mỗi Điều.
    Nếu file .docx không có bookmark theo Điều thì dựa vào DIEU_RE + bold (có triển khai bên dưới).
    """
    m = DIEU_BOOKMARK_RE.search(p._p.xml)
    return m.group(1) if m else None


def is_run_bold(r) -> bool:
    """
    Kiểm tra 1 run có bold hay không. Run là 1 phần của paragraph, chứa các text cùng style với nhau.
    Một run có thể là một paragraph.
    """
    if r.bold is True:
        return True
    if r.bold is False:
        return False
    # r.bold is None -> kiểm tra bold ở cấp style của run/paragraph
    try:
        return bool(r.style.font.bold)
    except AttributeError:
        return False


def is_bold_paragraph(p) -> bool:
    """True nếu mọi run có nội dung trong paragraph đều bold (trực tiếp hoặc qua style)."""
    runs = [r for r in p.runs if r.text.strip()]
    if not runs:
        return False
    return all(is_run_bold(r) for r in runs)


def parse_docx(path: str, source_filename: str | None = None):
    doc = docx.Document(path)
    # Metadata (including the document number) can live in a table.
    paragraphs = [Paragraph(p, doc) for p in doc.element.body.xpath('.//w:p')]
    paragraphs = [p for p in paragraphs if p.text.strip()]
    text = '\n'.join(p.text.strip() for p in paragraphs)
    number = re.search(r'(?:Luật|Bộ luật|Nghị định|Thông tư|Nghị quyết|Số)\s*(?:số)?\s*:\s*([\wĐđ-]+/\d{4}/[\wĐđ-]+)', text, re.IGNORECASE)
    source_filename = source_filename or Path(path).name
    document_number = number.group(1) if number else Path(source_filename).stem
    document_id = re.sub(r'[^\w-]+', '_', document_number.casefold()).strip('_')
    if not number:
        document_id += '_' + sha256(source_filename.encode()).hexdigest()[:12]

    chunks = []

    # --- 1. Tách phần mở đầu (trước "Chương I") ---
    first_chuong_idx = None
    for i, p in enumerate(paragraphs):
        if CHUONG_RE.match(p.text.strip()):
            first_chuong_idx = i
            break

    if first_chuong_idx is None:
        raise ValueError("Không tìm thấy 'Chương I' trong văn bản — kiểm tra lại file input.")

    preamble_text = "\n".join(p.text.strip() for p in paragraphs[:first_chuong_idx])
    if preamble_text.strip():
        chunks.append({
            "id": "preamble",
            "title": "Lời mở đầu",
            "text": preamble_text,
            "type": "preamble",
            "chuong_so": None,
            "chuong_ten": None,
            "muc_so": None,
            "muc_ten": None,
            "dieu_so": None,
            "dieu_ten": None,
        })

    # --- 2. Duyệt qua toàn bộ paragraph còn lại, gom theo Điều ---
    current_chuong_so = None
    current_chuong_ten = None
    current_muc_so = None
    current_muc_ten = None

    current_dieu_so = None
    current_dieu_ten = None
    current_dieu_lines = []

    def flush_dieu():
        if current_dieu_so is None:
            return
        header = f"[Chương {current_chuong_so} - {current_chuong_ten}]"
        if current_muc_so is not None:
            header += f" [Mục {current_muc_so} - {current_muc_ten}]"
        header += f"\nĐiều {current_dieu_so}. {current_dieu_ten}"

        body = "\n".join(current_dieu_lines)
        full_text = f"{header}\n\n{body}".strip()

        chunks.append({
            "id": f"dieu_{current_dieu_so}",
            "title": f"Điều {current_dieu_so}. {current_dieu_ten}",
            "text": full_text,
            "body": body,
            "type": "dieu",
            "chuong_so": current_chuong_so,
            "chuong_ten": current_chuong_ten,
            "muc_so": current_muc_so,
            "muc_ten": current_muc_ten,
            "dieu_so": current_dieu_so,
            "dieu_ten": current_dieu_ten,
        })

    i = first_chuong_idx
    n = len(paragraphs)
    while i < n:
        text = paragraphs[i].text.strip()

        # --- Chương: paragraph này là "Chương <số>", paragraph kế tiếp là tên ---
        m_chuong = CHUONG_RE.match(text)
        if m_chuong:
            flush_dieu()
            current_dieu_so = None
            current_dieu_ten = None
            current_dieu_lines = []

            current_chuong_so = m_chuong.group(1)
            # Tên chương nằm ở paragraph ngay sau, cũng phải bold + HOA
            if m_chuong.group(2):
                current_chuong_ten = m_chuong.group(2).strip()
                i += 1
            elif i + 1 < n and paragraphs[i + 1].text.strip().isupper():
                current_chuong_ten = paragraphs[i + 1].text.strip()
                i += 2
            else:
                current_chuong_ten = ""
                i += 1

            # Sang chương mới thì reset Mục
            current_muc_so = None
            current_muc_ten = None
            continue

        # --- Mục: "Mục <số>. TÊN MỤC" trên cùng 1 dòng ---
        m_muc = MUC_RE.match(text)
        if m_muc:
            flush_dieu()
            current_dieu_so = None
            current_dieu_ten = None
            current_dieu_lines = []

            current_muc_so = m_muc.group(1)
            current_muc_ten = (m_muc.group(2) or '').strip()
            i += 1
            if not current_muc_ten and i < n and paragraphs[i].text.strip().isupper():
                current_muc_ten = paragraphs[i].text.strip()
                i += 1
            continue

        # --- Điều: ưu tiên bookmark 'dieu_<n>' (đáng tin cậy nhất, không
        # phụ thuộc bold); nếu không có bookmark thì fallback về regex + bold ---
        bm_so = has_dieu_bookmark(paragraphs[i])
        m_dieu = DIEU_RE.match(text)
        if bm_so is not None or m_dieu:
            flush_dieu()
            if m_dieu:
                current_dieu_so = bm_so or m_dieu.group(1)
                current_dieu_ten = m_dieu.group(2).strip()
            else:
                # Có bookmark nhưng text không khớp regex chuẩn (hiếm) ->
                # vẫn lấy nguyên dòng làm tên, số điều lấy từ bookmark
                current_dieu_so = bm_so
                current_dieu_ten = text
            current_dieu_lines = []
            i += 1
            continue

        # --- Dòng nội dung bình thường (khoản, điểm...) thuộc Điều hiện tại ---
        if text.startswith('Bộ luật này đã được Quốc hội') or text.startswith('CHỦ TỊCH QUỐC HỘI'):
            break
        if current_dieu_so is not None:
            current_dieu_lines.append(text)
        i += 1

    flush_dieu()  # đừng quên Điều cuối cùng

    for chunk in chunks:
        chunk['id'] = f"{document_id}:{chunk['id']}"
        chunk['document_id'] = document_id
        chunk['document_number'] = document_number
        chunk['source_file'] = source_filename
        chunk.setdefault('body', chunk['text'])
        chunk['text'] = f"[Văn bản: {document_number}] [ID: {chunk['id']}]\n{chunk['text']}"
    return chunks


def parse_and_save_docx(input_path: str, output_paths: list[str] | str):
    chunks = parse_docx(input_path)

    if isinstance(output_paths, str):
        output_paths = [output_paths]

    for output_path in output_paths:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

    return chunks
