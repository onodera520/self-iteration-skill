# 内部数据与用户交付

以 assets/example-project.json 建立内部项目。用户只提供视频、原脚本、资产图，不必填 JSON。一次整理完整脚本后统一校验，来源不明保留 unknown/inference；路径相对项目文件或使用绝对路径。

## 输入及内部状态

- schema_version: 1、title、source_script：保留原始依据。
- assets: id/kind/description/path，kind 为 character/scene/prop；仅本地比对，不上传，不冒充视频抽帧。
- shots: id/script/scene_id/continuity_id/asset_ids/required_result；保持原镜序。imported 模式 duration 可省略或 null，若原文给定可保存但不参与审查或聚合。不估算或补填时长。shot_size 只填脚本明确景别；keyframe.description 保留关键画面要求。
- shots[].event：新项目每镜填写 `{"id":"E03","summary":"推门、到门外开伞并追出，构成连续行动","source":{"kind":"inference","ref":"S07 推门与 S08 门外开伞追出属于连续行动"}}`。id 为非空字母、数字、下划线或连字符组成的编号；同编号 summary 一致，source 沿用 script/asset/inference 分级。event 只决定相邻聚合，不替代 scene_id/continuity_id 或状态继承。旧项目允许全部不填，不能只填部分镜头。
- facts/state_changes/intent/omission_assessment：按 [事实规则](facts-and-planner.md)。requirements 按 [镜头要求](shot-requirements.md)，代理仅写入口种子和变化，工具计算完整状态。每镜 requirements 要求块一条 provenance，其他来源分级不变。
- reference：保留兼容 mode: anchor|ai_fill、path、role、reason、locked。它不是新的审查结论；最终读取独立 aggregation。
- groups：id/shot_ids/reason/version；一份输入视频对应一个来源组，列应覆盖的连续镜头。所有来源组顺序拼接必须恰好覆盖脚本一次。不得为降低漏镜占比修改应覆盖范围。
- config：workflow: video_evidence、video_source: imported、video_input_mode: assets、delivery_mode: storyboard_images、aspect_ratio。missing_policy 可省略，默认 min_count: 2、min_ratio: 0.2；两者同时达到才建议重新生成。保留 max_repair_rounds/max_submissions/budget_cny 等旧生成安全字段，默认无付费提交。
- imported_videos：import-video 登记 target_id/version/source: user_video/outputs/output_hashes/group_fingerprint/duration。duration 为原视频实测范围，只用于抽帧及证据定位。独立于付费 tasks，替换视频后旧证据失效。
- board_mappings：全组 matched/uncertain/absent，候选路径、实际时间、SHA256、observation。绑定视频、来源组及 evidence.json 哈希；完整补查确认 absent 时另填 full_rescan: true、rescan.ranges 和 rescan.observation，范围须覆盖整份实测视频。缺失镜头 candidates 为空，不能伪造对应帧。
- shots[].board.selected：选帧 path/sha256/source.kind: frame/source.time/reason；history 保存历史选择。当前有效图必须属于当前 matched 候选。
- reviews：四项组级 checks、按顺序的 shot_reviews、coverage.shot_ids/mapping_verified/limitations、带路径/哈希/时间的 evidence.observation、issues、uncertainties、boundary_checks、reference_assessments 和 context_fingerprint。imported review_schema 为 2；不要求 actual_shots 或每镜时长区间。详见 [审查结构](review.md)。
- shot_reviews：每镜 verdict: PASS|FAIL|uncertain|absent、reason、evidence_times；已定位镜须含七项 checks。一镜 FAIL 不妨碍其他镜独立 PASS；受影响的连续性边界仍须核对。漏镜不可 PASS。
- reference_assessments：每镜 decision: anchor|ai_fill|pending、reason、evidence_times、derivable: true|false|null、basis_shot_ids。ai_fill 须列顺序正确的两个已有前后依据镜，依据必须独立 PASS、保留图且有有效资产支持。漏镜不填本镜帧证据，改引用完整补查和依据镜。没有可靠结论填 null，不能当作必要漏镜计数。
- tasks/repairs/repair_round：旧生成与恢复记录仍保留。默认不用，不清空历史绕过安全限制。user_video_prompt 为旧生成模式字段，默认不需要。

## 独立聚合与失效

planner.py --post-review 在副本内处理规则，仅保存 p.aggregation；旧建议留在 aggregation_history。原 groups、视频版本、匹配时间和 tasks 不被覆盖。

groups 使用 A01 等编号、shot_ids、reason、source_group_ids；imported 聚合不含 planned_duration。decisions 包含 shot_id/group_id/source_group_id/mode/status/reason/bracket/frame/mapping_status/review_verdict/issues。

状态含义：anchor_reviewed 为检验通过保留图；ai_fill_suggested_unverified 为该镜通过且建议省图；absent_fill_suggested_unverified 为确认漏镜但可推导，未验证；mismatch 为该镜需重新生成；missing_required 为必要漏镜；pending 为证据或推导不足。mode 分别为 anchor/ai_fill/pending，不等于视频是否通过。

missing_summary 按来源视频记录 bad_num/total/ratio/regenerate，仅内部保存。bad_num 只计 missing_required，每原镜号一次；轻微错误、可推导漏镜、待检查不计。默认 2/10 触发，2/11 与 1/3 不触发。

evidence_fingerprint 绑定脚本（含 event）、资产、源视频、匹配、帧哈希、选帧、组级审查及漏镜策略。event 同时进入来源组指纹与审查上下文；增加或修改后重新绑定输入并审查，旧结论不可复用为通过。缺失镜头的结论绑定完整补查和依据图片，不创造缺失图的哈希。来源变化后旧审查和聚合失效，不能通过改状态字符串恢复通过。

## 固定交付

render 在干净目录生成 `分镜说明.md` 和 `images/`。保留抽帧原图供点击查看；所有镜头均生成 240×168 PNG 小分镜图（下部绘制镜号）。省图或缺图生成同尺寸文字卡，注明“可推导省图”“必要漏镜”或“待检查”。MD 使用相对图片链接，可整体移动。仅本地缩放与绘字，不生成 AI 分镜图。

MD 固定只包含两张表：

1. **分组表**：分组编号、镜头顺序、简短分组理由。只聚合相邻镜头，无时长列。
2. **逐镜表**：分组、原镜号、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。

检验通过与图片处理分列。轻微错误写“该镜需重新生成”；完全不符先“待检查”并补查。漏镜可推导须同时显示“视频漏镜”和“可推导省图，未验证”，列依据镜号及具体承接理由；必要漏镜写“必要漏镜，需补生成”。旧证据不支持当前通过或错误结论。

达到阈值时只在两张表下加一句“建议重新生成视频 ××，原因是必要漏镜达到阈值”。**不输出视频结论表，不展示内部 bad_num 或占比表**。未达到时，只在逐镜表列具体建议。

尚无有效聚合时按来源组展示待检查。失效历史帧可展示但必须标“历史抽帧 · 待检查”，不能支持当前省图；确认漏镜不以历史帧充当当前镜头。交付目录有额外文件则换新目录，工具不删除旧成果。

不交付视频、HTML、项目 JSON、规划日志或内部审查记录。缺失或错误只给建议，不触发 API。
