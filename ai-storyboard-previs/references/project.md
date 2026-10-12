# 内部数据与用户交付

默认以 [已有视频三镜模板](../assets/imported-project.json) 建立内部项目；[旧兼容示例](../assets/example-project.json) 保留供旧流程使用。用户提供视频、原脚本、资产图，可选提供 Shot 分组与原视频提示词，不必填 JSON。一次整理完整脚本后统一校验，来源不明保留 unknown/inference；路径相对项目文件或使用绝对路径。模板只示范结构与建议时长，不含真实图片、视频或已通过的审查结论，必须替换为本次脚本与资产。

## 一次校验与字段类型

填写项目之前先运行 `prepare_imported.py preflight --script 原脚本 --video 原视频 --asset 图1 --asset 图2`（每张原资产重复一个 --asset，保持顺序）。它一次列出缺失、空文件或不可读路径，不解码、不做语义判断，也不提供可跳过后续 SHA256 的凭据。路径失效先从用户指定目录定位真实文件并核对来源，不按文件名自动替换。

整理完成后使用 `prepare_imported.py run PROJECT.json G01 INPUT.mp4 EVIDENCE_DIR --run-dir PREPARE_INTERNAL_DIR`。入口先统一校验，再登记视频、冻结 baseline、稀疏抽帧；无需事先重复执行独立 validate。同次校验先检查对象、数组、必填字段与编号，再检查状态继承、来源及剧情分组；一次汇总当前能可靠判断的独立错误，按字段路径集中修正。不要逐镜校验，也不要另开一轮 LLM 字段预检。单独诊断仍可用 `previs.py validate`；错误返回非零退出码。

复用上一次任务留下的旧项目时，先运行 `previs.py validate`：通过才可沿用；未通过时，把本次输出的完整 ERROR 列表当作一次性修正清单，一次改完再重跑，或在本次输入可用时直接重建项目。禁止在未通过校验的旧项目上边跑边逐条试错（每发现一个 ERROR 才改一处），也禁止清空字段补空状态来绕过校验。

`ERROR` 是已确认的结构/语义问题；`BLOCKED` 是因上游无效暂不能完成的检查。前镜状态无效时，不补空状态、不伪造出口状态来继续推算；独立镜头继续检查，依赖镜修正上游后再验证。缺少本地图片仍按原约定返回 missing_assets/missing_anchors，与 JSON 错误分开；真实证据、SHA256 和付费安全检查仍在使用前执行，不以本次校验替代。

常见输入类型：

| 字段 | JSON 类型与约定 |
| --- | --- |
| facts / state_changes | 对象数组；facts 非空，state_changes 无变化用 `[]`，不是字符串 |
| facts[].entity / state_changes[].entity | 必须逐字匹配 `assets[].id`，不是 description、镜号、event.id 或随意命名的剧情实体；attribute 是非空字符串 |
| requirements.entry_state / keyframe.state | 对象；无新增入口种子用 `{}`；不手写 exit_state |
| requirements.must_have / must_not_have | 字符串数组，例如 `["男孩接住钥匙"]` |
| requirements.provenance | 来源对象数组；每个要求块一条来源 |
| duration_source | 每镜计划时长来源；两种分组模式均需填写 |
| event / narrative_plan | 自动分组模式的剧情依据；有输入 Shot 分组时不要求填写，格式见默认模板 |
| beat（可选） | 对象：id＋source；显式提供时覆盖全部镜头，否则全脚本按一个 Beat 处理 |
| repair_asset_style.assets[].visible_style_facts | 非空字符串数组，不能把整个列表写成一段字符串 |

先固定资产 ID 清单，再写所有镜头的 entity。属性属于谁就引用谁（例如人物的缺氧状态引用该人物 ID）；不存在对应资产的剧情要求保留在有来源的 requirements 描述与必要画面要求中，不硬套无关角色、不伪造资产、不丢弃剧情要求。当前版本不支持独立 story_entities，不能靠新增同名字段绕过约束。

准备入口持有同一 `.lock`，任一步失败立即停止，成功保存的前序阶段保留。它显式拦截 missing_assets，并重新核对全部资产文件；首轮还没有抽帧时 missing_anchors 是预期情况，不当作已通过画面。EVIDENCE_DIR 和 PREPARE_INTERNAL_DIR 必须是互不嵌套的新目录。内部 PREPARE_REPORT.json 记录失败阶段和机械耗时；失败后先修正原因，再换新目录重跑，当前视频路径、版本、组指纹及哈希仍一致才复用已有登记，baseline 不可改写。此入口不执行匹配、审查、生成或付费，也不改变脚本和采样策略。

`repair_asset_style` 是返修专用的资产风格数据，所有默认校对项目都可延后准备，基础模板不伪造 SHA256。完整脚本、shot_design 和原文基线仍在准备阶段整理并冻结；普通审查使用资产描述及真实帧事实。达到返修阈值、准备输出新提示词时，利用原图或有效中性观察一次补齐风格数据，重新运行 decide 绑定当前风格后才 export-prompt；不得改写冻结基线。一旦填写仍检查格式，导出前仍核对完整资产覆盖及当前哈希。精确片段如下（sha256 必须替换为工具实测值）：

```json
{
  "repair_asset_style": {
    "assets": [{
      "asset_id": "girl",
      "sha256": "填写工具计算的当前资产 SHA256",
      "visible_style_facts": ["人物外套为黄色", "背景为浅色"],
      "guidance": "沿用原资产的整体视觉风格，不改变脚本剧情"
    }],
    "preserves_story": true
  }
}
```

以上只是字段格式示意，真实内容必须来自本次资产，不复制示意中的观察。imported_videos、board_mappings、board.selected、reviews、aggregation 和实际证据哈希由现有工具流程登记，不从模板伪造已通过状态。

## 输入及内部状态

- schema_version: 1、title、source_script：保留原始依据。
- assets: id/kind/description/path，kind 为 character/scene/prop；审查阶段本地比对，不冒充视频抽帧；授权固定工作流返修时保持全部原始顺序上传。
- shots: id/script/scene_id/continuity_id/asset_ids/required_result；script 逐字保存本镜原文（含标点换行），不摘要；保持原镜序。imported 模式可先省略 duration 抽帧审查；最终聚合须填写正数计划秒数及 duration_source（kind: script 或 inference，ref: 原文出处或建议依据）。缺原文时长时代理提出建议并明确标注，不从实际视频冒充脚本值。shot_size 只填脚本明确景别；keyframe.description 保留关键画面要求。
- input_shot_groups：可选独立输入，接受分组表、文字或 JSON，工具规范化为有序的 id/shot_ids 列表。null 或不填沿用自动分组；空列表是冲突，不自动回退。固定采用用户分组，集中报告漏号、重复、乱序、不相邻、4–15秒、12镜、Beat 和跨来源边界冲突；只阻止受影响范围省图，不更改画面结论或返修额度。格式与导入见 [规划约定](planning.md#用户输入-shot-分组)。
- shots[].event：自动分组的新项目每镜填写 `{"id":"E03","summary":"推门、到门外开伞并追出，构成连续行动","source":{"kind":"inference","ref":"S07 推门与 S08 门外开伞追出属于连续行动"}}`。id 为非空字母、数字、下划线或连字符组成的编号；同编号 summary 一致，source 沿用 script/asset/inference 分级。event 只提供初步自然段，不替代 scene_id/continuity_id 或状态继承。自动分组旧项目允许全部不填，不能只填部分镜头；有输入 Shot 分组时不要求 event，已填字段仍须格式有效。
- shots[].beat：输入明确给定 Beat 时填 `{"id":"B01","source":{"kind":"script","ref":"原文 Beat 1"}}`，id 为字母、数字、下划线或连字符；source 为 script/inference 并说明出处。一旦显式使用，每镜都必须填写；未提供则全脚本视为一个隐式 Beat，不从 event 自动推导。不同 Beat 不合组，状态继承仍按 continuity_id 计算。
- narrative_plan：完整脚本的相邻承接、自然边界与整段复杂度依据，结构及三步规则见 [规划约定](planning.md)。不改变状态继承；仅自动分组要求此字段；缺少时允许审查，但不能交付自动合格聚合。输入 Shot 分组不要求此字段。
- facts/state_changes/intent/omission_assessment：按 [事实规则](facts-and-planner.md)。requirements 按 [镜头要求](shot-requirements.md)，代理仅写入口种子和变化，工具计算完整状态。每镜 requirements 要求块一条 provenance，其他来源分级不变。
- reference：保留兼容 mode: anchor|ai_fill、path、role、reason、locked。它不是新的审查结论；最终读取独立 aggregation。
- groups：id/shot_ids/reason/version；一份输入视频对应一个来源组，列应覆盖的连续镜头。所有来源组顺序拼接必须恰好覆盖脚本一次。不得为降低漏镜占比修改应覆盖范围。
- config：workflow: video_evidence、video_source: imported、video_input_mode: assets、delivery_mode: storyboard_images、aspect_ratio。固定工作流的新返修请求以当前来源视频的实际显示画幅覆盖本次请求参数，不回写此配置；宽高、像素比例、旋转与来源 SHA256 由工具探测并存入请求的 input_aspect，不由代理手填。missing_policy 可省略，默认 min_count: 2、min_ratio: 0.2；两者用于必要漏图的内部诊断，不作为最终视频返修门槛；最终采用独立的关键问题、严重画面损坏及普通剧情问题阈值。保留 max_repair_rounds/max_submissions/budget_cny 等安全字段。新项目模板保留 max_submissions=1，作为旧付费入口的上限，不代表自动授权。默认只导出新视频提示词，不占提交额度，不受零额度或预算阻挡；不修改这些字段。既有项目的预算、零额度及次数限制继续约束实际生成，不清空已有预算。可选 fixed_workflow_limits.max_duration_seconds 存已确认的工作流时长上限。
- imported_videos：import-video 登记 target_id/version/source: user_video/outputs/output_hashes/group_fingerprint/duration。duration 为原视频实测范围，只用于抽帧及证据定位。独立于付费 tasks，替换视频后旧证据失效。
- board_mappings：全组 matched/uncertain/absent，候选路径、实际时间、SHA256、observation。绑定视频、来源组及 evidence.json 哈希；完整补查确认 absent 时另填 full_rescan: true、rescan.ranges 和 rescan.observation，范围须覆盖整份实测视频。缺失镜头 candidates 为空，不能伪造对应帧。
- map 输入可带 selections 数组，批量原子登记映射及选帧，不增加 LLM 判断。对疑似把前镜延续当独立镜头的行，明确 independent_visual_unit: false；该行不得 matched，先补查。实际不同事件可在同一连续长镜中成立，需各自可见证据，不以时间递增冒充独立镜头。
- 抽帧 evidence.json 含 sampling（稀疏/局部密采/显式全片密采、实际补帧范围）、candidate_segments、contact_sheets 和可选 base_evidence。补帧 frames 保留完整证据，new_frame_paths 列本次新增帧；contact_sheet_scope: new_frames 时默认联系表只展示新增内容。context_contact_sheets 是少量旧邻帧导航；full_contact_sheets 可用 --full-contact-sheet 按需生成。联系表仅导航，sampling 不代表已回看；旧无这些字段的有效证据仍可审查。补帧用新证据目录，旧帧逐个校验哈希后复用，映射改绑新证据指纹；观察可复用，旧审查不可自动升级。
- 增量补查内部报告 incremental_review.json 保存旧有效 context、补帧证据哈希、mapping_draft 和受影响清单。完成一次批量 map 后，context --incremental-from 报告路径输出当前上下文、旧观察和可复用的部分 review_draft；补齐后仍走完整 review 校验。报告和草稿均不代表通过，不进入用户逐镜表交付。详见 [增量补查](review.md#增量补查与批量登记)。
- shots[].board.selected：选帧 path/sha256/source.kind: frame/source.time/reason；history 保存历史选择。当前有效图必须属于当前 matched 候选。
- reviews：三项组级 checks（shot/continuity/story，不含屏幕文字）、按顺序的 shot_reviews、coverage.shot_ids/mapping_verified/limitations、带路径/哈希/时间的 evidence.observation、issues、uncertainties、boundary_checks、reference_assessments 和 context_fingerprint。imported review_schema 为 5；仅自动分组且有 narrative_plan 时必须 grouping_checked: true，确认同时核对剧情分组与整个合并区间复杂度；不要求 actual_shots 或每镜时长区间。详见 [审查结构](review.md)。
- shot_reviews：每镜 verdict: PASS|FAIL|uncertain|absent、reason、evidence_times；已定位镜须含七项 checks。一镜 FAIL 不妨碍其他镜独立 PASS；受影响的连续性边界仍须核对。漏镜不可 PASS。
- reference_assessments：每镜 decision: anchor|ai_fill|pending、reason、evidence_times、derivable: true|false|null、basis_shot_ids。decision 是参考图取舍候选，独立于 mapping.status 与 shot_reviews.verdict；组合须遵守 [审查决策表](review.md#可推导省图判据与决策表)。ai_fill 须列按镜序前后夹住本镜的两个合格依据镜，优先选最近且足以支持剧情判断的 PASS＋anchor 锚点；最近是建议而非工具硬约束，选较远依据须说明原因。依据必须独立 PASS、保留图且有有效资产支持；reason 须说明省去独立图后故事仍可读且无歧义，不要求唯一复原手势或微表情；关键剧情节点保护，纯表演细节不自动保护。漏镜不填本镜帧证据，改引用完整补查和依据镜。没有可靠结论填 null，不计必要漏镜；已明确必须保留则填 false 并说明依据。连续缺失的镜头不能互为依据，应向外寻找合格双侧锚点；仍缺一侧且判断不足填 null，已知必须保留填 false。最终规划仍检查候选的必要锚点约束。所有省图均为建议/未验证。context.reference_policy_version 纳入指纹，旧结论需按当前判据复核。
- tasks/repairs/repair_round：保留旧生成与新增固定工作流返修记录，不清空历史绕过安全限制。user_video_prompt 为旧生成模式字段，默认不需要。
- source_video_prompts：可选的原视频生成提示词，按来源组编号保存 text、text_sha256、video_sha256，由 repair_reference.py 登记。repair_prompt_references：达阈值准备新提示词时一次填写的同源、同脚本筛选依据；普通审查无需填写。不把两字段放入 group，不作为成片证据，也不改变视觉审查和聚合指纹。原文及筛选只进入返修请求快照；格式见 [原视频提示词参考](auto-repair.md#原视频提示词参考)。
- repair_baseline / repair_decisions / repair_deliveries：冻结脚本原文、独立机读判定、原视频与历史实际返修各自不可覆盖的交付快照。repair_assessments 在原有组级审查内记录，repair policy=3 与脚本/资产/视频/审查/聚合指纹绑定，详见 [提示词与历史任务](auto-repair.md)。旧判定须重算，不自动升级；有效审查和聚合可复用，已提交任务仍严格恢复原请求。video_format_requirements 可选，须为 source_script 中全局格式要求的逐字摘录。

- repair_prompt_exports：按来源组保存用户提示词文件路径/哈希、内部请求快照路径/哈希、请求和判定指纹及 binding。文本导出记录独立于 tasks，不占提交额度，不改执行状态；过期记录只留历史，不能支持新请求。

- shots[].shot_design：一次整理从脚本摘取的镜头设计，与原文一并冻结；缺省只用已有景别或标未指定，不新增机位。repair_asset_style：达阈值导出提示词前按原资产顺序保存 asset_id、sha256、visible_style_facts、guidance 和 preserves_story，重新绑定返修判定；普通审查不提前要求此专用表单。详见 [受控提示词](auto-repair.md#受控提示词)。返修每镜固定 1.0s、总长为来源镜数 ×1 秒，含漏镜和 ai_fill；不覆盖原脚本 duration 或改变逐镜表计划时长。内部请求 prompt_version=5；blocks.text 保留冻结原文，generation_text 为来源绑定的纯视觉视图，不写回脚本。原提示词经同镜脚本核对的补充保存在 blocks.input_prompt_guidance，已转换的公共格式要求保存在 format_requirements。prompt_fingerprint 绑定版本、内部提示词与逐镜块，完整请求另有指纹；内部时长标签为【生成时长】，交付模板为【时长】1s，原头部计划时长不嵌套进正文。交付将修正、关键变化及目标静帧说明融入镜头内容，只保留必须／不得出现标签；内部绑定和逐镜字段不删。旧请求恢复和文件保留见提示词与历史任务规则。固定预演段与真实资产风格均不可由临时请求覆盖。

## 精简审查文件

storyboard.py prepare-map 在匹配前输出 matching-view-1 视图与 matching-worklist-1 工作单：完整要求、计算状态、资产、边界和全部抽帧集中列出，帧用 F 编号关联。工作单的 base_digest 绑定当前视图，按原序填写全部镜头的 status/observation、candidates（frame_id/observation/visible_facts）及 selection（frame_id/reason 或 null），不手填路径、时间、SHA256。map --view 恢复精确绑定后原子登记映射与选帧；证据或输入变化拒绝旧编号。工具不作视觉判断；旧完整映射与补查入口兼容。

review_draft.py prepare 一次输出完整 CONTEXT.json、REVIEW_DRAFT.json、只读 REVIEW_VIEW.json 和精简 WORKLIST.json。精简视图仍覆盖全部候选、连续帧、要求、资产、完整计算状态及左右边界；F 编号集中索引帧，E 编号索引草稿证据，详细 SHA256 保留在完整文件。read --index/--event/--shots 可先读索引再按事件或镜号读取，保留范围内全部候选、计算状态、邻镜和外部边界，明确列出未读内容及整组检查要求；不自动认定内容已读或允许部分审查。读取入口验证冻结上下文和当前证据一致，不改项目。工作单 format: review-worklist-2 与 base_digest 绑定固定草稿，只填明确判断及事实增量；FAIL/absent 的返修依据不能省。fill 由原草稿恢复完整绑定，走原完整校验，仍须 review 登记。匹配 F 编号和审查 F/E 编号各绑定各自视图，不能跨视图混用；编号或省略空模板不改变 review_schema/reference_policy_version，旧完整工作单兼容。详细约定见 [执行提效](efficiency.md#工作清单与协调草稿)。

## 资产审查证据版本

已有视频组级审查使用 review_schema: 5、reference_policy_version: 5，两者纳入 context_fingerprint 并保存在审查记录。review_scope.screen_text/subtitles 为 false，reference_omission_basis 为 story_readable_without_ambiguity；visual_match_basis 为 narrative_equivalence，允许非关键视觉差异，同时保留明确严格要求；reason/interpretation 复用现有字段说明剧情判断，不新增逐镜调用。旧版本（包括没有版本/上下文的记录）不能支持当前审查或聚合；有效原始抽帧、匹配、SHA256 可复用，旧自由文字 observation 不自动升级。

evidence 包含非空 visible_facts 和 interpretation，保留 observation 摘要及 shot_id/path/sha256/time，继续绑定当前视频。shot_reviews 每镜增加 identity_reason；普通通过不要求 identity_scope 或逐人外观比较。asset_comparisons 默认为 []，仅剧情相关外观要求/问题填写；详细字段见 [审查规则](review.md#资产外观判定剧情优先)。人物比较写 story_requirement，FAIL/uncertain 另写 story_impact。既有稳定冲突、逐镜资产/帧/时间绑定与问题引用门槛保留，但普通服装或脸部差异不单独判失败。

问题必须显式填 asset_ids、asset_comparison_ids（非资产问题均为空），多镜资产问题逐镜绑定。工具检查结构和关联，不是视觉真实性检测器。不新增 confidence，不更改用户逐镜表交付。缓存观察只在同哈希且内容有效时复用；解释被新证据推翻时重新校对受影响镜头与衔接。

## 独立聚合与失效

planner.py --post-review 在副本内处理规则，仅保存 p.aggregation；旧建议留在 aggregation_history。原 groups、视频版本、匹配时间和 tasks 不被覆盖。

groups 使用 A01 等编号、shot_ids、reason、source_group_ids；新版 imported 聚合含 planned_duration（计划总秒数）、duration_has_suggestion、planning_status、beat_id（未显式提供时为 null）。合格组为同一 Beat 内4–15秒、≤12镜的连续区间。有 input_shot_groups 时保留输入编号、顺序及冲突，未分配镜头显示“—”，不生成替代分组；自动模式 feasible: false 时使用 P 编号待规划占位，不把不满足时长或剧情约束的占位包装为合格组。grouping_trace 在输入模式保存集中冲突，在自动模式保存自然初分、相邻合并、必要的切分位置重排和短段复核，用户不必阅读内部记录。clipGroupList 保存同构的内部 JSON 清单：shotId、originClipIdList、totalDuration、assetIdList；按原镜序覆盖一次，时长守恒，资产取原镜绑定的并集并保持项目资产顺序；无解时为空。decisions 包含 shot_id/group_id/source_group_id/mode/status/reason/bracket/frame/mapping_status/review_verdict/issues。

状态含义：anchor_reviewed 为检验通过保留图；ai_fill_suggested_unverified 为该镜通过且建议省图；absent_fill_suggested_unverified 为确认漏镜但可推导，未验证；mismatch 为该镜需重新生成；missing_required 为必要漏镜；pending 为证据或推导不足。mode 分别为 anchor/ai_fill/pending，不等于视频是否通过。

missing_summary 按来源视频记录 bad_num/total/ratio/regenerate，仅作为参考图必要缺失的内部诊断保留。bad_num 只计 missing_required，每原镜号一次；已定位的画面错误、可推导漏镜、推导未知不计必要漏图。此处 regenerate 不再决定视频返修或表后建议。repair_decisions 独立统计影响剧情的已确认 FAIL/absent；关键剧情问题或严重损坏 1 镜触发，普通问题至少 2 镜且占全部应覆盖脚本镜头 ≥20% 触发。确认影响剧情的漏镜即计入，与参考图能否省去无关。

evidence_fingerprint 绑定脚本（含 beat、event、duration、duration_source、narrative_plan）、input_shot_groups 及聚合规则版本、资产、源视频、匹配、帧哈希、选帧、组级审查及漏镜策略。输入分组进入审查上下文与聚合指纹，但不进入视频来源组指纹；修改输入分组会使审查、聚合及交付结论失效，有效视频、抽帧、映射和中性观察仍可复用。上述时长、来源、剧情依据同时进入来源组指纹与审查上下文；增加或修改后重新绑定输入并审查，旧结论不可复用为通过。grouping policy=4；新版审查上下文包含4秒下限与同 Beat 范围，旧审查需重新核对分组依据，不自动升级为通过；有效帧与观察仍可复用。缺失镜头的结论绑定完整补查和依据图片，不创造缺失图的哈希。来源变化后旧审查和聚合失效，不能通过改状态字符串恢复通过。

## 固定交付

render 在干净目录生成 `分镜说明.md` 和 `images/`。仅确认漏镜且最终批准 ai_fill 的小分镜图栏用纯文字“可推导生成”，不复制原帧、不生成缩略图或占位图片、不输出图片链接；内部证据保留。已有且通过的 ai_fill 镜头与其余有图镜头均保留抽帧原图供点击查看，生成 240×168 PNG 小分镜图（图下标镜号）；必要漏镜或证据不足的缺图继续使用文字卡，分别写“必要漏镜”或“暂无有效画面”，不使用“待检查”标签。审查候选不是最终批准，不能据候选隐藏图片。MD 使用相对图片链接，可整体移动。仅本地缩放与绘字，不生成 AI 分镜图。

MD 固定只包含一张逐镜表，不另列分组顺序、总时长或理由表：

| 分组 | 原镜号 | 镜头时长 | 脚本描述 | 小分镜图 | 检验结果 | 图片处理 | 推导依据镜号 | 问题或修改建议 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

分组栏采用用户输入编号；无输入时采用自动聚合编号。每镜按原顺序出现一次，未分组镜头写“—”。输入冲突集中用简短文字说明，不静默改组；受影响省图暂不批准。

逐镜时长为脚本计划值，建议值注明“建议”；不拿原视频实际时长作内容失败依据。检验通过与图片处理分列。影响角色/行动识别、关键动作结果、因果或必要空间关系，或违反用户明确严格要求的错误写“该镜需重新生成”；不影响剧情的外观、站位、景别、姿势或动作细节差异可通过。无法对应本镜事件或必要证据不足先补查；仍无法确认时，检验结果写“—”、图片处理写“暂不省图”，问题栏说明具体缺口及补查方向，不写“待检查”。已确认漏镜但推导依据不足时仍写“视频漏镜”，问题栏说明缺少的省图依据；不能改成通过、必要漏镜或 ai_fill。内部 uncertain/pending 不变。最终省图的已有通过镜头仍展示抽帧图片，只有确认漏镜的小分镜图栏写“可推导生成”；两者图片处理栏均写“建议省图，未验证”；检验结果按原结论分别写“检验通过”或“视频漏镜”，列依据镜号及具体承接理由；必要漏镜写“必要漏镜，需补生成”。旧证据不支持当前通过或错误结论。

问题或修改建议优先一句短说明：错误镜写“具体差异；如何修正”，证据不足写“看不清什么；补查什么”，省图或保留镜写简短承接/保留理由。例如“钥匙持有者错误；改为女孩持钥匙”或“交接结果看不清；补看动作结束帧”。填写现有 shot_reviews.reason/followup、issues.problem/fix、reference_assessments.reason 时即使用简洁表达，不增加逐镜总结调用。渲染优先展示问题及处理，不叠加通用规划解释、完整时间范围或重复的“建议省图，未验证”；证据与详细判定保留内部。多个独立问题各一短句，保留锚点拒绝依据，不按字数硬截断，脚本原文不改写。

达到阈值时只在逐镜表下加一句“建议重新生成视频 ××，原因是……”，原因按当前独立判定填写关键剧情问题、严重画面损坏或普通剧情问题达到阈值。**不输出视频结论表，不展示内部 bad_num 或占比表**。没有有效独立判定时不借用必要漏图计数给整段返修建议；未达到时，只在逐镜表列具体建议。

尚无有效聚合时优先按输入 Shot 分组展示，没有输入时按来源组展示，检验结果写“—”，问题栏说明缺少当前有效审查。失效历史帧可展示但必须标“历史抽帧 · 证据不足”，不能支持当前省图；确认漏镜不以历史帧充当当前镜头。交付目录有额外文件则换新目录，工具不删除旧成果。

不交付视频、HTML、项目 JSON、规划日志或内部审查记录。默认 finish_review.py 保存 01_原视频审查.md 与图片；达到阈值并完成准备后，另用 repair_cycle.py export-prompt 交付新视频提示词 MD，含原资产顺序、生成时长及画幅，放独立新目录并停止。未触发只交付审查，准备受阻说明缺项。不调用生成 API，也不自动生成第二轮审查。用户交回新视频后独立审查、使用新交付目录，旧快照不覆盖。历史 repaired 入口仅用于真实安装并独立审查的返修视频。阈值不改变逐镜表或必要漏镜统计。
