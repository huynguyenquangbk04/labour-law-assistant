import openai 
from typing import Optional
from backend.config import settings

_async_client: Optional[openai.AsyncOpenAI] = None # If AsyncClient was used, it'd also point to AsyncOpenAI

def get_openai_client(): # Only declare openai_client, have not access to OpenRouter or any models, so don't have to be an async function
    global _async_client
    if _async_client is None:
        _async_client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY        
    )
    
    return _async_client

class QwenEmbeddingFunc: # Using different embedding model instead of default LightRAG's one for more control
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL
    
    def _get_prefix(self, is_query): 
        if is_query:
            return "Instruct: Given a legal query, retrieve relevant statutes...\nQuery: " # Specialized for Qwen (append an instruction if the text is a query, helps including efficiency)
        return ""

    async def __call__(self, texts: list[str]): # Callable class, using this design instead of only functions to better manage model_name and inner functions
        import numpy as np

        client = get_openai_client()

        prepared_texts: list[str] = []
        for text in texts: 
            prefix = self._get_prefix(text.strip().endswith("?"))
            prepared_texts.append(prefix + text)
        
        
        response = await client.embeddings.create(
            model_name=self.model_name, 
            input=prepared_texts
        )

        return np.array([item.embedding for item in response.data])

class BGEEmbeddingFunc:
    def __init__(self):
        from sentence_transformers import SentenceTransformer

        self.model_name = settings.EMBEDDING_MODEL
        self.model = SentenceTransformer(self.model_name)

    def _get_prefix(self, is_query: bool) -> str:
        # Prefix for BGE model
        if is_query:
            return "Represent this sentence for searching relevant passages: "
        return ""

    async def __call__(self, texts: list[str]):
        import numpy as np
        
        processed_texts = []
        for text in texts:
            is_query = text.strip().endswith("?")
            prefix = self._get_prefix(is_query=is_query)
            processed_texts.append(prefix + text)
            
        embeddings = self.model.encode(processed_texts, show_progress_bar=False)
        return np.array(embeddings)

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

async def parse_pdf(file_path: str): # parse pdf file (contaning information as images) to text 
    import base64
    from io import BytesIO
    from pdf2image import convert_from_path

    images = convert_from_path(pdf_path=file_path, first_page=1, last_page=5)
    
    client = get_openai_client()

    messages = [
        {
            "role": "system", 
            "content": (
                "You are an elite legal document parser. Extract every character from the images with 100% fidelity. "
                "STRICT INSTRUCTION: Output ONLY the raw extracted text. "
                "NO PREAMBLE. NO CONVERSATION. NO INTRODUCTIONS (e.g., 'Dưới đây là...', 'Here is the text...'). "
                "Directly start with the content of the document. "
                "Maintain original layout, headers, and spacing."
            )
        }
    ]

    content = []  
    for i, image in enumerate(images):
        buffered = BytesIO()
        image.save(buffered, format="JPEG") # use BytesIO as a buffer in RAM to quickly convert image into raw bytes

        value = base64.b64encode(buffered.getvalue()).decode("utf-8") # base64 helps convert raw bytes into bytes (with understandable characters), and then utf-8 decoder converts that into string, which is finally accepted by OpenRouter 

        content.append({
            "type": "text", 
            "text": f"--- Page {i+1} ---" # inform the page 
        }) 

        content.append({
            "type": "image_url", 
            "image_url": {
                "url": f"data:image/jpeg;base64,{value}" # send value and inform LLM the format so that it can decode base64 bytes to get image information
            }
        })
    
    messages.append({
        "role": "user", 
        "content": content
    })

    response = await client.chat.completions.create(
        model=settings.PDF_PARSE_MODEL, 
        messages=messages, 
        extra_headers={
            # "HTTP-Referer": "https://github.com/traffic/law-assistant", 
            "X-Title": "Labour Law Assistant PDF Parser", 
        }
    )
    return response.choices[0].message.content
      

    




    

            

