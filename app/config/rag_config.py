from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.utils import load_yaml_file
from app.utils.config_paths import get_config_dir, get_app_env


CONFIG_DIR = get_config_dir()


def _resolve_config_path() -> Path:
    """根据当前环境确定 rag 配置读写的目标文件，统一为 llm_config.{env_name}.yml：
    - APP_ENV 未设置 → env_name 默认 'local' → llm_config.local.yml
    - 其他环境（test / prod …）→ llm_config.{env_name}.yml
    读取与写入统一使用此判定。"""
    env_name = get_app_env()
    return CONFIG_DIR / f"llm_config.{env_name}.yml"


class EmbeddingConfig(BaseModel):
    """向量化模型（语义/混合检索依赖）独立配置块（顶层，与 llm / qdrant 同级）。

    与 agent 的 llm（app/config/llm.py）解耦，各自拥有独立的
    base_url / api_key / model。vector_size 须与嵌入模型实际输出维度一致，
    且须与 qdrant.vector_size 匹配。属基础设施配置，不由前端 PUT /rag/config 管理。
    """

    base_url: str = ""
    api_key: str = ""
    model: str = "text-embedding-v4"
    vector_size: int = Field(default=1536, ge=1)


class RerankConfig(BaseModel):
    """重排序模型独立配置（与 embedding 解耦，各自独立 base_url / api_key / model）。"""

    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class RagConfig(BaseModel):
    retrieval_strategy: str = "hybrid"  # bm25 | semantic | hybrid
    top_k: int = Field(default=5, ge=1)
    # 单一最小匹配度阈值：配置读出即为最终值，不做任何归一化/映射。
    # 不同检索策略适用量纲不同，由前端按 retrieval_strategy 控制可输入范围：
    #   - bm25    ：BM25(Modifier.IDF) 原始分数，0~10 量级，强命中约 4~6
    #   - semantic：余弦相似度，0~1
    #   - hybrid  ：RRF 融合分数约 1/(k+rank)，k=60 时最大 ~0.016，应接近 0
    # 默认 0.0 表示不按阈值过滤，仅取 top_k。
    min_score_threshold: float = 0.0
    # 切块参数（入库时使用，影响检索质量）：下发给分块策略，前端可控。
    chunk_size: int = Field(default=800, ge=50)
    chunk_overlap: int = Field(default=100, ge=0)
    min_chunk_size: int = Field(default=50, ge=1)
    # RRF 融合常数 k（仅 hybrid 策略生效），分越小权重越大。
    # 服务端融合时透传给 Qdrant 的 Rrf(k=rrf_k)（qdrant-client 1.18：RrfQuery(rrf=Rrf(k=...))）。
    rrf_k: int = Field(default=60, ge=1)
    rerank: RerankConfig = RerankConfig()
    # 注：向量化模型配置为顶层独立块 `embedding`（见 EmbeddingConfig），
    # 与 agent llm / qdrant 同级，不在此 RagConfig 内，不由前端 PUT /rag/config 管理。


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
    """将扁平/嵌套的 patch 应用到 pydantic model（rerank 支持一层嵌套）。"""
    for key, value in patch.items():
        if key == "rerank" and isinstance(value, dict):
            sub = model.rerank
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


def load_rag_config_raw() -> dict[str, object]:
    """读取当前环境配置文件中的 `rag` 原始段（dict）。

    该段由前端 PUT /rag/config 管理（检索策略、阈值、rerank 等）。
    无配置时返回空 dict。
    """
    path = _resolve_config_path()
    if not path.exists():
        return {}
    try:
        file_data = load_yaml_file(path)
    except Exception:
        return {}
    if isinstance(file_data, dict) and isinstance(file_data.get("rag"), dict):
        return dict(file_data["rag"])
    return {}


def load_embedding_config_raw() -> dict[str, object]:
    """读取当前环境配置文件中的顶层 `embedding` 原始段（dict）。

    `embedding` 为顶层独立配置块（与 `llm` / `qdrant` 同级，不由前端管理），
    包含 base_url / api_key / model / vector_size。
    为兼容过渡期旧配置，若顶层无 `embedding` 段，则回退读取 `rag.embedding`。
    无配置时返回空 dict。
    """
    path = _resolve_config_path()
    if not path.exists():
        return {}
    try:
        file_data = load_yaml_file(path)
    except Exception:
        return {}
    if not isinstance(file_data, dict):
        return {}
    if isinstance(file_data.get("embedding"), dict):
        return dict(file_data["embedding"])
    rag_section = file_data.get("rag")
    if isinstance(rag_section, dict) and isinstance(rag_section.get("embedding"), dict):
        return dict(rag_section["embedding"])
    return {}
