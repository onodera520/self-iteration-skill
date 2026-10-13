---
name: ai-storyboard-previs
description: 校对用户按顺序与脚本配对好的分镜参考图，核对人物、场景、道具、构图、可见状态及连续性，保留原有分组与省图判断，交付一张逐镜 Markdown 表和全部原图；达到阈值时输出整批新视频提示词供用户自行生成。无需视频、登记、抽帧或匹配。
---

# 分镜图校对与规划

默认输入是用户已经按顺序与脚本配对的分镜图、完整脚本及角色／场景／道具原资产。可选 Shot 分组及原生成提示词继续保留。顺序和对应关系直接采用，不重新匹配。JSON、文件指纹和工作单由代理维护，用户不用登记。

流程：**整批准备 → 校对图片与脚本 → 原有分组和省图判断 → 冻结审查报告 → 达阈值后导出整批新视频提示词**。图片入口不依赖 FFmpeg，不调用视频登记、抽帧、匹配或密集补查。用户自行生成；默认到提示词交付停止。

## 按阶段读取

只读当前阶段必要规则；已读且未变的内容直接复用，不提前展开无关阶段资料。

| 阶段 | 必读 | 按需补充 |
| --- | --- | --- |
| 整批准备 | [图片接口与快速入口](references/storyboard-images.md)、[镜头要求](references/shot-requirements.md)、[精简输入模板](assets/storyboard-input.json) | 已有图片项目或字段报错才查 [完整项目模板](assets/storyboard-project.json)、[项目字段](references/project.md)；有分组时查 [用户 Shot 分组](references/planning.md#用户输入-shot-分组) |
| 图片校对 | 图片接口的审查约定、[精简图片审查规则](references/storyboard-review.md) | 有明确错误读 [返修证据](references/repair-assessments.md)；细节不清时放大原图 |
| 分组和交付 | [规划规则](references/planning.md)、图片接口的交付与失效约定 | [执行提效](references/efficiency.md) |
| 阈值触发后 | [提示词编排](references/prompt-quality.md)、[提示词规则](references/auto-repair.md) | 有原提示词才读其筛选字段 |

## 默认执行顺序

1. **一次整理整批输入。** 原脚本采用“镜头N／【时长】【镜头设计】【镜头内容】”时，先用固定 extract 入口生成精简 INPUT 草稿，不临时编写解析器、不按非空行数拆镜。程序原样切取逐镜原文，兼容时长后的逗号、句号、空白及多行；同批补齐原资产、分组和逐镜必要判断。其他脚本格式按精简模板保留原文，不猜测格式或重写标点。要求只写必要状态、参考阶段、关键约束及来源，不逐项扩写脚本。purpose 与 required_result 相同时只写后者；固定字段、空数组和图片对应由程序补齐。只填状态种子和真实变化，完整入口／出口状态由 requirements.py 计算。用户给了 Shot 分组就采用，冲突集中提示、不擅自改组；未提供才准备 event/narrative_plan 并自动分组。用户未提供 Beat 时全脚本按一个 Beat 处理。普通景别、视线、姿势不自动升级成硬条件。
2. **一次准备。** 运行 prepare_storyboards.py prepare，并用 --output 指定计划交付目录，提前检查内部项目／工作目录与交付隔离；集中检查原文、必要字段、阶段枚举，再检查图片可读性、数量、镜号和顺序，记录原图与 SHA256，冻结脚本基线，并输出上下文和精简工作单。支持用户已排好的路径列表或镜号／路径对应项。错误是输入问题，提示修正，不记为剧情错误或计入阈值。提取或准备失败即停止依赖其输出的后续步骤；不得凭文件名重排或重新猜测对应关系。
3. **一次整批校对。** 对照原资产和每镜原图，一次记录 visible_facts，显式填写七项逐镜检查、阶段、结论、分组检查及取舍。通过镜头不写问题或修改建议，reason 由程序填“符合脚本”；程序复用可见观察补齐内部身份及阶段说明，观察须足以支撑这两项判断，确有必要时另填针对性说明。FAIL／uncertain 写具体原因、修正或需核查信息；省图仍写双侧依据和推导理由。检查人物、场景、道具、构图、关键状态和可见连续性，区分完整动作与参考阶段：动作前图不强求完成结果，单图不能证明运动也不自动判错。允许不影响剧情的合理差异，必要解释只留内部观察或资产对照。工具不替代理看图，不由空字段推定 PASS。
4. **一次收尾。** complete 在同一锁和证据校验周期内展开工作单、登记审查、规划、判断阈值、渲染、自动校验并冻结。有用户分组时固定采用；无输入才自动初分、相邻合并和短段复核。自动校验九列内容与当前脚本、审查及取舍一致，核验逐镜原图、缩略图、链接、哈希和顺序。成功直接交付，不再人工逐镜重看；校验失败或刚修改渲染／规则时才定位检查。所有原图均展示并保存，省图只减少建议使用的生成参考图，脚本镜头始终保留。
5. **仅达阈值时编排提示词。** complete 在准备齐全时输出 PROMPT.view.json 与精简 PROMPT.json；否则 FINISH_REPORT 列出缺项。将资产风格、必要纯视觉转换、可选旧提示词筛选在同一批次补齐，重新 decide，再 prepare 提示词计划。阅读完整来源视图，同批核对全部镜头、只改有必要的正文并完成九项检查；repair_quality.py finish 校验后导出到独立目录。共同画幅直接沿用；混用画幅先完成审查，再确定目标画幅，不能自动裁图。清楚的原表达直接保留，不强制重写。

```text
# 标注式原脚本：代理将用户已排好的对应写入 IMAGES.json，用固定入口提取：
python scripts/prepare_storyboards.py extract SCRIPT.txt --images IMAGES.json --output INPUT.json
# 同批补齐 INPUT 的原资产、分组和逐镜必要判断后，创建新项目及工作单：
python scripts/prepare_storyboards.py prepare PROJECT.json --input INPUT.json --run-dir PREPARE_INTERNAL --output DELIVERY
# 已有图片项目入口（二选一，不重复准备）：
# 仅在用户分组尚未保存时先导入：
python scripts/grouping.py PROJECT.json SHOT_GROUPS.md --apply
python scripts/prepare_storyboards.py prepare PROJECT.json --images IMAGES.json --run-dir PREPARE_INTERNAL --output DELIVERY
# 阅读 CONTEXT.json 和原图，整批填写 PREPARE_INTERNAL/WORKLIST.json：
python scripts/prepare_storyboards.py complete PROJECT.json PREPARE_INTERNAL/WORKLIST.json --output DELIVERY --run-dir FINISH_INTERNAL
# 仅触发阈值且 FINISH_INTERNAL/PROMPT.json 已就绪：
python scripts/repair_quality.py finish PROJECT.json G01 FINISH_INTERNAL/PROMPT.json --output PROMPT_DELIVERY/G01_新视频提示词.md
# 如提示词尚缺风格、纯视觉转换或目标画幅，补齐后：
python scripts/repair_cycle.py decide PROJECT.json G01
python scripts/repair_quality.py prepare PROJECT.json G01 PROMPT_INTERNAL/PROMPT.json
# 整批填写计划后仍用上面的 finish 命令，路径替换为新计划。
```

同场景、同连续段的共同约束只写一次：INPUT 的 requirement_templates 指明 scope、must_have/must_not_have 和来源，每镜显式填 requirements_template 引用，程序展开。每镜的阶段、状态变化、剧情关键性及特有要求仍单独填写，不自动跨时空套用；具体格式见镜头要求。

extract 只提取机械字段，不生成事实阶段、关键性或审查结论；图片相对路径以 IMAGES.json 为基准并转成绝对路径。镜号或字段不明时停止，不擅自重新编号。facts.phase 为 static/before/after，requirements.keyframe.phase 为 entry/action/exit，不能用 current 代替。

新项目的用户分组直接写 input_shot_groups，已有项目才用 grouping.py 导入。--input 只创建新项目，不覆盖旧文件，其余相对路径以 PROJECT.json 为基准。prepare 可省略 --images 使用项目已有对应表；可选 --original-prompt PROMPT.txt 只记录路径，未达阈值不打开、不分析。触发后读取原文并绑定来源，再筛选与脚本相容的视觉细节；读文件或筛选缺项不影响报告交付。complete --target-aspect 16:9 仅供已经确定混用图片的目标画幅时使用。不要求用户填写这些参数或工作单。

## 质量与交付边界

- **参考图标准。** 判断“是否符合该镜脚本并适合作为生成参考”。完整动作仍保留在脚本和新视频提示词中；参考阶段不改变剧情或降低人物、关键道具和可见状态的约束。外观差异按剧情影响判断；普通脸型、服装、角度等差异不单独制造错误。
- **分组与省图。** 沿用同 Beat 内相邻镜头、每组 4–15 秒、最多 12 镜，保留计划时长。省图需同组双侧 PASS 且保留的原图锚点、当前资产及状态依据，不循环推导，保护首尾和关键变化。FAIL／uncertain 暂不省图。输入分组冲突只提示，不成为画面 FAIL 或返修理由。
- **阈值。** 一处有证据的关键剧情错误，或一处妨碍必要内容辨认的严重画面损坏，或普通明确错误涉及至少两镜且占整批镜头至少 20%。按原镜号去重：2/10 触发，2/11 不触发。待核查、合理差异及输入问题不计入分子；分组、省图和待核查不改变整批分母。图片流程没有 absent、漏镜率、必要漏镜、可推导漏镜或补帧建议。
- **报告。** 01_分镜图审查.md 和 images/，仅一张九列表：分组、原镜号、镜头时长、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。通过镜头的最后一栏只写“符合脚本”，不追加问题、允许差异解释或修改建议；省图及依据留在专列。保留、省图、待核查均展示并保存原图。待核查显示“—／暂不省图”，写需放大或澄清的具体信息；不符合项写分镜图问题及修正建议。内部 JSON 不放用户交付目录。
- **提示词。** 覆盖整批所有镜头，每镜 1 秒、静音；保留资产对应、逐镜正文、固定预演要求和资产风格。使用原资产，原提示词仅作可筛选的视觉参考，不是审查证据。对白／OS／VO 使用来源绑定的纯视觉转换，不能发明动作补剧情。交付直接可复制，不含内部路径、参数表、代码块或返修标签。
- **失效与冻结。** workflow=storyboard_images、source.kind=provided、review_schema=6、reference_policy_version=5。证据记录原图、哈希和顺序，不制造视频时间或来源。图片、脚本、资产、要求或分组变化后重新核验审查、连续性、省图及提示词依赖；原交付不覆盖，修订另存新目录并保留关联记录。
- **速度。** 默认串行整批整理和整批视觉审查，无视频匹配轮次；工具在一次操作内复用哈希、图片信息与上下文，结束前重验文件内容。共同要求复用，按阶段读取精简规则；不逐镜调用工具，不重复预检和渲染，不为未达阈值项目读取原提示词或准备新提示词。自动交付校验后不重复人工核对。按需要看原图细节，不能以缩略图或缓存代替必要判断。记录工具及总墙钟，机械测试不得冒充模型视觉提速或保证固定速度。
