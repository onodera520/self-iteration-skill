# 已配对分镜图：默认入口

用户提供已按脚本顺序配对的分镜图、完整脚本和角色／场景／道具原资产；可选 Shot 分组及原生成提示词继续保留。以下文件与字段全部由代理维护，不让用户登记。

## 整批准备

新项目默认从 [精简输入模板](../assets/storyboard-input.json) 整理真实输入，使用 input_version=1；已有项目沿用原字段，完整格式仅在需要时查 [项目模板](../assets/storyboard-project.json)。逐镜 script 和 source_script 保留原文；duration 使用脚本计划秒数，并填写 duration_source。缺失时才提出有明确来源的建议时长，不把示例或推断当作用户事实。

原脚本有行首“镜头N”及依次排列的【时长】【镜头设计】【镜头内容】时，使用固定提取入口，不临时编写正则或把非空行数当镜头数：

```text
python scripts/prepare_storyboards.py extract SCRIPT.txt --images IMAGES.json --output INPUT.json
```

extract 原样切取逐镜段落，保留内部换行和标点；兼容 s／秒、小数时长及逗号、句号、空白、多行分隔。镜号须为连续递增正整数，保留原起始编号；缺号、重复、字段缺失、图片数量／对应错误时不写输出。不重新排序、不覆盖已有 INPUT。图片相对路径以 IMAGES.json 所在目录为基准，输出中转为绝对路径。其他格式仍按模板原样整理，不能猜测未识别的字段。

输出只是 INPUT 草稿：原文、镜号、时长及来源、镜头设计和图片对应。代理在同一批次补齐 assets、scene_id、continuity_id、asset_ids、required_result、facts、intent、requirements 与分组判断，再 prepare；提取成功不代表要求填写完成或审查通过。facts.phase 只用 static/before/after；requirements.keyframe.phase 只用 entry/action/exit，不能填写 current，也不能自动改成某个阶段。

精简输入每镜用 image 指向已配对原图。程序生成来源批次、图片对应、固定版本、占位 reference 及空项；purpose 与 required_result 相同时复用后者，不同则显式填写 purpose。requirements.status、keyframe.phase/description、provenance、有来源的必要 facts、intent 剧情标记及关键约束仍由代理明确判断；状态继承、种子、变化和来源不推断。未填的 must_have/must_not_have/state_changes 为无新增项，不能借此漏掉真实关键要求。省图初始占位评估不用另填，收尾时复用实际审查取舍。用户分组直接保留 input_shot_groups；无分组才按原规则同批填写 event/narrative_plan。

共同约束可在 requirement_templates 写一次，指定适用 scene_id、continuity_id 或 asset_ids；每镜通过 requirements_template 明确引用。只复用 must_have/must_not_have 与对应 provenance，并与本镜新增项合并；阶段、状态、关键性与特有来源仍逐镜填写。未知引用或范围不符会拒绝，不自动套用。示例见精简模板及 [共同要求](shot-requirements.md#共同要求只写一次)。

```text
python scripts/prepare_storyboards.py prepare PROJECT.json --input INPUT.json --run-dir PREPARE_INTERNAL --output DELIVERY
```

--input 仅用于不存在的 PROJECT.json，不和 --images 同用。除 extract 已转为绝对路径的图片外，项目相对路径仍以 PROJECT.json 为基准；项目及 INPUT 父目录须已存在。--output 是计划交付目录，prepare 提前拒绝已有交付或项目／工作目录落入交付中，不创建交付目录。先集中检查精简输入原文、必要字段和阶段枚举，再沿用完整要求校验与图片检查；全部通过后才保存项目和工作单。提取或准备失败即停止后续步骤，不能继续使用不存在的 INPUT／PROJECT 或自动猜测缺失要求。以下是已有项目的兼容入口，不重复执行两次准备。

`config.workflow=storyboard_images`；`storyboard_images` 依脚本原序完整覆盖每镜一次。输入可为下列两种 JSON，路径相对项目文件解析。已知对应关系不再匹配，不根据文件名排序；数量、镜号、顺序、重复对应或图片解码失败集中作为输入问题修正，不记为剧情错误。

```json
[{"shot_id":"S01","path":"storyboards/S01.png"},{"shot_id":"S02","path":"storyboards/S02.png"}]
```

```json
["storyboards/第一张.png","storyboards/第二张.png"]
```

支持 PNG、JPEG、WebP，按 EXIF 方向取得显示尺寸。每个镜号只能有一个对应项；同一图片被用户明确用于两个不同镜头时保留该对应，不自动去重。原图不裁切、不改写。内部 `groups` 是覆盖全部脚本的一批来源；用户 Shot 分组另存 `input_shot_groups`，不改变审查批次、阈值分母或提示词范围。

```text
python scripts/prepare_storyboards.py prepare PROJECT.json --images IMAGES.json --run-dir PREPARE_INTERNAL --output DELIVERY
```

省略 --images 使用已保存对应表；可选 --original-prompt PROMPT.txt 只记录文件路径，不打开或检查内容。prepare 在一次操作中验证全部图片、脚本要求和资产，建立基线，输出 CONTEXT.json 与 WORKLIST.json。目录须为新目录。输入失败不写入项目、不产生审查。原图和原资产缺少必要可见信息时，回到相应输入澄清，不能伪造证据。

## 一次整批审查

先阅读 [精简图片规则](storyboard-review.md)、CONTEXT 中的原文、已解析要求、原资产和每镜原图，再集中填写 WORKLIST。工具校验结构和文件绑定，视觉结论必须来自实际看图。不得把自动生成的 uncertain 草稿当成已完成审查，也不得用色块测试结果证明实际人物识别能力。

默认 WORKLIST 为版本 2，每镜显式填写七项 checks、verdict、reference_phase、observation.visible_facts 和 reference 取舍。可见事实记录一次，需足以支持身份、阶段和检查结论；工具复用这些事实填写 observation、identity_reason、phase_reason，必要时可显式覆盖说明。PASS 的 reason／interpretation 默认为“符合脚本”，不填写 followup；FAIL／uncertain 必须填 reason，uncertain 还须具体 followup，FAIL 的 issues 和 repair_assessments 继续完整。旧版工作单版本 1 原样兼容。阶段为 entry／action／exit／unknown；全镜动作来自 script 和 state_changes，静帧要求来自 keyframe。

| 情况 | 判断与处理 |
| --- | --- |
| 脚本为“甲把钥匙交给乙”，图为甲持钥匙、乙准备接 | 可作为 entry 参考；不要求乙已经拿到钥匙，不因没有运动证明而失败 |
| 明确处于交接结束状态，却由错误人物持钥匙 | 与脚本可见结果矛盾，FAIL；指出这张图具体应修改的持物关系 |
| 关键人物、道具、地点或已确定阶段的状态明确不符 | FAIL，附同镜原图观察、原文依据及具体修改建议 |
| 看不清持物者、必要道具或无法确定阶段 | uncertain，放大原图或集中澄清；未解决时显示“—／暂不省图” |
| 普通角度、服装细节、姿态有合理差异且不改变剧情 | 可 PASS；必要等效依据留在内部观察或资产对照，报告只写“符合脚本” |

阶段未知不得 PASS；明显人物矛盾仍可 FAIL，即使动作阶段无法确定。不要为了让图片通过而改写脚本或要求。相邻图片只校对可见连续性，不能要求它们证明中间运动轨迹。七项检查中的动作／构图应按参考图适用范围判断，无法证明动态过程本身不构成 uncertain。

工作单绑定一次准备时的 context_fingerprint。原图证据包含 path、sha256、observation、visible_facts、interpretation；工具展开时附回原绑定。完整审查采用 review_schema=6、reference_policy_version=5、source_kind=provided、source_fingerprint。不得填写视频时间、视频 SHA256、映射或 absent。全批 checks 为 shot／continuity／story；boundary_checks 为空，相邻图的可见连续性写入逐镜检查。

涉及原资产的判断继续填写 asset_comparisons 的镜号、资产 ID、aspect、decision 和实际观察／剧情依据；版本 2 自动补齐遗漏的 asset_sha256、同镜 evidence_refs、空辅助数组及 PASS 的空 followup。已填写的绑定不被覆盖，错误绑定仍被拒绝。只有 FAIL 镜头填写 repair_assessments。issues 填镜号、可见问题、expected、actual、fix 等原有语义字段，程序补同镜 evidence 和固定 repair_target=storyboard_image，不使用 time_range。返修字段详见 [返修依据](repair-assessments.md)。

省图仍先判断剧情分组，再在合法组内选图。必须有同组双侧已通过且保留的原图、当前原资产与可推导状态依据，不循环推导，保护首尾、关键变化及必要锚点。保留为 anchor／derivable=false，未填的理由补“保留原图”；建议省图为 ai_fill／derivable=true，双侧 basis_shot_ids 和 reason 仍须明确填写；FAIL 或 uncertain 为 pending／derivable=null，理由复用问题或待核查说明。所有原图仍展示并保存，省图不删除脚本镜头，不表示生成已验证。

## 一次收尾与冻结

```text
python scripts/prepare_storyboards.py complete PROJECT.json PREPARE_INTERNAL/WORKLIST.json --output DELIVERY --run-dir FINISH_INTERNAL
```

complete 在同一锁和证据周期内恢复完整审查、核验、记录、规划、判断阈值、渲染并冻结，避免多命令重复构建上下文。一次操作内复用哈希和图片元信息，退出前重新读取全部依赖内容；同大小、同修改时间的替换也不能绕过校验。内部目录、交付目录和项目独立，失败后查看 FINISH_REPORT，修正后使用新目录重试。

新报告 delivery_format_version=3：冻结前自动比对九列与当前脚本、审查及取舍，核验逐镜原图哈希与链接、缩略图预览像素、行序、完整覆盖及交付文件集合。校验成功直接交付，不再次人工逐镜核对报告和图片，也不再次渲染。失败或刚修改渲染／规则时才定位检查；旧冻结报告沿用原校验能力，不覆盖升级。自动校验确认交付准确呈现已有审查，不代替最初看图。

交付只有 **01_分镜图审查.md 与 images/**，报告恰有一张九列表：分组、原镜号、镜头时长、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。通过镜头最后一栏固定为“符合脚本”，不追加解释或建议，省图依据留在专列。时长采用脚本计划时长。所有行展示缩略图并链接保存的原图；不输出漏镜统计或补帧建议。

图片、脚本、原资产、要求或分组发生变化后，旧上下文、审查、可见连续性、省图依据及提示词绑定失效，须重新 prepare 并核验。工具不自动把失效当 FAIL。旧交付继续冻结，新审查写新目录，并在 repair_delivery_history 保留关联。脚本修订保留 repair_baseline_history；原交付与原输入继续保留。

## 阈值与新视频提示词

按整批全部原镜号计算：一处关键剧情错误，或一处妨碍必要内容辨认的严重画面损坏，或普通明确错误至少两镜且占全批至少 20%。一镜多个问题只计一次；2/10 触发、2/11 不触发。uncertain、输入错误与合理差异不计分子；待核查、分组或省图不缩小分母。普通明确错误无需附加 affects_story=true 门槛；关键／严重损坏仍须充分剧情影响证据。未达阈值的 FAIL 继续如实保留。

未达阈值时不读取或分析原生成提示词，也不准备新提示词。只有路径保存在内部 deferred_storyboard_prompts；显式 API 文本同样延后登记，不进入审查上下文。触发后才读取原文，保存在 source_storyboard_prompts 并冻结来源，后续筛选复用该原文。文件缺失、编码错误或筛选缺项只影响提示词准备，审查报告正常完成；尚未读成功的文件可补齐后在提示词准备阶段继续读取。

达到阈值后输出整批所有镜头的新视频提示词，用户自行生成。complete 若来源就绪，会同时写入 PROMPT.source.json、PROMPT.view.json、PROMPT.json；代理阅读视图，集中核对／修改精简计划，再用 repair_quality.py finish 导出。若缺资产风格、旧提示词筛选、纯视觉转换或混用画幅的目标，报告先正常完成，FINISH_REPORT 标 prompt_status=needs_preparation 并给出缺项。补齐后重新 decide，再 repair_quality.py prepare／finish，不重做仍有效的视觉判断。原提示词已登记后如主动修改须重新 register 并筛选，不能当作当前来源自动替换已冻结原文。

原资产对应、逐镜内容、每镜一秒和静音要求保持。所有图片共同画幅直接沿用；混用时导出前确定 storyboard_target_aspect（或 complete --target-aspect 宽:高），不自动裁图。旧提示词保存在 source_storyboard_prompts，绑定 source_fingerprint；repair_prompt_references 的来源字段也使用 source_fingerprint，其他筛选规则不变。它仅提供与脚本相容的视觉建议，不充当图像审查证据。

编排计划绑定完整来源；原资产、图片、脚本、目标画幅、原提示词或其筛选变化后必须重新准备并核验计划。项目到提示词导出停止，由用户自行生成。
