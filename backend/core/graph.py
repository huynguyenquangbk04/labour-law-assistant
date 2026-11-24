"""
graph.py — Multi-agent LangGraph system for the Labour Law Assistant.

Architecture
────────────
SupervisorAgent
├── QAAgent          (single-engine: lightrag or graphrag, optional critique loop)
└── ComparisonAgent  (parallel: naive + hybrid + drift, optional parallel reflect)

Public interface (used by routes.py, main.py — unchanged):
  agent = Agent(model, tavily, memory)
  agent.graph.ainvoke(input, config)
  agent.graph.astream_events(input, config, version="v2")
  agent.model  →  the ChatOpenAI instance

Routing (zero LLM cost):
  comparison_mode=False  →  QAAgent
  comparison_mode=True   →  ComparisonAgent
"""

import asyncio
import logging
import operator
import re
from contextlib import aclosing
from functools import partial
from typing import TypedDict, Annotated, Literal

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_openai import ChatOpenAI
from tavily import AsyncTavilyClient
from pydantic import BaseModel, Field, StringConstraints
from lightrag import QueryParam

from backend.config import settings
from backend.core.rag_engine import RAGEngine
from backend.core.graphrag_engine import GraphRAGEngine
from backend.services.payroll import run_payroll_skill
from backend.services.legal_retrieval import requested_article_id, requested_indexed_article
from backend.core.prompts import SUMMARIZE_PROMPT, RESEARCH_PROMPT, DRAFT_PROMPT, REFLECT_PROMPT


# ── Module-level singletons (imported by main.py) ─────────────────────────────

model = ChatOpenAI(
    model_name=settings.OPENAI_MODEL,
    temperature=0,
    base_url=settings.BASE_URL,
    api_key=settings.API_KEY,
)

tavily = AsyncTavilyClient()
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Shared state & Pydantic models
# ══════════════════════════════════════════════════════════════════════════════

class DualContent(TypedDict, total=False):
    naive: str
    hybrid: str
    drift: str
    active: str


class ModifyCheck(TypedDict, total=False):
    naive: bool
    hybrid: bool
    drift: bool
    active: bool


class SearchQueries(BaseModel):
    search_queries: list[str] = Field(
        ...,
        max_length=2,
        description=(
            "List of 0 to 2 concise search terms for Tavily. "
            "Return empty list if no search is needed."
        )
    )


class ReflectAnswer(BaseModel):
    should_modify: bool = Field(
        ...,
        description=(
            "Set to True ONLY if the draft contains critical legal errors, severe hallucinations, "
            "or fails to answer the user query. Set to False for acceptable or minor stylistic drafts."
        )
    )
    feedback: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        ...,
        description=(
            "Clear, actionable feedback detailing specific legal corrections required if "
            "should_modify is True. Provide brief justification if False."
        )
    )


class CritiqueReview(TypedDict):
    attempt: int
    should_modify: bool
    feedback: str


class CritiqueResult(TypedDict):
    status: Literal["approved", "limit_reached", "failed"]
    max_attempts: int
    reviews: list[CritiqueReview]


class BranchError(TypedDict):
    stage: Literal["retrieval", "draft", "reflection", "research"]
    message: str


async def _branch_error(mode: str, stage: Literal["retrieval", "draft", "reflection", "research"], error: Exception | None = None) -> BranchError:
    messages = {
        "retrieval": "This retrieval engine is temporarily unavailable.",
        "draft": "This answer could not be generated. Please try again.",
        "reflection": "This answer could not be verified. Please try again.",
        "research": "External research is unavailable; this answer uses retrieved context.",
    }
    if error is not None:
        logger.warning("Chat %s %s failed", mode, stage, exc_info=(type(error), error, error.__traceback__))
    detail: BranchError = {"stage": stage, "message": messages[stage]}
    await adispatch_custom_event("branch_error", {"mode": mode, **detail})
    return detail


class AgentState(TypedDict):
    query: str
    comparison_mode: bool
    critique: bool
    engine: str
    rag_mode: str
    lightrag_mode: str
    graphrag_method: str
    top_k: int
    community_level: int
    full_query: str
    context: DualContent
    drift_response: str
    references: list[str]
    payroll_calculation: str | None
    draft: DualContent
    reflect: DualContent
    should_modify: ModifyCheck
    critique_reviews: dict[str, list[CritiqueReview]]
    errors: dict[str, BranchError]
    revision_number: int
    max_revisions: int
    human_messages: Annotated[list[HumanMessage], operator.add]
    naive_messages: Annotated[list[AIMessage], operator.add]
    hybrid_messages: Annotated[list[AIMessage], operator.add]
    drift_messages: Annotated[list[AIMessage], operator.add]
    active_messages: Annotated[list[AIMessage], operator.add]


def get_critique_result(state: AgentState, mode: str) -> CritiqueResult | None:
    if not state.get("critique"):
        return None
    reviews = (state.get("critique_reviews") or {}).get(mode, [])
    max_attempts = state.get("max_revisions", 3)
    error = (state.get("errors") or {}).get(mode, {})
    status: Literal["approved", "limit_reached", "failed"] = "failed"
    if reviews and error.get("stage") not in ("retrieval", "draft", "reflection"):
        if not reviews[-1]["should_modify"]:
            status = "approved"
        elif reviews[-1]["attempt"] >= max_attempts:
            status = "limit_reached"
    return {"status": status, "max_attempts": max_attempts, "reviews": reviews}


async def _research(model, tavily, state: AgentState, modes: tuple[str, ...]):
    context = state.get("context", {})
    retrieved = context.get("active") or context.get("hybrid") or context.get("naive") or context.get("drift") or "No context retrieved."
    errors = dict(state.get("errors") or {})
    references = []
    if requested_indexed_article(state.get('query', '')) or all(errors.get(mode, {}).get("stage") == "retrieval" for mode in modes):
        return {"references": references, "errors": errors}
    try:
        search = await model.with_structured_output(SearchQueries, method="function_calling").ainvoke([
            SystemMessage(content=RESEARCH_PROMPT),
            HumanMessage(content=f"User Query:\n{state.get('full_query')}\n\nRetrieved Context:\n{retrieved[:3000]}")
        ])
        results = await asyncio.gather(*[
            tavily.search(query=query, max_results=2) for query in search.search_queries
        ], return_exceptions=True)
        failure = None
        for result in results:
            if isinstance(result, Exception):
                failure = result
                continue
            references.extend(
                item['content'] + (f"\nNguồn: {item['url']}" if isinstance(item.get('url'), str) else '')
                for item in result.get('results', []) if isinstance(item.get('content'), str)
            )
        if failure is not None:
            raise failure
    except Exception as error:
        for mode in modes:
            if mode not in errors:
                errors[mode] = await _branch_error(mode, "research", error)
    return {"references": references, "errors": errors}


async def _payroll(model, state: AgentState):
    history = [message.content for message in state.get('human_messages', [])[-5:] if isinstance(message.content, str)]
    sources = {'user': '\n'.join([*history, state.get('query', '')])}
    article_id = requested_article_id(state.get('full_query') or state.get('query', ''))
    for mode, text in state.get('context', {}).items():
        if text:
            source = article_id if article_id and text.startswith(f'Truy xuất chính xác [{article_id}]:\n') else f'context:{mode}'
            sources[source] = text
    sources.update({f'web:{index}': text for index, text in enumerate(state.get('references', []), 1)})
    feedback = '\n'.join(dict.fromkeys(text for mode, text in (state.get('reflect') or {}).items()
                                      if (state.get('should_modify') or {}).get(mode))) or None
    report = await run_payroll_skill(model, state.get('full_query') or state.get('query', ''), sources, feedback=feedback)
    return {'payroll_calculation': report}


async def _payroll_report(state: AgentState, mode: str, streaming: bool) -> str:
    report = state['payroll_calculation']
    if streaming:
        await adispatch_custom_event('comparison_chunk', {'mode': mode, 'content': report})
    return report


# ══════════════════════════════════════════════════════════════════════════════
# QA Agent — single-engine pipeline with optional critique loop
#
# Graph: summarize → get_context → research → payroll → draft → [reflect] → finalize
# ══════════════════════════════════════════════════════════════════════════════

class QAAgent:
    """Handles single-engine (lightrag or graphrag) queries with optional reflect loop."""

    def __init__(self, model, tavily, memory):
        self.model = model
        self.tavily = tavily

        graph = StateGraph(AgentState)
        graph.add_node("summarize", self.summarize_node)
        graph.add_node("get_context", self.get_context_node)
        graph.add_node("research", self.research_node)
        graph.add_node("payroll", partial(_payroll, self.model))
        graph.add_node("draft", self.draft_node)
        graph.add_node("reflect", self.reflect_node)
        graph.add_node("finalize", self.finalize_node)

        graph.add_edge("summarize", "get_context")
        graph.add_edge("get_context", "research")
        graph.add_edge("research", "payroll")
        graph.add_edge("payroll", "draft")
        graph.add_conditional_edges("draft", self._needs_critique, {True: "reflect", False: "finalize"})
        graph.add_conditional_edges("reflect", self._revision_target, {name: name for name in ('payroll', 'draft', 'finalize')})
        graph.add_edge("finalize", END)
        graph.set_entry_point("summarize")

        self.graph = graph.compile(checkpointer=memory)

    # ── Nodes ──────────────────────────────────────────────────────────────

    async def summarize_node(self, state: AgentState):
        human_history = state.get("human_messages", [])[-5:]
        ai_history = (state.get("active_messages", []) or state.get("hybrid_messages", []))[-5:]

        if not human_history or not ai_history:
            return {"full_query": state.get("query")}

        formatted_history = ""
        for hm_msg, ai_msg in zip(human_history, ai_history):
            formatted_history += f"User: {hm_msg.content}\nAssistant: {ai_msg.content}\n\n"

        response = await self.model.ainvoke([
            SystemMessage(content=SUMMARIZE_PROMPT),
            HumanMessage(content=formatted_history)
        ])

        full_query = (
            f"Chat history summary: {response.content}\n"
            f"Current user query: {state.get('query')}\n\n"
        )
        return {"full_query": full_query}

    async def get_context_node(self, state: AgentState):
        full_query = state.get("full_query")
        top_k = state.get("top_k", 5) or 5
        engine = state.get("engine", "lightrag")

        if engine == "graphrag":
            method = state.get("rag_mode") or state.get("graphrag_method") or "drift"
            try:
                graphrag_res, graphrag_ctx = await GraphRAGEngine.query(full_query, method=method)
            except Exception as e:
                return {"context": {}, "drift_response": "", "errors": {"hybrid": await _branch_error("hybrid", "retrieval", e)}}
            if not graphrag_res:
                return {"context": {}, "drift_response": "", "errors": {"hybrid": await _branch_error("hybrid", "retrieval")}}
            context_data = {
                "active": str(graphrag_ctx or ""),
                "hybrid": str(graphrag_ctx or ""),
            }
            return {"context": context_data, "drift_response": str(graphrag_res or "")}

        mode = state.get("rag_mode") or state.get("lightrag_mode") or "hybrid"
        try:
            ctx = await RAGEngine.query_context(
                query=full_query,
                param=QueryParam(mode=mode, only_need_context=True, top_k=top_k)
            )
        except Exception as error:
            return {"context": {}, "errors": {"hybrid": await _branch_error("hybrid", "retrieval", error)}}
        return {"context": {"active": ctx, "hybrid": ctx}}

    async def research_node(self, state: AgentState):
        return await _research(self.model, self.tavily, state, ("hybrid",))

    async def draft_node(self, state: AgentState):
        full_query = state.get("full_query")
        context = state.get("context", {})
        references = "\n\n".join(state.get("references", []))
        reflect = state.get("reflect") or {}
        draft = state.get("draft") or {}
        engine = state.get("engine", "lightrag")
        is_streaming = not self._needs_critique(state)
        errors = dict(state.get("errors") or {})
        if errors.get("hybrid", {}).get("stage") == "retrieval":
            return {"draft": {"hybrid": "", "active": ""}, "revision_number": state.get("revision_number", 0) + 1}

        if state.get('payroll_calculation'):
            answer = await _payroll_report(state, 'hybrid', is_streaming)
            return {"draft": {"hybrid": answer, "active": answer}, "revision_number": state.get("revision_number", 0) + 1}

        if references:
            full_query = full_query + f"References: {references}\n\n"

        active_ctx = context.get("active") or context.get("hybrid", "")

        # GraphRAG first pass: stream raw drift response without LLM re-draft
        if engine == "graphrag" and state.get("drift_response") and not reflect:
            graphrag_ans = re.sub(r'\[Data:\s*[^\]]+\]', '', state.get("drift_response", ""))
            if is_streaming and graphrag_ans:
                for offset in range(0, len(graphrag_ans), 120):
                    await adispatch_custom_event(
                        "comparison_chunk",
                        {"mode": "hybrid", "content": graphrag_ans[offset:offset + 120]},
                    )
            return {
                "draft": {"hybrid": graphrag_ans, "active": graphrag_ans},
                "revision_number": state.get("revision_number", 0) + 1,
            }

        hybrid_query = full_query + f"Context: {active_ctx}\n\n"
        if reflect.get("hybrid") or reflect.get("active"):
            feedback = reflect.get("active") or reflect.get("hybrid")
            prev_draft = draft.get("active") or draft.get("hybrid", "")
            hybrid_query += f"Feedback: {feedback}\nPrevious Draft: {prev_draft}\n\n"

        cfg = {"tags": ["final", "hybrid"]} if is_streaming else {}

        try:
            response = await self.model.ainvoke([
                SystemMessage(content=DRAFT_PROMPT),
                HumanMessage(content=hybrid_query)
            ], config=cfg)
        except Exception as error:
            errors["hybrid"] = await _branch_error("hybrid", "draft", error)
            return {"draft": {"hybrid": "", "active": ""}, "errors": errors, "revision_number": state.get("revision_number", 0) + 1}

        answer = response.content
        return {
            "draft": {"hybrid": answer, "active": answer},
            "revision_number": state.get("revision_number", 0) + 1,
        }

    async def reflect_node(self, state: AgentState):
        full_query = state.get("full_query")
        context = state.get("context", {})
        references = "\n\n".join(state.get("references", []))
        draft = state.get("draft", {})

        if references:
            full_query = full_query + f"References: {references}\n\n"

        active_ctx = context.get("active") or context.get("hybrid", "")
        active_draft = draft.get("active") or draft.get("hybrid", "")
        query = full_query + f"Context: {active_ctx}\nDraft: {active_draft}\n\n"
        if state.get('payroll_calculation'):
            query += f"Payroll calculation:\n{state['payroll_calculation']}\n\n"

        if not active_draft:
            return {"should_modify": {}}
        try:
            response = await self.model.with_structured_output(ReflectAnswer, method="function_calling").ainvoke([
                SystemMessage(content=REFLECT_PROMPT),
                HumanMessage(content=query)
            ])
        except Exception as error:
            errors = dict(state.get("errors") or {})
            errors["hybrid"] = await _branch_error("hybrid", "reflection", error)
            return {"should_modify": {}, "errors": errors}

        reviews = dict(state.get("critique_reviews") or {})
        reviews["hybrid"] = [*reviews.get("hybrid", []), {
            "attempt": state.get("revision_number", 0),
            "should_modify": response.should_modify,
            "feedback": response.feedback,
        }]
        return {
            "should_modify": {"hybrid": response.should_modify, "active": response.should_modify},
            "reflect": {"hybrid": response.feedback, "active": response.feedback},
            "critique_reviews": reviews,
        }

    def finalize_node(self, state: AgentState):
        draft = state.get("draft", {})
        query = state.get("query")
        hybrid_text = draft.get("hybrid")
        active_text = draft.get("active") or hybrid_text or ""

        return {
            "human_messages": [HumanMessage(content=query)],
            "active_messages": [AIMessage(content=active_text)],
            "hybrid_messages": [AIMessage(content=hybrid_text or active_text)],
        }

    # ── Routing predicates ─────────────────────────────────────────────────

    def _needs_critique(self, state: AgentState) -> bool:
        return bool(state.get("critique"))

    def _revision_target(self, state: AgentState) -> str:
        should_mod_dict = state.get("should_modify", {})
        if (
            any(should_mod_dict.values())
            and state.get("revision_number", 0) < state.get("max_revisions", 3)
        ):
            return 'payroll' if state.get('payroll_calculation') else 'draft'
        return 'finalize'


# ══════════════════════════════════════════════════════════════════════════════
# Comparison Agent — parallel naive / hybrid / drift with optional parallel reflect
#
# Graph: summarize → get_all_contexts → research → payroll → parallel_draft
#        → [parallel_reflect] → finalize_comparison
# ══════════════════════════════════════════════════════════════════════════════

class ComparisonAgent:
    """Runs all three retrieval engines concurrently and optionally reflects in parallel."""

    def __init__(self, model, tavily, memory):
        self.model = model
        self.tavily = tavily

        graph = StateGraph(AgentState)
        graph.add_node("summarize", self.summarize_node)
        graph.add_node("get_all_contexts", self.get_all_contexts_node)
        graph.add_node("research", self.research_node)
        graph.add_node("payroll", partial(_payroll, self.model))
        graph.add_node("parallel_draft", self.parallel_draft_node)
        graph.add_node("parallel_reflect", self.parallel_reflect_node)
        graph.add_node("finalize_comparison", self.finalize_comparison_node)

        graph.add_edge("summarize", "get_all_contexts")
        graph.add_edge("get_all_contexts", "research")
        graph.add_edge("research", "payroll")
        graph.add_edge("payroll", "parallel_draft")
        graph.add_conditional_edges(
            "parallel_draft", self._needs_critique,
            {True: "parallel_reflect", False: "finalize_comparison"}
        )
        graph.add_conditional_edges(
            "parallel_reflect", self._revision_target,
            {name: name for name in ('payroll', 'parallel_draft', 'finalize_comparison')}
        )
        graph.add_edge("finalize_comparison", END)
        graph.set_entry_point("summarize")

        self.graph = graph.compile(checkpointer=memory)

    # ── Nodes ──────────────────────────────────────────────────────────────

    async def summarize_node(self, state: AgentState):
        human_history = state.get("human_messages", [])[-5:]
        ai_history = (state.get("active_messages", []) or state.get("hybrid_messages", []))[-5:]

        if not human_history or not ai_history:
            return {"full_query": state.get("query")}

        formatted_history = ""
        for hm_msg, ai_msg in zip(human_history, ai_history):
            formatted_history += f"User: {hm_msg.content}\nAssistant: {ai_msg.content}\n\n"

        response = await self.model.ainvoke([
            SystemMessage(content=SUMMARIZE_PROMPT),
            HumanMessage(content=formatted_history)
        ])

        full_query = (
            f"Chat history summary: {response.content}\n"
            f"Current user query: {state.get('query')}\n\n"
        )
        return {"full_query": full_query}

    async def get_all_contexts_node(self, state: AgentState):
        """Fetch naive, hybrid (LightRAG), and drift (GraphRAG) contexts concurrently."""
        full_query = state.get("full_query")
        top_k = state.get("top_k", 5) or 5
        lr_mode = state.get("lightrag_mode") or "hybrid"
        gr_method = state.get("graphrag_method") or "drift"

        async def light_context(mode):
            return await RAGEngine.query_context(
                query=full_query,
                param=QueryParam(mode=mode, only_need_context=True, top_k=top_k)
            )

        naive_task = light_context("naive")
        hybrid_task = light_context(lr_mode)
        drift_task = GraphRAGEngine.query(full_query, method=gr_method)

        results = await asyncio.gather(naive_task, hybrid_task, drift_task, return_exceptions=True)

        context: DualContent = {}
        errors: dict[str, BranchError] = {}
        drift_response = ""
        for mode, result in zip(("naive", "hybrid", "drift"), results):
            if isinstance(result, Exception):
                context[mode] = ""
                errors[mode] = await _branch_error(mode, "retrieval", result)
            elif mode == "drift":
                response, drift_context = result
                drift_response = str(response or "")
                context[mode] = str(drift_context or "")
                if not drift_response:
                    errors[mode] = await _branch_error(mode, "retrieval")
            else:
                context[mode] = str(result or "")
        return {"context": context, "drift_response": drift_response, "errors": errors}

    async def research_node(self, state: AgentState):
        return await _research(self.model, self.tavily, state, ("naive", "hybrid", "drift"))

    async def parallel_draft_node(self, state: AgentState):
        """Draft all three engines in parallel; stream each as SSE chunks."""
        full_query = state.get("full_query")
        context = state.get("context", {})
        references = "\n\n".join(state.get("references", []))
        reflect = state.get("reflect") or {}
        draft = dict(state.get("draft") or {})
        should_mod = state.get("should_modify", {})
        is_streaming = not self._needs_critique(state)
        errors = dict(state.get("errors") or {})

        if state.get('payroll_calculation'):
            for mode in ('naive', 'hybrid', 'drift'):
                if errors.get(mode, {}).get('stage') != 'retrieval':
                    draft[mode] = await _payroll_report(state, mode, is_streaming)
            return {"draft": draft, "errors": errors, "revision_number": state.get("revision_number", 0) + 1}

        if references:
            full_query = full_query + f"References: {references}\n\n"

        tasks = {}

        # Naive
        if errors.get("naive", {}).get("stage") != "retrieval" and (not reflect or should_mod.get("naive", False)):
            naive_query = full_query + f"Context: {context.get('naive')}\n\n"
            if reflect.get("naive"):
                naive_query += f"Feedback: {reflect['naive']}\nPrevious Draft: {draft.get('naive', '')}\n\n"
            cfg_naive = {"tags": ["final", "naive"]} if is_streaming else {}
            tasks["naive"] = self.model.ainvoke([
                SystemMessage(content=DRAFT_PROMPT),
                HumanMessage(content=naive_query)
            ], config=cfg_naive)

        # Hybrid (LightRAG)
        if errors.get("hybrid", {}).get("stage") != "retrieval" and (not reflect or should_mod.get("hybrid", False)):
            hybrid_query = full_query + f"Context: {context.get('hybrid')}\n\n"
            if reflect.get("hybrid"):
                hybrid_query += f"Feedback: {reflect['hybrid']}\nPrevious Draft: {draft.get('hybrid', '')}\n\n"
            cfg_hybrid = {"tags": ["final", "hybrid"]} if is_streaming else {}
            tasks["hybrid"] = self.model.ainvoke([
                SystemMessage(content=DRAFT_PROMPT),
                HumanMessage(content=hybrid_query)
            ], config=cfg_hybrid)

        # Drift (GraphRAG) — first pass streams raw response; revision passes use LLM
        if errors.get("drift", {}).get("stage") != "retrieval" and (not reflect or should_mod.get("drift", False)):
            if not reflect:
                drift_response = re.sub(r'\[Data:\s*[^\]]+\]', '', state.get("drift_response", ""))
                draft["drift"] = drift_response
                if is_streaming and drift_response:
                    for offset in range(0, len(drift_response), 120):
                        await adispatch_custom_event(
                            "comparison_chunk",
                            {"mode": "drift", "content": drift_response[offset:offset + 120]},
                        )
            else:
                drift_query = (
                    full_query
                    + f"Context: {context.get('drift')}\n"
                    + f"Initial GraphRAG Drift response: {state.get('drift_response', '')}\n"
                    + f"Previous Draft: {draft.get('drift', '')}\n"
                    + f"Feedback: {reflect.get('drift', '')}\n\n"
                )
                cfg_drift = {"tags": ["final", "drift"]} if is_streaming else {}
                tasks["drift"] = self.model.ainvoke([
                    SystemMessage(content=DRAFT_PROMPT),
                    HumanMessage(content=drift_query)
                ], config=cfg_drift)

        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, response in zip(tasks.keys(), results):
                if isinstance(response, Exception):
                    draft[key] = ""
                    errors[key] = await _branch_error(key, "draft", response)
                else:
                    draft[key] = response.content

        return {"draft": draft, "errors": errors, "revision_number": state.get("revision_number", 0) + 1}

    async def parallel_reflect_node(self, state: AgentState):
        """Reflect on all three drafts concurrently."""
        full_query = state.get("full_query")
        if state.get('payroll_calculation'):
            full_query += f"\nPayroll calculation:\n{state['payroll_calculation']}\n\n"
        context = state.get("context", {})
        references = "\n\n".join(state.get("references", []))
        draft = state.get("draft", {})

        if references:
            full_query = full_query + f"References: {references}\n\n"

        errors = dict(state.get("errors") or {})

        async def reflect_mode(mode):
            query = full_query + f"Context: {context.get(mode)}\nDraft: {draft.get(mode, '')}\n\n"
            if mode == "drift":
                query += f"Initial GraphRAG Drift response: {state.get('drift_response', '')}\n"
            return await self.model.with_structured_output(ReflectAnswer, method="function_calling").ainvoke([
                SystemMessage(content=REFLECT_PROMPT), HumanMessage(content=query)
            ])

        reviews = dict(state.get("critique_reviews") or {})
        modes = [
            mode for mode in ("naive", "hybrid", "drift")
            if draft.get(mode)
            and errors.get(mode, {}).get("stage") not in ("retrieval", "draft", "reflection")
            and (state.get('payroll_calculation') or not reviews.get(mode) or reviews[mode][-1]["should_modify"])
        ]
        results = await asyncio.gather(*(reflect_mode(mode) for mode in modes), return_exceptions=True)
        should_modify: ModifyCheck = {}
        feedback: DualContent = dict(state.get("reflect") or {})
        for mode, response in zip(modes, results):
            if isinstance(response, Exception):
                should_modify[mode] = False
                errors[mode] = await _branch_error(mode, "reflection", response)
            else:
                should_modify[mode] = response.should_modify
                feedback[mode] = response.feedback
                reviews[mode] = [*reviews.get(mode, []), {
                    "attempt": state.get("revision_number", 0),
                    "should_modify": response.should_modify,
                    "feedback": response.feedback,
                }]
        return {"should_modify": should_modify, "reflect": feedback, "errors": errors, "critique_reviews": reviews}

    def finalize_comparison_node(self, state: AgentState):
        draft = state.get("draft", {})
        query = state.get("query")
        naive_text = draft.get("naive", "")
        hybrid_text = draft.get("hybrid", "")
        drift_text = draft.get("drift", "")
        active_text = hybrid_text or drift_text or ""

        updated_state = {
            "human_messages": [HumanMessage(content=query)],
            "active_messages": [AIMessage(content=active_text)],
            "hybrid_messages": [AIMessage(content=hybrid_text or active_text)],
        }
        if naive_text:
            updated_state["naive_messages"] = [AIMessage(content=naive_text)]
        if drift_text:
            updated_state["drift_messages"] = [AIMessage(content=drift_text)]
        return updated_state

    # ── Routing predicates ─────────────────────────────────────────────────

    def _needs_critique(self, state: AgentState) -> bool:
        return bool(state.get("critique"))

    def _revision_target(self, state: AgentState) -> str:
        should_mod_dict = state.get("should_modify", {})
        if (
            any(should_mod_dict.values())
            and state.get("revision_number", 0) < state.get("max_revisions", 3)
        ):
            return 'payroll' if state.get('payroll_calculation') else 'parallel_draft'
        return 'finalize_comparison'


# ══════════════════════════════════════════════════════════════════════════════
# Supervisor — routes to QAAgent or ComparisonAgent; exposes original Agent API
# ══════════════════════════════════════════════════════════════════════════════

class _SupervisorGraphProxy:
    """
    Proxy exposing ainvoke / astream_events by delegating directly to the
    chosen sub-agent graph — preserves native LangGraph event propagation.
    """

    def __init__(self, qa_agent: QAAgent, comparison_agent: ComparisonAgent):
        self._qa = qa_agent
        self._comparison = comparison_agent

    def _pick(self, state: AgentState):
        return self._comparison if state.get("comparison_mode") else self._qa

    async def ainvoke(self, input: AgentState, config=None):
        return await self._pick(input).graph.ainvoke(input, config=config)

    async def astream_events(self, input: AgentState, config=None, version: str = "v2"):
        async with aclosing(self._pick(input).graph.astream_events(input, config=config, version=version)) as events:
            async for event in events:
                yield event


class Agent:
    """
    Top-level agent — backward-compatible with the original single-class API.

    Usage (unchanged from before):
        agent = Agent(model, tavily, memory)
        agent.graph.ainvoke(input, config)
        agent.graph.astream_events(input, config, version="v2")
        agent.model
    """

    def __init__(self, model, tavily, memory):
        self.model = model
        self.tavily = tavily

        qa_agent = QAAgent(model, tavily, memory)
        comparison_agent = ComparisonAgent(model, tavily, memory)

        self.graph = _SupervisorGraphProxy(qa_agent, comparison_agent)
