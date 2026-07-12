# 意图识别单点评估报告（规则 + LLM 兜底）

## 总体结果
- 样本总数：1000
- 命中：965
- 准确率：96.50%
- 路由分布：
  - 规则命中：670 条
  - 未识别（走兜底）：1 条
  - LLM 兜底：261 条
  - 上下文跟进：68 条

## 按主意图
- `after_sale_refund`: 448/448 = 100.00%
- `complaint`: 23/23 = 100.00%
- `handoff_service`: 11/11 = 100.00%
- `logistics`: 229/263 = 87.07%
- `order_query`: 222/223 = 99.55%
- `unrecognize`: 28/28 = 100.00%
- `unsupported_biz`: 4/4 = 100.00%

## 未命中样本（前 50 条）
- `case_0035`: `我想物流更新很慢，单号D7721`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0129`: `单号C3090，我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0145`: `单号D7721，我想物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0156`: `我想物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0159`: `单号A1001，请问我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0201`: `麻烦我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0204`: `我的东西发出来没有，单号E4455`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0206`: `单号C3090，我想物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0345`: `我的东西发出来没有，单号B6688`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0355`: `请问我的东西发出来没有，单号E4455`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0371`: `单号A1001，麻烦物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0384`: `单号D7721，请问我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0419`: `麻烦查一下我买的`  expected `order_query/order_query.query_status`  actual `unrecognize/unrecognize.unknown`（路由：未识别（走兜底））
- `case_0467`: `单号E4455，请问买的东西一直没动静`  expected `logistics/logistics.not_received`  actual `logistics/logistics.delayed`（路由：LLM 兜底）
- `case_0478`: `单号B6688，麻烦我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0484`: `麻烦我的东西发出来没有，单号D7721`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0489`: `我想物流更新很慢，单号B6688`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0509`: `请问买的东西一直没动静，单号C3090`  expected `logistics/logistics.not_received`  actual `logistics/logistics.delayed`（路由：LLM 兜底）
- `case_0558`: `单号E4455，麻烦物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0560`: `物流更新很慢，单号E4455`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0570`: `单号D7721，我想我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0574`: `单号C3090，我想我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0611`: `我想我的东西发出来没有，单号E4455`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0613`: `麻烦我的东西发出来没有，单号C3090`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0629`: `请问买的东西一直没动静，单号B6688`  expected `logistics/logistics.not_received`  actual `logistics/logistics.delayed`（路由：LLM 兜底）
- `case_0640`: `麻烦物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0662`: `单号D7721，买的东西一直没动静`  expected `logistics/logistics.not_received`  actual `logistics/logistics.delayed`（路由：LLM 兜底）
- `case_0765`: `请问我的东西发出来没有`  expected `logistics/logistics.not_received`  actual `order_query/order_query.query_status`（路由：LLM 兜底）
- `case_0787`: `我想物流更新很慢，单号C3090`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0856`: `单号B6688，我想物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0896`: `麻烦买的东西一直没动静`  expected `logistics/logistics.not_received`  actual `logistics/logistics.delayed`（路由：LLM 兜底）
- `case_0913`: `物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0918`: `单号B6688，麻烦物流更新很慢`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
- `case_0985`: `单号C3090，麻烦买的东西一直没动静`  expected `logistics/logistics.not_received`  actual `logistics/logistics.delayed`（路由：LLM 兜底）
- `case_0986`: `我想物流更新很慢，单号E4455`  expected `logistics/logistics.delayed`  actual `logistics/logistics.not_received`（路由：规则命中）
