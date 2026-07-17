# 意图识别设计文档

本目录（`app/business/intent/`）承载意图识别的生产代码。文档分三部分：

- **原理**：意图是什么、意图集怎么确定。
- **集合**：本客服 Agent 的目标意图集（已拍板）。
- **识别**：如何把一条消息分到意图（目标架构 + 与当前实现对照）。

> 本文件为**活文档**，后续关于分类逻辑、阈值、规则或意图集划分的讨论都会同步更新此处。

---

## 1. 原理

### 1.1 意图的概念

**意图（intent）** 是对话系统对「用户这句话想干什么」的抽象标签，是连接原始文本与系统行为的桥梁。从实现视角，**意图是一段可以独立处理的逻辑**——对应一套完整处理链路（识别所需槽位、调用的工具/接口、生成的回复或动作）。

- 与**槽位（slots）**正交：意图是「目的」，`A1001` 是槽位值。
- 与**回复/动作**正交：意图是输入侧分类，动作是输出侧处理。
- 在本系统中，意图以 `main_intent` / `action` 表示，是状态机路由的**唯一依据**。

一句话：**意图 = 用户目标的可计算抽象，是系统决定「怎么处理这句话」的起点。**

### 1.2 什么算「一个意图」

确定一个意图该不该存在，标准不是「有没有这种话术」，而是：**它是否对应一段独立的处理逻辑**。判定充分必要条件，看以下维度里是否有**至少一个**与其他意图不可合并：目标 / 领域实体 / 动作类型 / 必须收集的槽位 / 后端动作。只要「交给谁处理、补什么槽、调什么动作」一致，就是同一意图；否则该拆。

### 1.3 怎么把意图集「找」出来

- **自顶向下（capability-driven）**：从系统能做什么出发，与实现对齐、可控。
- **自底向上（data-driven）**：从真实语料聚类，贴合真实分布。
- 实际项目通常**两者结合**：顶层按业务能力划骨架，再用语料补边缘。

### 1.4 两个正交轴

客服意图本质是两个轴的交叉：

- **A 轴 · 领域目标（domain goal）**：用户想让系统做成什么事。
- **B 轴 · 对话行为（dialogue act）**：问候、致谢、确认、拒绝、**抱怨/情绪**、闲聊。

一条消息常同时带两轴（「这订单还没到，太气了！」= A:物流 + B:抱怨）。设计第一个决策：**把 B 轴塞进意图名，还是让 B 轴作为独立一层？** 推荐后者——B 轴跨域，混进 A 轴会让维度爆炸（见 §2.1）。

### 1.5 粒度的张力

太粗：一个意图混多种处理；太细：语言难区分、维护翻倍。判据：**一个好意图应当「可识别、可处理、可稳定」**。

### 1.6 多级结构不是必须

**结论：意图不一定需要多级结构。** 多级（main+sub）是**组织与分发策略**，不是意图概念本身的要求。

- **多级真正「赚」的地方**（不是为了分类更准）：
  1. **槽位/话术/处理复用**：同一主意图下子意图共享 `order_id`、共享澄清模板。
  2. **意图切换的优雅处理**：主意图一变就归档旧状态、继承可继承槽位。
  3. **分级兜底**：子意图分不出时至少退到主意图层面不致命。
- **隐藏代价**：错误跨级累积——主意图分错则子意图再准也没用。

**判定口诀**：是否多级，看「是否成家族、能否复用」，不看个数。本设计据此只保留**主意图一级结构**，动作是字段而非子树（见 §2.1）。

---

## 2. 集合

### 2.1 主意图 × 动作 模型（拍板版）

意图由两部分组成：**主意图（main_intent）= 领域目标家族** + **动作（action）= 对该目标的操作**。意图不再是一棵「主→子」两级树——**主意图是唯一的结构层，动作是挂在其上的字段**。

```
主意图（领域目标家族，唯一结构层）:
  order        action ∈ { query_status, modify, cancel, invoice }
  logistics    action ∈ { track, not_received, damaged_lost }
  after_sales  action ∈ { consult, request_refund, return, exchange, warranty }
  handoff      action ∈ { request_human, complaint }
  unrecognize  （分不出意图）
  out_of_scope （分出但超出服务能力）

对话行为层（B 轴，独立字段，非意图）:
  路由相关（影响状态/动作，必须区分）: confirm / deny / complain(情绪)
  社交直接回复（路径相同，合并为一）: chitchat（含 greet 问候 / thanks 致谢 / 闲聊）

工具（非意图，agent_node 内 LLM 自选）:
  RagRetrieveTool / OrderQueryTool / LogisticsTool / RefundTool ...
```

设计要点：
- **动作维度 = 查询/咨询/执行/转交**：`after_sales + consult`（查政策，调 RAG）vs `after_sales + request_refund`（发起退款，写操作）即「读/写」拆分。
- **动作未知时分级兜底**：主意图命中但 `action` 缺失 → 在主意图内追问具体动作，无需退回上层。
- **`complaint` 的归处**：`complain`(动词/情绪) 留 B 轴；正式「投诉升级」= `handoff + action=complaint`。
- **结构层只剩「主意图」一级**：槽位继承、意图切换归档、家族级复用都发生在主意图层（见 §1.6）。

### 2.2 RAG 是工具，不是意图

**关键决策：`knowledge_qa` 不单独成意图。** 理由：

1. 它混淆了「意图」和「工具」——「查知识库」与「查订单接口」同级，都是 agent 可调用的工具。
2. `agent_node` 已注册 `RagRetrieveTool`，由 LLM 在函数调用时自行判断是否检索，正是 tool-calling 范式核心。
3. 拆成意图反而制造重复：`after_sales + consult` 答退款政策本质也得查知识库。

**缺口补法（不靠意图）**：兜底/策略层对「答得出但无结构意图」的提问，把 `current_action` 设为 `agent_process`（用工具的默认通道）而非 `unrecognize`——`main_intent` 可仍为 `unrecognize`，关键是动作走到 `agent_process`。

**描述即契约**：函数调用下，工具 `description` 是 LLM 决定「调不调、何时调」的唯一契约，必须界定适用范围与排除项（已写入 `rag_tool.py`）：

```
从企业知识库（FAQ / 政策 / 商品 / 帮助文档）检索事实性答案，
用于与具体订单无关的通用政策或常识问题。
不适用：查询特定订单状态或物流进度（请用 order / logistics 业务工具，需 order_id）、
发起退款等写操作、以及打招呼 / 致谢 / 闲聊（直接回复即可）。
```

### 2.3 扩展位（后续阶段，第一阶段不上）

| 意图 | 第一阶段不实现的原因 |
|---|---|
| `payment`（支付） | 核心模块、涉资金流水与对账，正确性与风险高，宜单独成阶段。 |
| `account`（账户） | 与已有 auth 系统重合，且高风险操作不宜走自由文本 Agent。 |
| `feedback`（反馈建议） | 不解除当下问题、缺后端落点、紧急情绪已被 B 轴 `complain` 覆盖；初期可用 `handoff` + 兜底吸收。 |

### 2.4 方案演进与拍板

初版（greenfield）曾设 10 主意图含 `payment`/`account`/`knowledge_qa`/`feedback`，并把 `complaint` 拆成「情绪(B 轴)+ feedback(主意图)」。经论证，相对初版做如下关键改动，得出 §2.1 拍板版：

1. **删除 `knowledge_qa`**：RAG 退化为工具，LLM 在 `agent_process` 内自选；纯 FAQ 经「兜底路由到 `agent_process`」接住。
2. **`complaint` 拆为两层**：`complain`(动词/情绪) 留 B 轴；正式投诉升级 = `handoff + action=complaint`，不再作主意图。
3. **`payment`/`account`/`feedback` 第一阶段不上**：分别因「核心模块需独立阶段」「与 auth 重合」「无后端落点」，先用 `handoff` + 兜底覆盖。
4. **RAG 工具 `description` 精确化**：同时写清适用范围与排除项。
5. **取消二级子意图树，改 `主意图 × 动作`**：主意图为唯一结构层，动作是字段而非子树；代码的 `sub_intent` 标签暂保留为过渡（语义=action），待重构。

### 2.5 第一阶段落地范围（高频 action 集，定稿）

```
第一阶段 action 集:
  order        action ∈ { query_status, cancel }
  logistics    action ∈ { track }
  after_sales  action ∈ { consult, request_refund }
  handoff      action ∈ { request_human }
  unrecognize / out_of_scope / B 轴：confirm / deny / complain + chitchat（含 greet / thanks / 闲聊）
```

- **已接线**：`query_status`、`track`、`consult`(rag)、`request_human`。
- **需补工具**：`cancel`、`request_refund`。
- **投诉处理**：B 轴 `complain`（情绪）保留（调语气 + 负向连续触发转人工）；`complaint` 独立落库第一阶段折叠进 `handoff + request_human`。
- **推后动作**：`order.modify/invoice`、`logistics.not_received/damaged_lost`、`after_sales.return/exchange/warranty`、`handoff.complaint`。

### 2.6 意图切换：不设单独意图

用户中途换话题（「查订单 A1001」→「那物流到哪了」）**不需要** `intent_switch` 类意图。理由：

1. 切换不是「意图」，而是意图间的转移事件——无独立处理链路（不补缺槽、不调工具、不生成专属话术）。
2. 由 `is_intent_shift` + 状态机隐式处理：`StateTrackerService` 检测到主意图变化即归档旧状态、按 `inheritable` 继承可复用槽位（§1.6 所述「多级在主意图层赚到的第二件事」）。
3. 设成意图反受其害：既要「代表切换」又得「知道切到哪」，既无独立处理逻辑（违反 §1.2），又让路由二选一、丢失「先归档再处理」时序。

**结论**：切换是状态机职责，不是意图集成员。B 轴 `confirm`/`deny` 只作用于当前主意图的槽位，不另起切换意图。

### 2.7 情绪：不单设安抚节点

情绪安抚**不设独立 graph 节点**，而是作为**状态属性**由生成回复的节点在内部塑形。「先安抚后答案」是*回复文本语序*，由 prompt 一句指令实现，而非节点切分。

**为什么不是单独节点**：
1. 情绪是跨切关注点，永远叠加在意图之上、不替代意图，无法作为 `agent_node`/`handoff_node` 的同层兄弟（不是「二选一」终点，而是「每条路径都附加」的修饰）。判据与 §2.4（complaint 不作意图）、§2.6（切换不设意图）一致。
2. 不满足 §1.2「独立处理逻辑」：安抚节点没有自己的目标/实体/槽位/工具，产出只是「调整语气」。
3. 单独节点反而破坏「先安抚后答案」：两次 LLM 生成拼接导致语气不连续；跑在答案前只能吐通用前缀（没拿到业务事实）；跑在之后重述易改事实。

**融合方案（拍板）**：抽共享 tone 助手 `build_tone_instruction(state)`，注入所有*产出回复*的节点 prompt（`response_generator` / `agent_node` / `clarification_node` / `handoff_node`）。每节点**一次 LLM 调用**，读 `state.emotion`/`negative_streak` 按「先安抚后答案」语序生成——全覆盖、零新增节点、语气连贯。

**落点**：检测 `_detect_emotion()` 写 `emotion`+`negative_streak`；塑形由回复节点消费；负向且连续追问 → 在 `HandoffClarificationPolicy.decide()` 提高转人工优先级。

---

## 3. 识别

识别职责：把一条消息映射为 **`(main_intent, actions[], slots, emotion, confidence, candidate_intents[])`**，再交状态机裁决路由。核心分两层职责、解耦：

- **单轮分类**：只回答「这句话当前是什么意图/动作/槽」，由「规则 + LLM」两层完成。
- **多轮状态裁决**：基于对话状态，对单轮结果做「采纳 / 覆盖 / 排队」决策，本身不识别意图。

> ⚠️ 术语更正：旧称「三级回退（规则 → 上下文跟进 → LLM）」是**误导**。`slot_followup` 本质是多轮状态继承，不是单轮分类第三级；「低置信重问 LLM」是 LLM 层内调优。**单轮只有规则 + LLM 两层**；多轮覆盖是叠加的独立层。

### 3.1 总体分层模型（目标架构）

```
Layer 0  归一化与实体预抽取（非意图）
Layer 1  单轮分类（2 子系统，联合产出）
            ├─ 规则快路径（确定性护栏，高精命中即返回）
            └─ LLM 语义层（兜底 + 细分类，一次联合产出 意图+动作+槽）
Layer 2  多轮状态裁决（覆盖，不改分类）  ← 独立 DialoguePolicy
            slot_followup / is_intent_shift / confirm·deny / 澄清隐式意图 / 置信度门槛
Layer 3  分类后辅助判定（不改路由）
            emotion → 语气；policy 升级 → 转人工
```

### 3.2 Layer 0 — 归一化与实体预抽取（非意图）

- 全半角 / 简繁归一、去噪。
- 正则预抽取实体（`order_id`、手机号、日期）直接进 `slots` 草稿，**不做意图判定**；下游 LLM 拿到预抽槽可直接补全。

### 3.3 Layer 1 — 单轮分类（规则 + LLM，联合产出）

1. **规则快路径（确定性护栏）**：高精度正则/关键词硬命中（如「查物流」+ `SF123` → `logistics`），便宜、可解释、零延迟。`config/intent_rules.yml` 的 `routing_rules` 列表顺序即优先级。支持 `needs_order`、`confidence_with_order/without_order`。
2. **LLM 语义层（兜底 + 细分类）**：规则未命中或冲突时，**一次调用联合产出** `{main_intent, actions[], slots, confidence, candidate_intents[]}`——意图、动作、槽同源产出，避免「先分类再填槽」级联错误。
3. **低置信度覆盖（LLM 层内调优，非独立层）**：规则命中但 `confidence < 阈值` 时再问一次 LLM，有结果则覆盖。

### 3.4 Layer 2 — 多轮状态裁决（DialoguePolicy）

单轮给出候选后，由对话状态机基于 `state`（slots / stage / previous_intent / pending）做覆盖决策。**本层不识别意图，只裁决单轮结果是否采纳**。覆盖项：

- **`slot_followup`（意图级复用）**：只给 `order_id` 且上一轮在意图中 → 沿用上一轮意图（confidence 0.86）。
- **`is_intent_shift`（跨意图槽继承）**：主意图变化 → 归档旧状态 + 按 `inheritable` 继承可复用槽。
- **`confirm` / `deny`**：只作用于当前 `pending` 槽，不另起切换意图（见 §2.6）。
- **澄清中隐式意图**：追问下用户直接给新意图 → 覆盖当前澄清态。
- **置信度门槛**：`< 阈值` → 澄清反问；`candidate_intents` 多候选 → 消歧。
- **同意图槽累积**：`intent.slots` 合并进 `state.slots` / `confirmed_slots`，实现多轮补槽。

**意图继承三机制**（均已在 `routing.py` / `policy.py` 落地）：① 意图级复用 `slot_followup`；② 跨意图槽继承 `DialoguePolicy.inherit_slots` + YAML `inheritable`；③ 同意图槽累积 `state.slots` 持久化。

### 3.5 Layer 3 — 分类后辅助判定（不改路由）

- `_detect_emotion()`：判负/正面情绪，写 `state.emotion` + `negative_streak`（保留上一轮负面记忆，轻微衰减）；情绪只塑形生成（§2.7），不进意图分类。
- `HandoffClarificationPolicy.decide()`：依据 `needs_clarification` / `handoff` / 意图类型 / `negative_streak` 产出 `current_action`，连续追问超阈值（默认 3）强制转人工。

### 3.6 多意图识别（规划中，当前未实现）

现有 `main_intent` 为单值，假设每轮只有一个意图；用户常一次性说多个（「查订单 A1001 物流，另外我要退款」）。

> ⚠️ 早期曾按「单 Agent 串行队列」实现（`pending_intents` + `_handle_pending_intents` 续办激活），但经验证：规则层「首命中即返回」会短路掉 LLM 兜底（唯一会产出多意图数组的路径），导致 `pending_intents` 永远为空，**实际并未真正并发处理多意图**。该实现已于 2026-07-17 撤销，**后续改由 multi-agent 架构实现**（每个意图一个子 Agent 并发处理、共享槽继承），不再保留串行队列。

设计方向（待 multi-agent 落地时复用）：

1. **先判清「多意图」还是「单意图多动作」**：「查物流并改地址」= 一个 `logistics` 意图 + 多 action；「查物流 + 退款」= 两个 `main_intent`。
2. **并发处理**：每个独立 `main_intent` 派发给对应子 Agent，共享槽（如 `order_id`）由编排层统一继承。
3. **前端配套**：会话面板显示「待处理意图」列表，逐个点亮。

### 3.7 多 action 识别（单意图内并列动作）

「查物流并更新地址」= 一个 `logistics` 意图下挂 `actions: [...]` 列表，而非单值 `action`。

1. **LLM 主识别，规则只播种单 action**：规则擅长单关键词硬命中，并列连词（「并/另外/再/顺带」）表达的复合动作规则难覆盖——多 action 主要由 LLM 联合产出：
   ```
   intent: logistics
   actions: [
     {action: query_status,   slots:{order_id:"A1001"}},
     {action: update_address, slots:{order_id:"A1001", new_address:?}}
   ]
   ```
2. **每个 action 自带 schema（YAML）**：给每个 `main_intent` 声明允许的 `actions` 及**每个 action 自己的 `required_slots`**；两个 action 各自校验缺槽，互不影响。
3. **槽分两层：意图级共享 + action 级私有**：`order_id` 是意图级共享槽，两个 action 复用只问一次；`new_address` 是 `update_address` 私有槽，缺了只对该 action 澄清。
4. **action 依赖 / 顺序**：「查物流**再**改地址」是顺序依赖；「查物流**并**改地址」可并行但绑定同一 `order_id`。LLM 输出带 `depends_on` / 顺序，由 `DialoguePolicy` 排程。

**落地到状态模型**：`state.action` 单值 → `state.actions: [...]` + `state.active_action_index`；当前 action 终态 → 推进下一个、共享槽自动带入；`missing_slots` 标到具体 action 上。

> 多意图（后续由并发 multi-agent 实现）与多 action（`actions` 队列）是**正交的两级**，状态机逻辑可复用「激活一个、排队其余、终态推进」。

### 3.8 调优入口（改配置而非代码）

- `config/intent_rules.yml`：规则关键词、优先级、情绪规则、置信度。
- `config/intent_schemas.yml`：主意图 `required_slots` / `inheritable` / `clarification_order`；后续补 `actions[].required_slots`。
- `config/llm_config.*.yml`：LLM 兜底开关（`enabled`）、`confidence_threshold`、模型与 key。

### 3.9 目标架构 vs 当前实现（已知缺口）

| 维度 | 当前实现 | 目标架构 | 状态 |
|---|---|---|---|
| 单轮分类 | 规则 + LLM 兜底 | 规则 + LLM 联合产出（意图+动作+槽一次调用） | ✅ LLM 已联合产出 slots（Phase 1） |
| 多轮覆盖 | 嵌在 `StateTrackerService` | 独立 `DialoguePolicy` 裁决层 | ✅ 已抽离（Phase 2） |
| 称谓 | 「三级回退」 | 单轮两层 + 多轮覆盖层 | ✅ 已更正（§3 开头） |
| 多意图 | 不支持（`main_intent` 单值） | 并发 multi-agent（各意图子 Agent，共享槽继承） | ⬜ 已撤销早期串行队列实现，改由 multi-agent 落地（见 §3.6） |
| 多 action | 不支持（`sub_intent`/`action` 单值） | `actions[]` + `active_action_index` | ⬜ 真实盲区，Phase 4 |
| `slot_followup` | 硬编码 4 子意图 + 仅 `order_id` | 通用化为「缺槽优先补齐」 | ⬜ 覆盖窄，Phase 2 未动（待 Phase 4 顺带） |
| `overwritable` | YAML 声明但 `routing.py` 从未读取 | 删除 | ✅ 已删除（Phase 0） |
