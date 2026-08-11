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
2. **`get_context`**: Retrieves legal context from LightRAG (supports *Hybrid* or *Naive vs. Hybrid* modes).
3. **`research`**: Triggers external web searches via Tavily if real-time news, current wage updates, or missing context is required.
4. **`draft`**: Synthesizes context into a structured answer.
5. **`reflect`**: Quality-assurance node that checks for legal inaccuracies, missing queries, or hallucinations. Redirects back to `draft` if revisions are needed.
6. **`finalize`**: Formats the final output state and records chat history for the response.

---

## 3. Key Features

- **Vietnamese Legal QA:** Grounded answers for labour law regulations.
- **Custom Knowledge Base:** Upload DOCX documents to dynamically expand the LightRAG store.
- **Hybrid Retrieval Strategy:** Combines vector search with knowledge graph entity-relationship extraction.
- **Web Search Fallback:** Tavily integration to handle information gaps.
- **Reflection Loop:** Multi-step verification mechanism to minimize hallucinations.

---

## 4. Local Setup & Installation

### Prerequisites
- Python 3.10+
- PostgreSQL / Docker
- Node.js & npm

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Start PostgreSQL & Backend
docker compose up -d
python -m backend.main
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```