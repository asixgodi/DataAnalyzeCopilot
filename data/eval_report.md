# 评估报告

生成时间：2026-05-13 04:09:04 UTC

## 总体指标

| 指标 | 值 |
| --- | --- |
| 测试用例总数 | 95 |
| 任务成功率 (task_success_rate) | 0.137 |
| 路由准确率 (route_accuracy) | 0.726 |
| 关键词召回率 (keyword_accuracy) | 0.316 |
| 工具调用准确率 (tool_call_accuracy) | 0.358 |
| SQL 执行成功率 (sql_execution_success_rate) | 1.0 |
| 文档引用命中率 (citation_hit_rate) | 1.0 |
| 平均延迟 (avg_latency_ms) | 1305.47 ms |
| 平均工具调用次数 (avg_tool_calls) | 1.15 |
| 重试成功率 (retry_success_rate) | N/A |

## 分类指标

| 分类 | 总数 | 通过 | 通过率 |
| --- | --- | --- | --- |
| sql | 20 | 0 | 0.0 |
| rag | 20 | 4 | 0.2 |
| hybrid | 25 | 0 | 0.0 |
| clarification | 10 | 6 | 0.6 |
| memory | 10 | 0 | 0.0 |
| rag_plus | 5 | 1 | 0.2 |
| ambiguous | 5 | 2 | 0.4 |

## 难度指标

| 难度 | 总数 | 通过 | 通过率 |
| --- | --- | --- | --- |
| easy | 31 | 9 | 0.29 |
| medium | 41 | 3 | 0.073 |
| hard | 23 | 1 | 0.043 |

## 失败用例明细

- **sql-001**: 4月服装类商品退款率是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-002**: 3月退款次数最高的商品是什么？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: True / 工具: False

- **sql-003**: 5月鞋靴类商品的订单数是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-004**: 4月数码类商品的退款率是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-005**: 3月服装类客服工单原因分布是什么样的？
  - 预期路由: sql / 实际路由: hybrid
  - 路由匹配: False / 关键词: False / 工具: False

- **sql-006**: 5月鞋靴类退款金额最高的3个商品是什么？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-007**: 4月工单量最高的退款原因是什么？
  - 预期路由: sql / 实际路由: hybrid
  - 路由匹配: False / 关键词: True / 工具: False

- **sql-008**: 查询5月数码类商品的总退款金额。
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-009**: 3月所有类目的退款率分别是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: True / 工具: False

- **sql-010**: 4月有哪些商品产生了超过5次退款？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-011**: 5月退款率对比4月是上升还是下降了？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-012**: 3月服装类商品的平均评分是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-013**: 4月P1级别的客服工单有多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-014**: 5月鞋靴类退款率排名第几位？和服装类对比如何？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-015**: 列出4月订单金额最高的5笔订单。
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-016**: 3月数码类被拒绝的退款申请有多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-017**: 4月服装类中退款原因分布，按次数从高到低排序。
  - 预期路由: sql / 实际路由: hybrid
  - 路由匹配: False / 关键词: False / 工具: False

- **sql-018**: 5月哪个类目的订单量最大？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-019**: 查询4月数码类产生客服工单的订单占比。
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **sql-020**: 3月到5月每个月的退款金额总额是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **rag-001**: 退款率指标口径是什么？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: True / 工具: True

- **rag-002**: 服装类商品的退款规则是什么？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: False / 工具: True

- **rag-003**: 客服工单的分类标准有哪些？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: False / 工具: True

- **rag-006**: 物流延迟发货怎么补偿？
  - 预期路由: rag / 实际路由: rag
  - 路由匹配: True / 关键词: False / 工具: True

- **rag-007**: 商品质量异常监控的阈值是什么？
  - 预期路由: rag / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-008**: orders表的字段有哪些？
  - 预期路由: rag / 实际路由: clarification
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-010**: P1工单包括哪些类型？
  - 预期路由: rag / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-011**: 数码类商品正常的退款率范围是多少？
  - 预期路由: rag / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-012**: Agent分析时需要输出哪些内容？
  - 预期路由: rag / 实际路由: clarification
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-013**: 物流丢失的处理流程是什么？
  - 预期路由: rag / 实际路由: rag
  - 路由匹配: True / 关键词: False / 工具: True

- **rag-014**: 鞋靴类商品退款的主要原因有哪些？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: False / 工具: True

- **rag-015**: FCR是什么指标？低于多少需要优化？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: True / 工具: True

- **rag-016**: 钻石会员的极速退款需要什么条件？
  - 预期路由: rag / 实际路由: rag
  - 路由匹配: True / 关键词: False / 工具: True

- **rag-017**: 工单升级到P0的条件是什么？
  - 预期路由: rag / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-019**: 物流问题导致的退款如何统计？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: True / 工具: True

- **rag-020**: 当分析信息不足时Agent应该怎么做？
  - 预期路由: rag / 实际路由: clarification
  - 路由匹配: False / 关键词: False / 工具: False

- **hybrid-001**: 4月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-002**: 5月鞋靴类客服工单中哪些原因最多？这和售后SOP的归因流程怎么对应？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-003**: 3月数码类退款率是否超过异常阈值？需要触达什么处理流程？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-004**: 4月服装类商品的差评率和退款率有什么关系？参考质量控制规则分析。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-005**: 5月有哪些商品退款率超过类目预警线？请结合类目指标参考给出判断。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-006**: 4月客服工单中P1级别占比是多少？按照工单升级规则是否需要升级处理？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-007**: 3月鞋靴类退款主要原因是什么？结合鞋靴类售后特点给出改善建议。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-008**: 5月退款金额最高的3个商品分别属于什么类目？这些类目的退款政策是什么？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-009**: 4月数码类商品有没有触发质量异常？根据质量监控指标判断。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-010**: 3月服装类的退款原因分布和指标口径怎么对照？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-011**: 5月整体退款率是多少？根据类目指标参考是否有类目需要预警？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-012**: 4月有哪些退款原因是物流相关的？这些退款按物流政策怎么处理？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-013**: 查询3月好评率最低的商品，并分析是否需要触发品控抽检。
  - 预期路由: hybrid / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **hybrid-014**: 4月服装类中退款次数最多的商品是什么？根据商品分类说明这个商品可能存在什么问题？
  - 预期路由: hybrid / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **hybrid-015**: 5月所有类目中哪些退款原因连续上升？需要按售后SOP启动什么归因流程？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-016**: 3月鞋靴类退款率是否在正常范围内？如果不正常，结合质量控制规则应该怎么处理？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-017**: 4月数码类的工单率是多少？根据质量监控指标FCR标准是否需要优化客服流程？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-018**: 对比4月和5月服装类的退款率变化，结合政策分析可能的原因并给出建议。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-019**: 5月哪些商品关联的客服工单中出现了批量质量投诉？按P0升级规则应如何处理？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-020**: 3月退款率最高的类目是什么？这个类目的售后处理SOP有什么特殊要求？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-021**: 4月服装类退款中色差原因占比多少？根据退款政策应该怎么排查？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-022**: 5月鞋靴类商品的订单退款率和客服工单率之间有什么关联？结合数据分析规范给出推理。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **hybrid-023**: 3月数码类商品有没有因为续航问题导致的退款？续航问题按照退款原因标准属于哪一类？
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: True / 工具: False

- **hybrid-024**: 4月所有类目按退款率从高到低排序，各类目的预警阈值分别是多少？
  - 预期路由: hybrid / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **hybrid-025**: 查询5月产生退款最多的商品，检查它的评价内容和退款原因是否一致，并给出整改方案。
  - 预期路由: hybrid / 实际路由: hybrid
  - 路由匹配: True / 关键词: False / 工具: False

- **clarify-003**: 帮我看看售后情况。
  - 预期路由: clarification / 实际路由: clarification
  - 路由匹配: True / 关键词: False / 工具: True

- **clarify-004**: 有什么问题吗？
  - 预期路由: clarification / 实际路由: clarification
  - 路由匹配: True / 关键词: False / 工具: True

- **clarify-006**: 数据怎么样？
  - 预期路由: clarification / 实际路由: clarification
  - 路由匹配: True / 关键词: False / 工具: True

- **clarify-009**: 看看订单。
  - 预期路由: clarification / 实际路由: clarification
  - 路由匹配: True / 关键词: False / 工具: True

- **memory-001**: 4月服装类商品退款率是多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: True / 工具: False

- **memory-002**: 那鞋靴类呢？
  - 预期路由: sql / 实际路由: clarification
  - 路由匹配: False / 关键词: False / 工具: False

- **memory-003**: 这个月和上个月对比呢？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **memory-004**: 3月数码类客服工单有多少？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **memory-005**: 这些工单中P1级别的占比呢？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **memory-006**: 退款率指标口径是什么？
  - 预期路由: rag / 实际路由: hybrid
  - 路由匹配: False / 关键词: True / 工具: True

- **memory-007**: 那鞋靴类的正常退款率范围呢？
  - 预期路由: rag / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **memory-008**: 5月退款次数最高的3个商品是什么？
  - 预期路由: sql / 实际路由: sql
  - 路由匹配: True / 关键词: False / 工具: False

- **memory-009**: 这些商品都属于什么类目？各有什么问题？
  - 预期路由: hybrid / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **memory-010**: 给我分析一下原因并提出改善方案。
  - 预期路由: hybrid / 实际路由: rag
  - 路由匹配: False / 关键词: False / 工具: True

- **rag-plus-001**: 金卡会员的退款流程是什么样的？需要参考哪些政策？
  - 预期路由: rag / 实际路由: rag
  - 路由匹配: True / 关键词: False / 工具: True

- **rag-plus-002**: 物流破损签收的处理流程和普通退款政策有什么不同？
  - 预期路由: rag / 实际路由: rag
  - 路由匹配: True / 关键词: False / 工具: True

- **rag-plus-003**: 对比服装类和数码类的售后特点，哪类商品的售后处理更复杂？
  - 预期路由: rag / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: False

- **rag-plus-005**: 会员等级如何影响退款处理时效？从普通到钻石会员的权益有哪些差异？
  - 预期路由: rag / 实际路由: rag
  - 路由匹配: True / 关键词: False / 工具: True

- **ambiguous-001**: 退款件数多不多？
  - 预期路由: clarification / 实际路由: clarification
  - 路由匹配: True / 关键词: False / 工具: True

- **ambiguous-002**: 商品质量怎么样？
  - 预期路由: clarification / 实际路由: sql
  - 路由匹配: False / 关键词: False / 工具: True

- **ambiguous-004**: 客服处理得好不好？
  - 预期路由: clarification / 实际路由: clarification
  - 路由匹配: True / 关键词: False / 工具: True
