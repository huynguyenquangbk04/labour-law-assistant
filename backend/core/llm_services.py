import openai 
from typing import Optional
from backend.config import settings
import re

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
    ): # NOTICE: these paramters are passed down by LightRAG including prompt and system_prompt. For example, LightRAG gets system_prompt + prompt from human, it then handles the prompts inside and creates its own prompt and system_prompt and pass to DeepSeek

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
        "seed", "tools", "tool_choice", "parallel_tool_calls"
    ] 

    api_kwargs = {k:v for k, v in kwargs.items() if k in allowed_params} # not every arguments returned by LightRAG can be used by different LLM model

    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages, 
        extra_headers=extra_headers,
        **api_kwargs
    )

    if api_kwargs.get("stream"):
        async def stream_generator(): # generator 
            print("LLM: Starting stream generator")
            try: 
                async for chunk in response: # continuosly listen for chink from response
                    if chunk.choices[0] and chunk.choices[0].delta.content: 
                        c = chunk.choices[0].delta.content
                        print(f"LLM CHUNK: {c}")
                        yield c 
            except Exception as e:
                print(f"LLM STREAM ERROR: {str(e)}")
            print("LLM: Stream generator finished")
        return stream_generator()
    
    return response.choices[0].message.content

# Custom LightRAG chunking function with each chunk contains one Dieu
CHUONG_RE = re.compile(r"^Chương\s+([IVXLCDM]+)\s*$", re.MULTILINE)
MUC_RE = re.compile(r"^Mục\s+(\d+)\.\s*(.*)$")
DIEU_RE = re.compile(r"^Điều\s+(\d+)\.\s*(.*)$")

def chunk_custom_func(
    tokenizer,
    content: str,
    split_by_character=None,
    split_by_character_only: bool = False,
    overlap_token_size: int = 0,
    chunk_token_size: int = 1200,
    **kwargs,
) -> list[dict]:
    
    lines = content.split("\n")
    n = len(lines)
 
    results = []
    order_idx = 0
 
    # Preamble
    first_chuong_line = None
    for i, line in enumerate(lines):
        if CHUONG_RE.match(line.strip()):
            first_chuong_line = i
            break

    # No Chuong included
    if first_chuong_line is None:
        text = content.strip()
        return [{
            "content": text,
            "tokens": len(tokenizer.encode(text)),
            "chunk_order_index": 0,
        }]
 
    preamble = "\n".join(l.strip() for l in lines[:first_chuong_line] if l.strip())
    if preamble:
        results.append({
            "content": preamble,
            "tokens": len(tokenizer.encode(preamble)),
            "chunk_order_index": order_idx,
        })
        order_idx += 1
 
    current_chuong_so = current_chuong_ten = None
    current_muc_so = current_muc_ten = None
    current_dieu_so = current_dieu_ten = None
    current_dieu_lines: list[str] = []

    def flush_dieu():   # flush Dieu each time reaching new Chuong/Muc/Dieu
        nonlocal order_idx
        if current_dieu_so is None:
            return
        header = f"[Chương {current_chuong_so} - {current_chuong_ten}]"
        if current_muc_so is not None:
            header += f" [Mục {current_muc_so} - {current_muc_ten}]"
        header += f"\nĐiều {current_dieu_so}. {current_dieu_ten}"
        body = "\n".join(current_dieu_lines)
        text = f"{header}\n\n{body}".strip()
        results.append({
            "content": text,
            "tokens": len(tokenizer.encode(text)),
            "chunk_order_index": order_idx,
        })
        order_idx += 1
 
    i = first_chuong_line
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
 
        m_chuong = CHUONG_RE.match(line)
        if m_chuong:
            flush_dieu()
            # reset Dieu
            current_dieu_so = current_dieu_ten = None
            current_dieu_lines = []
            current_chuong_so = m_chuong.group(1)
            # The name of Chuong is on the next line
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            current_chuong_ten = lines[j].strip() if j < n else ""
            # reset Muc
            current_muc_so = current_muc_ten = None
            i = j + 1
            continue
 
        m_muc = MUC_RE.match(line)
        if m_muc:
            flush_dieu()
            current_dieu_so = current_dieu_ten = None
            current_dieu_lines = []
            current_muc_so = m_muc.group(1)
            current_muc_ten = m_muc.group(2).strip()
            i += 1
            continue
 
        m_dieu = DIEU_RE.match(line)
        if m_dieu:
            flush_dieu()
            current_dieu_so = m_dieu.group(1)
            current_dieu_ten = m_dieu.group(2).strip()
            current_dieu_lines = []
            i += 1
            continue

        # If not Chuong/Muc/Dieu then it is the content in Dieu
        if current_dieu_so is not None:
            current_dieu_lines.append(line)
        i += 1
 
    flush_dieu() # final Dieu
    return results