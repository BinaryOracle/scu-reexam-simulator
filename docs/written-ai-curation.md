# 人工智能笔试训练题整理与校订记录

本题库是学习用的整理校订版，不是官方题库、官方答案或对未来考试范围的承诺。PDF 中关于历年考试比例、学校偏好和特定年份考点的叙述未作为已证实事实导入。

## 材料核对

| 材料 | 页数 | SHA-256 | 处理 |
|---|---:|---|---|
| 深度学习八股.pdf | 69 | `948db44b9e7e54ea0fbcc1662573530c8e57109b6514280f99734e41954063b3` | 按知识结构整理 |
| 机器学习八股.pdf | 13 | `db673fa1a07270176dd2ba46c3bc6f93fb397130d4dd8558492fbfa0c01139b5` | 按知识结构整理 |
| 机器学习八股 (1).pdf | 13 | `8bf7d85e56ab321cd54201e044679918311129fe5db56dd1ffe1d3ffee5c9a59` | 重复导出，不重复入库 |
| 大模型八股.pdf | 28 | `63c1346d8e831ec60a72100cd9b8bd8361dc0bb02c44884956eb885dfc03e34a` | 按知识结构整理 |
| Agent_Rag八股.pdf | 29 | `11f3a60b6b1db616d7e09e090ca4c570746c319e63ec5d530f844786895cba9b` | 按知识结构整理 |

两份机器学习文件的二进制哈希不同，但全部13页的提取文本和低分辨率逐页渲染结果一致，合并为同一来源，题目中保留重复来源文件名。

## 整理方式

先核对章节、标题和跨页关系，再将知识型标题改写成明确可回答的问题；同一问答中的编号步骤、公式和论证不会被机械拆成多个问题。问答范围相近但训练侧重不同的主题可以保留，例如“神经网络”在机器学习概览与深度学习结构中分别出现。大模型文档第21—23页反复出现的位置编码说明合并为一题。答案均重新组织为知识要点，不回显存在错误的原始裁片；题目保留来源页码、知识主题及校订参考链接。补充题标为 supplement，不伪造 PDF 页码。

| 集合 | 整理校订题 | 补充题 | 合计 |
|---|---:|---:|---:|
| 机器学习 | 28 | 16 | 44 |
| 深度学习 | 66 | 3 | 69 |
| 大模型 | 42 | 3 | 45 |
| Agent 与 RAG | 41 | 3 | 44 |

## 重点修正

| 原文问题 | 校订处理 |
|---|---|
| 决策树被一概描述成二叉树 | 区分 CART 二叉划分与可多分支的其他树 |
| 梯度提升描述混入提高错误样本抽样概率 | 区分 GBDT 负梯度拟合与 AdaBoost 的典型重加权 |
| SVM 支持向量仅指距离最近的点、使用核就能分开 | 补充软间隔中非零对偶系数与核方法的适用限制 |
| 朴素贝叶斯被描述为特征互相独立 | 改为给定类别后的条件独立假设 |
| GAN 一概列入半监督、线性回归列为标准分类器 | 按训练信号与任务区分，解释变体与阈值用法 |
| Z-score 不受异常值影响或会得到正态数据 | 说明其对异常值敏感，只改变位置和尺度 |
| BN 只在特征轴求均值方差 | 区分 NC 沿 N、NCHW 沿 N/H/W 的统计维度及推理运行统计 |
| BN 的作用仅归因于内部协变量偏移 | 保留历史解释，明确不是唯一已证实机制 |
| ReLU 被称为线性、Softplus 会使负梯度彻底消失问题消失 | 区分分段线性与整体非线性，说明 Softplus 负区间仍可小梯度 |
| L2 惩罚和权重衰减无条件等价 | 限定普通 SGD 的系数约定，补充 AdamW 解耦含义 |
| 卷积参数只比较核大小、Same 总保持尺寸 | 给出通道/分组/偏置完整公式及步长条件 |
| 池化和 CNN 保证平移、缩放不变 | 区分等变性、局部鲁棒性与严格不变性 |
| 每个字或单词就是一个 token、位置编码意味着无限上下文 | 说明分词器依赖性及计算、训练长度和服务限制 |
| LoRA 必须对原权重做 SVD、必然加速推理 | 改为冻结基座学习低秩增量，解释初始化及合并条件 |
| LN 的 γ/β 可还原任意样本原输入 | 说明共享仿射参数不能匹配所有样本的瞬时统计 |
| RAG 天然保障隐私、向量库必须独立部署 | 按实际数据流、权限及部署方式讨论，不作绝对保证 |
| 传统问答只能关键词检索、RAG 必然完成多跳推理 | 按检索与答案生成机制区分并明确能力依赖条件 |
| JSON mode 或 Function Calling 保证 schema 和业务正确 | 区分 JSON 语法、schema、语义及执行权限校验 |
| 仅用 BLEU/ROUGE 或向量相似度判 RAG 对错 | 改为辅助指标，并加入事实、证据与引用核验 |
| 固定数据条数、显存或 GPU 加速倍数作通用结论 | 改为配置依赖估算与实测要求 |

## 补全范围

机器学习新增训练/验证/测试划分、交叉验证、预处理 Pipeline、偏差方差、L1/L2、数据泄漏、类别不平衡、ROC/PR 与校准、缺失异常、剪枝、聚类选择、MLE/MAP、强化学习与 Q-learning、生成判别及实验可复现性。其他集合补充梯度累积、训练/评估模式、混合精度、采样控制、KV Cache、提示注入与工具幂等性等相关基础。

## 全量题目索引

以下编号使用稳定 source_key；数据库首次迁移按 source_key 去重，之后不会用该文件覆盖管理员编辑。参考链接在每题 source.references 中。

| 稳定编号 | 集合 | 来源页/类型 | 主题 | 整理后的题目 |
|---|---|---|---|
| written-ai-v1:ai_ml:001 | 机器学习 | 机器学习八股.pdf 1–2 | 学习范式 | 监督学习、无监督学习、半监督学习和强化学习分别解决什么问题？ |
| written-ai-v1:ai_ml:002 | 机器学习 | 机器学习八股.pdf 2–2 | 线性回归 | 线性回归的模型、目标函数与适用任务是什么？ |
| written-ai-v1:ai_ml:003 | 机器学习 | 机器学习八股.pdf 2–2 | 逻辑回归 | 逻辑回归为什么用于分类？它与线性回归有什么区别？ |
| written-ai-v1:ai_ml:004 | 机器学习 | 机器学习八股.pdf 2–3 | 决策树 | 决策树由哪些部分组成？所有决策树都是二叉树吗？ |
| written-ai-v1:ai_ml:005 | 机器学习 | 机器学习八股.pdf 3–3 | 信息增益 | 什么是熵与信息增益？信息增益选择特征有什么偏好？ |
| written-ai-v1:ai_ml:006 | 机器学习 | 机器学习八股.pdf 3–3 | 回归树 | 回归树如何选择划分？方差与分类树的划分指标有什么区别？ |
| written-ai-v1:ai_ml:007 | 机器学习 | 机器学习八股.pdf 3–3 | 集成与Bagging | Bagging 如何构建集成？为什么可以降低方差？ |
| written-ai-v1:ai_ml:008 | 机器学习 | 机器学习八股.pdf 4–4 | 随机森林 | 随机森林相对 Bagging 决策树增加了什么随机性？ |
| written-ai-v1:ai_ml:009 | 机器学习 | 机器学习八股.pdf 4–4 | 梯度提升 | GBDT 的基本思想是什么？它与 AdaBoost 的样本重加权有何不同？ |
| written-ai-v1:ai_ml:010 | 机器学习 | 机器学习八股.pdf 4–4 | XGBoost | XGBoost 在梯度提升框架上有哪些重要改进？ |
| written-ai-v1:ai_ml:011 | 机器学习 | 机器学习八股.pdf 4–5 | SVM | 支持向量机如何确定决策边界？什么是支持向量？ |
| written-ai-v1:ai_ml:012 | 机器学习 | 机器学习八股.pdf 4–5 | SVM间隔 | 硬间隔与软间隔 SVM 的适用条件是什么？ |
| written-ai-v1:ai_ml:013 | 机器学习 | 机器学习八股.pdf 4–5 | 核方法 | SVM 的核技巧是什么？使用核函数就一定能线性可分吗？ |
| written-ai-v1:ai_ml:014 | 机器学习 | 机器学习八股.pdf 5–6 | 朴素贝叶斯 | 朴素贝叶斯的“朴素”假设是什么？如何避免零概率？ |
| written-ai-v1:ai_ml:015 | 机器学习 | 机器学习八股.pdf 6–6 | KNN | KNN 如何进行分类与回归？K 值及特征尺度有什么影响？ |
| written-ai-v1:ai_ml:016 | 机器学习 | 机器学习八股.pdf 7–7 | 神经网络 | 神经网络怎样用于监督学习？训练目标是什么？ |
| written-ai-v1:ai_ml:017 | 机器学习 | 机器学习八股.pdf 7–8 | K-Means | K-Means 的优化目标与基本步骤是什么？ |
| written-ai-v1:ai_ml:018 | 机器学习 | 机器学习八股.pdf 8–9 | PCA | PCA 的原理及计算步骤是什么？为什么它不是线性回归？ |
| written-ai-v1:ai_ml:019 | 机器学习 | 机器学习八股.pdf 9–9 | PCA应用 | 如何选择 PCA 主成分数？标准化与去噪应注意什么？ |
| written-ai-v1:ai_ml:020 | 机器学习 | 机器学习八股.pdf 9–10 | 自编码器 | 自编码器的结构、训练目标及应用是什么？ |
| written-ai-v1:ai_ml:021 | 机器学习 | 机器学习八股.pdf 10–10 | 半监督分类 | 半监督学习为何可能有效？使用伪标签有什么风险？ |
| written-ai-v1:ai_ml:022 | 机器学习 | 机器学习八股.pdf 10–11 | 学习范式比较 | 监督学习、无监督学习与半监督学习怎样选择？GAN 必然属于半监督吗？ |
| written-ai-v1:ai_ml:023 | 机器学习 | 机器学习八股.pdf 11–11 | 集成学习 | 集成学习为什么有效？Bagging、Boosting 与 Stacking 有何不同？ |
| written-ai-v1:ai_ml:024 | 机器学习 | 机器学习八股.pdf 11–11 | 前向与反向传播 | 前向传播、反向传播和参数更新分别做什么？ |
| written-ai-v1:ai_ml:025 | 机器学习 | 机器学习八股.pdf 12–12 | 深度学习 | 深度学习与传统机器学习的主要区别是什么？ |
| written-ai-v1:ai_ml:026 | 机器学习 | 机器学习八股.pdf 12–12 | 应用 | CNN、RNN、LSTM 与 GAN 分别适合什么任务？ |
| written-ai-v1:ai_ml:027 | 机器学习 | 机器学习八股.pdf 12–13 | 分类器 | 什么是线性分类器？线性回归能否直接称为分类器？ |
| written-ai-v1:ai_ml:028 | 机器学习 | 机器学习八股.pdf 13–13 | 感知机 | 感知机与多层感知机有什么区别？为什么单层感知机不能解决 XOR？ |
| written-ai-v1:ai_ml:029 | 机器学习 | 补充题 | 数据划分 | 训练集、验证集和测试集分别有什么用途？ |
| written-ai-v1:ai_ml:030 | 机器学习 | 补充题 | 交叉验证 | K 折交叉验证怎样做？预处理为什么应放进 Pipeline？ |
| written-ai-v1:ai_ml:031 | 机器学习 | 补充题 | 偏差方差 | 什么是欠拟合、过拟合及偏差—方差权衡？ |
| written-ai-v1:ai_ml:032 | 机器学习 | 补充题 | 正则化 | L1 与 L2 正则化有什么区别？ |
| written-ai-v1:ai_ml:033 | 机器学习 | 补充题 | 数据泄漏 | 什么是数据泄漏？请给出排查方法。 |
| written-ai-v1:ai_ml:034 | 机器学习 | 补充题 | 评估指标 | 准确率、精确率、召回率和 F1 如何计算？类别不平衡时选什么？ |
| written-ai-v1:ai_ml:035 | 机器学习 | 补充题 | 阈值与曲线 | ROC-AUC 与 PR-AUC 有何不同？概率校准与阈值选择是什么？ |
| written-ai-v1:ai_ml:036 | 机器学习 | 补充题 | 不平衡数据 | 类别不平衡有哪些常见处理方法？ |
| written-ai-v1:ai_ml:037 | 机器学习 | 补充题 | 缺失与异常 | 如何处理缺失值和异常值？ |
| written-ai-v1:ai_ml:038 | 机器学习 | 补充题 | 树模型 | 决策树为什么容易过拟合？如何剪枝？ |
| written-ai-v1:ai_ml:039 | 机器学习 | 补充题 | 聚类评估 | 怎样选择 K-Means 的 K？它适合所有形状的簇吗？ |
| written-ai-v1:ai_ml:040 | 机器学习 | 补充题 | 概率模型 | 贝叶斯定理、最大似然估计与最大后验估计有什么关系？ |
| written-ai-v1:ai_ml:041 | 机器学习 | 补充题 | 强化学习 | 强化学习中状态、动作、奖励、策略与价值函数是什么？ |
| written-ai-v1:ai_ml:042 | 机器学习 | 补充题 | Q学习 | Q-learning 的更新公式与核心思想是什么？ |
| written-ai-v1:ai_ml:043 | 机器学习 | 补充题 | 生成与判别 | 生成式模型与判别式模型有什么区别？ |
| written-ai-v1:ai_ml:044 | 机器学习 | 补充题 | 可复现性 | 如何设计一个可信的机器学习实验基线？ |
| written-ai-v1:ai_dl:001 | 深度学习 | 深度学习八股.pdf 1–1 | 神经网络 | 什么是神经网络？输入层、隐藏层与输出层分别做什么？ |
| written-ai-v1:ai_dl:002 | 深度学习 | 深度学习八股.pdf 2–2 | 感知机与MLP | 感知机与多层感知机的结构和表达能力有什么区别？ |
| written-ai-v1:ai_dl:003 | 深度学习 | 深度学习八股.pdf 3–3 | 网络深度 | 什么是深度神经网络？增加深度有什么意义与代价？ |
| written-ai-v1:ai_dl:004 | 深度学习 | 深度学习八股.pdf 3–7 | 训练困难 | 深层神经网络为什么难训练？有哪些常见改善方法？ |
| written-ai-v1:ai_dl:005 | 深度学习 | 深度学习八股.pdf 4–5 | 内部协变量偏移 | 如何理解内部协变量偏移？BN 的收益是否只能由它解释？ |
| written-ai-v1:ai_dl:006 | 深度学习 | 深度学习八股.pdf 5–6 | 梯度消失 | 梯度消失如何产生？怎样诊断和缓解？ |
| written-ai-v1:ai_dl:007 | 深度学习 | 深度学习八股.pdf 6–7 | 梯度爆炸 | 梯度爆炸的原因、表现及处理方法是什么？ |
| written-ai-v1:ai_dl:008 | 深度学习 | 深度学习八股.pdf 8–9 | 激活函数 | 为什么神经网络需要非线性激活函数？ |
| written-ai-v1:ai_dl:009 | 深度学习 | 深度学习八股.pdf 9–10 | Sigmoid | Sigmoid 的定义、适用位置和局限是什么？ |
| written-ai-v1:ai_dl:010 | 深度学习 | 深度学习八股.pdf 10–11 | Tanh | Tanh 与 Sigmoid 相比有什么特点？ |
| written-ai-v1:ai_dl:011 | 深度学习 | 深度学习八股.pdf 11–13 | ReLU | ReLU 的定义、优点与“死亡 ReLU”问题是什么？ |
| written-ai-v1:ai_dl:012 | 深度学习 | 深度学习八股.pdf 13–14 | LeakyReLU | Leaky ReLU 怎样缓解 ReLU 的零梯度问题？ |
| written-ai-v1:ai_dl:013 | 深度学习 | 深度学习八股.pdf 14–15 | Softplus | Softplus 的定义、导数与局限是什么？ |
| written-ai-v1:ai_dl:014 | 深度学习 | 深度学习八股.pdf 15–16 | Softmax | Softmax 如何把 logits 转为概率？怎样稳定计算？ |
| written-ai-v1:ai_dl:015 | 深度学习 | 深度学习八股.pdf 16–17 | 交叉熵 | 多分类交叉熵如何定义？Softmax 与交叉熵结合的梯度是什么？ |
| written-ai-v1:ai_dl:016 | 深度学习 | 深度学习八股.pdf 17–19 | 传播 | 前向传播、反向传播与优化器更新有何区别？ |
| written-ai-v1:ai_dl:017 | 深度学习 | 深度学习八股.pdf 19–20 | 超参数 | 模型参数与超参数有什么区别？如何调节超参数？ |
| written-ai-v1:ai_dl:018 | 深度学习 | 深度学习八股.pdf 20–20 | 批量 | 什么是 Batch Size？全批、随机与小批梯度下降怎样区分？ |
| written-ai-v1:ai_dl:019 | 深度学习 | 深度学习八股.pdf 20–22 | 批量选择 | 增大或减小 Batch Size 会怎样影响训练？ |
| written-ai-v1:ai_dl:020 | 深度学习 | 深度学习八股.pdf 23–23 | 归一化 | 数据归一化、标准化与网络内归一化有什么不同？ |
| written-ai-v1:ai_dl:021 | 深度学习 | 深度学习八股.pdf 23–26 | 归一化与优化 | 为什么特征尺度差异会影响梯度优化？缩放是否总能加速？ |
| written-ai-v1:ai_dl:022 | 深度学习 | 深度学习八股.pdf 26–26 | Min-Max | Min-Max 归一化如何计算？有哪些限制？ |
| written-ai-v1:ai_dl:023 | 深度学习 | 深度学习八股.pdf 27–27 | Z-score | Z-score 标准化是什么？它会使数据服从正态分布吗？ |
| written-ai-v1:ai_dl:024 | 深度学习 | 深度学习八股.pdf 27–27 | 对数变换 | 对数变换适合什么数据？使用时要注意什么？ |
| written-ai-v1:ai_dl:025 | 深度学习 | 深度学习八股.pdf 28–28 | L2归一化 | L2 向量归一化如何计算？它与 Z-score 有何区别？ |
| written-ai-v1:ai_dl:026 | 深度学习 | 深度学习八股.pdf 28–32 | BN | Batch Normalization 的计算步骤与训练、推理差异是什么？ |
| written-ai-v1:ai_dl:027 | 深度学习 | 深度学习八股.pdf 29–31 | BN维度 | 全连接层与卷积层的 BN 通常沿哪些维度统计？ |
| written-ai-v1:ai_dl:028 | 深度学习 | 深度学习八股.pdf 29–32 | BN适用性 | BN 有哪些好处与局限？小批量训练时怎么办？ |
| written-ai-v1:ai_dl:029 | 深度学习 | 深度学习八股.pdf 32–33 | LN | LayerNorm 如何计算？与 BatchNorm 有何区别？ |
| written-ai-v1:ai_dl:030 | 深度学习 | 深度学习八股.pdf 33–34 | 预训练微调 | 预训练为什么有帮助？微调时哪些参数会更新？ |
| written-ai-v1:ai_dl:031 | 深度学习 | 深度学习八股.pdf 34–35 | 初始化 | 为什么不能把同层所有权重初始化为相同值？Xavier 与 He 初始化怎样选？ |
| written-ai-v1:ai_dl:032 | 深度学习 | 深度学习八股.pdf 35–37 | 学习率 | 学习率过大或过小会有什么表现？如何选择？ |
| written-ai-v1:ai_dl:033 | 深度学习 | 深度学习八股.pdf 36–37 | 调度 | 常见学习率调度与 Warmup 分别起什么作用？ |
| written-ai-v1:ai_dl:034 | 深度学习 | 深度学习八股.pdf 38–39 | 梯度下降 | 全批、随机与小批梯度下降各有哪些优缺点？ |
| written-ai-v1:ai_dl:035 | 深度学习 | 深度学习八股.pdf 39–39 | AdaGrad | AdaGrad 如何自适应调整学习率？主要局限是什么？ |
| written-ai-v1:ai_dl:036 | 深度学习 | 深度学习八股.pdf 39–40 | RMSProp | RMSProp 与 AdaGrad 有何区别？它如何强调近期梯度？ |
| written-ai-v1:ai_dl:037 | 深度学习 | 深度学习八股.pdf 40–40 | 动量 | 动量法如何改进普通梯度下降？ |
| written-ai-v1:ai_dl:038 | 深度学习 | 深度学习八股.pdf 41–41 | Adam | Adam 的一阶矩、二阶矩和偏差校正是什么？ |
| written-ai-v1:ai_dl:039 | 深度学习 | 深度学习八股.pdf 41–42 | L2与权重衰减 | L2 正则化与权重衰减是否总是等价？AdamW 为什么解耦衰减？ |
| written-ai-v1:ai_dl:040 | 深度学习 | 深度学习八股.pdf 42–42 | Dropout | Dropout 在训练和推理时分别怎样工作？ |
| written-ai-v1:ai_dl:041 | 深度学习 | 深度学习八股.pdf 42–44 | 评估 | 准确率、精确率、召回率与 F1 各适合怎样的需求？ |
| written-ai-v1:ai_dl:042 | 深度学习 | 深度学习八股.pdf 44–46 | CNN基础 | CNN 的基本组成与局部连接、参数共享有什么意义？ |
| written-ai-v1:ai_dl:043 | 深度学习 | 深度学习八股.pdf 47–47 | 卷积直观 | 卷积在图像中起什么作用？卷积核必须是人工设计的吗？ |
| written-ai-v1:ai_dl:044 | 深度学习 | 深度学习八股.pdf 47–50 | 卷积参数 | 卷积层有哪些参数？输出尺寸与可训练参数量怎样计算？ |
| written-ai-v1:ai_dl:045 | 深度学习 | 深度学习八股.pdf 48–48 | Padding | Valid 与 Same Padding 的含义是什么？Same 是否总让尺寸不变？ |
| written-ai-v1:ai_dl:046 | 深度学习 | 深度学习八股.pdf 50–50 | 卷积计算 | 标准卷积怎样从多输入通道计算一个输出通道？ |
| written-ai-v1:ai_dl:047 | 深度学习 | 深度学习八股.pdf 50–52 | 池化 | 最大池化、平均池化、全局池化与自适应池化有什么区别？ |
| written-ai-v1:ai_dl:048 | 深度学习 | 深度学习八股.pdf 52–52 | 1×1卷积 | 1×1 卷积有哪些作用？它能直接融合相邻空间位置吗？ |
| written-ai-v1:ai_dl:049 | 深度学习 | 深度学习八股.pdf 53–53 | 卷积与池化 | 卷积层与池化层的主要区别是什么？ |
| written-ai-v1:ai_dl:050 | 深度学习 | 深度学习八股.pdf 53–54 | 卷积核大小 | 大卷积核与叠加小卷积核在感受野、参数和非线性方面有何差别？ |
| written-ai-v1:ai_dl:051 | 深度学习 | 深度学习八股.pdf 54–55 | 多尺度 | 同一网络层能否并行使用不同尺寸的卷积核？ |
| written-ai-v1:ai_dl:052 | 深度学习 | 深度学习八股.pdf 55–56 | 参数压缩 | 如何减少 CNN 的参数量和计算量？二者一定同步下降吗？ |
| written-ai-v1:ai_dl:053 | 深度学习 | 深度学习八股.pdf 56–59 | 泛化 | 有哪些提升 CNN 泛化能力的方法？ |
| written-ai-v1:ai_dl:054 | 深度学习 | 深度学习八股.pdf 57–57 | 数据增强 | Mixup、Cutout 与 CutMix 分别做什么？ |
| written-ai-v1:ai_dl:055 | 深度学习 | 深度学习八股.pdf 59–60 | 归纳偏置 | CNN 的局部连接、权值共享和池化怎样利用图像共性？ |
| written-ai-v1:ai_dl:056 | 深度学习 | 深度学习八股.pdf 61–61 | LeNet | LeNet 的典型结构和历史意义是什么？ |
| written-ai-v1:ai_dl:057 | 深度学习 | 深度学习八股.pdf 61–62 | AlexNet | AlexNet 的主要特点与贡献是什么？ |
| written-ai-v1:ai_dl:058 | 深度学习 | 深度学习八股.pdf 62–62 | VGG | VGG 为什么大量堆叠 3×3 卷积？有什么缺点？ |
| written-ai-v1:ai_dl:059 | 深度学习 | 深度学习八股.pdf 62–64 | NiN | Network in Network 的 MLPConv 与全局平均池化有什么作用？ |
| written-ai-v1:ai_dl:060 | 深度学习 | 深度学习八股.pdf 64–65 | GoogLeNet | GoogLeNet 的 Inception 模块如何融合多尺度特征？ |
| written-ai-v1:ai_dl:061 | 深度学习 | 深度学习八股.pdf 65–66 | 退化问题 | 深层网络的退化问题与过拟合、梯度消失有什么区别？ |
| written-ai-v1:ai_dl:062 | 深度学习 | 深度学习八股.pdf 66–66 | 残差 | 残差连接为什么便于学习恒等映射并改善梯度传播？ |
| written-ai-v1:ai_dl:063 | 深度学习 | 深度学习八股.pdf 67–67 | 残差维度 | 残差分支输入输出维度不一致时怎么办？ |
| written-ai-v1:ai_dl:064 | 深度学习 | 深度学习八股.pdf 67–67 | 瓶颈 | ResNet 的 Bottleneck 结构如何降低开销？ |
| written-ai-v1:ai_dl:065 | 深度学习 | 深度学习八股.pdf 67–68 | 全局平均池化 | 全局平均池化相对 Flatten 加全连接有什么优缺点？ |
| written-ai-v1:ai_dl:066 | 深度学习 | 深度学习八股.pdf 69–69 | 张量 | 标量、向量、矩阵与张量有什么关系？ |
| written-ai-v1:ai_dl:067 | 深度学习 | 补充题 | 训练实现 | 为什么每次梯度更新前通常需要清空梯度？梯度累积如何使用？ |
| written-ai-v1:ai_dl:068 | 深度学习 | 补充题 | 训练模式 | model.train()、model.eval() 与 no_grad() 有何区别？ |
| written-ai-v1:ai_dl:069 | 深度学习 | 补充题 | 数值精度 | 混合精度训练为什么可能溢出或下溢？如何缓解？ |
| written-ai-v1:ai_llm:001 | 大模型 | 大模型八股.pdf 1–1 | 大模型 | 什么是大语言模型？“大”是否存在固定参数门槛？ |
| written-ai-v1:ai_llm:002 | 大模型 | 大模型八股.pdf 1–2 | Token | Token 是什么？一个汉字或英文单词总对应一个 Token 吗？ |
| written-ai-v1:ai_llm:003 | 大模型 | 大模型八股.pdf 2–2 | 参数 | 模型参数量与运行显存有什么关系？ |
| written-ai-v1:ai_llm:004 | 大模型 | 大模型八股.pdf 2–3 | 上下文 | 什么是上下文窗口？支持长窗口是否保证能有效利用所有内容？ |
| written-ai-v1:ai_llm:005 | 大模型 | 大模型八股.pdf 3–4 | Embedding | 词嵌入表和句向量模型有什么区别？ |
| written-ai-v1:ai_llm:006 | 大模型 | 大模型八股.pdf 4–4 | 幻觉 | 什么是大模型幻觉？流畅或自信的回答为何仍可能错误？ |
| written-ai-v1:ai_llm:007 | 大模型 | 大模型八股.pdf 4–4 | 提示 | Prompt 中角色、任务、上下文、示例和输出约束分别起什么作用？ |
| written-ai-v1:ai_llm:008 | 大模型 | 大模型八股.pdf 4–5 | 编码器 | Transformer Encoder 的主要结构与用途是什么？ |
| written-ai-v1:ai_llm:009 | 大模型 | 大模型八股.pdf 5–5 | 解码器 | Decoder-only 与 Encoder–Decoder 架构怎样区别？ |
| written-ai-v1:ai_llm:010 | 大模型 | 大模型八股.pdf 5–6 | 注意力 | 缩放点积注意力如何计算？Q、K、V 分别是什么？ |
| written-ai-v1:ai_llm:011 | 大模型 | 大模型八股.pdf 6–7 | 指令微调 | 什么是 SFT？它与基座预训练的训练数据和目标有何不同？ |
| written-ai-v1:ai_llm:012 | 大模型 | 大模型八股.pdf 7–8 | 温度 | Temperature 如何影响采样？低温度等于高准确率吗？ |
| written-ai-v1:ai_llm:013 | 大模型 | 大模型八股.pdf 8–9 | 预训练 | 自回归语言模型的预训练过程与目标是什么？ |
| written-ai-v1:ai_llm:014 | 大模型 | 大模型八股.pdf 9–10 | KL散度 | KL 散度如何定义？它为什么不是距离？ |
| written-ai-v1:ai_llm:015 | 大模型 | 大模型八股.pdf 10–11 | 模型体系 | 怎样客观比较不同开放权重语言模型？ |
| written-ai-v1:ai_llm:016 | 大模型 | 大模型八股.pdf 11–11 | 优点 | 大语言模型有哪些优势？能力边界是什么？ |
| written-ai-v1:ai_llm:017 | 大模型 | 大模型八股.pdf 11–12 | 缺点 | 大语言模型有哪些主要局限？ |
| written-ai-v1:ai_llm:018 | 大模型 | 大模型八股.pdf 12–12 | 小批量 | 微调时 Batch Size 太小可能带来哪些问题？ |
| written-ai-v1:ai_llm:019 | 大模型 | 大模型八股.pdf 12–12 | 大批量 | 微调时 Batch Size 太大可能带来哪些问题？ |
| written-ai-v1:ai_llm:020 | 大模型 | 大模型八股.pdf 12–12 | 创作与幻觉 | “幻觉不一定有害”应怎样准确表述？ |
| written-ai-v1:ai_llm:021 | 大模型 | 大模型八股.pdf 12–13 | 幻觉诱因 | 大模型在什么情况下更容易产生无依据内容？ |
| written-ai-v1:ai_llm:022 | 大模型 | 大模型八股.pdf 13–13 | 架构比较 | Encoder-only、Decoder-only 与 Encoder–Decoder 各适合哪些任务？ |
| written-ai-v1:ai_llm:023 | 大模型 | 大模型八股.pdf 13–14 | 长度限制 | LLaMA 等模型的输入长度能否无限增长？ |
| written-ai-v1:ai_llm:024 | 大模型 | 大模型八股.pdf 14–14 | 长文本 | 有哪些处理长文本的方法？它们有什么取舍？ |
| written-ai-v1:ai_llm:025 | 大模型 | 大模型八股.pdf 14–15 | 评测 | 大模型应从哪些维度评测？ |
| written-ai-v1:ai_llm:026 | 大模型 | 大模型八股.pdf 15–15 | 不确定性 | 模型能可靠判断“自己是否知道”吗？如何改善？ |
| written-ai-v1:ai_llm:027 | 大模型 | 大模型八股.pdf 15–16 | 偏好数据 | 如何降低偏好标注成本？AI 反馈有哪些风险？ |
| written-ai-v1:ai_llm:028 | 大模型 | 大模型八股.pdf 16–16 | CPU与GPU | 为什么大模型在 CPU 与 GPU 上的推理速度差异不能给固定倍数？ |
| written-ai-v1:ai_llm:029 | 大模型 | 大模型八股.pdf 16–17 | 微调数据 | 高质量指令微调数据应怎样构建？ |
| written-ai-v1:ai_llm:030 | 大模型 | 大模型八股.pdf 17–17 | 训练路线 | 从头预训练、继续预训练、SFT 与 RAG 应怎样选择？ |
| written-ai-v1:ai_llm:031 | 大模型 | 大模型八股.pdf 17–18 | SFT收益 | 指令微调有哪些收益和潜在副作用？ |
| written-ai-v1:ai_llm:032 | 大模型 | 大模型八股.pdf 18–18 | 显存估算 | 微调所需显存如何估算？为什么只算权重不够？ |
| written-ai-v1:ai_llm:033 | 大模型 | 大模型八股.pdf 18–19 | 训练流程 | 一轮语言模型训练通常包含哪些步骤？ |
| written-ai-v1:ai_llm:034 | 大模型 | 大模型八股.pdf 19–19 | 数据量 | 微调需要多少条数据？能否用固定条数保证效果？ |
| written-ai-v1:ai_llm:035 | 大模型 | 大模型八股.pdf 19–20 | 领域知识 | 领域知识适配一定要选预训练或微调中的一种吗？ |
| written-ai-v1:ai_llm:036 | 大模型 | 大模型八股.pdf 20–21 | LoRA | LoRA 的低秩更新公式与初始化是什么？必须先做 SVD 吗？ |
| written-ai-v1:ai_llm:037 | 大模型 | 大模型八股.pdf 20–21 | LoRA限制 | LoRA 节省哪些资源？是否一定加速推理或无需遗忘评估？ |
| written-ai-v1:ai_llm:038 | 大模型 | 大模型八股.pdf 21–22 | 位置编码 | Transformer 为什么需要位置信息？绝对位置、相对位置与 RoPE 有何区别？ |
| written-ai-v1:ai_llm:039 | 大模型 | 大模型八股.pdf 22–24 | Adapter | Adapter 微调的原理是什么？与 LoRA 有何不同？ |
| written-ai-v1:ai_llm:040 | 大模型 | 大模型八股.pdf 24–25 | 词相似度 | 如何衡量词或文本的相似性？余弦、PMI 与词典路径各有什么限制？ |
| written-ai-v1:ai_llm:041 | 大模型 | 大模型八股.pdf 25–27 | Adam | Adam 如何结合动量与自适应缩放？ |
| written-ai-v1:ai_llm:042 | 大模型 | 大模型八股.pdf 27–28 | LayerNorm | Transformer 中 LayerNorm 通常沿哪些维度计算？γ、β 能否任意还原每个样本？ |
| written-ai-v1:ai_llm:043 | 大模型 | 补充题 | 生成控制 | Top-k、Top-p 与温度有什么区别？ |
| written-ai-v1:ai_llm:044 | 大模型 | 补充题 | 推理缓存 | KV Cache 为什么能加速自回归解码？有什么代价？ |
| written-ai-v1:ai_llm:045 | 大模型 | 补充题 | RAG与微调 | RAG 与微调在知识更新、引用和行为适配方面有什么区别？ |
| written-ai-v1:ai_agent_rag:001 | Agent 与 RAG | Agent_Rag八股.pdf 1–2 | Agent定义 | 什么是 AI Agent？它与普通大模型对话有什么区别？ |
| written-ai-v1:ai_agent_rag:002 | Agent 与 RAG | Agent_Rag八股.pdf 2–3 | 核心组件 | AI Agent 的核心组件通常有哪些？ |
| written-ai-v1:ai_agent_rag:003 | Agent 与 RAG | Agent_Rag八股.pdf 3–3 | ReAct | ReAct 如何结合推理、行动和观察？有什么局限？ |
| written-ai-v1:ai_agent_rag:004 | Agent 与 RAG | Agent_Rag八股.pdf 3–4 | CoT | 思维链提示与 Agent 有什么关系？它是否保证推理正确？ |
| written-ai-v1:ai_agent_rag:005 | Agent 与 RAG | Agent_Rag八股.pdf 4–5 | 记忆 | Agent 的短期与长期记忆如何实现？ |
| written-ai-v1:ai_agent_rag:006 | Agent 与 RAG | Agent_Rag八股.pdf 5–5 | 工具价值 | 工具使用如何扩展大模型能力？为什么不能仅依靠文本生成？ |
| written-ai-v1:ai_agent_rag:007 | Agent 与 RAG | Agent_Rag八股.pdf 5–6 | RAG与Agent | RAG 与 Agent 的关系是什么？两者能否结合？ |
| written-ai-v1:ai_agent_rag:008 | Agent 与 RAG | Agent_Rag八股.pdf 6–7 | 多智能体 | 多 Agent 相对单 Agent 有哪些潜在收益与成本？ |
| written-ai-v1:ai_agent_rag:009 | Agent 与 RAG | Agent_Rag八股.pdf 7–7 | 行动幻觉 | 为什么 Agent 中的幻觉可能比普通对话错误更危险？ |
| written-ai-v1:ai_agent_rag:010 | Agent 与 RAG | Agent_Rag八股.pdf 7–8 | 具身智能 | 什么是具身智能？它与软件 Agent 有什么联系和区别？ |
| written-ai-v1:ai_agent_rag:011 | Agent 与 RAG | Agent_Rag八股.pdf 8–8 | 上下文瓶颈 | 上下文长度为什么限制 Agent？如何管理长任务状态？ |
| written-ai-v1:ai_agent_rag:012 | Agent 与 RAG | Agent_Rag八股.pdf 8–9 | 反思 | Reflection 机制如何帮助 Agent？为什么仍需要外部验证？ |
| written-ai-v1:ai_agent_rag:013 | Agent 与 RAG | Agent_Rag八股.pdf 9–10 | 结构输出 | Agent 为什么需要结构化输出？JSON 合法就足够吗？ |
| written-ai-v1:ai_agent_rag:014 | Agent 与 RAG | Agent_Rag八股.pdf 10–10 | 交互模式 | Copilot 与自主 Agent 在用户交互上有何不同？ |
| written-ai-v1:ai_agent_rag:015 | Agent 与 RAG | Agent_Rag八股.pdf 10–11 | 评估 | 评估 Agent 应考虑哪些维度和困难？ |
| written-ai-v1:ai_agent_rag:016 | Agent 与 RAG | Agent_Rag八股.pdf 11–12 | 成本延迟 | Agent 的成本和延迟主要来自哪里？怎样优化？ |
| written-ai-v1:ai_agent_rag:017 | Agent 与 RAG | Agent_Rag八股.pdf 12–13 | 工具实现 | 一个可靠的 Tool Use 流程应包含哪些步骤？ |
| written-ai-v1:ai_agent_rag:018 | Agent 与 RAG | Agent_Rag八股.pdf 13–13 | RAG定义 | RAG 的核心思想是什么？它会更新模型参数吗？ |
| written-ai-v1:ai_agent_rag:019 | Agent 与 RAG | Agent_Rag八股.pdf 13–14 | 三阶段 | 标准 RAG 通常包含哪三个主要阶段？ |
| written-ai-v1:ai_agent_rag:020 | Agent 与 RAG | Agent_Rag八股.pdf 14–15 | 微调比较 | RAG 与 Fine-tuning 各有哪些适用场景与限制？ |
| written-ai-v1:ai_agent_rag:021 | Agent 与 RAG | Agent_Rag八股.pdf 15–15 | 语义嵌入 | Embedding 如何支持语义检索？相似度高是否一定相关？ |
| written-ai-v1:ai_agent_rag:022 | Agent 与 RAG | Agent_Rag八股.pdf 15–16 | 向量数据库 | RAG 是否必须使用独立向量数据库？与关系数据库如何配合？ |
| written-ai-v1:ai_agent_rag:023 | Agent 与 RAG | Agent_Rag八股.pdf 16–16 | 评估维度 | 怎样分开评估 RAG 的检索质量与生成质量？ |
| written-ai-v1:ai_agent_rag:024 | Agent 与 RAG | Agent_Rag八股.pdf 16–17 | 工作流程 | 从用户提问到带引用回答，完整 RAG 链路如何组织？ |
| written-ai-v1:ai_agent_rag:025 | Agent 与 RAG | Agent_Rag八股.pdf 17–17 | 检索优化 | RAG 检索器可采用哪些优化策略？ |
| written-ai-v1:ai_agent_rag:026 | Agent 与 RAG | Agent_Rag八股.pdf 18–18 | 生成优化 | RAG 生成器如何更可靠地利用证据？ |
| written-ai-v1:ai_agent_rag:027 | Agent 与 RAG | Agent_Rag八股.pdf 19–19 | 收益 | RAG 有哪些收益？它是否天然保障隐私？ |
| written-ai-v1:ai_agent_rag:028 | Agent 与 RAG | Agent_Rag八股.pdf 19–19 | 局限 | RAG 常见失败原因有哪些？ |
| written-ai-v1:ai_agent_rag:029 | Agent 与 RAG | Agent_Rag八股.pdf 20–20 | 核心技术 | RAG 的关键技术是否只有向量搜索？ |
| written-ai-v1:ai_agent_rag:030 | Agent 与 RAG | Agent_Rag八股.pdf 20–21 | RAG三指标 | 上下文相关性、答案忠实度与答案相关性分别比较什么？ |
| written-ai-v1:ai_agent_rag:031 | Agent 与 RAG | Agent_Rag八股.pdf 21–22 | 检索指标 | Precision@k、Recall@k、MRR 与 nDCG 有何区别？ |
| written-ai-v1:ai_agent_rag:032 | Agent 与 RAG | Agent_Rag八股.pdf 22–23 | 生成指标 | 为什么不能只用 BLEU、ROUGE 或向量相似度评价 RAG 答案？ |
| written-ai-v1:ai_agent_rag:033 | Agent 与 RAG | Agent_Rag八股.pdf 23–23 | 工程指标 | RAG 的 TTFT、端到端延迟和拒答率怎样解释？ |
| written-ai-v1:ai_agent_rag:034 | Agent 与 RAG | Agent_Rag八股.pdf 23–24 | 应用 | RAG 在企业知识库、专业问答和个人记忆中应注意什么？ |
| written-ai-v1:ai_agent_rag:035 | Agent 与 RAG | Agent_Rag八股.pdf 24–25 | 混合检索 | 为什么组合 BM25、向量检索与重排序？ |
| written-ai-v1:ai_agent_rag:036 | Agent 与 RAG | Agent_Rag八股.pdf 24–25 | 查询改写 | Query Rewriting 怎样提高检索？有哪些风险？ |
| written-ai-v1:ai_agent_rag:037 | Agent 与 RAG | Agent_Rag八股.pdf 25–25 | GraphRAG | GraphRAG 的基本思想、优势与代价是什么？ |
| written-ai-v1:ai_agent_rag:038 | Agent 与 RAG | Agent_Rag八股.pdf 25–26 | AgenticRAG | Agentic RAG 与固定 RAG 流程有什么区别？ |
| written-ai-v1:ai_agent_rag:039 | Agent 与 RAG | Agent_Rag八股.pdf 26–27 | 检索问答比较 | 生成式 RAG 与传统检索或抽取式问答有什么区别？ |
| written-ai-v1:ai_agent_rag:040 | Agent 与 RAG | Agent_Rag八股.pdf 27–28 | 内容缺失 | 知识库有答案但 RAG 没答出，应怎样排查？ |
| written-ai-v1:ai_agent_rag:041 | Agent 与 RAG | Agent_Rag八股.pdf 28–29 | 格式错误 | RAG 输出 JSON 或引用格式错误时如何处理？ |
| written-ai-v1:ai_agent_rag:042 | Agent 与 RAG | 补充题 | 提示注入 | 如何防范检索文档或工具结果中的提示注入？ |
| written-ai-v1:ai_agent_rag:043 | Agent 与 RAG | 补充题 | 切片 | Chunk Size 与 Overlap 应如何设置？ |
| written-ai-v1:ai_agent_rag:044 | Agent 与 RAG | 补充题 | 工具重试 | Agent 执行有副作用的工具时，为什么需要幂等性与结果核验？ |
