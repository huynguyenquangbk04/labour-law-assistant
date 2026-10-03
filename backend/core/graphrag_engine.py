import os
from pathlib import Path

import pandas as pd

from graphrag.config.load_config import load_config
from graphrag.api import build_index, local_search, global_search, drift_search, basic_search

from backend.config import settings


def _read_parquet_or_none(path: Path) -> pd.DataFrame | None:
    """covariates.parquet chỉ tồn tại nếu extract_claims.enabled=true.
    Trả về None nếu file không có, để khớp signature cho phép covariates=None."""
    return pd.read_parquet(path) if path.exists() else None


class GraphRAGEngine:
    """Class method pattern giống RAGEngine (LightRAG) để 2 hệ thống có
    interface đối xứng, dễ so sánh trong thí nghiệm."""

    _instance = None  # sẽ giữ GraphRagConfig sau khi initialize()

    @staticmethod
    def _working_dir() -> Path:
        configured_dir = Path(settings.GRAPHRAG_WORKING_DIR)
        if configured_dir.is_absolute():
            return configured_dir
        return Path(__file__).resolve().parents[2] / configured_dir

    @classmethod
    async def initialize(cls):
        """Chỉ load config, KHÔNG tự chạy build_index — tránh tốn LLM call
        mỗi lần app khởi động. Gọi build_index() riêng khi cần index dữ liệu mới."""
        if cls._instance is None:
            original_cwd = Path.cwd()
            working_dir = cls._working_dir().resolve()
            try:
                config = load_config(root_dir=working_dir)

                prompt_configs = (
                    (config.extract_graph, "prompt"),
                    (config.summarize_descriptions, "prompt"),
                    (config.extract_claims, "prompt"),
                    (config.community_reports, "graph_prompt"),
                    (config.community_reports, "text_prompt"),
                    (config.local_search, "prompt"),
                    (config.global_search, "map_prompt"),
                    (config.global_search, "reduce_prompt"),
                    (config.global_search, "knowledge_prompt"),
                    (config.drift_search, "prompt"),
                    (config.drift_search, "reduce_prompt"),
                    (config.basic_search, "prompt"),
                )
                for prompt_config, field_name in prompt_configs:
                    prompt = getattr(prompt_config, field_name)
                    if prompt is not None:
                        prompt_path = Path(prompt)
                        if not prompt_path.is_absolute():
                            setattr(
                                prompt_config,
                                field_name,
                                str((working_dir / prompt_path).resolve()),
                            )

                cache_storage = config.cache.storage
                if cache_storage is not None and cache_storage.base_dir:
                    cache_path = Path(cache_storage.base_dir)
                    if not cache_path.is_absolute():
                        cache_storage.base_dir = str(
                            (working_dir / cache_path).resolve()
                        )

                cls._instance = config
            finally:
                os.chdir(original_cwd)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            raise RuntimeError(
                "GraphRAGEngine not initialized. Call GraphRAGEngine.initialize() first."
            )
        return cls._instance

    @classmethod
    async def build_index(cls):
        """Chạy pipeline indexing đầy đủ. Gọi tay khi có dữ liệu luật mới,
        KHÔNG gọi trong luồng khởi động app thông thường."""
        config = cls.get_instance()
        results = await build_index(config=config)
        failed = [result for result in results if result.error is not None]
        if failed:
            details = "; ".join(
                f"{result.workflow}: {result.error}" for result in failed
            )
            raise RuntimeError(f"GraphRAG indexing failed: {details}")

    @classmethod
    async def query(cls, question: str, method: str = "local"):
        """method: 'local' | 'global' | 'drift' | 'basic'
        Trả về (response: str, context: Any) — giống cấu trúc aquery() bên LightRAG
        để dễ so sánh song song trong thí nghiệm.

        LƯU Ý: local_search/global_search/drift_search KHÔNG tự đọc dữ liệu đã
        index từ config — phải tự load parquet rồi truyền vào (khác LightRAG,
        nơi aquery() tự động đọc storage bên trong)."""
        config = cls.get_instance()
        output_dir = cls._working_dir() / "output"

        common_kwargs = {"config": config, "query": question, "response_type": "multiple paragraphs"}

        if method == "local":
            response, context = await local_search(
                **common_kwargs,
                entities=pd.read_parquet(output_dir / "entities.parquet"),
                communities=pd.read_parquet(output_dir / "communities.parquet"),
                community_reports=pd.read_parquet(output_dir / "community_reports.parquet"),
                text_units=pd.read_parquet(output_dir / "text_units.parquet"),
                relationships=pd.read_parquet(output_dir / "relationships.parquet"),
                covariates=_read_parquet_or_none(output_dir / "covariates.parquet"),
                community_level=2,
            )
        elif method == "global":
            response, context = await global_search(
                **common_kwargs,
                communities=pd.read_parquet(output_dir / "communities.parquet"),
                community_reports=pd.read_parquet(output_dir / "community_reports.parquet"),
                community_level=2,
                dynamic_community_selection=False,
            )
        elif method == "drift":
            response, context = await drift_search(
                **common_kwargs,
                entities=pd.read_parquet(output_dir / "entities.parquet"),
                communities=pd.read_parquet(output_dir / "communities.parquet"),
                community_reports=pd.read_parquet(output_dir / "community_reports.parquet"),
                text_units=pd.read_parquet(output_dir / "text_units.parquet"),
                relationships=pd.read_parquet(output_dir / "relationships.parquet"),
                community_level=2,
            )
        elif method == "basic":
            response, context = await basic_search(
                **common_kwargs,
                text_units=pd.read_parquet(output_dir / "text_units.parquet"),
            )
        else:
            raise ValueError(f"Unknown method: {method}")

        return response, context