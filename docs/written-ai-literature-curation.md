# 笔试人工智能·文献翻译校订记录

## 范围

原始资料为41页《笔试文献翻译部分练习素材.pdf》，SHA-256：`919b2ae4d559542c68419239cae1e8618eba318d97aced182c1b78f27b30765f`。逐页检查文字和版面，按完整语义整理全部英文摘要、引言选段及贡献列表，共57张卡片、18个来源主题；资料把Gemini 1.5段落放在2.5标题下，故拆为两个来源主题。前言中的考情、分值和“最新”等判断不作为本站承诺。词汇截图不单独计题，另行编写与主题对应的关键词对照。

## 存储与访问

规范种子为`app/assets/training/written-ai-literature.json`，数据库集合为`ai_literature_translation`，篇章为`written_ai`、类别为`translation`。英文存question，中文参考译文存answer；source包含原资料页码、文章、段落、校订说明、词汇及可确认的论文链接。必要时保留original_english供比对。运行时数据库为维护入口，JSON为首次导入与版本分发资料，重启不覆盖管理员的修改、停用或删除。

版本21仅向现有人工智能篇追加本集合；面试英文翻译集合保持独立。升级在事务中执行，不重新导入已有202道AI问答题，也不改变旧训练、自评、收藏、游标与签到。随机/顺序、指定题量/整个集合、私人投稿、审核、重点回顾及自评权重沿用每日训练规则。

## 校订原则

保留作者的英文观点，不将历史实验结论改写成当前通用事实；只修复明显拼写、脚注污染、缺失空格和局部语法，并在说明中记录。参考译文重新组织措辞、补齐漏译、保持数字和逻辑对应。论文中的first、SOTA、fixed cost、成本下降等限定于其论述与实验条件，不是本站对模型或产品的性能保证。链接已核对arXiv标题；没有确认原论文逐字出处的资料段不伪造引用。

| 来源主题 | 卡片数 | 英文所在资料页码 |
| --- | ---: | --- |
| Gemini 2.5: Pushing the Frontier with Advanced Reasoning, Multimodality, Long Context, and Next Generation Agentic Capabilities | 1 | 1, 2 |
| Gemini 1.5: Unlocking multimodal understanding across millions of tokens of context | 1 | 2 |
| Model Card Addendum: Claude 3.5 Haiku and Upgraded Claude 3.5 Sonnet | 2 | 3, 4 |
| Qwen2.5 Technical Report | 3 | 5, 6 |
| From Local to Global: A Graph RAG Approach to Query-Focused Summarization | 3 | 7, 8, 9 |
| Training language models to follow instructions with human feedback | 3 | 10, 11 |
| DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning | 3 | 12 |
| Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks | 3 | 13, 14 |
| A Survey of Retrieval-Augmented Generation (RAG) for Large Language Models（资料标题） | 1 | 15, 16 |
| AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation | 2 | 17, 18 |
| A Survey on Test-Time Scaling in Large Language Models | 2 | 19, 20 |
| Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity | 3 | 21, 22 |
| MMAudio: Taming Multimodal Joint Training for High-Quality Video-to-Audio Synthesis | 2 | 23, 24 |
| Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG | 10 | 25, 26, 27, 28 |
| Titans: Learning to Memorize at Test Time | 5 | 30, 32 |
| Search-o1: Agentic Search-Enhanced Large Reasoning Models | 10 | 34, 35, 36, 37 |
| Agent Laboratory: Using LLM Agents as Research Assistants | 2 | 39 |
| Emerging Properties in Unified Multimodal Pretraining | 1 | 40, 41 |

## 关键修正

- Gemini：1.5英文原文被配成2.5中文，已按1.5重译；10M上下文能力标记为报告实验，不宣称为公开API窗口。
- Claude：模型卡与Claude Code产品区分；agentic译为智能体相关。
- Qwen：open-weight译为开放权重，human preference译为偏好对齐；保留B参数单位与历史规格，DPO与在线RL区别见卡片说明。
- GraphRAG：修复task.Prior等粘连，QFS译为面向查询的摘要，global sensemaking译为整体信息理解与综合分析。
- InstructGPT：preferred译为更受偏好，不能等同全任务性能优于；原文100x为粗略数量级，175/1.3约135，译文使用两个数量级并说明；补译because。
- DeepSeek-R1：纯RL仅指所述推理训练设置，不声称无预训练或完整R1流程无监督阶段。
- RAG：formulations译为建模方式；保留sequence/token条件区别；RAG不保证没有幻觉。
- RAG综述概述：上传段落未确认是具体论文摘要的逐字引用，明确标记为资料概述，不冒充论文原摘要。
- AutoGen：AutoGen2的2为脚注污染，恢复名称。
- TTS：在推理时扩展上下文中解释缩写，避免误作语音合成；AGI为作者讨论方向。
- Switch：constant cost指总参数扩展时激活计算预算的语境；up to 7x译为最高约7倍。
- MMAudio：Foley译为拟音，frame-level同步、flow matching、latents术语统一；延迟和感知阈值附场景限定。
- Agentic RAG：agent统一译为智能体，工作流术语统一；实时检索不是所有RAG必备特征。
- Titans：修复state-ofthe-art、effort of how effectively utilize及单复数错误；二次复杂度限定标准全注意力，不推广为全部变体。
- Search-o1：修复Reason-inDocuments、LRMswith、Wepropose、缺失to和QwenQwQ；知识不足、遗忘和首创性保留作者归属，不当普遍定理。
- Agent Laboratory：成本下降84%限于原实验比较，生成研究需人工核验。
- BAGEL：修复BAGELexhibits与protocal，checkpoints译为模型检查点。

## 逐题索引

| 序号 | 来源 | 段落 | 页码 |
| ---: | --- | --- | --- |
| 1 | gemini25 | 摘要 | 1-2 |
| 2 | gemini15 | 引言选段 | 2-2 |
| 3 | claude35 | 引言·模型与安全 | 3-3 |
| 4 | claude35 | 引言·计算机使用 | 4-4 |
| 5 | qwen25 | 训练与技术改进 | 5-5 |
| 6 | qwen25 | 模型规格与发布 | 6-6 |
| 7 | qwen25 | 性能表现 | 6-6 |
| 8 | graphrag | 摘要 | 7-8 |
| 9 | graphrag | 摘要 | 8-8 |
| 10 | graphrag | 引言 | 8-9 |
| 11 | instructgpt | 摘要 | 10-10 |
| 12 | instructgpt | 摘要 | 10-10 |
| 13 | instructgpt | 引言 | 10-11 |
| 14 | deepseekr1 | 摘要 | 12-12 |
| 15 | deepseekr1 | 摘要 | 12-12 |
| 16 | deepseekr1 | 引言 | 12-12 |
| 17 | rag | 摘要 | 13-13 |
| 18 | rag | 摘要 | 13-14 |
| 19 | rag | 引言 | 14-14 |
| 20 | ragsurvey | 综述概述选段 | 15-16 |
| 21 | autogen | 摘要 | 17-18 |
| 22 | autogen | 引言 | 18-18 |
| 23 | testtimescaling | 摘要 | 19-20 |
| 24 | testtimescaling | 引言 | 20-20 |
| 25 | switch | 摘要 | 21-22 |
| 26 | switch | 摘要 | 22-22 |
| 27 | switch | 引言 | 22-22 |
| 28 | mmaudio | 摘要 | 23-24 |
| 29 | mmaudio | 引言 | 24-24 |
| 30 | agenticrag | 摘要 | 25-26 |
| 31 | agenticrag | 摘要 | 26-26 |
| 32 | agenticrag | 摘要 | 26-26 |
| 33 | agenticrag | 引言 | 27-27 |
| 34 | agenticrag | 引言 | 27-27 |
| 35 | agenticrag | 引言 | 27-28 |
| 36 | agenticrag | 引言 | 28-28 |
| 37 | agenticrag | 引言 | 28-28 |
| 38 | agenticrag | 引言 | 28-28 |
| 39 | agenticrag | 引言 | 28-28 |
| 40 | titans | 摘要 | 30-30 |
| 41 | titans | 摘要 | 30-30 |
| 42 | titans | 引言 | 32-32 |
| 43 | titans | 引言 | 32-32 |
| 44 | titans | 引言 | 32-32 |
| 45 | searcho1 | 摘要 | 34-34 |
| 46 | searcho1 | 摘要 | 34-34 |
| 47 | searcho1 | 引言 | 35-35 |
| 48 | searcho1 | 引言 | 35-36 |
| 49 | searcho1 | 引言 | 36-36 |
| 50 | searcho1 | 引言 | 36-36 |
| 51 | searcho1 | 引言 | 36-36 |
| 52 | searcho1 | 引言 | 36-36 |
| 53 | searcho1 | 引言 | 37-37 |
| 54 | searcho1 | 引言 | 37-37 |
| 55 | agentlaboratory | 摘要 | 39-39 |
| 56 | agentlaboratory | 摘要 | 39-39 |
| 57 | bagel | 摘要 | 40-41 |
