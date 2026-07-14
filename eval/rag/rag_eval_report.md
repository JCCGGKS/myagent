# RAG 检索质量评估报告（BM25 腿）

- 检索策略：`bm25`（当前 `rag.retrieval_strategy` 配置）
- 入库块数：47（来自 `template/knowledge` 8 篇文档）
- top_k：5；BM25 阈值：5.0
- 用例数：22；无需 embedding / LLM，端到端命中本地 Qdrant

## 一、总体召回

| 指标 | 数值 |
| --- | --- |
| recall@1 | **64.29%** |
| recall@3 | **90.48%** |
| recall@5 | **92.86%** |
| 关键事实总数 / 命中@5 | 42 / 39 |

## 二、按知识文档（类别）

| 文档 | 用例数 | 事实数 | 命中@5 | recall@5 | 未满分用例 |
| --- | --- | --- | --- | --- | --- |
| refund_policy | 4 | 8 | 8 | 100.00% | 0 |
| after_sale | 3 | 6 | 6 | 100.00% | 0 |
| logistics_shipping | 3 | 6 | 6 | 100.00% | 0 |
| order_faq | 2 | 4 | 4 | 100.00% | 0 |
| invoice_rule | 2 | 4 | 3 | 75.00% | 1 |
| membership_faq | 2 | 3 | 3 | 100.00% | 0 |
| product_robot_pro | 3 | 5 | 5 | 100.00% | 0 |
| product_kb_pack | 3 | 6 | 4 | 66.67% | 1 |

## 三、逐用例明细

| id | 文档 | query | 事实数 | 命中@5 | recall@5 | 召回块数 | 首块来源 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rag_001 | refund_policy | 七天无理由退货怎么操作 | 2 | 2 | 100% | 12 | after_sale.md / 售后服务与退换货流程>退换货流程 |
| rag_002 | refund_policy | 退款一般多久能到账 | 2 | 2 | 100% | 11 | refund_policy.md / 退款政策>退款到账时间 |
| rag_003 | refund_policy | 哪些情况不支持无理由退款 | 2 | 2 | 100% | 20 | refund_policy.md / 退款政策>七天无理由退货退款 |
| rag_004 | refund_policy | 退款进度都有哪些状态 | 2 | 2 | 100% | 8 | refund_policy.md / 退款政策>退款进度查询 |
| rag_005 | after_sale | 退货退款的流程是什么 | 2 | 2 | 100% | 16 | after_sale.md / 售后服务与退换货流程>退换货流程 |
| rag_006 | after_sale | 智能客服机器人Pro质保多久 | 2 | 2 | 100% | 11 | after_sale.md / 售后服务与退换货流程>质保与保修 |
| rag_007 | after_sale | 什么情况算质量问题可以退换 | 2 | 2 | 100% | 14 | after_sale.md / 售后服务与退换货流程>退换货流程 |
| rag_008 | logistics_shipping | 订单满多少可以包邮 | 2 | 2 | 100% | 11 | order_faq.md / 订单常见问题（FAQ）>如何取消订单 |
| rag_009 | logistics_shipping | 偏远地区运费怎么算 | 2 | 2 | 100% | 5 | logistics_shipping.md / 物流与配送规则>配送范围 |
| rag_010 | logistics_shipping | 跨省物流一般几天能到 | 2 | 2 | 100% | 5 | logistics_shipping.md / 物流与配送规则>配送时效 |
| rag_011 | order_faq | 怎么修改收货地址 | 2 | 2 | 100% | 6 | order_faq.md / 订单常见问题（FAQ）>如何修改收货地址 |
| rag_012 | order_faq | 已经发货的订单还能取消吗 | 2 | 2 | 100% | 10 | order_faq.md / 订单常见问题（FAQ）>如何取消订单 |
| rag_013 | invoice_rule | 怎么开电子发票 | 2 | 1 | 50% | 7 | invoice_rule.md / 发票规则>发票类型 |
| rag_014 | invoice_rule | 开增值税专用发票需要什么信息 | 2 | 2 | 100% | 9 | invoice_rule.md / 发票规则>发票类型 |
| rag_015 | membership_faq | 金卡会员有什么权益 | 2 | 2 | 100% | 4 | membership_faq.md / 会员与账户常见问题（FAQ）>会员等级与权益 |
| rag_016 | membership_faq | 怎么联系人工客服 | 1 | 1 | 100% | 9 | refund_policy.md / 退款政策>退款到账时间 |
| rag_017 | product_robot_pro | 智能客服机器人Pro多少钱 | 2 | 2 | 100% | 9 | product_kb_pack.md / 产品说明：知识库增强包>与其他产品关系 |
| rag_018 | product_robot_pro | 机器人Pro支持多少路并发 | 1 | 1 | 100% | 14 | after_sale.md / 售后服务与退换货流程>质保与保修 |
| rag_019 | product_robot_pro | 机器人Pro怎么部署 | 2 | 2 | 100% | 6 | after_sale.md / 售后服务与退换货流程>质保与保修 |
| rag_020 | product_kb_pack | 知识库增强包多少钱 | 2 | 2 | 100% | 7 | product_kb_pack.md / 产品说明：知识库增强包>主要功能 |
| rag_021 | product_kb_pack | 知识库增强包能无理由退款吗 | 2 | 0 | 0% | 19 | refund_policy.md / 退款政策>七天无理由退货退款 |
| rag_022 | product_kb_pack | 知识库增强包能单独使用吗 | 2 | 2 | 100% | 13 | product_kb_pack.md / 产品说明：知识库增强包>与其他产品关系 |

## 四、说明与后续

- 本评估仅覆盖 BM25 腿：当前 `embedding.api_key` 为空、策略为 `bm25`。
- 中文按字切分（MVP 分词），口语化同义问法召回依赖字重叠，长尾问法可能漏召。
- 若启用 semantic / hybrid，需先填 `embedding.api_key` 并重新入库稠密向量；
  届时本脚本可扩展为对 semantic / hybrid 策略分别评估（替换 `BM25Strategy`）。