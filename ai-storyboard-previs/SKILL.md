---
name: ai-storyboard-previs
description: 根据资产图和有序脚本生成快速切镜视频作为取图素材，匹配抽帧、审查并局部修图补图，最终交付分镜图片和清晰的 Markdown 说明。用于 AI 分镜图制作、视频取图和分镜连续性检查。
---

# AI 分镜图制作

最终目标是分镜图与 `分镜说明.md`。视频只是批量获得候选画面的中间素材，不交付视频，不要求修好的图片回流重做视频。

## 工作流程

1. **整理资产与脚本**：读 [内部数据与交付](references/project.md)，以示例建立内部工作文件。保留原镜头编号、顺序、剧情、用户时长和画幅。默认每镜需要最终分镜图；生成输入参考图的省略与最终不配图是两种独立决定。
2. **定稿镜头要求并分组生成**：读 [镜头要求](references/shot-requirements.md)，明确每镜目的、取图阶段、动作前后状态及必要画面约束。生成、取图、修图和验收共用该设计；提示词优化不得暗改设计。再读 [分组规则](references/planning.md) 与 [事实约束](references/facts-and-planner.md)。默认 `video_input_mode: assets`，直接用资产图生成，不先为每镜补一张输入图。按模型图片数和时长限制划分相邻镜头；模型和预算确定后依 [生成与恢复](references/generation.md) 调用 RunningHub。先试一个多镜头组，再扩展其余组。
3. **匹配与抽帧**：依 [匹配、审查与修复](references/review.md) 对照脚本定位实际画面。每镜保留多个候选帧与实际时间，再选最能表达构图和关键状态的一张。抽不到先回看原视频并加密抽帧；分别记录匹配、确认缺失和不确定，不强行配对。
4. **检查分镜图**：以脚本、资产及已定稿的目标关键帧为准检查人物、场景、道具、构图、动作阶段、画面清晰度与连续性。区分世界位置、画面左右与角色自身手别，画外状态继续保留。抽帧或接口成功不等于通过。图中看不出的完整运动不声称验证；一镜需要多个关键状态时可补充图片，并保持同一原镜头编号。
5. **局部修复**：局部错误编辑图片；必要图缺失或整体图意错误时单独补图。重新抽帧能解决的先重新匹配。视频组整体失配、单图修复不合适时，说明原因后只重生成相关组。根据错误严重程度、范围及成本决定，不只用 bad_num 阈值。修完图复查该镜及相邻图，不要求中间视频修好。通过的图片保留。
6. **交付**：按原顺序检查全部最终图片及故事可读性，再用 render 输出 Markdown 与图片附件。每镜展示分镜图、脚本、计划时长与必要状态。无需单独配图必须有剧情及前后画面的依据，保留编号与脚本。不附项目清单、规划/审查记录、取图视频或 HTML。

默认最多三轮付费返修，受本次预算和提交上限约束；每批受影响镜头计一轮，重新匹配不消耗生成轮次。只有确认失败或确认缺失的必要图触发付费返修；不确定先补证据。到上限保留最佳可用图片并说明剩余问题。任务超时继续查原 ID，禁止直接重复提交。

## 工具入口

Python 3.10+，图片文件验证需要 Pillow，抽帧需要 FFmpeg/FFprobe。模型参数使用本机 runninghub 技能的注册表和客户端。

```text
python scripts/previs.py validate PROJECT.json
python scripts/planner.py PROJECT.json PROFILE.json --output PLAN.json --apply
python scripts/previs.py prompt PROJECT.json G01
python scripts/rh_tasks.py dry-run PROJECT.json REQUEST.json
python scripts/rh_tasks.py run PROJECT.json REQUEST.json
python scripts/rh_tasks.py resume PROJECT.json REQUEST_ID
python scripts/media.py extract VIDEO.mp4 EVIDENCE_DIR --project PROJECT.json --group G01
python scripts/storyboard.py map PROJECT.json MAPPING.json
python scripts/storyboard.py select PROJECT.json SELECTION.json
python scripts/storyboard.py restore PROJECT.json RESTORE.json
python scripts/storyboard.py context PROJECT.json S01
python scripts/storyboard.py review PROJECT.json IMAGE_REVIEW.json
python scripts/storyboard.py repair PROJECT.json REPAIR_BATCH.json
python scripts/storyboard.py omit PROJECT.json OMISSION.json
python scripts/previs.py render PROJECT.json DELIVERY_DIR
```

代理负责实际读图、比对脚本、选择修复方式并连续执行；脚本负责文件绑定、版本、状态、限额与输出，不是自动视觉分类器。模拟接口、合成视频与构图示意只验证工具流程；真实模型生成和修图效果需实际验收。
