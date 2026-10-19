# 字段速查

保留 prepare 生成的 WORKLIST 结构和指纹；正常新任务用 `--concise` 生成版本4，SKILL 入口已列出普通校对字段，不另读本表。只有显式状态建模、省图或特殊证据需要扩展字段时再查，不遍历源码找字段。

| 位置 | 必填与易错点 |
| --- | --- |
| INPUT facts | 普通保留图校对可省略或 []，可见事实仍须写 observation.visible_facts。明确状态建模或省图时才填：entity 精确匹配 assets[].id（含场景资产，不能填 continuity_id）；attribute、value、status、critical、phase、source 齐全。status=known/unknown；phase=static/before/after；source={kind:script/asset/inference, ref:具体出处}。不要把整镜剧情写成 static 属性；没有对应资产的要求放 requirements，不造实体，不把推断升级为脚本事实。未填省图依据保守保留原图 |
| INPUT requirements | status=ready；keyframe={phase:entry/action/exit, description:当前参考阶段}；provenance=[{field:所支持字段, status:observed/user_provided/script/assumed/unknown, source:具体出处}]。provenance.status 与 facts.source.kind 不是同一组枚举；过程图不强制终态，参见审查规则 |
| INPUT state_changes | 普通校对可省略。已填写的真实变化仍须来源、authorized、before/after 及匹配的 requirements.entry_state 或明确继承；阶段及跨镜状态冲突在 prepare 检查，不等待 complete。不能为满足必填而编造变化或改名隐藏冲突 |
| 每镜结论 | verdict=PASS/FAIL/uncertain 明确覆盖主体内容、状态承接、参考可用性三组；reference_phase=entry/action/exit/unknown；PASS 的 match_level=0–3，其他为 null。未知阶段不得 PASS |
| observation.visible_facts | 非空字符串数组，复用首看已存事实，须支撑本镜判断。核心动作／表演可读而局部模糊或道具、脚下位置出框可通过，不把画外物体写成已看见；核心表演被构图整体排除或脚本明确朝向相反须记错误。有事实不代表已经通过 |
| findings | PASS/uncertain 为 []；FAIL 至少一项。每个错误只填写下列证据一次，程序生成 reason、issues、repair_assessments，不另写这些重复字段 |
| unresolved | 无疑点为 []；uncertain 至少一项 {check:具体项, reason:无法确认的必要信息}。不放大、不排复查；FAIL 也可保留其他疑点 |
| reference | 通常省略，由程序补保留图或暂不省图。仅建议省图时写 {decision:ai_fill, derivable:true, basis_shot_ids:[同组前镜,同组后镜], reason:明确推导理由}；双侧须 PASS 且保留，保护首尾及必要锚点，不自动降低省图门槛 |
| 根字段 | reviewed_groups 固定 content/state/reference；核对分组后 grouping_checked=true；无整体限制 limitations=[]。不另写全批 checks、issues 或 repair_assessments |

显式状态建模时，只用 requirements.entry_state 补新增持久状态种子，沿同 continuity_id 的 inherits_from 继承出口；state_changes 的 before 须吻合入口，并有来源与 authorized。出口由程序计算，临时姿态放 keyframe。critical 标记须有剧情依据。baseline_conflict、change_start_conflict、unexplained_after_state 在准备时集中检查；持久状态与 facts 可用同名属性，合法阶段及授权变化应一致。冲突回查来源与阶段，不能删事实、改成 note 属性或清空状态绕过。详细状态约定见 [镜头要求](shot-requirements.md#内部约定)。

扩展 omission_assessment 使用 allowed、risk、rationale、source，risk 可为 low/medium/high/unknown；未判断时 allowed=null、risk=unknown 并说明未审查。intent 的 critical_result、narrative_turn、required_cut 均为布尔值。字段齐全不代表省图已获批准，仍须实际审查及双侧依据。

FAIL 的 findings 每项：

```json
{"check":"props","script_quote":"男孩接住钥匙，女孩松手","actual":"结束阶段仍由女孩持钥匙","fix":"修改该分镜图为男孩拿稳钥匙、女孩松手，保留其他脚本内容","kind":"wrong_transfer_result","affects_story":true,"preserves_script":true,"impact":"交接完成的关键结果与脚本相反"}
```

check 为 identity/scene/props/composition/key_state/continuity/cleanliness 之一；引文逐字来自同镜脚本，actual 写可见不符，含构图整体排除核心表演，fix 保留原意。此类构图错误通常用 composition、ordinary，不自动记关键错误或严重损坏。kind=ordinary 表示普通明确错误，affects_story 显式 true/false，preserves_script=true；普通错误不必另写 impact，程序复用引文与不符事实。关键错误 kind 为 missing_key_node/wrong_actor/broken_causality/wrong_transfer_result/explicit_key_requirement，须 affects_story=true 并明确 impact。严重损坏 kind=severe_visual_damage，另写 impact、damage_description、obscured_content；原图 SHA 自动绑定。分类来自实际判断，不能从文字自动猜测。

默认 asset_comparisons=[]，不为填字段打开原资产。只有用户明确要求资产外观对照时才写：id、shot_id、asset_id、aspect=wardrobe/appearance/prop/scene、decision。PASS 写 stable_matches；FAIL 写 stable_conflicts=[{feature,expected,observed,environment_exclusion}] 并在 finding 的 asset_ids/asset_comparison_ids 关联；uncertain 写 unobservable_features 与 followup。人物对照另写 story_requirement，非 PASS 写 story_impact。程序补来源哈希和同镜证据，不代填判断。

一次填写完直接 complete。保留原图扩展名与字节，输入打不开先修正，不计剧情 FAIL。版本1/2/3仍可恢复；其独立 checks、issues、repair_assessments 格式仅旧任务需要，见 [图片接口](storyboard-images.md)及 [返修依据](repair-assessments.md)。
