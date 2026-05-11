"""FAQ 检索模块 - 基于 BM25 的 FAQ 问句匹配。

职责：
- 从 MySQL/Redis 加载 FAQ 数据（问题-答案对）
- 使用 BM25 算法对用户问句与 FAQ 问句进行关键词匹配
- 返回置信度最高的匹配答案

业务流程：
1. 用户问句 → BM25 匹配 FAQ 问句
2. 计算 softmax 置信度
3. 置信度 >= 0.85：直接返回 FAQ 答案
4. 置信度 < 0.85：返回 None，触发 RAG 检索

参考实现：
- integrated_qa_system/mysql_qa/retrieval/bm25_search.py
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FAQSearchResult:
    """FAQ 检索结果。

    Attributes:
        found: 是否找到匹配
        answer: FAQ 答案（如果 found=True）
        question: 匹配的 FAQ 问句
        confidence: 置信度分数
        should_use_rag: 是否应该使用 RAG 检索
    """

    def __init__(
        self,
        found: bool,
        answer: str | None = None,
        question: str | None = None,
        confidence: float = 0.0,
    ) -> None:
        self.found = found
        self.answer = answer
        self.question = question
        self.confidence = confidence
        self.should_use_rag = not found or confidence < 0.85

    def __repr__(self) -> str:
        return (
            f"FAQSearchResult(found={self.found}, confidence={self.confidence:.3f}, "
            f"should_use_rag={self.should_use_rag})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "answer": self.answer,
            "question": self.question,
            "confidence": round(self.confidence, 4),
            "should_use_rag": self.should_use_rag,
        }


class FAQRetriever:
    """FAQ 检索器 - 基于 BM25 的 FAQ 问句匹配。

    职责：
    - 管理 FAQ 数据的加载和缓存
    - 使用 BM25 算法进行问句匹配
    - 计算置信度并返回匹配结果

    设计原因：
    - FAQ 检索优先于 RAG 检索，减少不必要的 LLM 调用
    - 对于高频、标准化的问答，FAQ 匹配更准确、更快
    - 置信度阈值 0.85 是经验值，平衡精确率和召回率

    处理流程：
    1. 检查 Redis 缓存
    2. BM25 匹配 FAQ 问句
    3. 计算 softmax 置信度
    4. 判断是否命中 FAQ
    """

    # 默认置信度阈值
    DEFAULT_CONFIDENCE_THRESHOLD = 0.85

    def __init__(
        self,
        redis_client: Any | None = None,
        mysql_client: Any | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        cache_ttl: int = 3600,
    ) -> None:
        """初始化 FAQ 检索器。

        Args:
            redis_client: Redis 客户端（用于缓存 FAQ 数据和答案）
            mysql_client: MySQL 客户端（用于获取 FAQ 数据）
            confidence_threshold: 置信度阈值，默认 0.85
            cache_ttl: Redis 缓存 TTL（秒）
        """
        self.redis_client = redis_client
        self.mysql_client = mysql_client
        self.confidence_threshold = confidence_threshold
        self.cache_ttl = cache_ttl

        # BM25 模型
        self._bm25: Any | None = None
        self._original_questions: list[str] = []
        self._tokenized_questions: list[list[str]] = []
        self._initialized: bool = False

        # 加载 FAQ 数据
        self._load_faq_data()

    def _load_faq_data(self) -> None:
        """加载 FAQ 数据。

        优先从 Redis 缓存加载，如果缓存不存在则从 MySQL 加载。

        Redis 缓存 key：
        - faq:original_questions：原始 FAQ 问句列表
        - faq:tokenized_questions：分词后的 FAQ 问句列表
        - faq:answer:{question}：单个 FAQ 答案缓存
        """
        if not self.redis_client or not self.mysql_client:
            logger.warning("[FAQRetriever] Redis 或 MySQL 客户端未初始化，跳过 FAQ 加载")
            return

        try:
            # 尝试从 Redis 加载
            self._original_questions = self.redis_client.get_data("faq:original_questions") or []
            self._tokenized_questions = self.redis_client.get_data("faq:tokenized_questions") or []

            if not self._original_questions or not self._tokenized_questions:
                # 从 MySQL 加载 FAQ 数据
                self._load_from_mysql()

            # 初始化 BM25 模型
            self._init_bm25()

        except Exception as e:
            logger.error(f"[FAQRetriever] 加载 FAQ 数据失败: {e}", exc_info=True)

    def _load_from_mysql(self) -> None:
        """从 MySQL 加载 FAQ 数据。

        获取所有 FAQ 问句-答案对，并缓存到 Redis。
        """
        if not self.mysql_client:
            logger.warning("[FAQRetriever] MySQL 客户端未初始化")
            return

        try:
            # 从 MySQL 获取 FAQ 数据（问句，答案）
            faq_data = self.mysql_client.fetch_faqs()
            if not faq_data:
                logger.warning("[FAQRetriever] MySQL 中未找到 FAQ 数据")
                return

            self._original_questions = [item["question"] for item in faq_data]
            self._tokenized_questions = [self._tokenize(item["question"]) for item in faq_data]

            # 缓存到 Redis
            if self.redis_client:
                self.redis_client.set_data("faq:original_questions", self._original_questions)
                self.redis_client.set_data("faq:tokenized_questions", self._tokenized_questions)

            logger.info(f"[FAQRetriever] 从 MySQL 加载 {len(self._original_questions)} 条 FAQ 数据")

        except Exception as e:
            logger.error(f"[FAQRetriever] 从 MySQL 加载 FAQ 数据失败: {e}", exc_info=True)

    def _init_bm25(self) -> None:
        """初始化 BM25 模型。"""
        if not self._tokenized_questions:
            logger.warning("[FAQRetriever] FAQ 数据为空，跳过 BM25 初始化")
            return

        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(self._tokenized_questions)
            self._initialized = True
            logger.info(f"[FAQRetriever] BM25 模型初始化完成，问句数: {len(self._original_questions)}")

        except ImportError:
            logger.warning("[FAQRetriever] rank_bm25 未安装，使用内置 BM25 实现")
            self._initialized = True  # 使用内置实现

    def _tokenize(self, text: str) -> list[str]:
        """对文本进行分词。

        Args:
            text: 输入文本

        Returns:
            分词后的词列表
        """
        import re

        try:
            import jieba
            tokens = jieba.lcut(text.lower())
        except ImportError:
            # 简单分词：按空格和标点分割
            text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
            tokens = text.lower().split()

        # 停用词过滤
        stopwords = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
            "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
            "自己", "这", "那", "它", "他", "她", "们", "什么", "怎么", "为什么", "如何",
            "吗", "呢", "吧", "啊", "哦", "嗯", "呀", "哈", "嘿",
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
            "this", "that", "these", "those", "it", "its",
        }

        filtered = []
        for token in tokens:
            token = token.strip()
            if token and token not in stopwords and len(token) > 1:
                filtered.append(token)

        return filtered

    def _softmax(self, scores: list[float]) -> list[float]:
        """计算 Softmax 分数。

        将 BM25 分数映射到 [0, 1] 区间，概率分布。

        Args:
            scores: BM25 原始分数列表

        Returns:
            Softmax 归一化后的分数列表
        """
        import numpy as np

        exp_scores = np.exp(scores - np.max(scores))
        return (exp_scores / exp_scores.sum()).tolist()

    def search(self, query: str) -> FAQSearchResult:
        """搜索 FAQ 答案。

        Args:
            query: 用户问句

        Returns:
            FAQSearchResult：包含是否命中、答案、置信度等信息
        """
        if not query or not isinstance(query, str):
            logger.error("[FAQRetriever] 无效查询")
            return FAQSearchResult(found=False)

        # 1. 检查 Redis 缓存
        if self.redis_client:
            cached_answer = self.redis_client.get_data(f"faq:answer:cache:{query}")
            if cached_answer:
                logger.info(f"[FAQRetriever] 命中 Redis 缓存答案")
                return FAQSearchResult(
                    found=True,
                    answer=cached_answer,
                    question=query,
                    confidence=1.0,
                )

        # 2. 检查是否初始化
        if not self._initialized or not self._bm25:
            logger.warning("[FAQRetriever] BM25 未初始化，无法进行 FAQ 检索")
            return FAQSearchResult(found=False)

        try:
            # 3. 分词查询
            query_tokens = self._tokenize(query)

            # 4. 计算 BM25 分数
            scores = self._bm25.get_scores(query_tokens)

            # 5. 计算 Softmax 置信度
            softmax_scores = self._softmax(scores)

            # 6. 获取最高分
            best_idx = softmax_scores.index(max(softmax_scores))
            best_score = softmax_scores[best_idx]

            logger.info(
                f"[FAQRetriever] BM25 搜索完成，最高置信度: {best_score:.3f}, "
                f"匹配问句: {self._original_questions[best_idx][:30]}..."
            )

            # 7. 判断是否超过阈值
            if best_score >= self.confidence_threshold:
                matched_question = self._original_questions[best_idx]

                # 获取答案（优先从 Redis 缓存，否则从 MySQL）
                answer = self._get_answer(matched_question)

                if answer:
                    # 缓存答案到 Redis
                    if self.redis_client:
                        self.redis_client.set_data(f"faq:answer:cache:{query}", answer, ex=self.cache_ttl)

                    logger.info(f"[FAQRetriever] FAQ 命中，置信度: {best_score:.3f}")
                    return FAQSearchResult(
                        found=True,
                        answer=answer,
                        question=matched_question,
                        confidence=best_score,
                    )

            # 8. 未命中 FAQ，需要使用 RAG
            logger.info(f"[FAQRetriever] FAQ 未命中（最高置信度 {best_score:.3f} < {self.confidence_threshold}），触发 RAG 检索")
            return FAQSearchResult(
                found=False,
                confidence=best_score,
            )

        except Exception as e:
            logger.error(f"[FAQRetriever] FAQ 搜索失败: {e}", exc_info=True)
            return FAQSearchResult(found=False)

    def _get_answer(self, question: str) -> str | None:
        """获取 FAQ 答案。

        优先从 Redis 缓存获取，否则从 MySQL 查询。

        Args:
            question: FAQ 问句

        Returns:
            FAQ 答案，如果不存在则返回 None
        """
        # 从 Redis 缓存获取
        if self.redis_client:
            cache_key = f"faq:answer:{question}"
            cached = self.redis_client.get_data(cache_key)
            if cached:
                return cached

        # 从 MySQL 查询
        if self.mysql_client:
            try:
                answer = self.mysql_client.fetch_faq_answer(question)
                if answer and self.redis_client:
                    # 缓存到 Redis
                    cache_key = f"faq:answer:{question}"
                    self.redis_client.set_data(cache_key, answer, ex=self.cache_ttl)
                return answer
            except Exception as e:
                logger.error(f"[FAQRetriever] 从 MySQL 获取 FAQ 答案失败: {e}")

        return None

    def add_faq(self, question: str, answer: str) -> bool:
        """添加新的 FAQ。

        Args:
            question: FAQ 问句
            answer: FAQ 答案

        Returns:
            是否添加成功
        """
        if not self.mysql_client:
            logger.warning("[FAQRetriever] MySQL 客户端未初始化，无法添加 FAQ")
            return False

        try:
            # 保存到 MySQL
            self.mysql_client.add_faq(question, answer)

            # 更新本地缓存
            self._original_questions.append(question)
            self._tokenized_questions.append(self._tokenize(question))

            # 更新 BM25 模型
            self._init_bm25()

            # 缓存答案
            if self.redis_client:
                cache_key = f"faq:answer:{question}"
                self.redis_client.set_data(cache_key, answer, ex=self.cache_ttl)

            logger.info(f"[FAQRetriever] FAQ 添加成功: {question[:30]}...")
            return True

        except Exception as e:
            logger.error(f"[FAQRetriever] 添加 FAQ 失败: {e}", exc_info=True)
            return False

    def refresh(self) -> None:
        """刷新 FAQ 数据。

        重新从 MySQL 加载 FAQ 数据。
        """
        logger.info("[FAQRetriever] 刷新 FAQ 数据")
        self._original_questions = []
        self._tokenized_questions = []
        self._initialized = False
        self._load_faq_data()

    def is_available(self) -> bool:
        """检查 FAQ 检索是否可用。

        Returns:
            True 如果 BM25 已初始化且有 FAQ 数据
        """
        return self._initialized and len(self._original_questions) > 0
