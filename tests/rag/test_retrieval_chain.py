"""检索链路测试脚本。

用于测试 RAG 检索链路的基本功能。
"""

import sys
import traceback

def test_imports():
    """测试模块导入。"""
    print("=" * 50)
    print("测试 1: 模块导入")
    print("=" * 50)

    try:
        from core.rag import (
            DenseRetriever,
            SparseRetriever,
            HybridSearch,
            Reranker,
            RetrievalChain,
            CitationBuilder,
            create_retrieval_chain,
            create_simple_retrieval_chain,
        )
        print("✅ 所有模块导入成功")
        return True
    except Exception as e:
        print(f"❌ 模块导入失败: {e}")
        traceback.print_exc()
        return False


def test_citation_builder():
    """测试引用构建器。"""
    print("\n" + "=" * 50)
    print("测试 2: CitationBuilder")
    print("=" * 50)

    try:
        from core.rag import CitationBuilder

        builder = CitationBuilder(citation_format="bracket")

        # 模拟检索结果
        chunks = [
            {
                "chunk_uuid": "chunk_001",
                "content": "第一条 为了加强安全生产管理，防止和减少生产安全事故...",
                "content_preview": "第一条 为了加强安全生产管理...",
                "score": 0.856,
                "section_title": "第一章 总则",
                "page_start": 1,
                "chunk_type": "child_text",
                "document_id": "doc_001",
                "metadata": {"section_title": "第一章 总则"},
            },
            {
                "chunk_uuid": "chunk_002",
                "content": "第二条 在中华人民共和国领域内从事生产经营活动的单位...",
                "content_preview": "第二条 在中华人民共和国领域...",
                "score": 0.723,
                "section_title": "第一章 总则",
                "page_start": 1,
                "chunk_type": "child_text",
                "document_id": "doc_001",
                "metadata": {"section_title": "第一章 总则"},
            },
        ]

        citations = builder.build_citations(chunks)

        print(f"✅ 生成 {len(citations)} 个引用")
        for cite in citations:
            print(f"   {cite['citation_id']} {cite['section_title']} (score={cite['score']:.2%})")

        # 测试引用列表构建
        ref_list = builder.build_reference_list(citations)
        print(f"\n📋 引用列表:\n{ref_list}")

        return True
    except Exception as e:
        print(f"❌ CitationBuilder 测试失败: {e}")
        traceback.print_exc()
        return False


def test_dense_retriever():
    """测试 Dense 检索器。"""
    print("\n" + "=" * 50)
    print("测试 3: DenseRetriever")
    print("=" * 50)

    try:
        from core.rag import DenseRetriever
        from core.vectorstore.milvus_store import MilvusStore

        # 创建模拟的 EmbeddingGateway
        class MockEmbeddingGateway:
            def embed_query(self, text):
                # 返回模拟向量
                return {"dense_vector": [0.1] * 768, "sparse_vector": {}}

            def embed_texts(self, texts):
                return [{"dense_vector": [0.1] * 768, "sparse_vector": {}} for _ in texts]

        mock_embedding = MockEmbeddingGateway()
        vector_store = MilvusStore()

        # 添加测试数据
        test_chunks = [
            {
                "chunk_uuid": "chunk_001",
                "document_id": "doc_001",
                "content": "第一条 为了加强安全生产管理，防止和减少生产安全事故...",
                "content_preview": "第一条 为了加强安全生产管理...",
                "dense_vector": [0.5] * 768,
                "sparse_vector": {"安全": 0.8, "生产": 0.9},
                "chunk_type": "child_text",
                "section_title": "第一章 总则",
                "page_start": 1,
                "metadata": {},
            },
        ]

        vector_store.upsert_chunks(test_chunks)

        # 创建 Dense 检索器
        retriever = DenseRetriever(
            embedding_gateway=mock_embedding,
            vector_store=vector_store,
            top_k=5,
        )

        # 执行检索
        results = retriever.retrieve("安全生产注意事项")

        print(f"✅ Dense 检索成功，返回 {len(results)} 条结果")
        for r in results[:2]:
            print(f"   - {r['chunk_uuid']}: score={r['score']:.4f}")

        return True
    except Exception as e:
        print(f"❌ DenseRetriever 测试失败: {e}")
        traceback.print_exc()
        return False


def test_hybrid_search():
    """测试混合检索。"""
    print("\n" + "=" * 50)
    print("测试 4: HybridSearch")
    print("=" * 50)

    try:
        from core.rag import DenseRetriever, SparseRetriever, HybridSearch
        from core.vectorstore.milvus_store import MilvusStore

        # 创建模拟的 EmbeddingGateway
        class MockEmbeddingGateway:
            def embed_query(self, text):
                return {"dense_vector": [0.1] * 768, "sparse_vector": {"安全": 0.8}}

            def embed_texts(self, texts):
                return [{"dense_vector": [0.1] * 768, "sparse_vector": {}} for _ in texts]

        mock_embedding = MockEmbeddingGateway()
        vector_store = MilvusStore()

        # 添加测试数据
        test_chunks = [
            {
                "chunk_uuid": "chunk_001",
                "document_id": "doc_001",
                "content": "安全生产管理条例",
                "content_preview": "安全生产管理条例",
                "dense_vector": [0.5] * 768,
                "sparse_vector": {"安全": 0.9, "生产": 0.8},
                "chunk_type": "child_text",
                "section_title": "第一章",
                "page_start": 1,
                "metadata": {},
            },
            {
                "chunk_uuid": "chunk_002",
                "document_id": "doc_001",
                "content": "设备检修规程",
                "content_preview": "设备检修规程",
                "dense_vector": [0.3] * 768,
                "sparse_vector": {"设备": 0.9},
                "chunk_type": "child_text",
                "section_title": "第二章",
                "page_start": 5,
                "metadata": {},
            },
        ]
        vector_store.upsert_chunks(test_chunks)

        # 创建检索器
        dense = DenseRetriever(mock_embedding, vector_store, top_k=5)
        sparse = SparseRetriever(mock_embedding, vector_store, top_k=5)

        # 创建混合检索
        hybrid = HybridSearch(dense, sparse, fusion_method="weighted")

        # 执行检索
        results = hybrid.search("安全生产", top_k=5)

        print(f"✅ 混合检索成功，返回 {len(results)} 条结果")
        for r in results:
            print(f"   - {r['chunk_uuid']}: score={r['score']:.4f}, dense={r['dense_score']:.4f}, sparse={r['sparse_score']:.4f}")

        return True
    except Exception as e:
        print(f"❌ HybridSearch 测试失败: {e}")
        traceback.print_exc()
        return False


def test_reranker():
    """测试 Reranker。"""
    print("\n" + "=" * 50)
    print("测试 5: Reranker")
    print("=" * 50)

    try:
        from core.rag import Reranker

        # 创建 Reranker 但不加载模型
        # 注意：is_available() 会触发模型加载，在某些环境下会导致 segfault
        # 所以这里直接测试实例化和基本方法
        reranker = Reranker()

        print(f"✅ Reranker 实例化成功")
        print(f"   - reranker_model: {reranker.reranker_model}")
        print(f"   - device: {reranker.device}")
        print(f"   - top_n: {reranker.top_n}")

        # 测试 _build_pairs 方法（不加载模型）
        docs = [
            {"chunk_uuid": "chunk_001", "content": "安全生产管理条例第一条", "score": 0.8},
            {"chunk_uuid": "chunk_002", "content": "设备检修规程", "score": 0.6},
        ]
        pairs = reranker._build_pairs("安全生产", docs)
        print(f"   - _build_pairs() 测试通过，生成了 {len(pairs)} 个 pairs")

        # 如果模型未加载，rerank 会返回原始顺序
        if reranker._model is None:
            print("⚠️ Reranker 模型未加载（sentence_transformers 未安装或加载失败）")
            print("   这在本地开发环境是正常的，部署时会安装依赖")
            print("   rerank() 会返回原始顺序作为 fallback")

        return True
    except Exception as e:
        print(f"❌ Reranker 测试失败: {e}")
        traceback.print_exc()
        return False


def main():
    """运行所有测试。"""
    print("\n" + "=" * 60)
    print("🧪 RAG 检索链路测试")
    print("=" * 60)

    results = []

    results.append(("模块导入", test_imports()))
    results.append(("CitationBuilder", test_citation_builder()))
    results.append(("DenseRetriever", test_dense_retriever()))
    results.append(("HybridSearch", test_hybrid_search()))
    results.append(("Reranker", test_reranker()))

    # 汇总
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {name}: {status}")

    print(f"\n总计: {passed}/{total} 通过")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
