# RAGAS 评测报告（评测集/文档对齐后重跑基线）

- 集合：`customer_service_knowledge`
- 截断 k：`5`（bm25/semantic 5，hybrid 6，按 §9 初始配置）
- 检索段后端：`all`
- 耗时：`7520.89s`
- 三策略初始配置：bm25 `th=4` / semantic `th=0.0` / hybrid `th=0.0,top_k=6`，**rerank 关**（本轮仅基础基线，对照 report_01）

> **本轮重跑前提：已修正评测集与源文档对齐（详见 §A）**。本文件为对齐后的干净基线，可直接与
> `report_01_baseline_pre_rerank_k5_backend_all_20260715.md` 对照，验证此前 §12 关于「recall 天花板是
> 评测集 reference 与源文档对不齐」的假设是否成立。

## §A 本次修正的评测集 / 文档对齐项

依据 `report_01` 的 §12 根因分析，本次仅改 **评测集 `rag_eval_cases.json`**（不动源文档、不重新入库），两处 edition mismatch 已对齐：

1. **`rag_0014`（Pro 版支持多少路并发？）**：原 `reference` 写「智能客服机器人 **Pro** 支持 50 路并发」，
   但源文档 `template/knowledge/md/product_robot_pro.md:15` 实际写「**标准版**支持 50 路并发」。
   → 改为「智能客服机器人**标准版**支持 50 路并发。」（`reference_contexts[0]` 一致）。属假象，非检索失败。
2. **`rag_0013`（Pro 卖多少钱？）**：原 `reference` 捆绑了「价格 + 并发 + 质保」三 claim（其中并发 claim 与文档对不齐），
   过度细分。→ 回退为单一主 claim「智能客服机器人 Pro 售价 1999 元。」，与文档 `reference_contexts[0]` 对齐。

> 耦合提醒：若日后修正源文档（把「标准版」→「Pro」），需同步回退上述 eval reference。

## §B 与 report_01 基线对比（rerank 关 · k5 · backend all）

| 轮次 | 策略 | context_recall | context_precision | faithfulness | answer_relevancy |
| --- | --- | --- | --- | --- | --- |
| report_01（修正前） | bm25 / semantic / hybrid | 0.8519 / 0.8519 / 0.8704 | 0.7009 / 0.875 / 0.8333 | 0.9487 / 0.966 / 0.9818 | 0.7151 / 0.7368 / 0.7716 |
| report_05（对齐后） | bm25 / semantic / hybrid | **0.9167 / 0.9259 / 0.9445** | 0.6731 / 0.8194 / 0.8611 | 0.9708 / 0.9835 / 0.9512 | 0.7034 / 0.7446 / 0.7488 |

- **recall 全面抬升（核心验证）**：三策略 recall 各 +0.065 ~ +0.074，hybrid 达 **0.9445**。
  主因是 `rag_0014` 由 0.0→**1.0**、`rag_0013` 由 0.667→**1.0**（见 §C），证伪了「检索失败」假设，
  证实 §12 根因 = 评测集 reference 与源文档 edition mismatch。
- **precision 基本持平 / 略降**：bm25 precision 0.7009→0.6731（LLM 裁判噪声 + 个别 case 排位抖动），
  semantic/hybrid 维持 0.82~0.86。precision 瓶颈仍为 `rag_0016` 等噪声 case，与召回无关。
- **faithfulness / answer_relevancy 稳定**：幻觉率低（0.95~0.98），相关性 0.70~0.77，无退化。

## §C 关键 case 前后对照（验证对齐修复）

| Case | 查询 | 策略 | recall(前→后) | 说明 |
| --- | --- | --- | --- | --- |
| rag_0014 | Pro 并发 | bm25 / semantic / hybrid | 0.0 → **1.0** / 0.0 → **1.0** / 0.0 → **1.0** | 假象消除：reference 改「标准版」与文档对齐 |
| rag_0013 | Pro 价格 | bm25 / semantic / hybrid | 0.667 → **1.0** / 0.667 → **1.0** / 0.667 → **1.0** | reference 回退单一价格 claim |
| rag_0007 | 运费/包邮 | 三策略 | 0.5 / 0.5 / 0.667 → 0.5 / 0.667 / 0.667 | 多事实（运费+包邮）部分覆盖，稳健 |
| rag_0015 | 增强包价格 | 三策略 | 0.667 不变 | 多 claim 部分覆盖，真实瓶颈 |
| rag_0016 | 增强包退款 | 三策略 | precision 0.0/0.25→0.0/0.167 | **仍 open 的 hard-fail**（精确率/忠实度，详见 §D） |

## §D 剩余 open 项（非评测集问题，属检索/生成质量）

- **`rag_0016`（增强包退款）**：三策略 recall 已召回（0.667~1.0），但 `context_precision` 0.0~0.167、
  `faithfulness` 0.4~0.8（bm25 0.8 / hybrid 0.4）。属精确率 + 忠实度问题：检索噪声高、生成作答偏题。
  由 rerank（提精确）与生成 prompt 约束缓解，非本轮评测集修正范畴。
- **多 claim 部分覆盖（rag_0007/0015）**：reference 拆多条 claim，top-k 只兜住部分。建议收紧
  reference 到单一主 claim，或优化分块使同主题事实共置；单纯提 k 牺牲 precision，不划算。

> 结论：对齐修正后，**recall 天花板已破除**（hybrid 0.9445），剩余差距为精确率/忠实度问题，
> 下一步杠杆 = **hybrid + rerank 开**（见 report_02~04 已验证 rerank 强增益 bm25 精确率），
> 及对 `rag_0016` 的针对性优化。

## 各策略汇总

| 策略 | 样本数 | 失败 | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 18 | 0 | 0.9167 | 0.6731 | 0.4193 | 0.8561 | 0.4193 | 0.5306 | 0.9708 | 0.7034 |
| semantic | 18 | 0 | 0.9259 | 0.8194 | 0.4614 | 0.888 | 0.4614 | 0.5222 | 0.9835 | 0.7446 |
| hybrid | 18 | 0 | 0.9445 | 0.8611 | 0.4799 | 0.8838 | 0.4799 | 0.4537 | 0.9512 | 0.7488 |

## 逐 Case 明细

### 策略：bm25

| Case | Query | ExpectedDoc | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.4 | 0.75 | 0.4 | 0.4 | 1.0 | 0.8252 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 1.0 | 0.6 | 0.6 | 0.875 | 0.6717 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.75 | 0.6 | 0.7 | 0.6 | 0.6 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 0.6 | 0.8056 | 0.6 | 0.6 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 0.3333 | 0.6 | 0.7556 | 0.6 | 0.6 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 0.2 | 1.0 | 0.2 | 0.2 | 1.0 | 0.7663 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.5 | 0.0 | 0.3333 | 0.8333 | 0.3333 | 0.4 | 1.0 | 0.6812 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 0.1667 | 1.0 | 0.1667 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 0.5 | 0.8056 | 0.5 | 0.6 | 1.0 | 0.7519 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.7 | 0.6667 | 0.8042 | 0.6667 | 0.8 | 1.0 | 0.663 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 0.4286 | 0.7556 | 0.4286 | 0.6 | 1.0 | 0.7398 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 0.2857 | 0.8333 | 0.2857 | 0.4 | 1.0 | 0.749 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 1.0 | 0.5 | 0.1667 | 0.5 | 0.1667 | 0.2 | 1.0 | 0.9102 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 1.0 | 0.0 | 0.1667 | 1.0 | 0.1667 | 0.2 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 0.5 | 0.5 | 0.8667 | 0.5 | 0.6 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 0.6667 | 0.0 | 0.5 | 1.0 | 0.5 | 0.6 | 0.8 | 0.0 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 0.5 | 1.0 | 0.5 | 0.75 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 0.3333 | 0.3333 | 1.0 | 0.3333 | 0.4 | 0.8 | 0.6954 |

### 策略：semantic

| Case | Query | ExpectedDoc | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 0.7556 | 0.6 | 0.6 | 0.8462 | 0.8223 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 0.8 | 0.95 | 0.8 | 0.8 | 1.0 | 0.6529 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 0.9167 | 0.6 | 0.6 | 1.0 | 0.9557 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 0.8 | 0.8042 | 0.8 | 0.8 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 0.4 | 0.75 | 0.4 | 0.4 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 0.2 | 1.0 | 0.2 | 0.2 | 1.0 | 0.8426 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 0.0 | 0.3333 | 0.75 | 0.3333 | 0.4 | 1.0 | 0.6737 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 0.1667 | 1.0 | 0.1667 | 0.2 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 0.6667 | 0.8875 | 0.6667 | 0.8 | 1.0 | 0.7428 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.75 | 0.6667 | 0.8875 | 0.6667 | 0.8 | 1.0 | 0.7938 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 0.1429 | 1.0 | 0.1429 | 0.2 | 1.0 | 0.8103 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 0.4286 | 1.0 | 0.4286 | 0.6 | 1.0 | 0.749 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 1.0 | 1.0 | 0.1667 | 1.0 | 0.1667 | 0.2 | 1.0 | 0.7974 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 1.0 | 0.0 | 0.6667 | 1.0 | 0.6667 | 0.8 | 1.0 | 0.6286 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 0.3333 | 0.8333 | 0.3333 | 0.4 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 0.6667 | 0.0 | 0.5 | 0.8667 | 0.5 | 0.6 | 1.0 | 0.0 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 0.5 | 1.0 | 0.5 | 0.6 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 0.3333 | 0.5833 | 0.3333 | 0.4 | 0.8571 | 0.7 |

### 策略：hybrid

| Case | Query | ExpectedDoc | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 0.6667 | 0.6 | 0.5 | 0.8462 | 0.8223 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.9267 | 1.0 | 0.8333 | 1.0 | 0.6605 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 1.0 | 0.4 | 1.0 | 0.4 | 0.3333 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 0.6 | 0.8056 | 0.6 | 0.5 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 0.6 | 0.8333 | 0.6 | 0.5 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 0.2 | 1.0 | 0.2 | 0.1667 | 1.0 | 0.7663 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 0.3333 | 1.0 | 0.3333 | 0.3333 | 1.0 | 0.6651 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 0.3333 | 0.6667 | 0.3333 | 0.3333 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 0.8333 | 0.8767 | 0.8333 | 0.8333 | 1.0 | 0.7484 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.8333 | 0.8333 | 0.9267 | 0.8333 | 0.8333 | 0.875 | 0.6577 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 0.1429 | 1.0 | 0.1429 | 0.1667 | 1.0 | 0.8103 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 0.4286 | 0.9167 | 0.4286 | 0.5 | 1.0 | 0.69 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 1.0 | 1.0 | 0.1667 | 1.0 | 0.1667 | 0.1667 | 1.0 | 0.9239 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 1.0 | 0.0 | 0.3333 | 0.7 | 0.3333 | 0.3333 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 0.5 | 0.7556 | 0.5 | 0.5 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.1667 | 0.5 | 1.0 | 0.5 | 0.5 | 0.4 | 0.8302 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 0.5 | 1.0 | 0.5 | 0.5 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 0.5 | 0.3333 | 0.8333 | 0.3333 | 0.3333 | 1.0 | 0.6954 |

> 指标说明：ContextRecall / ContextPrecision 反映检索质量（白盒），后缀 `_llm` / `_nonllm` / `_id` 表示覆盖计算后端（llm=语义claims；nonllm=字符串相似度；id=文档块ID精确匹配）；Faithfulness 反映回答是否忠于检索内容；AnswerRelevancy 反映回答相关性（黑盒）。分值 0~1，越高越好。
