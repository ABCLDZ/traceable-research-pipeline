# Evidence intake experiment

该目录保存旧“搜索工作流”的关键实验结论。

生产代码已经迁移至 `src/research_pipeline/`；原始运行数据和旧批处理脚本
仍保留在旧工作区，不复制到新项目。旧批处理脚本不属于生产主线。

V1/V2抽取器保存在 `legacy_code/`，用于说明从“模型直接输出引文”到
span-selection的迭代历史；安装包只保留V3为正式抽取器。

已验证的核心原则是span-selection：模型选择句子位置，代码恢复逐字原文。
“原文匹配”不等价于证据召回率或研究正确性。
