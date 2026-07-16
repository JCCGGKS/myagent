# RAGAS 评测报告

- 集合：`customer_service_knowledge`
- 截断 k：`10`
- 检索段后端：`llm`
- 耗时：`691.87s`

## 各策略汇总

| 策略 | 样本数 | 失败 | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 18 | 0 | 0.8611 | 0.7104 | 0.9727 | 0.7736 |
| semantic | 18 | 0 | 0.8796 | 0.8642 | 0.9715 | 0.7692 |
| hybrid | 18 | 0 | 0.8889 | 0.8148 | 0.9861 | 0.7401 |

## 逐 Case 明细

### 策略：bm25

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.7833 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 0.875 | 0.6717 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.25 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.6036 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 0.3333 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.7663 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.5 | 1.0 | 1.0 | 0.6812 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.7484 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.7 | 1.0 | 0.675 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.7847 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.69 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 0.5 | 1.0 | 0.8037 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 1.0 | 0.605 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 0.5 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.1714 | 0.8333 | 0.8001 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 0.3333 | 0.8 | 0.6985 |

### 策略：semantic

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.9375 | 0.7984 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.6489 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.954 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 0.6429 | 1.0 | 0.7663 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.5 | 1.0 | 1.0 | 0.6694 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.6083 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.75 | 1.0 | 0.6644 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.8103 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.69 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 1.0 | 0.8037 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 1.0 | 0.8173 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 1.0 | 0.8517 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.1625 | 0.8 | 0.8001 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 1.0 | 1.0 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 0.75 | 0.7 |

### 策略：hybrid

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.8045 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.6605 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.5 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 0.625 | 1.0 | 0.9952 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 1.0 | 0.6802 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.5574 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.8333 | 0.75 | 0.6838 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.8103 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.749 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 1.0 | 0.7974 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 1.0 | 0.8517 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.2083 | 1.0 | 0.8001 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 1.0 | 1.0 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 0.5 | 1.0 | 0.6954 |

> 指标说明：ContextRecall / ContextPrecision 反映检索质量（白盒），后缀 `_llm` / `_nonllm` / `_id` 表示覆盖计算后端（llm=语义claims；nonllm=字符串相似度；id=文档块ID精确匹配）；Faithfulness 反映回答是否忠于检索内容；AnswerRelevancy 反映回答相关性（黑盒）。分值 0~1，越高越好。
