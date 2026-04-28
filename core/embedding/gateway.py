"""Embedding Gateway。

为什么需要 Gateway / Provider 抽象：
- 业务代码不应该直接耦合具体模型 SDK；
- 后续可能从本地模型切到服务化 embedding 网关；
- 模型升级、量化、私有化部署都不应影响 ingestion / retrieval service 的调用方式。

为什么本项目必须同时保留 dense + sparse：
- dense 向量擅长语义相似召回；
- sparse 向量擅长制度条款号、设备编号、表头关键词等精确匹配；
- 企业文档场景既有“语义问法”，也有“关键词/编号问法”，所以要为 hybrid retrieval 预留双路输入。
"""

from __future__ import annotations

from core.config.settings import Settings
from core.embedding.providers.bge_m3_provider import BGEM3Provider


class EmbeddingGateway:
    """统一 Embedding 网关。"""

    def __init__(self, settings: Settings, provider: BGEM3Provider | None = None) -> None:
        """初始化 Embedding Gateway。"""

        self.settings = settings
        self.provider = provider or BGEM3Provider(
            model_name=settings.embedding_model_name,
            allow_real_model=settings.embedding_allow_real_model,
        )

    @property
    def provider_name(self) -> str:
        """返回当前 Provider 名称。"""

        return self.settings.embedding_provider

    @property
    def model_name(self) -> str:
        """返回当前模型名称。"""

        return self.provider.model_name

    def embed_texts(self, texts: list[str]) -> list[dict]:
        """批量生成文本向量。"""

        return self.provider.embed_texts(texts)

    def embed_query(self, text: str) -> dict:
        """生成查询向量。"""

        return self.provider.embed_query(text)
