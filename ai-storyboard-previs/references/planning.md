# 分组与省图

## 已配对图片

全部图片按用户给定的镜序作为一个 G01 审查批次；Shot 分组与批次独立。每张原图继续展示和保存。省图只减少建议用于生成的参考图，不删除脚本镜头，不改变全批返修阈值的分母。

## 用户输入 Shot 分组

可用文字 `A01：S01–S03；A02：S04–S06`、前两列为分组／镜头顺序的 Markdown 表，或 JSON：

```json
{"input_shot_groups":[{"id":"A01","shot_ids":["S01","S02","S03"]},{"id":"A02","shot_ids":["S04","S05","S06"]}]}
```

新项目直接写入 INPUT；已有图片项目可用 `python scripts/grouping.py PROJECT.json SHOT_GROUPS.md --apply`，不带 --apply 只检查。保留用户编号、顺序及冲突，不自动排序或修复。null／未提供表示自动分组；显式空列表表示提供了空分组，报告漏号，不自动回退。

整批收集漏号、重复、未知镜号、乱序、非相邻、时长、镜数、Beat 及审查批次边界冲突。输入分组跳过自动初分、相邻合并和短段复核，不要求这些步骤专用的 event、narrative_plan 或 grouping_checked。仍保留每镜通用要求与状态。画面审查继续；冲突组及未分组镜头暂不省图，其余合法组可独立判断。分组冲突不成为画面 FAIL 或返修依据。

## 计划时长与剧情依据

沿用每镜 duration，duration_source.kind 为 script 或 inference，ref 写原文出处或建议依据。脚本未给时长才提出建议，不能冒称原值。所有镜头都参与覆盖和求和，包括待核查及 ai_fill。

只聚合同一 Beat 内相邻且 continuity_id 一致的镜头。明确 Beat 时逐镜填写 beat.id 与 source，覆盖全部镜头；未提供时全脚本视为一个隐式 Beat，不把 event.id 当作 Beat。Beat 不改变状态继承。

自动模式在一次通读中填写 event 和 narrative_plan。event 是初步自然段，可跨 scene_id；场景变化不自动拆组。narrative_plan 使用块级来源；boundaries 按原序覆盖全部相邻位置，merge_allowed 表示剧情允许承接，strength 为 0–3。safe_spans 提供认可复杂度的完整连续区间及具体理由；其子区间可复用，重叠区间不证明并集安全，不能从两两允许合并无限外推。

```json
{"source":{"kind":"inference","ref":"S01–S03：观察后交接属于连续事件"},"boundaries":[{"before_shot_id":"S02","merge_allowed":true,"strength":2,"reason":"同一关系下观察"},{"before_shot_id":"S03","merge_allowed":true,"strength":3,"reason":"立即交接"}],"safe_spans":[{"shot_ids":["S01","S02","S03"],"reason":"两人一把钥匙，完整区间只有一次交接"}]}
```

## 自动分组：先剧情，后选图

1. 找自然边界。景别、视角、运镜变化、局部特写、即时反应、情绪升级、同一行动与关系内主体切换、余波及短 OS/VO 优先承接。独立新事件、目标变化、时空跳跃、新主体持续主导或明显复杂度上升才作为切分依据，写具体原因。自然段超限制时在内部弱承接处拆分，同等条件取较长合法前段。
2. 检查相邻段二次合并。同 Beat、连续剧情自然承接且人物／空间／关系／视觉中心稳定，整段复杂度可接受，在 15 秒及 12 镜内继续合并。优先强承接，同等条件从前向后。不能停在 event 初分，也不能为了少用图决定剧情边界。
3. 复核小于 8 秒的短段。余波、结果、反应或起势优先并入承接更强的一侧，同等优先前组。独立事件、关键转折及受时长／镜数／Beat／连续性／复杂度约束者可保留，写明理由；仍须至少 4 秒。8 秒只是复核线。尾组不足 4 秒先重排合法切分，例如 13 个 1 秒镜可取 9+4，不能输出 12+1。

每组计划总长 4–15 秒且最多 12 镜，按十进制精确求和。单镜超过 15 秒、过短独立事件、缺时长或依据以及其他无解约束标 feasible=false，说明需调整的输入。自动模式用 P 编号待规划占位，不包装成合格 A 组；不得删镜、复制内容、补动作、跨 Beat 或静默改秒数。自定义自动规则意义不明时可回到原脚本连贯性判断，仍不得绕过上述约束；用户输入分组不走此兜底。

## 审查后的参考图选择

同一次图片审查提供 shot_reviews 和 reference_assessments。逐镜结论独立，组内部分 FAIL 不妨碍其他镜头保留。先固定合法最终组，再选择参考图。规划仅在副本中将审查转为约束，不改原 facts，也不将省图建议升级为 script。省图标准见 [图片审查规则](storyboard-review.md#资产对照与省图)。

组首尾、人物首次出现、场景边界、关键状态／空间变化、转折、关键结果、未知关键事实及用户锁定图作为必要锚点。普通微表情或局部手势不因单列一镜就成为关键；确有暗号、偷换等剧情作用仍保护。状态差分为零不独自证明可省图。

ai_fill 需该镜 PASS、同组双侧 PASS 且保留的原图锚点，按序夹住该镜，并有当前资产及明确可推导状态依据。不能以另一个 ai_fill 作依据或循环推导。FAIL、uncertain、依据失效或分组冲突均暂不省图。省图后故事须可读、无歧义；结论仍是未验证建议，不保证未来生成复现。

## 完整性与内部结果

submit／complete 已自动规划，不另调用。仅调试当前方案时使用 `python scripts/planner.py PROJECT.json --output AGGREGATION.json`。优化只针对结构约束下的参考图选择，不证明真实生成效果或全局视觉质量，也不新增模型或 API 调用。

工具核对全部原镜按序各出现一次、每组约束、组内时长与全批总时长守恒、Beat 及连续性，输入模式与用户分组完全一致。aggregation.clipGroupList 保存内部结果：shotId、originClipIdList、totalDuration、assetIdList。资产取原镜绑定并集，按项目资产原序，不猜新资产。

```json
{"clipGroupList":[{"shotId":"A01","originClipIdList":["S01","S02","S03"],"totalDuration":5.5,"assetIdList":["girl","boy","key"]}]}
```

无解时 clipGroupList 为空；输入模式保留原组及冲突，未分组镜头显示“—”。聚合独立保存，不覆盖来源批次。grouping policy=4；脚本、计划时长及来源、Beat、剧情依据、输入分组、资产、图片与审查进入指纹链，变化后重新核验。内部 JSON 不新增到交付目录，公开报告只展示分组编号。
