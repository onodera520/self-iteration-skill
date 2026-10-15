# 图片项目内部字段

普通新项目优先使用 [精简 INPUT](../assets/storyboard-input.json)，由 prepare_storyboards.py 创建 PROJECT.json。仅排查字段或维护已有图片项目时查 [完整项目模板](../assets/storyboard-project.json)。这些文件由代理维护，不要求用户填写或随报告交付。

## 输入与来源

config.workflow=storyboard_images。角色／场景／道具 assets 保留用户原顺序、ID、kind、原路径及观察；shots 保留原镜号、顺序、完整逐镜 script、asset_ids、scene_id、continuity_id、计划 duration 与 duration_source。source_script 保存完整原输入。shot_design 只摘取原设计，不添机位或运镜。

事实、持久变化、requirements 及 provenance 按 [镜头要求](shot-requirements.md) 整批整理；共同必要条件用有明确 scope 和逐镜引用的 requirement_templates，程序展开。自动分组填写 event／narrative_plan；input_shot_groups 独立保存用户 Shot 分组，空与未提供不同，见 [分组规则](planning.md)。

storyboard_images 一镜一图，路径按用户给定顺序配对。G01 覆盖全部原镜，source.kind=provided；记录原图 SHA256、显示尺寸和顺序，不构造视频时间或映射。prepare 一次集中检查字段类型、文件可读性、数量、镜号、顺序、资产与状态冲突；输入失败不写项目或审查。

## 审查与失效

review_schema=6、reference_policy_version=5。精简工作单 version=2 包含可见事实、七项 checks、阶段、逐镜结论、分组确认及取舍；程序补机械绑定、空项和 PASS 的“符合脚本”。FAIL／uncertain 与省图保留各自必要依据；完整字段见 [图片接口](storyboard-images.md#一次整批审查)。结构通过不代替实际看图。

source_fingerprint 与 context_fingerprint 绑定脚本、要求、图片、原资产、顺序及分组。一次操作内复用哈希／图片信息，退出前重读依赖验证。同大小、同修改时间的替换仍失效。输入改变后重新 prepare 并核验受影响审查、连续性、省图和提示词，不把失效自动当 FAIL。

## 聚合与提示词

aggregation 独立保存 groups、逐镜 decisions、grouping_trace、clipGroupList 与证据指纹；无解保留待规划／冲突，不批准受影响省图。原审查批次不被覆盖。计划总长和完整覆盖由程序核对。

deferred_storyboard_prompts 只保存原提示词路径或延后文本，未达阈值不读取分析。触发后 source_storyboard_prompts 保存原文与文本 SHA256、source_fingerprint；repair_prompt_references 保存脚本绑定的相容视觉筛选。缺文件／筛选只阻止提示词准备，不影响报告。

repair_baseline 冻结 source_script、逐镜原文及设计、逐字摘录的 video_format_requirements。repair_decisions 绑定当前审查、聚合、原资产和基线；每个确认 FAIL 有一条 repair_assessment，阈值见 [返修证据](repair-assessments.md)。达到阈值后优先填写 repair_asset_style、必要 repair_visual_adaptations 和原提示词筛选，完成整批提示词导出。提示词 preserves_story／story_basis 仅确认保留已有可见剧情，排除对白文字及其含义；不要求视觉转译对白，不因其无法无声表达停止导出。

提示词来源 request prompt_version=5，经过全镜编排的请求为 version=6；不改原 script、duration 或 baseline。默认 prompt_work 内的 plan_version=3 只记录必要 edits 与覆盖九项检查的四组具体结论，notes 按需，仍确认全部镜号已核对；版本2及详细计划继续兼容，详见 [编排规则](prompt-quality.md)。

## 固定交付

公开目录仅有 01_分镜图审查.md 与 images/：一张九列表，全部原图与展示缩略图。PASS 的问题栏只写“符合脚本”；待核查显示“—／暂不省图”。省图依据在专列，所有原镜与原图仍保留。达阈值优先在同一 case 根目录或新视频提示词/ 新增 G01_新视频提示词.md，单独登记文件与请求指纹，原报告和图片清单不改写；内部 JSON 不外放。prompt_work 将准备与四组审计合并为一次提交，历史计划版本2及详细计划继续兼容。

delivery_format_version=3 在冻结前自动核对九列与当前已完成审查、逐镜对应／原图哈希、链接、缩略图预览、覆盖、顺序及文件集合。未达阈值通过后直接交付，达阈值优先导出提示词后再结束交付，不重复人工逐镜核对。失败定位对应部分。不能用机械校验代替初次视觉判断。

原交付冻结；修订另用新目录，repair_delivery_history 记录关联，脚本修订保留 repair_baseline_history。目录已有无关文件时换空目录，不覆盖原成果。现有历史报告和原输入文件不因 Skill 清理而删除。
