from abc import ABC, abstractmethod

# 1. 抽象策略基类
class RetrieveStrategy(ABC):
    @abstractmethod
    def search(self, query: str, top_k: int = 5):
        """统一检索接口"""
        pass

# 2. 具体策略1：BM25关键词检索
class BM25Retrieve(RetrieveStrategy):
    def search(self, query: str, top_k: int = 5):
        print(f"【BM25策略】关键词检索：{query}，取top{top_k}")
        return [f"bm25_doc_{i}" for i in range(top_k)]

# 3. 具体策略2：稠密向量相似度检索
class DenseEmbeddingRetrieve(RetrieveStrategy):
    def search(self, query: str, top_k: int = 5):
        print(f"【稠密向量策略】语义检索：{query}，取top{top_k}")
        return [f"dense_doc_{i}" for i in range(top_k)]

# 4. 具体策略3：BM25+稠密混合RRF检索
class HybridRetrieve(RetrieveStrategy):
    def search(self, query: str, top_k: int = 5):
        print(f"【混合检索策略】BM25+向量RRF融合：{query}，取top{top_k}")
        return [f"hybrid_doc_{i}" for i in range(top_k)]

# 5. 上下文 Context
class RagContext:
    def __init__(self, strategy: RetrieveStrategy):
        self._strategy = strategy

    # 动态切换策略
    def set_strategy(self, strategy: RetrieveStrategy):
        self._strategy = strategy

    # 对外统一执行方法
    def execute_search(self, query: str, top_k: int = 5):
        return self._strategy.search(query, top_k)


# ========= 使用示例 =========
if __name__ == "__main__":
    # 初始化上下文，默认混合检索
    ctx = RagContext(HybridRetrieve())
    res = ctx.execute_search("物流丢件退款", top_k=3)
    print("结果：", res, "\n")

    # 运行时切换为纯BM25策略
    ctx.set_strategy(BM25Retrieve())
    res = ctx.execute_search("订单号123456")
    print("结果：", res, "\n")

    # 切换稠密向量策略
    ctx.set_strategy(DenseEmbeddingRetrieve())
    res = ctx.execute_search("商品收到破损怎么办")
    print("结果：", res)
