# RAGAS 评测报告

- 集合：`customer_service_knowledge`
- 截断 k：`5`
- 检索段后端：`llm`
- 耗时：`547.97s`

## 各策略汇总

| 策略 | 样本数 | 失败 | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 18 | 0 | 0.8704 | 0.8935 | 0.9841 | 0.7424 |
| semantic | 18 | 0 | 0.8704 | 0.8769 | 0.9921 | 0.7621 |
| hybrid | 18 | 0 | 0.8704 | 0.8074 | 1.0 | 0.7552 |

## 逐 Case 明细

### 策略：bm25

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.8252 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.6565 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.7828 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 0.8333 | 1.0 | 0.9952 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 1.0 | 0.6802 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.5884 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.8142 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.6715 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.7616 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.749 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 1.0 | 0.8037 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 1.0 | 0.9113 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.25 | 1.0 | 0.9182 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 1.0 | 0.9362 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 0.7143 | 0.7 |

### 策略：semantic

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.8223 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.6775 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.7 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 0.8333 | 1.0 | 0.8426 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 1.0 | 0.6812 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.7428 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.6715 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.7398 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.8079 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 1.0 | 0.9698 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 1.0 | 0.9113 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.25 | 1.0 | 0.9182 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 0.8571 | 0.6954 |

### 策略：hybrid

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.8252 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.6717 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.7 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 0.8333 | 1.0 | 0.8426 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 0.0 | 1.0 | 0.6758 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.7428 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.7475 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.7831 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 0.75 | 1.0 | 0.6799 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 1.0 | 0.8151 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.25 | 1.0 | 0.9182 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 1.0 | 0.6842 |

> 指标说明：ContextRecall / ContextPrecision 反映检索质量（白盒），后缀 `_llm` / `_nonllm` / `_id` 表示覆盖计算后端（llm=语义claims；nonllm=字符串相似度；id=文档块ID精确匹配）；Faithfulness 反映回答是否忠于检索内容；AnswerRelevancy 反映回答相关性（黑盒）。分值 0~1，越高越好。
