import operator
import asyncio
import re
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_openai import ChatOpenAI
from tavily import AsyncTavilyClient
from typing import TypedDict, Annotated
from pydantic import BaseModel, Field
from lightrag import QueryParam
from backend.config import settings
from backend.core.rag_engine import RAGEngine
from backend.core.graphrag_engine import GraphRAGEngine
from backend.core.prompts import SUMMARIZE_PROMPT, RESEARCH_PROMPT, DRAFT_PROMPT, REFLECT_PROMPT

tavily = AsyncTavilyClient()
model = ChatOpenAI(model_name=settings.OPENAI_MODEL, temperature=0, streaming=True, base_url=settings.BASE_URL, api_key=settings.API_KEY)

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
        description=(
            "List of 0 to 2 concise search terms for Tavily. Return empty list if no search is needed."
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
    feedback: str = Field(
        ..., 
        description=(
            "Clear, actionable feedback detailing specific legal corrections required if should_modify is True. "
            "Provide brief justification if False."
        )
    )

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
    draft: DualContent
    reflect: DualContent
    should_modify: ModifyCheck
    revision_number: Annotated[int, operator.add]
    max_revisions: int
    human_messages: Annotated[list[HumanMessage], operator.add]
    naive_messages: Annotated[list[AIMessage], operator.add]
    hybrid_messages: Annotated[list[AIMessage], operator.add]
    drift_messages: Annotated[list[AIMessage], operator.add]
    active_messages: Annotated[list[AIMessage], operator.add]

class Agent: 
    def __init__(self, model, tavily, memory):
        graph = StateGraph(AgentState)
        graph.add_node("summarize", self.summarize_node)
        graph.add_node("get_context", self.get_context_node)
        graph.add_node("research", self.research_node)
        graph.add_node("draft", self.draft_node)
        graph.add_node("reflect", self.reflect_node)
        graph.add_node("finalize", self.finalize_node)

        graph.add_edge("summarize", "get_context")
        graph.add_edge("get_context", "research")
        graph.add_edge("research", "draft")
        graph.add_conditional_edges("draft", self.needs_critique, {True: "reflect", False: "finalize"})
        graph.add_conditional_edges("reflect", self.should_modify, {True: "draft", False: "finalize"})
        graph.add_edge("finalize", END)
        graph.set_entry_point("summarize")
        
        self.graph = graph.compile(
            checkpointer=memory,
            interrupt_after=["reflect"],  # HITL: pause after reflect so human can approve/reject redraft
        )
        
        self.graph = graph.compile(checkpointer=memory)
        self.model = model
        self.tavily = tavily

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

        full_query = f"Chat history summary: {response.content}\nCurrent user query: {state.get('query')}\n\n" 
        return {"full_query": full_query}
          
    async def get_context_node(self, state: AgentState):
        rag = RAGEngine.get_instance()
        full_query = state.get("full_query")
        top_k = state.get("top_k", 5) or 5

        context_data = {}
        if not state.get("comparison_mode"): 
            engine = state.get("engine", "lightrag")
            if engine == "graphrag":
                method = state.get("rag_mode") or state.get("graphrag_method") or "drift"
                try:
                    graphrag_res, graphrag_ctx = await GraphRAGEngine.query(full_query, method=method)
                except Exception as e:
                    graphrag_res, graphrag_ctx = f"GraphRAG error: {str(e)}", ""

                context_data["active"] = str(graphrag_ctx or "")
                context_data["hybrid"] = str(graphrag_ctx or "")
                context_data["drift"] = str(graphrag_ctx or "")
                return {"context": context_data, "drift_response": str(graphrag_res or "")}
            else:
                mode = state.get("rag_mode") or state.get("lightrag_mode") or "hybrid"
                ctx = await rag.aquery(query=full_query, param=QueryParam(mode=mode, only_need_context=True, top_k=top_k))
                context_data["active"] = ctx
                context_data["hybrid"] = ctx
                return {"context": context_data}
        else: 
            lr_mode = state.get("lightrag_mode") or "hybrid"
            gr_method = state.get("graphrag_method") or "drift"

            naive_task = rag.aquery(query=full_query, param=QueryParam(mode="naive", only_need_context=True, top_k=top_k))
            hybrid_task = rag.aquery(query=full_query, param=QueryParam(mode=lr_mode, only_need_context=True, top_k=top_k))
            drift_task = GraphRAGEngine.query(full_query, method=gr_method)

            results = await asyncio.gather(naive_task, hybrid_task, drift_task, return_exceptions=True)
            naive_res = results[0] if not isinstance(results[0], Exception) else f"Naive error: {results[0]}"
            hybrid_res = results[1] if not isinstance(results[1], Exception) else f"LightRAG ({lr_mode}) error: {results[1]}"
            if isinstance(results[2], Exception):
                drift_res, drift_context = f"GraphRAG ({gr_method}) error: {results[2]}", ""
            else:
                drift_res, drift_context = results[2]

            context_data["naive"] = naive_res
            context_data["hybrid"] = hybrid_res
            context_data["drift"] = str(drift_context or "")
            return {"context": context_data, "drift_response": str(drift_res or "")}
        return {"context": context_data}

    async def research_node(self, state: AgentState):
        full_query = state.get("full_query")
        context_data = state.get("context", {})

        retrieved_context = context_data.get("hybrid") or context_data.get("naive") or "No context retrieved."

        input_payload = f"User Query:\n{full_query}\n\nRetrieved Context:\n{retrieved_context[:3000]}"

        search = await self.model.with_structured_output(SearchQueries).ainvoke([
            SystemMessage(content=RESEARCH_PROMPT),
            HumanMessage(content=input_payload)
        ])

        if not search.search_queries:
            return {"references": []}

        search_tasks = [
            self.tavily.search(query=q, max_results=2) 
            for q in search.search_queries
        ]
        results_list = await asyncio.gather(*search_tasks)

        references = []
        for tavily_results in results_list:
            for r in tavily_results.get("results", []):
                references.append(r["content"])

        return {"references": references}

    async def draft_node(self, state: AgentState):
        full_query = state.get("full_query")
        context = state.get("context")
        references = "\n\n".join(state.get("references", [])) 
        reflect = state.get("reflect") 
        draft = state.get("draft") 
        should_mod = state.get("should_modify")

        if references: 
            full_query = full_query + f"References: {references}\n\n"

        is_streaming_path = not self.needs_critique(state)

        if state.get("comparison_mode"): 
            tasks = {}
            draft = dict(draft or {})

            if not reflect or should_mod.get("naive", False): 
                naive_query = full_query + f"Context: {context.get('naive')}\n\n"

                if reflect.get("naive"):
                    naive_query += f"Feedback: {reflect.get('naive')}\nPrevious Draft: {draft.get('naive', '')}\n\n"

                cfg_naive = {"tags": ["final", "naive"]} if is_streaming_path else {}

                tasks["naive"] = self.model.ainvoke([
                SystemMessage(content=DRAFT_PROMPT), 
                HumanMessage(content=naive_query)
                ], config=cfg_naive)

            if not reflect or should_mod.get("hybrid", False): 
                hybrid_query = full_query + f"Context: {context.get('hybrid')}\n\n"

                if reflect.get("hybrid"):
                    hybrid_query += f"Feedback: {reflect.get('hybrid')}\nPrevious Draft: {draft.get('hybrid', '')}\n\n"
 
                cfg_hybrid = {"tags": ["final", "hybrid"]} if is_streaming_path else {}

                tasks["hybrid"] = self.model.ainvoke([
                    SystemMessage(content=DRAFT_PROMPT), 
                    HumanMessage(content=hybrid_query)
                ], config=cfg_hybrid)

            if not reflect or should_mod.get("drift", False):
                if not reflect:
                    drift_response = state.get("drift_response", "")
                    drift_response = re.sub(r'\[Data:\s*[^\]]+\]', '', drift_response)
                    draft["drift"] = drift_response
                    if is_streaming_path and drift_response:
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
                    cfg_drift = {"tags": ["final", "drift"]} if is_streaming_path else {}
                    tasks["drift"] = self.model.ainvoke([
                        SystemMessage(content=DRAFT_PROMPT),
                        HumanMessage(content=drift_query)
                    ], config=cfg_drift)

            if tasks:
                results = await asyncio.gather(*tasks.values())
                for key, response in zip(tasks.keys(), results):
                    draft[key] = response.content

            return {
                "draft": draft,
                "revision_number": 1
            }  
        
        else: 
            active_ctx = context.get("active") or context.get("hybrid", "")
            engine = state.get("engine", "lightrag")

            if engine == "graphrag" and state.get("drift_response") and not reflect:
                graphrag_ans = state.get("drift_response", "")
                if is_streaming_path and graphrag_ans:
                    for offset in range(0, len(graphrag_ans), 120):
                        await adispatch_custom_event(
                            "comparison_chunk",
                            {"mode": "hybrid", "content": graphrag_ans[offset:offset + 120]},
                        )
                return {
                    "draft": {"hybrid": graphrag_ans, "active": graphrag_ans},
                    "revision_number": 1
                }

            hybrid_query = full_query + f"Context: {active_ctx}\n\n"

            if reflect.get("hybrid") or reflect.get("active"):
                fb = reflect.get("active") or reflect.get("hybrid")
                prev = draft.get("active") or draft.get("hybrid", "")
                hybrid_query += f"Feedback: {fb}\nPrevious Draft: {prev}\n\n"

            cfg_hybrid = {"tags": ["final", "hybrid"]} if is_streaming_path else {}

            hybrid_response = await self.model.ainvoke([
                SystemMessage(content=DRAFT_PROMPT), 
                HumanMessage(content=hybrid_query)
            ], config=cfg_hybrid)

            return {
                "draft": {"hybrid": hybrid_response.content, "active": hybrid_response.content},
                "revision_number": 1
            }    
                
    async def reflect_node(self, state: AgentState):
        full_query = state.get("full_query")
        context = state.get("context")
        references = "\n\n".join(state.get("references", [])) 
        draft = state.get("draft") 

        if references: 
            full_query = full_query + f"References: {references}\n\n"

        if state.get("comparison_mode"): 
            naive_query = full_query + f"Context: {context.get('naive')}\nDraft: {draft.get('naive', '')}\n\n"
            hybrid_query = full_query + f"Context: {context.get('hybrid')}\nDraft: {draft.get('hybrid', '')}\n\n"
            drift_query = (
                full_query
                + f"Context: {context.get('drift')}\n"
                + f"Initial GraphRAG Drift response: {state.get('drift_response', '')}\n"
                + f"Draft: {draft.get('drift', '')}\n\n"
            )

            naive_task = self.model.with_structured_output(ReflectAnswer).ainvoke([
                SystemMessage(content=REFLECT_PROMPT), 
                HumanMessage(content=naive_query)
            ]) 

            hybrid_task = self.model.with_structured_output(ReflectAnswer).ainvoke([
                SystemMessage(content=REFLECT_PROMPT), 
                HumanMessage(content=hybrid_query)
            ]) 

            drift_task = self.model.with_structured_output(ReflectAnswer).ainvoke([
                SystemMessage(content=REFLECT_PROMPT),
                HumanMessage(content=drift_query)
            ])

            naive_response, hybrid_response, drift_reflection = await asyncio.gather(
                naive_task, hybrid_task, drift_task
            )

            should_mod = {
                "naive": naive_response.should_modify,
                "hybrid": hybrid_response.should_modify,
                "drift": drift_reflection.should_modify,
            }

            return {
                "should_modify": should_mod, 
                "reflect": {
                    "naive": naive_response.feedback,
                    "hybrid": hybrid_response.feedback,
                    "drift": drift_reflection.feedback,
                }
            }

        else: 
            active_ctx = context.get("active") or context.get("hybrid", "")
            active_draft = draft.get("active") or draft.get("hybrid", "")
            hybrid_query = full_query + f"Context: {active_ctx}\nDraft: {active_draft}\n\n"

            hybrid_response = await self.model.with_structured_output(ReflectAnswer).ainvoke([
                SystemMessage(content=REFLECT_PROMPT), 
                HumanMessage(content=hybrid_query)
            ])     

            return {
                "should_modify": {"hybrid": hybrid_response.should_modify, "active": hybrid_response.should_modify}, 
                "reflect": {"hybrid": hybrid_response.feedback, "active": hybrid_response.feedback}
            }          
        
    def needs_critique(self, state: AgentState):
        context = state.get("context", {})
        active_ctx = context.get("active") or context.get("hybrid", "")
        if not state.get("critique") or len(active_ctx) < 200: 
            return False
        return True
    
    def should_modify(self, state: AgentState):
        should_mod_dict = state.get("should_modify", {})
        any_mod = any(should_mod_dict.values())
        if not any_mod or state.get("revision_number") >= state.get("max_revisions"):
            return False
        return True

    def finalize_node(self, state: AgentState):
        draft = state.get("draft", {})
        query = state.get("query")
        
        naive_text = draft.get("naive")
        hybrid_text = draft.get("hybrid")
        drift_text = draft.get("drift")
        active_text = draft.get("active") or hybrid_text or drift_text
        
        updated_state = {
            "human_messages": [HumanMessage(content=query)],
            "active_messages": [AIMessage(content=active_text if active_text else "")],
            "hybrid_messages": [AIMessage(content=hybrid_text if hybrid_text else (active_text or ""))]
        }
        
        if naive_text:
            updated_state["naive_messages"] = [AIMessage(content=naive_text)]

        if "drift" in draft:
            updated_state["drift_messages"] = [AIMessage(content=drift_text)]
            
        return updated_state


