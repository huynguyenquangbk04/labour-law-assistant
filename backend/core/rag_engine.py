import os
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc
from backend.core.llm_services import EmbeddingFuncWrapper, llm_reasoning_func
from backend.config import settings

class RAGEngine: # Because intialize one LightRAG including connecting it with database is very heavy, we use class method in order to maitain only one LightRAG engine
    _instance = None

    @classmethod
    async def initialize(cls):
        if cls._instance is None:
            embedding_func = EmbeddingFuncWrapper()

            # install the database information into os system
            os.environ["POSTGRES_HOST"] = settings.POSTGRES_HOST
            os.environ["POSTGRES_PORT"] = str(settings.POSTGRES_PORT)
            os.environ["POSTGRES_USER"] = settings.POSTGRES_USER
            os.environ["POSTGRES_PASSWORD"] = settings.POSTGRES_PASSWORD
            os.environ["POSTGRES_DATABASE"] = settings.POSTGRES_DATABASE

            cls._instance = LightRAG(
                working_dir=settings.LIGHTRAG_WORKING_DIR,
                llm_model_func=llm_reasoning_func,
                embedding_func=EmbeddingFunc(
                    # embedding_dim=1536, # Qwen
                    embedding_dim=1024, # BGE
                    max_token_size=512,
                    func=embedding_func,
                    model_name=settings.EMBEDDING_MODEL
                ),

                # automatically search and load the database information in os system
                kv_storage="PGKVStorage",
                vector_storage="PGVectorStorage",
                graph_storage="PGGraphStorage",
                doc_status_storage="PGDocStatusStorage",

                addon_params={
                    "language": settings.SUMMARY_LANGUAGE,
                    "entity_types": settings.ENTITY_TYPES
                }
            )
            await cls._instance.initialize_storages() # initialize connection pools

            return cls._instance
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None: 
            return RuntimeError("RAGEngine not initialized. Call RAGEngine.initialize() first.")
        return cls._instance
