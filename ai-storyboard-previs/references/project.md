# 内部数据与用户交付

以 assets/example-project.json 建立内部项目。用户只提供视频、原脚本、资产图，不必填 JSON。一次整理完整脚本后统一校验，来源不明保留 unknown/inference；路径相对项目文件或使用绝对路径。

## 输入及内部状态

- schema_version: 1、title、source_script：保留原始依据。
- assets: id/kind/description/path，kind 为 character/scene/prop；仅本地比对，不上传，不冒充视频抽帧。
- shots: id/script/scene_id/continuity_id/asset_ids/required_result；保持原镜序。imported 模式可先省略 duration 抽帧审查；最终聚合须填写正数计划秒数及 duration_source（kind: script 或 inference，ref: 原文出处或建议依据）。缺原文时长时代理提出建议并明确标注，不从实际视频冒充脚本值。shot_size 只填脚本明确景别；keyframe.description 保留关键画面要求。
- shots[].event：新项目每镜填写 `{"id":"E03","summary":"推门、到门外开伞并追出，构成连续行动","source":{"kind":"inference","ref":"S07 推门与 S08 门外开伞追出属于连续行动"}}`。id 为非空字母、数字、下划线或连字符组成的编号；同编号 summary 一致，source 沿用 script/asset/inference 分级。event 只提供初步自然段，不替代 scene_id/continuity_id 或状态继承。旧项目允许全部不填，不能只填部分镜头。
- narrative_plan：完整脚本的相邻承接、自然边界与整段复杂度依据，结构及三步规则见 [规划约定](planning.md)。不改变状态继承；缺少时允许审查，但不能交付新版合格聚合。
- facts/state_changes/intent/omission_assessment：按 [事实规则](facts-and-planner.md)。requirements 按 [镜头要求](shot-requirements.md)，代理仅写入口种子和变化，工具计算完整状态。每镜 requirements 要求块一条 provenance，其他来源分级不变。
- reference：保留兼容 mode: anchor|ai_fill、path、role、reason、locked。它不是新的审查结论；最终读取独立 aggregation。
- groups：id/shot_ids/reason/version；一份输入视频对应一个来源组，列应覆盖的连续镜头。所有来源组顺序拼接必须恰好覆盖脚本一次。不得为降低漏镜占比修改应覆盖范围。
- config：workflow: video_evidence、video_source: imported、video_input_mode: assets、delivery_mode: storyboard_images、aspect_ratio。missing_policy 可省略，默认 min_count: 2、min_ratio: 0.2；两者同时达到才建议重新生成。保留 max_repair_rounds/max_submissions/budget_cny 等旧生成安全字段，默认无付费提交。
- imported_videos：import-video 登记 target_id/version/source: user_video/outputs/output_hashes/group_fingerprint/duration。duration 为原视频实测范围，只用于抽帧及证据定位。独立于付费 tasks，替换视频后旧证据失效。
- board_mappings：全组 matched/uncertain/absent，候选路径、实际时间、SHA256、observation。绑定视频、来源组及 evidence.json 哈希；完整补查确认 absent 时另填 full_rescan: true、rescan.ranges 和 rescan.observation，范围须覆盖整份实测视频。缺失镜头 candidates 为空，不能伪造对应帧。
- shots[].board.selected：选帧 path/sha256/source.kind: frame/source.time/reason；history 保存历史选择。当前有效图必须属于当前 matched 候选。
- reviews：四项组级 checks、按顺序的 shot_reviews、coverage.shot_ids/mapping_verified/limitations、带路径/哈希/时间的 evidence.observation、issues、uncertainties、boundary_checks、reference_assessments 和 context_fingerprint。imported review_schema 为 4；有 narrative_plan 时必须 grouping_checked: true，确认同时核对剧情分组与整个合并区间复杂度；不要求 actual_shots 或每镜时长区间。详见 [审查结构](review.md)。
- shot_reviews：每镜 verdict: PASS|FAIL|uncertain|absent、reason、evidence_times；已定位镜须含七项 checks。一镜 FAIL 不妨碍其他镜独立 PASS；受影响的连续性边界仍须核对。漏镜不可 PASS。
- reference_assessments：每镜 decision: anchor|ai_fill|pending、reason、evidence_times、derivable: true|false|null、basis_shot_ids。decision 是参考图取舍候选，独立于 mapping.status 与 shot_reviews.verdict；组合须遵守 [审查决策表](review.md#可推导省图判据与决策表)。ai_fill 须列顺序正确的两个已有前后依据镜，依据必须独立 PASS、保留图且有有效资产支持；状态不变不足以批准，reason 须解释状态承接与叙事信息。漏镜不填本镜帧证据，改引用完整补查和依据镜。没有可靠结论填 null，不计必要漏镜；已明确必须保留则填 false 并说明依据。最终规划仍检查候选的必要锚点约束。所有省图均为建议/未验证。context.reference_policy_version 纳入指纹，旧结论需按当前判据复核。
- tasks/repairs/repair_round：旧生成与恢复记录仍保留。默认不用，不清空历史绕过安全限制。user_video_prompt 为旧生成模式字段，默认不需要。

## 资产审查证据版本

已有视频组级审查使用 review_schema: 4、reference_policy_version: 3，两者纳入 context_fingerprint 并保存在审查记录。旧版本（包括没有版本/上下文的记录）不能支持当前审查或聚合；有效原始抽帧、匹配、SHA256 可复用，旧自由文字 observation 不自动升级。

evidence 包含非空 visible_facts 和 interpretation，保留 observation 摘要及 shot_id/path/sha256/time，继续绑定当前视频。shot_reviews 每镜增加 identity_reason；普通通过不要求 identity_scope 或逐人外观比较。asset_comparisons 默认为 []，仅剧情相关外观要求/问题填写；详细字段见 [审查规则](review.md#资产外观判定剧情优先)。人物比较写 story_requirement，FAIL/uncertain 另写 story_impact。既有稳定冲突、逐镜资产/帧/时间绑定与问题引用门槛保留，但普通服装或脸部差异不单独判失败。

问题必须显式填 asset_ids、asset_comparison_ids（非资产问题均为空），多镜资产问题逐镜绑定。工具检查结构和关联，不是视觉真实性检测器。不新增 confidence，不更改用户两表交付。缓存观察只在同哈希且内容有效时复用；解释被新证据推翻时重新校对受影响镜头与衔接。

## 独立聚合与失效

planner.py --post-review 在副本内处理规则，仅保存 p.aggregation；旧建议留在 aggregation_history。原 groups、视频版本、匹配时间和 tasks 不被覆盖。

groups 使用 A01 等编号、shot_ids、reason、source_group_ids；新版 imported 聚合含 planned_duration（计划总秒数）、duration_has_suggestion、planning_status。feasible: false 时使用 P 编号待规划占位，不把超限单镜包装为合格组。grouping_trace 保存自然初分、相邻合并和短段复核，用户不必阅读内部记录。decisions 包含 shot_id/group_id/source_group_id/mode/status/reason/bracket/frame/mapping_status/review_verdict/issues。

状态含义：anchor_reviewed 为检验通过保留图；ai_fill_suggested_unverified 为该镜通过且建议省图；absent_fill_suggested_unverified 为确认漏镜但可推导，未验证；mismatch 为该镜需重新生成；missing_required 为必要漏镜；pending 为证据或推导不足。mode 分别为 anchor/ai_fill/pending，不等于视频是否通过。

missing_summary 按来源视频记录 bad_num/total/ratio/regenerate，仅内部保存。bad_num 只计 missing_required，每原镜号一次；轻微错误、可推导漏镜、待检查不计。默认 2/10 触发，2/11 与 1/3 不触发。

evidence_fingerprint 绑定脚本（含 event、duration、duration_source、narrative_plan）及聚合规则版本、资产、源视频、匹配、帧哈希、选帧、组级审查及漏镜策略。上述时长、来源、剧情依据同时进入来源组指纹与审查上下文；增加或修改后重新绑定输入并审查，旧结论不可复用为通过。缺失镜头的结论绑定完整补查和依据图片，不创造缺失图的哈希。来源变化后旧审查和聚合失效，不能通过改状态字符串恢复通过。

## 固定交付

render 在干净目录生成 `分镜说明.md` 和 `images/`。最终批准 ai_fill 的小分镜图栏仅纯文字“可推导生成”，不复制原帧、不生成缩略图或占位图片、不输出图片链接；内部证据保留。其余镜头保留原图供点击查看，生成 240×168 PNG 小分镜图（图下标镜号）；必要漏镜或待检查缺图继续使用文字卡。审查候选不是最终批准，不能据候选隐藏图片。MD 使用相对图片链接，可整体移动。仅本地缩放与绘字，不生成 AI 分镜图。

MD 固定只包含两张表：

1. **分组表**：分组编号、镜头顺序、总时长、简短分组理由。只聚合相邻镜头，每组 ≤15 秒、≤12 镜；包含建议时长的组注明“含建议值”。
2. **逐镜表**：分组、原镜号、镜头时长、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。

逐镜时长为脚本计划值，建议值注明“建议”；不拿原视频实际时长作内容失败依据。检验通过与图片处理分列。剧情、动作或明确要求的轻微错误写“该镜需重新生成”，不影响剧情的普通外观偏差不判失败；完全不符先“待检查”并补查。最终省图的小分镜图栏写“可推导生成”，图片处理栏写“建议省图，未验证”；检验结果按原结论分别写“检验通过”或“视频漏镜”，列依据镜号及具体承接理由；必要漏镜写“必要漏镜，需补生成”。旧证据不支持当前通过或错误结论。

达到阈值时只在两张表下加一句“建议重新生成视频 ××，原因是必要漏镜达到阈值”。**不输出视频结论表，不展示内部 bad_num 或占比表**。未达到时，只在逐镜表列具体建议。

尚无有效聚合时按来源组展示待检查。失效历史帧可展示但必须标“历史抽帧 · 待检查”，不能支持当前省图；确认漏镜不以历史帧充当当前镜头。交付目录有额外文件则换新目录，工具不删除旧成果。

不交付视频、HTML、项目 JSON、规划日志或内部审查记录。缺失或错误只给建议，不触发 API。
