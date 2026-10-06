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
        "Hành vi vi phạm", "Hình thức xử phạt", "Thời hạn", "Khái niệm pháp lý",
        "Điều", "Chương", "Mục", "Khoản"
    ]
    APP_ENTITY_TYPE_DESCRIPTIONS: dict[str, str] = {
        "Văn bản pháp luật": "Luật, nghị định, thông tư, quyết định, bộ luật",
        "Điều khoản": "Điều, khoản, mục, phụ lục trong văn bản pháp luật",
        "Điều": "Điều luật cụ thể (vd: Điều 5, Điều 10)",
        "Chương": "Chương trong văn bản (vd: Chương I, Chương II)",
        "Mục": "Mục trong chương",
        "Khoản": "Khoản trong một điều luật",
        "Cơ quan ban hành": "Bộ, cục, ủy ban, cơ quan nhà nước ban hành văn bản",
        "Đối tượng áp dụng": "Người lao động, người sử dụng lao động, tổ chức bị điều chỉnh",
        "Hành vi vi phạm": "Hành vi bị cấm hoặc vi phạm pháp luật lao động",
        "Hình thức xử phạt": "Phạt tiền, cảnh cáo, đình chỉ, biện pháp xử lý vi phạm",
        "Thời hạn": "Thời gian, thời hạn, mốc thời gian có ý nghĩa pháp lý",
        "Khái niệm pháp lý": "Định nghĩa, thuật ngữ, khái niệm được định nghĩa trong luật",
    }
    APP_EDGE_TYPES: list[str] = [
        "quy định", "áp dụng cho", "ban hành bởi", "liên quan đến",
        "REPLACES", "MODIFIES", "SUPPLEMENTS", "OVERLAPS"
    ]
    APP_EDGE_TYPE_DESCRIPTIONS: dict[str, str] = {
        "Quy định": "Văn bản pháp luật quy định về một đối tượng hoặc hành vi",
        "Áp dụng cho": "Điều khoản áp dụng cho đối tượng cụ thể",
        "Ban hành bởi": "Văn bản được ban hành bởi cơ quan hoặc nhà nước",
        "Liên quan đến": "Hai thực thể có liên quan pháp lý với nhau",
        "Chứa" : "Một thực thể chứa thực thể khác (vd: Chương chứa Điều, Điều chứa Khoản)",
        "REPLACES": "Văn bản/điều luật mới thay thế hoàn toàn văn bản/điều luật cũ",
        "MODIFIES": "Văn bản/điều luật mới sửa đổi một phần văn bản/điều luật cũ",
        "SUPPLEMENTS": "Văn bản/điều luật mới bổ sung nội dung cho văn bản/điều luật cũ",
        "OVERLAPS": "Hai điều luật quy định cùng vấn đề từ các văn bản khác nhau, có thể gây mâu thuẫn",
    }

    @property
    def edge_types_guidance(self) -> str:
        """Build the conflict edge types guidance string for the ConflictAnalyzer prompt."""
        conflict_types = [t for t in self.APP_EDGE_TYPES if t.isupper()]
        lines = []
        for i, t in enumerate(conflict_types, 1):
            desc = self.APP_EDGE_TYPE_DESCRIPTIONS.get(t, "")
            lines.append(f"{i}. **{t}** — {desc}" if desc else f"{i}. **{t}**")
        return "\n".join(lines)

    @property
    def entity_types_guidance(self) -> str:
        """Build the entity_types_guidance string for LightRAG addon_params from config."""
        lines = ["Classify each entity using ONLY one of these Vietnamese legal entity types:"]
        for t in self.APP_ENTITY_TYPES:
            desc = self.APP_ENTITY_TYPE_DESCRIPTIONS.get(t, "")
            lines.append(f"- {t}: {desc}" if desc else f"- {t}")
        fallback = self.APP_ENTITY_TYPES[-1] if self.APP_ENTITY_TYPES else "Khái niệm pháp lý"
        lines.append(f"If no type fits, use: {fallback}")
        lines.append(
            "\nIMPORTANT RULES: "
            "1. Normalize all entity names to lowercase to prevent duplicate nodes. "
            "2. DO NOT hallucinate, infer, or use your prior knowledge. "
            "3. DO NOT generate specific examples if they are not explicitly written in the text."
        )
        return "\n".join(lines)

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