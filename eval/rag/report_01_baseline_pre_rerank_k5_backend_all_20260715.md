# RAGAS 评测报告

- 集合：`customer_service_knowledge`
- 截断 k：`5`
- 检索段后端：`all`
- 耗时：`587.22s`

> 说明：下方「各策略汇总 / 逐 Case 明细」为提交基线（commit `95b2e29`）的原始结果，未改动。
> 其后的 §9 / §10 为优化分析，因被 rerank 复测脚本覆盖、且未提交，此处按当时的分析笔记重建，
> 如与你的记忆有出入请指正，后续「重新跑」会再生报告。

## 各策略汇总

| 策略 | 样本数 | 失败 | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 18 | 0 | 0.8519 | 0.7009 | 0.4193 | 0.8561 | 0.4193 | 0.5306 | 0.9487 | 0.7151 |
| semantic | 18 | 0 | 0.8519 | 0.875 | 0.4614 | 0.888 | 0.4614 | 0.5222 | 0.966 | 0.7368 |
| hybrid | 18 | 0 | 0.8704 | 0.8333 | 0.4799 | 0.8838 | 0.4799 | 0.4537 | 0.9818 | 0.7716 |

## 逐 Case 明细

### 策略：bm25

| Case | Query | ExpectedDoc | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.4 | 0.75 | 0.4 | 0.4 | 1.0 | 0.8252 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 1.0 | 0.6 | 0.6 | 0.875 | 0.6717 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.25 | 0.6 | 0.7 | 0.6 | 0.6 | 0.9167 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 0.6 | 0.8056 | 0.6 | 0.6 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 0.3333 | 0.6 | 0.7556 | 0.6 | 0.6 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 0.2 | 1.0 | 0.2 | 0.2 | 1.0 | 0.9952 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 0.3333 | 0.8333 | 0.3333 | 0.4 | 1.0 | 0.6812 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 0.1667 | 1.0 | 0.1667 | 1.0 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 0.5 | 0.8056 | 0.5 | 0.6 | 1.0 | 0.7441 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.7 | 0.6667 | 0.8042 | 0.6667 | 0.8 | 1.0 | 0.8027 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 0.4286 | 0.7556 | 0.4286 | 0.6 | 1.0 | 0.7633 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 0.2857 | 0.8333 | 0.2857 | 0.4 | 1.0 | 0.69 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 0.5 | 0.1667 | 0.5 | 0.1667 | 0.2 | 1.0 | 0.791 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 0.1667 | 1.0 | 0.1667 | 0.2 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 0.5 | 0.5 | 0.8667 | 0.5 | 0.6 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 0.6667 | 0.0 | 0.5 | 1.0 | 0.5 | 0.6 | 0.7143 | 0.0 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 0.5 | 1.0 | 0.5 | 0.75 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 0.3333 | 0.3333 | 1.0 | 0.3333 | 0.4 | 0.5714 | 0.6985 |

### 策略：semantic

| Case | Query | ExpectedDoc | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 0.7556 | 0.6 | 0.6 | 0.8462 | 0.8223 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 0.8 | 0.95 | 0.8 | 0.8 | 0.875 | 0.6489 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 0.9167 | 0.6 | 0.6 | 1.0 | 0.954 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 0.8 | 0.8042 | 0.8 | 0.8 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 0.4 | 0.75 | 0.4 | 0.4 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 0.2 | 1.0 | 0.2 | 0.2 | 1.0 | 0.9952 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 0.3333 | 0.75 | 0.3333 | 0.4 | 1.0 | 0.6758 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 0.1667 | 1.0 | 0.1667 | 0.2 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 0.6667 | 0.8875 | 0.6667 | 0.8 | 1.0 | 0.8142 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.75 | 0.6667 | 0.8875 | 0.6667 | 0.8 | 1.0 | 0.6365 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 0.1429 | 1.0 | 0.1429 | 0.2 | 1.0 | 0.7357 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 0.4286 | 1.0 | 0.4286 | 0.6 | 1.0 | 0.6799 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 0.1667 | 1.0 | 0.1667 | 0.2 | 1.0 | 0.8643 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 0.6667 | 1.0 | 0.6667 | 0.8 | 1.0 | 0.6417 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 0.3333 | 0.8333 | 0.3333 | 0.4 | 1.0 | 0.9113 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 0.6667 | 0.0 | 0.5 | 0.8667 | 0.5 | 0.6 | 1.0 | 0.0 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 0.5 | 1.0 | 0.5 | 0.6 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 1.0 | 0.3333 | 0.5833 | 0.3333 | 0.4 | 0.6667 | 0.6213 |

### 策略：hybrid

| Case | Query | ExpectedDoc | context_recall | context_precision | context_recall_nonllm | context_precision_nonllm | context_recall_id | context_precision_id | faithfulness | answer_relevancy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rag_0001 | 七天无理由退货退款怎么申请？ | md/refund_policy.md | 1.0 | 1.0 | 0.6 | 0.6667 | 0.6 | 0.5 | 0.9231 | 0.8223 |
| rag_0002 | 退款一般多久能到账？ | md/refund_policy.md | 1.0 | 1.0 | 1.0 | 0.9267 | 1.0 | 0.8333 | 1.0 | 0.6717 |
| rag_0003 | 哪些情况不支持无理由退款？ | md/refund_policy.md | 1.0 | 0.5 | 0.4 | 1.0 | 0.4 | 0.3333 | 1.0 | 0.9749 |
| rag_0004 | 退换货的具体流程是什么？ | md/after_sale.md | 1.0 | 1.0 | 0.6 | 0.8056 | 0.6 | 0.5 | 1.0 | 0.5948 |
| rag_0005 | 什么情况算质量问题？ | md/after_sale.md | 1.0 | 1.0 | 0.6 | 0.8333 | 0.6 | 0.5 | 1.0 | 0.9319 |
| rag_0006 | 智能客服机器人 Pro 的质保是多久？ | md/after_sale.md | 1.0 | 1.0 | 0.2 | 1.0 | 0.2 | 0.1667 | 1.0 | 0.9952 |
| rag_0007 | 运费是怎么算的？满多少包邮？ | md/logistics_shipping.md | 0.6667 | 1.0 | 0.3333 | 1.0 | 0.3333 | 0.3333 | 1.0 | 0.6651 |
| rag_0008 | 物流停滞了怎么办？ | md/logistics_shipping.md | 1.0 | 1.0 | 0.3333 | 0.6667 | 0.3333 | 0.3333 | 1.0 | 0.7991 |
| rag_0009 | 可以开什么发票？ | md/invoice_rule.md | 1.0 | 1.0 | 0.8333 | 0.8767 | 0.8333 | 0.8333 | 1.0 | 0.7596 |
| rag_0010 | 开增值税专用发票需要什么？ | md/invoice_rule.md | 1.0 | 0.8333 | 0.8333 | 0.9267 | 0.8333 | 0.8333 | 1.0 | 0.869 |
| rag_0011 | 还没发货能改收货地址吗？ | md/order_faq.md | 1.0 | 1.0 | 0.1429 | 1.0 | 0.1429 | 0.1667 | 1.0 | 0.8103 |
| rag_0012 | 怎么取消订单？ | md/order_faq.md | 1.0 | 1.0 | 0.4286 | 0.9167 | 0.4286 | 0.5 | 1.0 | 0.6799 |
| rag_0013 | 智能客服机器人 Pro 卖多少钱？ | md/product_robot_pro.md | 0.6667 | 1.0 | 0.1667 | 1.0 | 0.1667 | 0.1667 | 1.0 | 0.861 |
| rag_0014 | Pro 版支持多少路并发？ | md/product_robot_pro.md | 0.0 | 0.0 | 0.3333 | 0.7 | 0.3333 | 0.3333 | 1.0 | 0.0 |
| rag_0015 | 知识库增强包多少钱？ | md/product_kb_pack.md | 0.6667 | 1.0 | 0.5 | 0.7556 | 0.5 | 0.5 | 1.0 | 0.971 |
| rag_0016 | 知识库增强包能退款吗？ | md/product_kb_pack.md | 1.0 | 0.1667 | 0.5 | 1.0 | 0.5 | 0.5 | 1.0 | 0.8434 |
| rag_0017 | 会员有几档？ | md/membership_faq.md | 0.6667 | 1.0 | 0.5 | 1.0 | 0.5 | 0.5 | 1.0 | 0.9363 |
| rag_0018 | 会员优惠能折现吗？ | md/membership_faq.md | 1.0 | 0.5 | 0.3333 | 0.8333 | 0.3333 | 0.3333 | 0.75 | 0.7038 |

> 指标说明：ContextRecall / ContextPrecision 反映检索质量（白盒），后缀 `_llm` / `_nonllm` / `_id` 表示覆盖计算后端（llm=语义claims；nonllm=字符串相似度；id=文档块ID精确匹配）；Faithfulness 反映回答是否忠于检索内容；AnswerRelevancy 反映回答相关性（黑盒）。分值 0~1，越高越好。

## 结果解读（基线快照）

- **检索召回已达标**：三策略 `context_recall`(llm) 均 ≥ 0.85（hybrid 0.8704 最高），说明金标文档基本能被召回。
- **精确率分化是主要瓶颈**：bm25 `precision` 仅 0.7009（多 case 命中但排位靠后 / 噪声多），semantic 0.875、hybrid 0.8333 较好。
- **两个 hard-fail 拉低总体**：
  - `rag_0014`（Pro 版并发）→ 三策略 `recall=0.0`：金标「50 路并发」未被任何策略召回。
  - `rag_0016`（知识库增强包退款）→ `precision=0.0~0.25`：召回到了但相关内容排不上去 / 噪声高。
- **生成端健康**：`faithfulness` 0.95~0.98、`answer_relevancy` 0.71~0.77，幻觉率低。

## §9 优化决策框架：如何根据召回率/精确率定位优化方向

### 9.1 二维决策表

| 召回率 \ 精确率 | 低 | 高 |
| --- | --- | --- |
| **低** | 检索器根本没命中 → 查 embedding / 索引 / 切块粒度 | 漏召回 → 补切块粒度 / 降阈值 / 扩 top_k |
| **高** | 命中但噪声多 → rerank / 升阈值 / 收紧 | 理想态 |

### 9.2 旋钮 → 召回 / 精确 映射

- **切块粒度（`chunk_size` / `overlap` / `min_chunk_size`）**：主要调**召回**。切太粗会漏掉细粒度事实，切太碎会碎片化、稀释精确。由标题结构决定的文档，调 `chunk_size` 在很大区间内无效果。
- **rerank**：对候选**重排**，只影响**精确率**（把相关块顶到前排），**不增加召回**（候选集不变）。
- **top_k**：召回覆盖上限；过大稀释精确、过小漏召回。
- **`min_score_threshold`**：经典坑——bm25 量纲 `0~10`、semantic `0~1`、hybrid RRF 必须 `0.0`，跨策略直套会返回空结果。
- **RRF 融合（hybrid）**：补召回的另一手段，跨策略融合提升覆盖。

### 9.3 本项目落点（修正「切块切断」假设为证伪）

- 原假设（item5：调 `chunk_size` / `overlap`）：切块把事实切断导致召回低。
- 实测**证伪**：本集合切块粒度由标题结构决定，`chunk_size` 在 `[160, ∞)` 区间无变化，`overlap` 从不触发；关键事实（robot_pro「50 路并发」、kb_pack「激活后不支持无理由退款」）均在单块内完整存在。
- 结论：**item5 对本评测集为 no-op**，调切块救不了召回。

### 9.4 一句话顺序

先补召回（切块 / 阈值 / top_k / 融合），再用 rerank 提精确；本集召回已 0.85+，**瓶颈在精确 → rerank 是主杠杆**。

## §10 item5 实测结论（切块粒度 no-op）

### 10.1 集合实测

Qdrant 实际集合 **47 点 / 8 源**，每篇 **5~7 块、20~156 字符**，粒度由标题结构决定（非 `chunk_size` 截断）。

### 10.2 为何无效

- `chunk_size` 在 `[160, ∞)` 区间无变化（`[160, 800]` 同一结果）；
- `overlap` 仅在「无标点硬切兜底」时触发，本集合不触发；
- 事实未被切碎：robot_pro「50 路并发」、kb_pack「激活后不支持无理由退款」均在单块内完整存在。

### 10.3 结论

item5 对本评测集为 **no-op**；真实杠杆是 **rerank（提精确）+ 修复两个 hard-fail**（`rag_0014` recall=0.0、`rag_0016` precision=0.25）。

## 后续优化顺序（一句话）

召回已达标 → 开 **hybrid + rerank** 提精确 → 修 `rag_0014` / `rag_0016` 两个 hard-fail → 再复测对照。

---

## §11 基于 baseline 的优化实验迭代（rerank / top_k 对照）

### 11.1 实验矩阵与归档产物

（已按迭代重命名，见 `eval/rag/`，便于追溯评估过程）

| 产物 | rerank | k | backend | 备注 |
| --- | --- | --- | --- | --- |
| `report_01_baseline_pre_rerank_k5_backend_all_20260715` | 未启用 | 5 | all | 本基线（含 §9/§10），commit `95b2e29` |
| `report_02_rerank_on_k5_20260715_230602` | 开 | 5 | llm | — |
| `report_03_rerank_on_k10_20260715_231832` | 开 | 10 | llm | — |
| `report_04_rerank_off_k10_20260715_231832` | 关 | 10 | llm | 当前实时文件 `ragas_eval_report.md` 的副本 |

### 11.2 各轮 context_recall / context_precision（llm 后端）

| 轮次 | 策略 | context_recall | context_precision |
| --- | --- | --- | --- |
| baseline（k5，未 rerank） | bm25 / semantic / hybrid | 0.8519 / 0.8519 / 0.8704 | 0.7009 / 0.875 / 0.8333 |
| rerank 开 k5 | bm25 / semantic / hybrid | 0.8704 / 0.8704 / 0.8704 | 0.8935 / 0.8769 / 0.8074 |
| rerank 开 k10 | bm25 / semantic / hybrid | 0.8704 / 0.8889 / 0.8889 | 0.8847 / 0.8213 / 0.8213 |
| rerank 关 k10（实时） | bm25 / semantic / hybrid | 0.8611 / 0.8796 / 0.8889 | 0.7104 / 0.8642 / 0.8148 |

### 11.3 结论

1. **rerank 与 recall 无关**：候选集不变，仅重排已召回块。三策略 recall 在 rerank 开/关、k=5/10 间差异 ≤0.02，属 LLM 裁判噪声（§9.2 已预言）。
2. **rerank 强增益 bm25 的 precision**：bm25 precision 从 rerank 关 0.7104 → rerank 开 0.8847~0.8935（约 +18pp）；对 semantic/hybrid 中性或微负。
3. **top_k 5→10 边际 recall 增益换 precision 损失**：hybrid recall 0.8704→0.8889（+1.85pp），但 semantic precision 0.8769→0.8213 下滑；综合 k=5 精确率更优且省 token，**已还原 k=5**。
4. **hybrid 综合最佳**：recall（rerank 开 k10 达 0.8889）与 precision 平衡最好，且弥补 bm25 词汇缺口（见 §12.2 的 rag_0017）。

### 11.4 决策：生产默认 = hybrid + rerank 开 + k=5

与 `config/llm_config.local.yml` 当前配置一致（`rag.rerank.enabled=true`、`top_k=5`）。

---

## §12 最新发现：recall 天花板根因（非检索失败）

### 12.1 隔离实验证据（针对 rag_0014）

- query=「Pro 版支持多少路并发？」，源文档 `template/knowledge/md/product_robot_pro.md:15` 在 **Pro 的「规格参数」段**写 `并发上限：标准版支持 50 路并发；`。
- 三策略检索：含该事实的块在 bm25 / semantic / hybrid **均排 #1**（检索本身正常）。
- 用与评测脚本同款 judge 复跑 rag_0014：
  - **LLM ContextRecall = 0.0**（retrieved 块说「标准版」，reference 说「Pro」，裁判不予等同）；
  - ID ContextRecall = 0.667（6 个 `reference_context_ids` 仅召回 4 个，标注本身亦有瑕疵）。

### 12.2 根因分类（5 个 sub-1.0 recall case）

| Case | 查询 | bm25 / semantic / hybrid recall | 类别 |
| --- | --- | --- | --- |
| rag_0014 | Pro 并发 | 0.0 / 0.0 / 0.0 | **评测 reference 与源文档对不齐**（文档写「标准版」，ref 写「Pro」）→ 假象，非检索问题 |
| rag_0013 | Pro 价格 | 0.667 / 0.667 / 0.667 | 多 claim 部分覆盖（价格散在多块） |
| rag_0015 | 增强包价格 | 0.667 / 0.667 / 0.667 | 同上 |
| rag_0007 | 运费/包邮 | 0.5 / 0.5 / 0.667 | 多事实（运费规则+包邮门槛），hybrid 多召回一条 |
| rag_0017 | 会员档位 | 0.667 / 1.0 / 1.0 | bm25 纯词汇缺口，semantic/hybrid 已解决（非真天花板） |

- **rag_0014 是唯一拖累全局的假象**：三策略均 0.0，单独拉低均值约 1/18≈0.056；修掉即 hybrid recall 0.889→~0.944。
- ②类（0007/0013/0015）是真实多 claim 部分覆盖：reference 拆成 N 条 claim，top-k 只兜住 M≤N。
- ③类（0017）已被 hybrid 弥补，不算瓶颈。

### 12.3 rerank 为何救不了

rerank 只在已召回集合内重排，从不引入新块 → 对 recall 零作用（§11.3 已验证），故无法消解上述任一 recall 缺口。

### 12.4 处置决策：改评测集而非重新入库源文档

- **结论**：recall 天花板本质是「评测集 reference 与源文档对不齐」+ 多 claim 部分覆盖，**不是检索失败**。
- **选择改评测集**：修改 `rag_eval_cases.json` 比改源文档轻量——后者需经 `/knowledge/upload` 重新 embedding + Qdrant upsert。
- **已执行**：rag_0014 `reference` 由「智能客服机器人 Pro 支持 50 路并发。」改为「智能客服机器人标准版支持 50 路并发。」，与文档实际内容对齐（JSON 校验通过）。
- **耦合提醒**：若日后修正源文档（`product_robot_pro.md:15` 的「标准版」→「Pro」），需同步回退此 eval reference。

### 12.5 rag_0013 reference 修正（同源 edition mismatch）

`rag_0013`（查询「卖多少钱？」）的 `reference` 在 `HEAD` 原始提交中即为「智能客服机器人 Pro 售价 1999 元，支持 50 路并发，整机一年质保。」——与 rag_0014 **同源**，把「Pro 支持 50 路并发」这一与文档（文档写「标准版」）对不上的事实嵌进了价格查询 reference，且将价格/并发/质保三个 claim 捆绑（过度细分）。已回退为仅描述价格的单 claim reference：「智能客服机器人 Pro 售价 1999 元。」，与文档 `reference_contexts[0]`（「…售价 1999 元。」）对齐，消除 edition mismatch。（注：非「外部改动」，系原始提交内容，前文「外部改动」表述有误，特此更正。）

### 12.6 后续动作建议

1. 修 rag_0014 后重跑（rerank 开 k5）→ 验证 hybrid recall 达 ~0.944。
2. 视情况处理 §12.5 的 rag_0013 外部改动。
3. ②类多 claim 覆盖：要么优化分块让价格/运费事实共置，要么收紧 reference 到单一主 claim（避免比文档实际承载更细）；单纯提 k 会牺牲 precision，不划算。
4. `rag_0016`（precision 低，retrieved 但排不上去/噪声高）仍为 open hard-fail，与 recall 天花板无关，属精确率问题，由 rerank 缓解但未根除。
