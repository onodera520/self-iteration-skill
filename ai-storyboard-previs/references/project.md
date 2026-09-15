# 内部数据与用户交付

以 assets/example-project.json 建立内部项目；用户只需提供视频、脚本和资产图，不必填写 JSON。一次整理完整脚本的字段，统一 validate，按报错集中修正。路径相对项目 JSON 或使用绝对路径；模型参数独立保存。

## 输入与运行状态

- schema_version: 1、title、source_script：保留原始依据。
- imported_videos：用户视频登记记录，含 source: user_video、target_id、version、outputs、output_hashes、group_fingerprint、duration；独立于付费 tasks。通过 import-video 登记替换文件，旧哈希结论失效。
- user_video_prompt（旧生成模式可选，默认不需要）：原样保存用户视频提示词。单个生成组直接使用；多个生成组须填写各组 video_prompt，保留对应原文，仅作必要的分组适配。缺提示词时先补齐，不回退为自动创作。
- assets: id/kind/description/path；kind 为 character/scene/prop。默认上传组内全部相关资产图，资产图不直接冒充抽帧成果。
- shots: id/script/scene_id/continuity_id/duration/asset_ids/required_result。数组保持原顺序，duration 是计划秒数；脚本明确景别时填写 shot_size，并在 keyframe.description 保留构图要求。
- facts/state_changes/intent：见 [事实规则](facts-and-planner.md)。requirements：见 [镜头要求](shot-requirements.md)。只填入口种子，不维护第二份完整状态账本。
- requirements.provenance：每镜要求块一条来源，混合假设保守标记；facts.source/state_changes.source 的来源层级不变。
- reference：保留旧 mode: anchor|ai_fill、path、role、reason、locked。资产试生成不读取其图片作为输入，也不把旧 mode 当作最终取舍结论。
- groups：默认按用户视频划分的来源组；旧模式为实际生成组的 id/shot_ids/reason/version，可有 video_prompt、prompt_notes。默认按每份输入视频覆盖的连续镜头维护；必须连续覆盖所有镜头。不能拿最终聚合建议覆盖它。
- config：workflow: video_evidence、video_source: imported、video_input_mode: assets、delivery_mode: storyboard_images、aspect_ratio、max_repair_rounds（默认且至多 3）、max_submissions（示例 0）、可选 budget_cny。新项目采用这些模式；旧项目缺 workflow 可继续兼容，进入新流程时补上此字段和缺失要求块。
- tasks：请求、原任务 ID、状态、下载结果及哈希。保留记录用于预算和恢复。
- board_mappings：整组匹配，绑定视频 SHA256、生成组指纹、evidence.json 哈希和每张候选图的路径/实际时间/哈希。观察存在 shots[].observation；同哈希观察复用，重新配对不能伪造观察。
- shots[].board.selected：所选抽帧的路径、SHA256、source.kind: frame、source.time 和理由。history 保存旧选择。当前帧必须仍属于当前视频的有效 matched 候选。
- reviews：视频组级审查，含四项 checks、覆盖、实际镜头区间、带路径/哈希/时间的 evidence.observation、问题、边界检查、reference_assessments 和 context_fingerprint。旧 board_reviews 不代替新组级证据。
- repairs/repair_round：现有视频有限返修记录。不删历史绕过限额。

## 聚合建议单独保存

`planner.py --post-review --output INTERNAL.json` 保存 p.aggregation；旧建议进入 aggregation_history。仅此入口消费当前组级证据，不重新发起逐镜 LLM 判断。

建议内 groups 使用 A01 等编号、shot_ids、planned_duration、source_group_ids；decisions 包含 shot_id/group_id/source_group_id/mode/status/reason/bracket/frame。mode 是 anchor、ai_fill 或 pending；status 分别为 anchor_reviewed、ai_fill_suggested_unverified、pending。

evidence_fingerprint 绑定脚本、用户提示词、资产、模型配置、生成视频、匹配及帧哈希、组级审查和当前选帧。来源变化后旧建议不再有效；不能靠修改状态字符串恢复通过。原 groups/tasks/board_mappings/实际时间完全保留。

## 交付

render 只在干净目录生成 `分镜说明.md` 与保留图片的 images/。图片使用相对链接，可整体移动目录。按聚合组展示原镜号、计划时长、原脚本、图或 ai_fill 占位、简短理由；实际视频时间留在内部，不能当作计划时长。

ai_fill 标明“建议省图，未验证”，原脚本仍列出。pending 不省图，有可用抽帧则展示并标待检查；无图明确说明。建议失效时不复用旧 ai_fill，回到实际生成分组展示待检查。新视频更差或预算到限时可保留历史抽帧，但只能标“历史抽帧 · 待检查”，不能用旧图批准当前省图。

模型约束下无可行参考图方案时保留试生成分组和所有镜头，注明需调整配置；不删镜换取可行。交付目录已有额外文件时换新目录，工具不自动清除旧成果。

用户文档不附任务清单、审查日志、JSON、提示词配置、中间视频、HTML、模型费用或内部时间索引。内部记录仍必须保存以支持恢复及证据失效检查。
