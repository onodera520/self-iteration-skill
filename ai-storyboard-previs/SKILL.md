---
name: ai-storyboard-previs
description: 根据用户提供的视频、脚本和资产图，抽帧匹配并审查人物、场景、道具、动作与连续性，再提出相邻分镜聚合和 ai_fill 省图建议，交付保留抽帧与简洁 Markdown。用于已有视频的分镜校对、聚合规划和参考图取舍。
---

# 视频实证分镜规划

默认输入：**视频＋脚本＋资产图**。

默认链路：**登记视频 → 抽帧对应脚本 → 组级内容与连续性审查 → 相邻聚合与参考图取舍 → 保留图片＋简洁 MD**。不需要视频提示词，不进入 API 生成或独立修图流程。

## 默认执行流程

1. **一次整理输入**：读 [项目约定](references/project.md)、[镜头要求](references/shot-requirements.md)。依据完整脚本与资产一次填写全部 facts/state_changes/requirements/块级 provenance。只写入口种子和 state_changes，完整状态由 requirements.py 计算。视频画面是待核对证据，不能用错误画面改写脚本要求。保留原镜号、顺序、剧情、时长及画幅。
2. **登记已有视频**：设置 workflow: video_evidence、video_source: imported。一份视频对应一个来源组，包含它应覆盖的连续脚本镜头；这不是最终聚合方案。使用 import-video 保存文件哈希与实测时长，不伪造生成任务、不计付费提交。资产图用于身份、外观、场景和道具比对，不上传。脚本没有镜头时长时先用估算区间辅助抽样，不能把估算当成真实对应时间。
3. **一次批量匹配**：按 [审查规则](references/review.md) 抽取镜头内部、切点前后和连续帧，整组匹配脚本。记录候选、实际时间、SHA256 和 observation；同哈希观察复用。matched 仅表示定位成功；uncertain 先回看或加密抽帧；absent 必须完整补查确认。
4. **一次组级审查并给出取舍依据**：previs.py context 一次读取整组要求、资产、候选帧、选帧和相邻组边界。一次判断人物、场景、道具、动作及结果、镜头顺序、必要切镜、字幕与连续性，同时填写全组 reference_assessments；一次 review 登记。禁止逐镜 context/review。composition 仅比对脚本明确景别及关键帧要求与已记录描述。稀疏抽帧不能确认的动作或转场标待检查，不宣称完整通过。
5. **补查与问题处理**：证据不足先补查；确认内容错误或漏镜则定位镜号、时间和修改建议，保留有效结果并标待检查。本流程不自动付费重生成、修图或补图。用户给出替换视频后重新 import-video，整份替换视频重新匹配审查，并复查左右来源组边界；其他有效结果复用。
6. **工具聚合并交付**：按 [规划规则](references/planning.md) 运行 planner.py --post-review，保存独立 aggregation，不覆盖来源组、视频或时间映射。仅组合相邻镜头，保护首尾、首次出场、关键状态、空间变化和必要锚点；ai_fill 须处于可靠锚点之间。render 输出保留抽帧和分镜说明.md，逐镜列原编号、脚本、图或占位、简短理由；问题注明待检查。不交付视频、HTML 或内部记录。

ai_fill 只省独立参考图，不能删除原脚本镜头。漏镜、不确定及画面错误不批准省图。默认是**有实证依据的省图建议，未验证**：已有视频成功不证明后续采用新聚合及参考图组合也成功。

事实来源分级、SHA256、.lock、观察复用规则保持。旧生成模式的预算、max_retries=1、三轮上限及 submission_unknown 恢复逻辑保留兼容；仅在用户另行要求生成时读取 [生成与恢复](references/generation.md)，不进入默认流程。不实现 CLIP，不并发。

## 工具入口

Python 3.10+、Pillow、FFmpeg/FFprobe。项目、证据、规划配置均在内部工作目录；用户不必填写 JSON。

```text
python scripts/previs.py validate PROJECT.json
python scripts/previs.py import-video PROJECT.json G01 INPUT.mp4
python scripts/media.py extract INPUT.mp4 EVIDENCE_DIR --project PROJECT.json --group G01
python scripts/storyboard.py map PROJECT.json MAPPING.json
python scripts/storyboard.py select PROJECT.json SELECTION.json
python scripts/previs.py context PROJECT.json G01
python scripts/previs.py review PROJECT.json GROUP_REVIEW.json
python scripts/planner.py PROJECT.json PROFILE.json --post-review --output AGGREGATION.json
python scripts/previs.py render PROJECT.json DELIVERY_DIR
```

PROFILE 是聚合约束，未指定下游模型时采用明确标注的规划假设，不查询或选定生成模型。详见 [事实与规划](references/facts-and-planner.md)。正常三镜组仍设计为 3 次 LLM 判断：完整提取、批量匹配、组级审查与取舍；工具完成登记、抽帧、规划和渲染。这不是实测耗时，补查时以审查质量为先。
