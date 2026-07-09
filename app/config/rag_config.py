from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.utils import load_yaml_file


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


def _resolve_config_path() -> Path:
    """根据当前环境确定 rag 配置读写的目标文件，统一为 llm_config.{env_name}.yml：
    - APP_ENV 未设置 → env_name 默认 'local' → llm_config.local.yml
    - 其他环境（test / prod …）→ llm_config.{env_name}.yml
    读取与写入统一使用此判定。"""
    env_name = os.getenv("APP_ENV", "").strip().lower()
    if not env_name:
        env_name = "local"
    return CONFIG_DIR / f"llm_config.{env_name}.yml"


class BM25Config(BaseModel):
    min_score_threshold: float = 5.0


class SemanticConfig(BaseModel):
    metric: str = "cosine"  # cosine | dot_product | euclidean
    min_score_threshold: float = 0.7


class HybridConfig(BaseModel):
    fusion_method: str = "rrf"  # rrf | weighted
    weighted_alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    min_score_threshold: float = 0.5


class RerankConfig(BaseModel):
    enabled: bool = False
    model: str = ""


class RagConfig(BaseModel):
    retrieval_strategy: str = "hybrid"  # bm25 | semantic | hybrid
    top_k: int = Field(default=5, ge=1)
    bm25: BM25Config = BM25Config()
    semantic: SemanticConfig = SemanticConfig()
    hybrid: HybridConfig = HybridConfig()
    rerank: RerankConfig = RerankConfig()


class RagConfigService:
    """RAG 检索配置的运行时持有与持久化服务（单例）。"""

    def __init__(self, config: RagConfig | None = None) -> None:
        self._config = config or _load_rag_config()

    @property
    def config(self) -> RagConfig:
        return self._config

    def get_config(self) -> RagConfig:
        return self._config

    def update_config(self, patch: dict[str, object]) -> RagConfig:
        """局部更新检索配置，并将结果写回 llm_config.local.yml。"""
        updated = self._config.model_copy(deep=True)
        _apply_patch(updated, patch)
        self._config = updated
        _persist(updated)
        return self._config


def _load_rag_config() -> RagConfig:
    """读取当前环境对应的配置文件中的 rag 段（无则回退到 pydantic 默认值）。"""
    path = _resolve_config_path()

    rag_data: dict[str, object] = {}
    if path.exists():
        try:
            file_data = load_yaml_file(path)
        except Exception:
            file_data = {}
        if isinstance(file_data, dict):
            section = file_data.get("rag")
            if isinstance(section, dict):
                rag_data.update(section)

    return RagConfig(**rag_data)


def _apply_patch(model: BaseModel, patch: dict[str, object]) -> None:
    """将扁平/嵌套的 patch 应用到 pydantic model（仅支持一层嵌套）。"""
    for key, value in patch.items():
        if key in ("bm25", "semantic", "hybrid", "rerank") and isinstance(value, dict):
            sub = getattr(model, key)
            for sub_key, sub_value in value.items():
                if sub_value is not None and hasattr(sub, sub_key):
                    setattr(sub, sub_key, sub_value)
        elif value is not None and hasattr(model, key):
            setattr(model, key, value)


def _persist(config: RagConfig) -> None:
    """将 rag 段写回当前环境对应的配置文件（保留该文件其他段）。"""
    import yaml

    target = _resolve_config_path()
    data: dict[str, object] = {}
    if target.exists():
        try:
            file_data = load_yaml_file(target)
            if isinstance(file_data, dict):
                data = dict(file_data)
        except Exception:
            data = {}

    data["rag"] = config.model_dump()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


# 模块级单例
_rag_config_service = RagConfigService()


def get_rag_config_service() -> RagConfigService:
    return _rag_config_service
