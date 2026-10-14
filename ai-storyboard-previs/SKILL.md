---
name: ai-storyboard-previs
description: 校对用户按顺序配对脚本的分镜参考图，保留分组和省图判断，交付逐镜 Markdown 报告与全部原图；达阈值后导出整批新视频提示词。默认无需视频、登记、抽帧或匹配。
---

# 分镜图校对

用户提供已排序并配对脚本的分镜图、完整脚本、人物／场景／道具原资产，可选 Shot 分组和原提示词。直接采用对应关系，不重新匹配。内部 JSON 和指纹由代理维护，用户不用登记。默认流程不依赖 FFmpeg；旧视频任务才查 [历史项目接口](references/project.md)。到报告或新视频提示词交付停止，用户自行生成。

## 最少读取

记录任务计时起点，包含规则阅读。先确定当前阶段，**只读该阶段列出的文件或段落**；已读且未变的规则复用。正常运行只执行脚本，不通读源码、全部 references、PROJECT、CONTEXT 或提示词来源大文件。工具默认简报已给足下一步路径，不加 --detailed。

| 当前阶段 | 阅读入口 |
| --- | --- |
| 新输入 | [字段速查](references/fields.md)；已有 extract 草稿直接补齐。手工建输入才查 [INPUT 模板](assets/storyboard-input.json)。阶段、来源、共享要求或继承不明时查 [镜头要求](references/shot-requirements.md)对应段落 |
| 图片审查 | [图片审查规则](references/storyboard-review.md)、prepare 给出的逐页审查包；旧项目用 REVIEW.view.json；有 FAIL 才查 [返修证据](references/repair-assessments.md) |
| 分组／省图 | [规划规则](references/planning.md)相关输入或自动分组段；校验成功直接交付 |
| 达阈值后 | [提示词编排](references/prompt-quality.md)、[提示词规则](references/auto-repair.md)、PROMPT.view.json；缺项才读 PROMPT.inputs.json |
| 中断／压缩后 | 下方“恢复”及 RUN.json；不重走准备和已完成审查 |

详细命令和兼容说明按需查 [图片接口](references/storyboard-images.md)，计时／调优才查 [执行提效](references/efficiency.md)。原生成提示词只在触发阈值后读取，不能作图像证据。

## 执行

1. 保留完整脚本和逐镜原文、镜号、计划时长及来源。标注式“镜头N／【时长】【镜头设计】【镜头内容】”用 extract，不临时写解析器或按非空行拆镜。补齐有出处的事实、阶段、关键要求和剧情关键性，不自动猜测。普通姿势、景别不升级为硬条件；完整动作结果不强制每张参考图都是终态。只填状态种子和真实变化，程序解析完整状态。有用户分组就用，无 Beat 时全脚本按一个 Beat。
2. 整批 prepare，一次检查输入并生成精简视图、工作单、3×3编号总览与恢复记录。输入错误先修正，不算剧情错误；失败停止依赖步骤。视图保留原文，requirements 的 {$ref:Rxx} 须结合 shared_requirements 完整读取。哈希和重复来源存在 CONTEXT，工具维护，不手写。
3. 按页批量校对：读取 REVIEW.pageNNN.json，同一工具调用批量显示 images_to_open 的总览／相关原资产，保留原始显示尺寸；不先通读整批视图。每页一次记录明确项，再集中打开必要细节不清的原图；已明确的错误不用反复全批重看。跨页检查相邻连续性，未压缩且资产未变时复用已看资产。及时保存 WORKLIST 的 visible_facts、七项 checks、阶段、结论与取舍；空字段不代表 PASS。FAIL／uncertain 写具体原因，待核查不自动判错；省图写同组双侧 PASS 锚点及推导理由。所有原图保留，整批分组和连续性仍完成。
4. 一次 complete，展开工作单、核验整批、规划、判阈值、渲染并冻结。成功直接交付，不再人工重看整表；失败只定位相关字段／镜头。报告为 01_分镜图审查.md 和 images/，一张九列表，采用脚本计划时长，通过的问题栏只写“符合脚本”。省图不删除脚本镜头或原图，待核查显示“—／暂不省图”，没有漏镜条目。
5. 阈值为关键剧情错误一镜，或严重画面损坏一镜，或普通明确错误至少两镜且占整批至少20%；按原镜号去重，2/10触发、2/11不触发。待核查、输入问题、分组和省图不改变整批分母。触发后如 PROMPT 已就绪直接核对；缺项同批补齐后再准备提示词，不重做有效审查。逐镜核对全部来源并完成九项语义检查，finish 导出全部镜头，每镜1秒、静音、保留资产对应和剧情；共同画幅直接沿用，混用先确定目标，不自动裁图。

```text
python scripts/prepare_storyboards.py extract SCRIPT.txt --images IMAGES.json --output INTERNAL/INPUT.json
python scripts/prepare_storyboards.py prepare PROJECT.json --input INTERNAL/INPUT.json --run-dir PREPARE_INTERNAL --output DELIVERY
# 已有图片项目省略 --input；需要提供新对应表时用 --images IMAGES.json。
# 阅读 prepare 返回的 review_batches，批量看图并保存 WORKLIST 后：
python scripts/prepare_storyboards.py complete PROJECT.json PREPARE_INTERNAL/WORKLIST.json --output DELIVERY --run-dir FINISH_INTERNAL
# 仅达阈值且计划就绪时，阅读 PROMPT.view.json 并填写 PROMPT.json：
python scripts/repair_quality.py finish PROJECT.json G01 FINISH_INTERNAL/PROMPT.json --output PROMPT_DELIVERY/G01_新视频提示词.md
# 缺准备项时，同批补齐后：
python scripts/repair_quality.py prepare PROJECT.json G01 PROMPT_INTERNAL/PROMPT.json
```

## 恢复

任务摘要保留 RUN.json 的绝对路径、当前阶段和下一步；实际观察及判断必须落盘，不靠聊天记录。压缩／中断后先读 RUN.json，然后：

```text
python scripts/prepare_storyboards.py resume PROJECT.json PREPARE_INTERNAL
# 调出一页的脚本、相关原资产和跨页相邻背景：
python scripts/prepare_storyboards.py resume PROJECT.json PREPARE_INTERNAL --page 2
# 只调出需要继续或修正的镜头，自动包含相邻镜头及已有记录：
python scripts/prepare_storyboards.py resume PROJECT.json PREPARE_INTERNAL --shots S06
```

resume 重验图片、脚本、资产和总览绑定，摘要只统计已保存字段，**不批准审查或自动补 PASS**。从未记录／不完整项目继续；涉及分组、省图或远处锚点时补读相应镜号，最终 complete 仍核验整批。已经 complete 的阶段只读 FINISH.view.json，按 prompt_status 接着执行；不因压缩重新 prepare、complete 或读完整冻结清单。

图片、脚本、资产、要求或分组变化时恢复停止，重新准备并核验受影响结论；旧交付冻结，新结果另存。workflow=storyboard_images、source.kind=provided，不制造视频来源或时间戳。程序计时不等于模型端到端耗时；不为了减少上下文跳过初次看图、必要放大或语义检查。
