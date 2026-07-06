# 父子意图设计说明

## 1. 什么是父子意图

在客服 Agent 中，意图识别的目标不是“给一句话贴标签”，而是把用户输入路由到一条可执行的处理链路。

单层意图的做法是：

- `faq`
- `query_order`
- `query_logistics`
- `refund_consult`
- `handoff_human`

父子意图的做法是把它拆成两层：

- 父意图（主意图，`main_intent`）
- 子意图（细分意图，`sub_intent`）

例如：

- `order_service` -> `order_service.query_status`
- `logistics_service` -> `logistics_service.query_status`
- `handoff_service` -> `handoff_service.request_human`
- `chitchat` -> `chitchat.greeting`

父意图负责回答一个更大的问题：

> 当前应该进入哪条主处理链路？

子意图负责回答一个更细的问题：

> 进入这条链路后，当前具体要走哪个分支？

---

## 2. 为什么客服场景适合父子意图

### 2.1 单层意图容易膨胀

客服场景天然会不断长出新意图。

例如售后相关就可能出现：

- 退款咨询
- 退款进度查询
- 退货咨询
- 换货咨询
- 商品破损
- 漏发错发
- 投诉升级

如果全部平铺，后端状态机、规则词表、前端调试信息都会越来越难维护。

父子意图把这些细分场景收进一个更大的父类中，例如：

- `after_sales_service`
  - `after_sales_service.refund_consult`
  - `after_sales_service.refund_status`
  - `after_sales_service.return_consult`
  - `after_sales_service.complaint`

这样可以先在父意图级别稳定主链路，再逐步细化子流程。

### 2.2 更符合实际工程分层

在工程实现里，很多能力本来就是按模块划分的：

- FAQ 模块
- 订单模块
- 物流模块
- 售后模块
- 人工客服模块

父意图天然对应“模块边界”，子意图对应“模块内部动作”。

这使得：

- 路由更清晰
- service 设计更自然
- 后续接真实接口更容易扩展

### 2.3 更适合多轮对话

很多用户第一句只表达大方向，不会一次把意图说完整。

例如：

- “我要查订单”
- “我要退款”
- “物流呢”

第一轮其实只够判断父意图，后续再依靠补槽位、澄清问题、工具结果去收敛到子意图。

父子意图结构更适合这种“先粗分，再细分”的过程。

### 2.4 更适合调试和观测

相比只看到一个 `intent=query_order`，双层结构可以更清楚地看出 Agent 的决策：

- `main_intent=order_service`
- `sub_intent=order_service.query_status`

这对排查问题更有帮助：

- 是主链路走错了？
- 还是主链路对，但子分支走错了？

---

## 3. 为什么当前项目选择父子意图

本项目当前已经具备以下能力：

- FAQ
- 订单查询
- 物流查询
- 转人工
- 问候

如果继续沿用单层意图，短期能工作，但后面一旦补这些能力就会开始混乱：

- `refund_consult`
- `query_refund_status`
- `thanks`
- `complaint`
- `invoice_consult`

因此当前阶段切换到父子意图，有几个明确收益。

### 3.1 先稳定主链路，再补细分场景

现在父意图已经确定为：

- `faq`
- `order_service`
- `logistics_service`
- `handoff_service`
- `chitchat`
- `unsupported`

后续增加新能力时，可以优先判断：

1. 这是新增一个父意图，还是已有父意图下新增一个子意图？
2. 是否需要新 service？
3. 是否需要新槽位？

这个决策会更稳定。

### 3.2 保持状态机简单

当前项目是一个 LangGraph + 规则路由的 MVP。

状态机目前主要关心这些事情：

- 当前在哪条主链路
- 是否缺少关键槽位
- 是继续追问，还是执行工具，还是直接回复

这些决策更多依赖父意图，而不是所有细粒度意图。

例如：

- `order_service.*` 大概率都需要订单相关槽位
- `logistics_service.*` 大概率都会走物流模块
- `handoff_service.*` 都会进入转人工逻辑

也就是说，父意图更接近“状态机的骨架”，子意图更接近“骨架上的分支”。

### 3.3 更便于前后端协同

前端调试面板现在会直接展示：

- `main_intent`
- `sub_intent`
- `stage`
- `slots`
- `missing_slots`

对于开发调试来说，这比单个 `intent` 更容易理解。

例如：

- 用户看到的是“查订单”
- 前端能看到的是 `order_service / order_service.query_status`
- 后端知道应该走订单模块

---

## 4. 当前项目中的父子意图映射

当前项目先收敛为以下结构。

### 4.1 FAQ

- 父意图：`faq`
- 子意图：`faq.general`

适用场景：

- 发票怎么开
- 支持哪些支付方式
- 退款多久到账

特点：

- 主要走 FAQ 检索
- 不调用订单或物流工具

### 4.2 订单服务

- 父意图：`order_service`
- 子意图：`order_service.query_status`

适用场景：

- 查订单
- 我的订单状态
- 订单 A1001 发货了吗

特点：

- 需要 `order_id`
- 缺失时先追问
- 齐全后走订单查询工具

### 4.3 物流服务

- 父意图：`logistics_service`
- 子意图：`logistics_service.query_status`

适用场景：

- 查物流
- 快递到哪了
- 配送进度

特点：

- 需要 `order_id`
- 缺失时先追问
- 齐全后走物流查询工具

### 4.4 转人工

- 父意图：`handoff_service`
- 子意图：`handoff_service.request_human`

适用场景：

- 转人工
- 我要人工客服

特点：

- 不需要复杂槽位
- 直接进入 handoff 流程

### 4.5 闲聊

- 父意图：`chitchat`
- 子意图：`chitchat.greeting`

适用场景：

- 你好
- 您好
- 在吗

特点：

- 不进入订单/物流/FAQ 工具链
- 直接用模板化回复

### 4.6 兜底

- 父意图：`unsupported`
- 子意图：`unsupported.unknown`

适用场景：

- 当前规则和 FAQ 都无法识别
- 需要用户换种表达

特点：

- 不应沿用上一轮业务意图
- 不应误触发工具调用

---

## 5. 父子意图在代码里的落点

当前实现里，父子意图不是只存在于“概念层”，而是已经落到代码结构里。

### 5.1 数据模型

`app/models.py`

- `IntentResult`
  - `main_intent`
  - `sub_intent`
- `ConversationState`
  - `current_main_intent`
  - `current_sub_intent`
- `ChatResponse`
  - `main_intent`
  - `sub_intent`

### 5.2 路由层

`app/agent.py`

`intent_router()` 负责输出：

- 主意图
- 子意图
- 槽位
- 是否需要澄清

例如：

- `你好` -> `chitchat.greeting`
- `查订单 A1001` -> `order_service.query_status`
- `查物流` -> `logistics_service.query_status`

### 5.3 状态跟踪层

`state_tracker()` 负责把父子意图写入状态对象，并决定：

- 当前阶段 `stage`
- 是否缺槽位
- 是否转人工

这里父意图比子意图更重要，因为阶段推进主要由主链路决定。

### 5.4 执行层

执行层根据父意图和子意图分流：

- `faq` -> FAQ 检索
- `order_service` -> 订单工具
- `logistics_service` -> 物流工具
- `handoff_service` -> 转人工
- `chitchat` -> 直接回复

---

## 6. 设计原则

后续继续扩展时，建议遵守下面几个原则。

### 6.1 父意图不要过细

父意图应该对应“主链路”，而不是小功能点。

好的父意图：

- `order_service`
- `logistics_service`
- `after_sales_service`

不好的父意图：

- `query_order_status`
- `query_order_amount`
- `query_order_delivery_time`

这些更适合作为子意图。

### 6.2 子意图必须能对应具体差异

不要为了分层而分层。

只有当一个细分场景在以下方面有明显差异时，才值得拆成子意图：

- 槽位不同
- 工具不同
- 回复策略不同
- 风险等级不同
- 澄清方式不同

### 6.3 优先保证父意图正确

在客服场景里，主链路走错的成本远高于子分支不够细。

例如：

- 把“查物流”错分到 FAQ，会直接答错
- 把“订单查询”细分不够完整，通常还能靠补问兜住

所以识别时应优先保证父意图准确，再逐步细化子意图。

### 6.4 未识别时回到 unsupported

父子意图结构下，最大的风险之一是“沿用上一轮状态误判”。

因此当本轮确实无法识别时，必须显式回到：

- `main_intent=unsupported`
- `sub_intent=unsupported.unknown`

而不是继续沿用上一轮的业务意图。

---

## 7. 后续扩展建议

当前项目下一步最自然的扩展方向是售后模块。

建议新增：

- 父意图：`after_sales_service`

第一批子意图：

- `after_sales_service.refund_consult`
- `after_sales_service.refund_status`
- `after_sales_service.complaint`

这样就能把当前“退款多久到账”这类问题从 FAQ 升级为正式售后能力。

闲聊类也可以继续补：

- `chitchat.thanks`
- `chitchat.goodbye`

这样 `你好`、`谢谢`、`再见` 都能走统一的 `chitchat` 父链路，而不是散落成多个无关业务意图。

---

## 8. 总结

父子意图的核心价值，不是“概念更高级”，而是它更适合客服 Agent 的工程落地。

它解决的是三个实际问题：

- 单层意图会膨胀
- 多轮对话需要先粗分再细分
- 后端状态机和前端调试都需要更稳定的结构

因此当前项目选择“父意图 + 子意图”而不是继续扩展单层 `intent`，本质上是在为后续的订单、物流、售后、转人工等多模块演进提前打基础。
