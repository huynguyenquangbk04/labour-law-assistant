from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from backend.core.legal_schema import CONFLICT_TYPES, entity_guidance, edge_guidance

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
    APP_ENTITY_TYPE_DESCRIPTIONS: dict[str, str] = Field(min_length=1)
    APP_EDGE_TYPE_DESCRIPTIONS: dict[str, str] = Field(min_length=1)

    @field_validator("APP_ENTITY_TYPE_DESCRIPTIONS", "APP_EDGE_TYPE_DESCRIPTIONS")
    @classmethod
    def validate_type_descriptions(cls, definitions: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() or not description.strip() for name, description in definitions.items()):
            raise ValueError("Type names and descriptions must not be blank")
        return definitions

    @property
    def APP_ENTITY_TYPES(self) -> list[str]:
        return list(self.APP_ENTITY_TYPE_DESCRIPTIONS)

    @property
    def APP_EDGE_TYPES(self) -> list[str]:
        return list(self.APP_EDGE_TYPE_DESCRIPTIONS)

    @property
    def entity_types_guidance(self) -> str:
        return entity_guidance(self.APP_ENTITY_TYPE_DESCRIPTIONS, self.APP_EDGE_TYPE_DESCRIPTIONS)

    @property
    def edge_types_guidance(self) -> str:
        return edge_guidance(self.APP_EDGE_TYPE_DESCRIPTIONS)

    @property
    def conflict_types_guidance(self) -> str:
        return '\n'.join(f'- {kind}: {description}' for kind, description in CONFLICT_TYPES.items())

    WORKING_DIR: str = "./backend/data"
    LIGHTRAG_WORKING_DIR: str = "./backend/core/lightrag_project"
    GRAPHRAG_WORKING_DIR: str = "./backend/core/graphrag_project"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True,
    ) # os -> .env -> default value

settings = Settings()
