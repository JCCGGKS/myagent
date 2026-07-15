"""RAG 检索评测测试集生成器（白盒检索层）。

基于 ``template/knowledge/md/`` 下结构化知识文档构造带金标（ground-truth）的
检索评测集 ``rag_eval_cases.json``。每条 case 包含一个用户问法 + 期望命中的文档
+ 必含事实点（must_contain）。

设计要点：
- 金标事实点（must_contain）手工对齐自各 md 知识文件中的关键陈述，覆盖 md/ 下
  全部 8 个文件（退款/售后/物流/订单FAQ/发票/产品×2/会员）；
- 每个文件构造多条 query，难度梯度兼顾「强关键词命中」与「需语义召回的口语化问法」，
  用于检验 BM25 + 向量双路混合检索；
- 跨文件存在的事实冲突（如退款时效：md/refund_policy.md 写「以支付渠道为准
  1-3 或 3-7 工作日」，md/product 文档写「整机一年质保」等）作为真实语料噪声，
  考验检索精确率；
- 与 eval/eval.md 的分层评估对齐：本集只评「检索召回质量（Recall@k）」，不评
  LLM 生成（Faithfulness / Answer Relevance 已由 eval/answer 覆盖）。

用法：
  python3 eval/rag/gen_cases.py            # 生成（覆盖）rag_eval_cases.json
  python3 eval/rag/gen_cases.py --count N  # 每文件目标 query 数（默认 3）
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 知识库根目录（相对仓库根）
KNOWLEDGE_DIR = ROOT / "template" / "knowledge"

# 一条 doc 规格：(相对路径, doc_type, [金标事实点], [query 变体])
# 金标事实点必须为文档中的「逐字子串」（substring），否则 Recall@k 的子串判定会
# 失真；每个事实点对应文档中一个可被检索命中的片段。
# query 变体混合：关键词命中型 + 语义/口语化型
CASES = [
    (
        "md/refund_policy.md", "policy",
        ["七天无理由退货退款", "退款将原路退回至原支付账户", "到账时间以支付渠道为准"],
        ["七天无理由怎么退款", "钱什么时候退回来", "退款是原路返回到付款账户吗"],
    ),
    (
        "md/after_sale.md", "policy",
        ["标准退换货流程", "质量问题退换货的往返运费由商家承担", "整机一年质保，主要部件两年"],
        ["退换货具体怎么操作", "质量问题的退货运费谁出", "智能客服机器人 Pro 保修多久"],
    ),
    (
        "md/logistics_shipping.md", "policy",
        ["订单实付满 99 元包邮", "基础运费 8 元", "跨省：3-5 天", "物流停滞超过 72 小时未更新"],
        ["下单满多少包邮", "寄快递基础运费怎么算", "我的快递好几天没动了怎么办"],
    ),
    (
        "md/order_faq.md", "faq",
        ["未发货", "修改地址", "已发货", "不支持直接取消"],
        ["想改一下收货地址", "怎么取消还没付款的订单", "订单显示已发货是什么意思"],
    ),
    (
        "md/invoice_rule.md", "policy",
        ["电子普通发票", "增值税专用发票", "企业税号", "已发货", "已完成", "方可申请发票"],
        ["怎么开发票", "开增值税专用发票需要什么信息", "还没发货能先开发票吗"],
    ),
    (
        "md/product_robot_pro.md", "product",
        ["售价 1999 元", "50 路并发", "整机一年质保，主要部件两年"],
        ["智能客服机器人 Pro 多少钱", "这个机器人能同时接多少路会话", "Pro 版保修期多长"],
    ),
    (
        "md/product_kb_pack.md", "product",
        ["售价 399 元", "知识库增强包依赖智能客服机器人 Pro 使用", "一经激活不支持无理由退款"],
        ["知识库增强包价格", "增强包要配合什么才能用", "买了增强包还能退吗"],
    ),
    (
        "md/membership_faq.md", "faq",
        ["普通会员、银卡、金卡三档", "创建服务单并接入人工客服", "优惠不折现、不补发"],
        ["会员分几档", "怎么联系人工客服", "退款后优惠券会退给我吗"],
    ),
]


def generate(per_doc: int = 3) -> list[dict]:
    random.seed(20240712)
    cases: list[dict] = []
    for doc, doc_type, facts, queries in CASES:
        picked = queries if len(queries) <= per_doc else random.sample(queries, per_doc)
        for q in picked:
            cases.append({
                "expected_doc": doc,
                "doc_type": doc_type,
                "must_contain": facts,
                "query": q,
            })
    # 赋唯一 id 并打散
    random.shuffle(cases)
    for i, c in enumerate(cases, 1):
        c["id"] = f"rag_{i:04d}"
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 RAG 检索评测测试集")
    parser.add_argument("--count", type=int, default=3, help="每文件目标 query 数（默认 3）")
    args = parser.parse_args()

    cases = generate(per_doc=args.count)

    out_path = Path(__file__).resolve().parent / "rag_eval_cases.json"
    backup = out_path.with_suffix(".json.bak")
    if out_path.exists():
        out_path.replace(backup)
        print(f"[BACKUP] 旧测试集已备份到 {backup.name}")

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    from collections import Counter
    by_doc = Counter(c["expected_doc"] for c in cases)
    by_type = Counter(c["doc_type"] for c in cases)
    print(f"[OK] 已生成 {len(cases)} 条 case -> {out_path.name}")
    print("  按文档：")
    for k, v in by_doc.most_common():
        print(f"    - {k}: {v}")
    print("  按 doc_type：")
    for k, v in by_type.most_common():
        print(f"    - {k}: {v}")


if __name__ == "__main__":
    main()
