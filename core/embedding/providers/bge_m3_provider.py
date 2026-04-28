"""BGE-M3 Provider。

当前阶段实现目标：
- 统一输出 dense_vector + sparse_vector；
- 有真实模型时优先尝试真实调用；
- 没有模型依赖时使用稳定、可复现的占位向量，保证 ingestion / retrieval 闭环可运行。

注意：
- 这里的占位向量不是最终线上质量；
- 但它保留了“同一接口、同一返回结构、同一 dense+sparse 双路语义”，
  后续替换真实模型时不需要改上层业务服务。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any


class BGEM3Provider:
    """BGE-M3 Provider。"""

    DENSE_DIMENSION = 24

    def __init__(self, model_name: str = "BAAI/bge-m3", allow_real_model: bool = False) -> None:
        """初始化 Provider。"""

        self.model_name = model_name
        self.allow_real_model = allow_real_model
        self._real_model: Any | None = None
        self._model_import_error: Exception | None = None

    def embed_texts(self, texts: list[str]) -> list[dict]:
        """批量生成 dense + sparse 向量。"""

        real_model = self._get_real_model()
        if real_model is not None:
            real_result = self._try_real_embed(real_model, texts)
            if real_result is not None:
                return real_result

        return [self._build_placeholder_embedding(text) for text in texts]

    def embed_query(self, text: str) -> dict:
        """生成单条查询向量。"""

        return self.embed_texts([text])[0]

    def _get_real_model(self) -> Any | None:
        """惰性获取真实模型。

        当前优先尝试 FlagEmbedding 的 BGEM3FlagModel。
        如果运行环境没有该依赖，则回退到占位实现。
        """

        if self._real_model is not None:
            return self._real_model
        if self._model_import_error is not None:
            return None
        if not self.allow_real_model:
            self._model_import_error = RuntimeError("real_embedding_model_disabled")
            return None

        try:  # pragma: no cover - 真实模型路径依赖运行环境
            from FlagEmbedding import BGEM3FlagModel  # type: ignore

            self._real_model = BGEM3FlagModel(self.model_name, use_fp16=False)
        except Exception as exc:  # pragma: no cover - 占位回退是当前主路径
            self._model_import_error = exc
            self._real_model = None
        return self._real_model

    def _try_real_embed(self, real_model: Any, texts: list[str]) -> list[dict] | None:
        """尝试真实模型调用。

        这里专门单独包一层，是为了避免不同版本 SDK 的返回结构差异
        直接污染上层业务代码。
        """

        try:  # pragma: no cover - 真实模型路径依赖运行环境
            result = real_model.encode(
                texts,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )
            dense_vectors = result.get("dense_vecs") or []
            sparse_vectors = result.get("lexical_weights") or []
            embeddings: list[dict] = []
            for index, text in enumerate(texts):
                dense_vector = list(dense_vectors[index]) if index < len(dense_vectors) else []
                sparse_vector = sparse_vectors[index] if index < len(sparse_vectors) else {}
                embeddings.append(
                    {
                        "dense_vector": dense_vector,
                        "sparse_vector": dict(sparse_vector or {}),
                        "model_name": self.model_name,
                        "vector_source": "real_model",
                        "text_length": len(text),
                    }
                )
            return embeddings
        except Exception:
            return None

    def _build_placeholder_embedding(self, text: str) -> dict:
        """构造可复现的占位向量。

        占位 dense 向量：
        - 基于 token hash 落桶；
        - 做 L2 归一化；
        - 便于本地做最小 cosine 检索验证。

        占位 sparse 向量：
        - 保留关键词权重；
        - 便于验证 hybrid retrieval 中的稀疏通道。
        """

        tokens = self._tokenize(text)
        counter = Counter(tokens)
        dense_vector = [0.0 for _ in range(self.DENSE_DIMENSION)]

        for token, weight in counter.items():
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.DENSE_DIMENSION
            dense_vector[bucket] += float(weight)

        norm = math.sqrt(sum(value * value for value in dense_vector)) or 1.0
        dense_vector = [value / norm for value in dense_vector]

        total = sum(counter.values()) or 1
        sparse_vector = {
            token: round(weight / total, 6)
            for token, weight in counter.items()
        }

        return {
            "dense_vector": dense_vector,
            "sparse_vector": sparse_vector,
            "model_name": self.model_name,
            "vector_source": "placeholder",
            "text_length": len(text),
        }

    def _tokenize(self, text: str) -> list[str]:
        """做最小分词。

        这里不是最终检索 tokenizer，
        但要尽量兼顾：
        - 中文关键词；
        - 英文单词；
        - 编号、日期、设备代码。
        """

        normalized = re.sub(r"\s+", " ", text or "").strip().lower()
        if not normalized:
            return ["<empty>"]

        tokens: list[str] = []
        latin_tokens = re.findall(r"[a-z0-9_]+", normalized)
        tokens.extend(latin_tokens)

        chinese_segments = re.findall(r"[\u4e00-\u9fff]+", normalized)
        for segment in chinese_segments:
            if len(segment) == 1:
                tokens.append(segment)
                continue
            tokens.extend(segment)
            for index in range(len(segment) - 1):
                tokens.append(segment[index : index + 2])

        return tokens or ["<empty>"]
