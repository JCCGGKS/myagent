# 规则 Only vs 规则+LLM 对比评估

## 说明

- `规则-only`：只运行当前显式规则和 FAQ 规则
- `规则+LLM`：先运行规则；当规则结果落到 `fallback` 时，再尝试调用 LLM 兜底
- 当前对比不会覆盖规则直接返回 `unsupported` 但未进入 `fallback` 的样本，这与现有后端实现保持一致

## 规则-only

- 样本总数：42
- 命中样本：41
- 准确率：97.62%

## 规则+LLM

- 本次未执行
- 原因：`llm_import_unavailable: ModuleNotFoundError("No module named 'pydantic'")`

## 结论

当前无法得到有效的 `规则+LLM` 对比结果。
要生成对比结果，需要安装依赖并在本地可用配置中启用 LLM fallback。

建议检查：

- 是否已安装 `openai`、`pydantic` 等依赖
- `config/llm_config.local.json` 是否存在且 `enabled=true`
- `api_key`、`base_url`、`model` 是否可用
- 中转站是否兼容 `responses.parse` 或 `chat.completions` 的 JSON 结构化输出

