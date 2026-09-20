# 事实约束与相邻分组

默认输入为视频、脚本和资产图：跳过初始试生成规划，登记视频来源组后直接进行匹配与审查，再运行 --post-review。已有视频可无脚本时长先抽帧审查；新版聚合前补齐计划时长和来源。PROFILE.json 可写 {}，按剧情聚合，固定每组 ≤15 秒、≤12 镜，不使用模型时长与成本限制。


代理从资产和原脚本提取有来源的事实，工具只计算结构化约束。不把抽取判断包装成数学确定性。

按 SKILL.md 的“一次整理完整输入”统一提取，后续复用，不逐镜或逐字段再次提取。输入类型、entity 允许范围及集中纠错以 [项目约定](project.md#一次校验与字段类型) 为准。来源不明仍保留 unknown/inference，不能为了减少往返升级成事实。

每镜 facts 示例：

```json
{"entity":"key","attribute":"holder","value":"girl","status":"known","phase":"before","critical":true,"source":{"kind":"script","ref":"S02 女孩递出钥匙，尚未交接完成"}}
```

phase 为 static/before/after；status 为 known/unknown，未知值可为 null。source.kind 为 script/asset/inference。屏幕左右与人物自身左右手分开，脚本未规定左右手时不擅自设为关键要求。

state_changes 保存 entity、attribute、before、after、critical、authorized、source。只有脚本授权变化才能更新期望状态，生成图中的错误不成为后镜基线。未知状态不是没变化；前后事实矛盾先核对来源。

intent 为 critical_result、narrative_turn、required_cut 三个布尔值。初始 omission_assessment 保留结构 allowed/risk/rationale/source，未判断时用 null/unknown 并说明未审查。审查后规划仅在副本里把当前 reference_assessments 转为补足约束，来源仍为 inference，不升级为脚本事实，也不修改原字段。最终省图走 planner.py --post-review；关键结果、关键状态变化、未知关键事实和锁定图受硬约束保护。

## 默认已有视频：审查后求解

完整结构化输入在 previs.py validate（包括 prepare_imported.py run）时，已提前复用 planner.analyze 的状态账本检查，集中报告 baseline_conflict、change_start_conflict、unexplained_after_state。规划时仍保留原检查。facts 与持久状态可以使用同一属性名；合法 before/after 和授权 state_changes 应相互吻合。冲突要回查来源、阶段及变化，不改成 *_note、删除事实或清空状态来绕过。旧项目缺规划字段仍按原兼容规则处理，不能把未检查当作已通过。

一次组级审查记录逐镜检验结果与推导依据，同组失败不影响其他镜头独立通过。已定位并通过或完整补查确认漏镜的非关键镜头，满足已通过前后保留锚点、资产支持及硬规则后可成为 ai_fill 候选；后者仍标视频漏镜，不能声称已通过。证据不足先补查，缺失镜头不能互作推导依据。

```text
python scripts/planner.py PROJECT.json PROFILE.json --post-review --output AGGREGATION.json
```

--post-review 不与 --apply 合用，不覆盖来源组、版本或时间映射。先自然初分、强制相邻合并、再复核小于 8 秒短段，event 不再是最终硬边界；只聚合相邻且 continuity_id 一致、来源边界通过的镜头，可以跨场景。整段复杂度不得由两两可合并无限外推。固定最终组后再优化保留图，保护首尾、关键状态和必要锚点。脚本计划时长十进制求和 ≤15 秒，每组 ≤12 镜；实际时间戳不参与求和。旧项目缺新字段先待规划；单镜超限明确提示，不截短或删镜。没有新增 LLM 判断或 API 调用，也不声称优化真实视觉质量。

详细判定、每份视频的必要漏镜阈值及证据失效见 [实证聚合](planning.md)。最终仅两张表与小分镜图，内部规划数据不交付。

## 旧生成模式：模型配置与求解（默认不执行）

assets/example-model-profile.json 是假设数据，实际运行查询模型准确能力与来源。填 max_images、min_duration、max_duration、allowed_durations（或 null）、aspect_ratios、allow_multi_shot、max_shots_per_group（最多 12），以及兼容字段 max_fill_per_group、video_cost_cny、missing_anchor_cost_cny。

旧资产生成模式枚举相邻、同场景、同连续事件的区间，以使用的资产数检查图片上限，以原镜计划时长之和检查时间限制，用动态规划选择可行的较低估价方案。没有最终分镜图也能先规划和生成。上传资产数与最终输出图数无关。

旧生成模式的审查后入口复用已有 anchor 区间规划：先验证每镜当前视频、匹配、选帧及组级 PASS，再执行首尾、关键结果、未知事实及锁定图保护；低风险补足位于已通过的前后 anchor 之间。ΔI 只是新增事实比例，不能独自决定省图。完整脚本及必要切镜不变。

```text
python scripts/planner.py PROJECT.json PROFILE.json --output PLAN.json --apply
```

只在未生成、未选择最终图的项目上使用 --apply。审查后用下列独立入口；--post-review 不可与 --apply 合用，不覆盖实际生成组、版本和时间映射。

```text
python scripts/planner.py PROJECT.json PROFILE.json --post-review --output AGGREGATION.json
```

规则依当前证据给出建议，不新增 LLM 取舍或付费提交。硬约束后优先较低估算视频成本，再减少保留图片数量；不计补图费用，因为此流程不补图。来源哈希变化后建议失效。模型约束下无可行方案则全部保留展示并标明限制；不得删除原镜头。最优性只针对本版同场景区间与可加估价，非真实画面质量。省图组合未经专项生成仍未验证。求解记录只内部保存。
