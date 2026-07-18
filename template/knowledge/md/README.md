# 知识库评估文档集

本目录为 RAG 评估准备的知识库文档（Markdown）。上传时按 `doc_type` 分类，
与 `template/06.3_知识库设计.md` 的文档类型约定一致：`faq / policy / product / help`。

## 文档清单

| 文件名 | doc_type | 主题 | 关键事实点（eval 金标） |
|---|---|---|---|
| `refund_policy.md` | policy | 退款政策 | 七天无理由退货退款 / 原路退回 / 到账时间以支付渠道为准（1-3 或 3-7 工作日） |
| `after_sale.md` | policy | 售后与退换货流程 | 退换货 5 步流程 / 质量问题免运费 / 质保一年（Pro 整机一年、主要部件两年） |
| `logistics_shipping.md` | policy | 物流配送规则 | 满 99 包邮 / 基础运费 8 元 / 跨省 3-5 天 / 物流停滞 72h 催查 |
| `order_faq.md` | faq | 订单常见问题 | 修改地址（未发货前）/ 取消订单状态区分 / 订单状态说明 |
| `invoice_rule.md` | policy | 发票规则 | 电子普票 / 增值专票（需税号）/ 已发货或已完成才可开票 |
| `product_robot_pro.md` | product | 智能客服机器人 Pro | 售价 1999 / 50 路并发 / 整机一年质保 |
| `product_kb_pack.md` | product | 知识库增强包 | 售价 399 / 依赖 Pro 版 / 虚拟服务激活后不支持无理由退款 |
| `membership_faq.md` | faq | 会员与账户 FAQ | 三档会员 / 转人工创建服务单 / 优惠不折现 |

## 设计要点（便于评估）

- **覆盖 RAG 触发场景**：退款咨询（`after_sale_refund.consult_policy`）、FAQ、售后规则——
  与 `06.3_知识库设计.md` 第 8 节「检索触发策略」对齐；不覆盖订单 / 物流实时状态
  （那些走工具调用，不进知识库）。
- **包含答案评测期望事实**：`refund_policy.md` 显式包含「七天无理由退货退款 / 原路退回 /
  到账时间以支付渠道为准」，与 `eval/answer` 的 `must_contain` 对齐，便于验证检索召回质量。
- **结构利于切块**：每篇按 `#` 主标题 + `##` 小节切分，单块聚焦单一主题，契合
  `Chunker.chunk_markdown` 的标题切块策略。
- **难度梯度**：既有强关键词命中（如「七天无理由」「满 99 包邮」），也有需语义召回的
  口语化问法（如「钱什么时候退回来」「货到哪了」），用于检验 BM25 + 向量双路混合检索。

## 上传方式

通过 `POST /knowledge/upload` 上传（`.md` 已被前端允许），每个文件设置对应 `doc_type`。
评估时建议全部上传后再跑 `eval/rag` 的检索评测。
