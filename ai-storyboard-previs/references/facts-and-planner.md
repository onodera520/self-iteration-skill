# 事实、状态与相邻分组

事实和省图约束与 [镜头要求](shot-requirements.md)、[分组规则](planning.md)一起使用。新项目一次整理全部镜头；complete 在当前审查后自动运行规划，无需另调用。

facts 记录 entity、attribute、value、status、critical、phase 与 source。entity 使用已声明资产、scene 或 continuity 实体；status 为 known／unknown，phase 为 static／before／after，source.kind 为 script／asset／inference，并说明出处。不把推断升级为脚本事实。

只用 requirements.entry_state 补尚未定义的持久状态种子，沿同 continuity_id 的 inherits_from 继承出口；state_changes 记录有来源且 authorized 的 before／after 变化。before 必须吻合入口；临时姿态放 keyframe，不另写出口快照。关键事实与变化须有剧情依据。

intent 的 critical_result、narrative_turn、required_cut 是三个布尔值。omission_assessment 使用 allowed／risk／rationale／source，未判断时 allowed=null、risk=unknown 并说明未审查，不因字段齐全自动批准。审查提供 reference_assessments，规划只在副本中转为约束，不改原 facts 或把建议升级为 script。

准备时集中检查 baseline_conflict、change_start_conflict、unexplained_after_state。持久状态与 facts 可用同名属性，合法阶段及授权变化应吻合；冲突回查来源与阶段，不能删事实、改成 note 属性或清空状态绕过。

需单独查看当前规划时：

```text
python scripts/planner.py PROJECT.json --output AGGREGATION.json
```

先按输入分组或剧情三步法确定完整合法区间，再优化保留锚点。保护首尾、场景边界、关键结果／变化、未知关键事实及用户锁定图；省图须同组双侧保留 PASS 与实际推导依据。优化的是结构约束下的参考图选择，不是对真实生成效果或全局视觉质量的证明。不新增模型或 API 调用。
