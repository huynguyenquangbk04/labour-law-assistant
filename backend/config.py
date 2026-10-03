from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import json
from pydantic import field_validator

BASE_DIR = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/law_assistant"
    
    # Postgres individual components for LightRAG
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DATABASE: str = "law_assistant"
    
    # REDIS_URL: Optional[str] = None
    
    BASE_URL: Optional[str] = None
    API_KEY: Optional[str] = None
    
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    EMBEDDING_QUERY_SENTENCE: str = "Instruct: Given a legal query, retrieve relevant statutes...\nQuery: "
    LLM_MODEL: str = "deepseek/deepseek-v3.2"

    OPENAI_API_BASE: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "deepseek/deepseek-v3.2"
    TAVILY_API_KEY: Optional[str] = None
    
    SUMMARY_LANGUAGE: str = "Vietnamese"
    APP_ENTITY_TYPES: list[str] = [
        "Văn bản pháp luật", "Điều khoản", "Cơ quan ban hành", "Đối tượng áp dụng", 
        "Hành vi vi phạm", "Hình thức xử phạt", "Thời hạn", "Khái niệm pháp lý"
    ]

    WORKING_DIR: str = "./backend/data"
    LIGHTRAG_WORKING_DIR: str = "./backend/core/lightrag_project"
    GRAPHRAG_WORKING_DIR: str = "./backend/core/graphrag_project"

    @field_validator("APP_ENTITY_TYPES", mode="before")
    @classmethod
    def parse_entity_types(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except:
                    pass
            return [x.strip() for x in v.split(",")]
        return v

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore") # os -> .env -> default value

settings = Settings()