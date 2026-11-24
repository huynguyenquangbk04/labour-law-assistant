import httpx
import openai 
from typing import Optional
from backend.config import settings

_async_client: Optional[openai.AsyncOpenAI] = None # If AsyncClient was used, it'd also point to AsyncOpenAI

def get_openai_client(): # Only declare openai_client, have not access to OpenRouter or any models, so don't have to be an async function
    global _async_client
    if _async_client is None:
        _async_client = openai.AsyncOpenAI(
            base_url=settings.BASE_URL,
            api_key=settings.API_KEY        
    )
    
    return _async_client

class EmbeddingFuncWrapper: # Using different embedding model instead of default LightRAG's one for more control
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL
    
    def _get_prefix(self, is_query): 
        if is_query:
            return settings.EMBEDDING_QUERY_SENTENCE # distinguish query text and information text 
        return ""

    async def __call__(self, texts: list[str]): # Callable class, using this design instead of only functions to better manage model_name and inner functions
        import numpy as np

        client = get_openai_client()

        prepared_texts: list[str] = []
        for text in texts: 
            prefix = self._get_prefix(text.strip().endswith("?"))
            prepared_texts.append(prefix + text)
        
        
        response = await client.embeddings.create(
            model=self.model_name, 
            input=prepared_texts
        )

        return np.array([item.embedding for item in response.data])

async def llm_reasoning_func( # Using different reasoning model instead of default LightRAG's one for more control
        prompt: str, 
        system_prompt: str = None,
        history: list[dict] = None,
        **kwargs
    ): # NOTICE: these parameters are passed down by LightRAG, including prompt and system_prompt.

    # GraphRAG sends extraction as a user message, including during gleaning.
    extraction_messages = [prompt or '', *(m.get('content', '') for m in history or [])]
    if any(isinstance(text, str) and text.startswith('[[LEGAL_GRAPH_EXTRACTION]]') for text in extraction_messages):
        system_prompt = (system_prompt or '') + '\n' + settings.entity_types_guidance

    client = get_openai_client()
    messages = []

    if system_prompt: 
        messages.append({"role": "system", "content": system_prompt})

    if history:
        messages.extend(history)
    
    if prompt: 
        messages.append({"role": "user", "content": prompt})

    extra_headers = {
        # "HTTP-Referer": "https://github.com/traffic/law-assistant", # optional, rank the project on OpenRouter leaderboard 
        "X-Title": "Labour Law Assistant", # for tracking on OpenRouter dashboard
    }

    allowed_params = [
        "model", "messages", "stream", "temperature", "top_p", "n", "stop", "max_tokens",
        "presence_penalty", "frequency_penalty", "logit_bias", "user", "response_format",
        "seed", "tools", "tool_choice", "parallel_tool_calls", "timeout"
    ] 

    api_kwargs = {k:v for k, v in kwargs.items() if k in allowed_params} # not every arguments returned by LightRAG can be used by different LLM model    
    api_kwargs["temperature"] = 0.0
    stream_requested = api_kwargs.pop("stream", False)
    
    # Use the SDK's SSE decoder for provider keep-alives; buffer only for non-streaming callers.
    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages, 
        extra_headers=extra_headers,
        stream=True,
        **api_kwargs
    )

    async def stream_generator():
        completed = False
        async with response:
            try:
                async for chunk in response:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason == "error":
                        raise openai.APIError("Upstream completion failed", request=response.response.request, body=None)
                    if choice.finish_reason is not None:
                        completed = True
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None)
                    if content is not None:
                        if not isinstance(content, str):
                            raise openai.APIError("Invalid upstream content", request=response.response.request, body=None)
                        yield content
            except httpx.TransportError as error:
                raise openai.APIConnectionError(
                    message="Upstream model connection failed", request=response.response.request,
                ) from error
            if not completed:
                raise openai.APIError("Incomplete upstream completion", request=response.response.request, body=None)

    if stream_requested:
        return stream_generator()
    return "".join([text async for text in stream_generator()])
