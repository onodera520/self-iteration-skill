# 图片项目内部约定

普通新任务按 [技能入口](../SKILL.md)使用 start／submit，由工具创建项目与工作单。仅排查字段或维护已有图片项目时读本文件；扩展字段查 [字段速查](fields.md)，状态与来源查 [镜头要求](shot-requirements.md)，原 prepare／complete 及恢复查 [图片接口](storyboard-images.md)。普通输入、状态交接和完整项目模板仍分别保留为 [最小输入](../assets/storyboard-input-minimal.json)、[状态交接](../assets/storyboard-input.json)、[完整项目](../assets/storyboard-project.json)，不要求用户填写或随报告交付。

## 输入、审查与规划

config.workflow=storyboard_images，G01 覆盖全部原镜，source.kind=provided。assets 保留用户原顺序、ID、kind、路径及观察；shots 保留原镜号、顺序、逐镜 script、asset_ids、scene_id、continuity_id、计划 duration 及来源；source_script 保存完整输入，shot_design 只摘原设计，不添机位或运镜。

storyboard_images 一镜一图，绑定原图 SHA256、显示尺寸与顺序，不构造视频时间或映射。输入、目录、资产及状态检查失败不写项目或审查。共同约束、状态继承与省图按扩展字段约定；自动分组的 event／narrative_plan 与用户 input_shot_groups 分开，空与未提供不同，详见 [分组规则](planning.md)。

review_schema=6、reference_policy_version=5。当前入口展开版本4工作单，由程序生成七项检查、问题及返修依据，旧版本1／2／3兼容；字段齐全不等于实际看图或 PASS。aggregation 独立保存 groups、decisions、grouping_trace、clipGroupList 及证据指纹；不覆盖审查批次，无解保留冲突，不批准受影响省图，计划总长和完整覆盖由程序核对。

source_fingerprint／context_fingerprint 绑定脚本、要求、图片、原资产、顺序与分组。一次操作内复用哈希和图片信息，结束前重验全部依赖；同大小、同修改时间的替换仍失效。输入变化须重新核验审查、连续性、省图及提示词，不把失效自动当 FAIL。

## 提示词内部记录

deferred_storyboard_prompts 保存原提示词路径或延后文本，未达阈值不读取分析。触发后 source_storyboard_prompts 保存原文、文本 SHA256 与 source_fingerprint；repair_prompt_references 保存脚本绑定的相容视觉筛选。缺文件或筛选只阻止提示词准备，不影响报告。

repair_baseline 冻结 source_script、逐镜原文及设计、逐字摘录的 video_format_requirements；repair_decisions 绑定当前审查、聚合、原资产和基线。每个确认 FAIL 保留 repair_assessment，门槛见 [返修证据](repair-assessments.md)。达阈值优先补齐资产风格、必要纯视觉转换和原提示词筛选并导出整批提示词。preserves_story／story_basis 只确认已有可见剧情，排除对白文字及其含义，不因对白无法无声表达停止导出。

来源请求 prompt_version=5，经过全镜编排的请求 version=6；不改 script、duration 或 baseline。当前 prompt_work 的 plan_version=3 记录必要 edits 和覆盖九项检查的四组具体结论，notes 按需；旧计划版本2及详细格式继续兼容，见 [编排规则](prompt-quality.md)。

## 交付与冻结

公开目录仅有 01_分镜图审查.md 和 images/，固定一张九列表，全部原图与缩略图。PASS 问题栏只写“符合脚本”，待核查写“—／暂不省图”；省图依据单列，原镜和原图仍保留。达阈值优先在同一 case 根目录或新视频提示词/ 新增 G01_新视频提示词.md，独立登记文件和请求指纹，不改原报告与图片清单，内部 JSON 不外放。

delivery_format_version=3 在冻结前自动核对九列、当前审查、逐镜原图哈希、链接、缩略图预览、覆盖、顺序与文件集合。未达阈值通过后直接交付，达阈值先完成提示词；不重复人工逐镜核对，不以机械校验代替初次视觉判断。

原交付冻结；修订另存新目录，repair_delivery_history 记录关联，脚本修订保留 repair_baseline_history。无关文件占用的交付目录换空目录，不覆盖旧成果。Skill 清理不删除历史报告、输入及运行记录。
