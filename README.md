# Labour Law Assistant

**Labour Law Assistant** is a Vietnamese legal Q&A and advisory system combining **Retrieval-Augmented Generation (RAG)**, **LightRAG**, and **LangGraph**. It helps users query labour law issues (contracts, wages, working hours, termination, insurance, etc.) and provides responses backed by grounded legal sources.

---

## 1. System Architecture

The project consists of three main layers:

- **Frontend:** React + Vite + Tailwind CSS interface for direct chat, strategy comparison, and DOCX document uploads.
- **Backend:** FastAPI handling chat APIs, document processing, LLM calls, and reasoning flow orchestration.
- **Knowledge & Storage Layer:** LightRAG integrated with PostgreSQL (using `PGKVStorage`, `PGVectorStorage`, `PGGraphStorage`, and `PGDocStatusStorage`) to build vector embeddings and knowledge graphs from legal documents.

---


## 2. LangGraph Workflow & Node Roles

The system uses a stateful, iterative multi-agent workflow orchestrated by **LangGraph**:

1. **`summarize`**: Generates a standalone query from recent chat history to maintain conversation context.
2. **`get_context`**: Retrieves legal context from LightRAG or GraphRAG. Comparison mode runs naive, hybrid, and drift branches in parallel.
3. **`research`**: Triggers external web searches via Tavily if real-time news, current wage updates, or missing context is required.
4. **`draft`**: Synthesizes context into a structured answer.
5. **`reflect`**: Quality-assurance node that checks legal scope, evidence, conditions, exceptions, validity claims, and hallucinations. Redirects back to `draft` if revisions are needed.
6. **`finalize`**: Formats the final output state and records chat history for the response.

---

## 3. Key Features

- **Vietnamese Legal QA:** Grounded answers for labour law regulations.
- **Custom Knowledge Base:** Upload DOCX documents to dynamically expand the LightRAG store.
- **Flexible Retrieval Modes:** The architecture supports both Hybrid mode (Local + Global LightRAG) and NaiveRAG + Hybrid mode for comparison and evaluation.
- **Choice of Reflection Strategy:** The system allows users to decide whether to enable reflection for higher accuracy or disable it for faster response time.
  Critique mode reviews every answer and uses correction notes to revise it, stopping on acceptance or after three total answer attempts. The chat shows the review notes and distinguishes approval, the attempt limit, and an incomplete review.
- **Web Search Fallback:** Tavily integration to handle information gaps.
- **Payroll skill:** [Skill tính lương và thuế TNCN](backend/skills/payroll/SKILL.md) tự áp dụng
  cho câu hỏi tính tiền tại Việt Nam. Agent hỏi dữ liệu còn thiếu, kiểm tra căn cứ theo kỳ tính
  và dùng `Decimal` để lập bảng số tiền phải trả/thực nhận. Thông số phải có trích dẫn nguồn;
  không có biểu thuế, mức giảm trừ hoặc trần bảo hiểm mặc định trong code.
- **Reflection Loop:** Multi-step verification mechanism to minimize hallucinations.

Graph relations are validated against configured endpoint types and must retain source evidence for semantic relations. The graph API preserves directed relations from `legal_relations`; legacy edges without recoverable direction are marked undirected.

---

## 4. Local Setup & Installation

### Prerequisites
- Python 3.12
- Docker
- Node.js & npm

### Environment Configuration
Copy the example environment file and fill in your own values:

Then update the values in [.env](.env) such as API keys, model names, and database settings.

### Backend Setup
```bash
docker compose up -d
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
