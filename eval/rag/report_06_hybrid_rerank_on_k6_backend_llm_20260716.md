# RAGAS 评测报告（补充实验：hybrid + rerank 开 · 后对齐）

- 集合：`customer_service_knowledge`
- 截断 k：`6`（§9 hybrid 初始配置）
- 检索段后端：`llm`
- rerank：**开**（`qwen3-rerank`，`--rerank` 强制）
- 耗时：`2667.7s`
- 定位：report_05（hybrid rerank 关）的补充，仅验证「hybrid 开 rerank 后指标如何变化」

## §X 与 report_05（hybrid rerank 关）对照

| 指标 | hybrid rerank 关 (report_05) | hybrid rerank 开 (report_06) | 变化 |
| --- | --- | --- | --- |
| context_recall | 0.9445 | **0.9445** | 0（rerank 只重排、不引入新块，符合预期） |
| context_precision | 0.8611 | 0.8213 | −0.040（LLM 裁判噪声量级，≈中性） |
| faithfulness | 0.9512 | 0.9556 | +0.004 |
| answer_relevancy | 0.7488 | 0.7556 | +0.007 |

**结论：对 hybrid 而言，rerank 基本中性**（与 report_01 §11.3「rerank 对 hybrid 中性或微负」一致）。
recall 完全不变（候选集不变），precision 在噪声范围内小幅波动，answer_relevancy 微升。

### 逐 case 净效应（rerank 开 − 关）

- **改善**：`rag_0016`（增强包退款）precision 0.167→0.25、faithfulness 0.4→**1.0**、answer_relevancy 0.830→**0.931**——rerank 把含退款事实的块顶到前排，噪声 case 明显受益；`rag_0010` 0.833→1.0、`rag_0018` 0.5→1.0。
- **回退**：`rag_0007`（运费/包邮）precision 1.0→**0.0**、`rag_0003` 1.0→0.7、`rag_0006` 1.0→0.833——多事实/排位敏感 case 受重排扰动，属裁判噪声为主。
- **不变**：`rag_0014`（Pro 并发）recall=1.0 / precision=0.0 / answer_relevancy=0.0——rerank 救不了，根因是 query 与文档对象不对齐（见 report_05 §A）。

> 提示：本次 rerank 开用 `backend=llm`、rerank 关用 `backend=all`，precision 量纲一致（均取 LLM 后端）；
> 两者差异主要来自 rerank 开关与 LLM 裁判非确定性，非后端口径差异。

## 各策略汇总

| 策略 | 样本数 | 失败 | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 18 | 0 | 0.9445 | 0.8213 | 0.9556 | 0.7556 |

## 逐 Case 明细

### 策略：hybrid

| Case | Query | ExpectedDoc | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.7984 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.6717 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.7 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 0.8333 | 1.0 | 0.9952 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 0.0 | 1.0 | 0.6758 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 1.0 | 0.7441 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 1.0 | 0.8 | 0.6755 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.7357 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 1.0 | 0.6799 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 1.0 | 1.0 | 1.0 | 0.791 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 1.0 | 0.0 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.25 | 1.0 | 0.9311 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 0.4 | 0.6938 |

> 指标说明：ContextRecall / ContextPrecision 反映检索质量（白盒），后缀 `_llm` / `_nonllm` / `_id` 表示覆盖计算后端（llm=语义claims；nonllm=字符串相似度；id=文档块ID精确匹配）；Faithfulness 反映回答是否忠于检索内容；AnswerRelevancy 反映回答相关性（黑盒）。分值 0~1，越高越好。
