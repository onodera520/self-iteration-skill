# 已配对分镜图：默认入口

用户提供已按脚本顺序配对的分镜图、完整脚本和角色／场景／道具原资产；可选 Shot 分组及原生成提示词继续保留。以下文件与字段全部由代理维护，不让用户登记。

## 首看拼图

新任务先走独立入口，只读原脚本与用户确认的图片对应，不等 facts、requirements、intent 或原资产整理：

```text
python scripts/prepare_storyboards.py overview SCRIPT.txt --images IMAGES.json --output FIRST_LOOK_INTERNAL --delivery DELIVERY
```

立即显示结果 pages 中的编号拼图；每页 view 保留逐镜原文和图片对应，status=unreviewed。首次入口不读取既有 INPUT、项目或审查。FIRST_LOOK_INTERNAL 须为新目录，保存拼图、逐页首看材料、INITIAL_OVERVIEWS.json 和 INPUT.draft.json；脚本或对应异常不创建目录，打不开的图片先修正。中途失败停止后续依赖，不把局部首看文件当成功输出。

复制 input_draft 到新的 INPUT.json 后集中补齐必要判断，不必再 extract。正式准备时显式传 --reuse-overviews FIRST_LOOK_INTERNAL（也可传 INITIAL_OVERVIEWS.json 路径）：核对完整脚本、逐镜原文／时长、镜序、原图 SHA、拼图及首看材料 SHA。有效拼图直接复用；变更、损坏或缺失会从当前原图重建，简报 initial_reuse 给出结果。仅复用图片材料，当前要求、资产审查包和空工作单仍新建，不复用任何审查判断。保留首看内部目录供恢复和交付核验。

## 整批准备

新项目默认按 SKILL 内约定补齐首看 input_draft，使用 input_version=1；手工建普通输入才查 [普通输入模板](../assets/storyboard-input-minimal.json)，需要状态建模才查 [状态交接模板](../assets/storyboard-input.json)。已有项目沿用原字段，完整格式仅在需要时查 [项目模板](../assets/storyboard-project.json)。逐镜 script 和 source_script 保留原文；duration 使用脚本计划秒数，并填写 duration_source。缺失时才提出有明确来源的建议时长，不把示例或推断当作用户事实。

原脚本有行首“镜头N”及依次排列的【时长】【镜头设计】【镜头内容】时，overview 和 extract 共用固定提取器，不临时编写正则或把非空行数当镜头数。需要单独提取而不出拼图时用原入口：

```text
python scripts/prepare_storyboards.py extract SCRIPT.txt --images IMAGES.json --output INPUT.json
```

extract 原样切取逐镜段落，保留内部换行和标点；兼容 s／秒、小数时长及逗号、句号、空白、多行分隔。镜号须为连续递增正整数，保留原起始编号；缺号、重复、字段缺失、图片数量／对应错误时不写输出。不重新排序、不覆盖已有 INPUT。图片相对路径以 IMAGES.json 所在目录为基准，输出中转为绝对路径。其他格式仍按模板原样整理，不能猜测未识别的字段。

输出只是 INPUT 草稿：原文、镜号、时长及来源、镜头设计和图片对应。代理在同一批次补齐 assets、scene_id、continuity_id、asset_ids、required_result、intent、requirements 与分组判断，再 prepare；提取成功不代表要求填写完成或审查通过。普通保留图任务不要求 facts；显式状态建模或省图才按需填写真实状态依据。facts.phase 只用 static/before/after；requirements.keyframe.phase 只用 entry/action/exit，不能填写 current，也不能自动改成某个阶段。

精简输入每镜用 image 指向已配对原图。程序生成来源批次、图片对应、固定版本、占位 reference 及空项；purpose 与 required_result 相同时复用后者，不同则显式填写 purpose。requirements.status、keyframe.phase/description、provenance、intent 剧情标记及关键约束仍由代理明确判断；普通任务不重复填写 planner facts。提供状态继承、种子或变化时必须有真实来源，不把整镜原文当 static 状态，也不为消除冲突编造变化。未填的 must_have/must_not_have/state_changes 为无新增项，不能借此漏掉真实关键要求。省图初始占位评估不用另填，收尾时复用实际审查取舍。用户分组直接保留 input_shot_groups；无分组才按原规则同批填写 event/narrative_plan。

共同约束可在 requirement_templates 写一次，指定适用 scene_id、continuity_id 或 asset_ids；每镜通过 requirements_template 明确引用。只复用 must_have/must_not_have 与对应 provenance，并与本镜新增项合并；阶段、状态、关键性与特有来源仍逐镜填写。未知引用或范围不符会拒绝，不自动套用。示例见精简模板及 [共同要求](shot-requirements.md#共同要求只写一次)。

```text
python scripts/prepare_storyboards.py prepare PROJECT.json --input INPUT.json --reuse-overviews FIRST_LOOK_INTERNAL --run-dir PREPARE_INTERNAL --output DELIVERY --concise
```

--input 仅用于不存在的 PROJECT.json，不和 --images 同用。除 extract 已转为绝对路径的图片外，项目相对路径仍以 PROJECT.json 为基准；项目及 INPUT 父目录须已存在。--output 是计划交付目录，接受新目录或已存在的空目录，不删除空目录；拒绝已有文件的交付或项目／工作目录落入交付中，不创建交付目录。先集中检查目录、精简输入原文、必要字段和阶段枚举；显式状态冲突在准备阶段检查，再沿用完整要求校验与图片检查。全部通过后才保存项目和工作单。提取或准备失败即停止后续步骤，不能继续使用不存在的 INPUT／PROJECT 或自动猜测缺失要求。以下是已有项目的兼容入口，不重复执行两次准备。

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

省略 --images 使用已保存对应表；可选 --original-prompt PROMPT.txt 只记录文件路径，不打开或检查内容。prepare 在一次操作中验证全部图片、脚本要求和资产，建立基线，输出 CONTEXT.json、REVIEW.view.json、WORKLIST.json、RUN.json。传 --reuse-overviews 时使用核验有效的首看拼图；否则新建 overviews/overview_NNN.png。阅读视图给出总览路径和各页镜号；WORKLIST.overview_manifest 绑定新工作目录内的 overviews/OVERVIEWS.json。总览属于内部看图材料，交付仍保存全部原图。内部运行目录须为新目录；交付可使用空目录。输入失败不写入项目、不产生审查。原图和原资产缺少必要可见信息时，回到相应输入澄清，不能伪造证据。

总览默认每页9张、3×3，从左到右、从上到下严格沿用已确认镜序，不按文件名重排。超过9张自动分页，末页空位留白；按 EXIF 方向等比完整缩放，镜号放在图片外，不遮挡画面。分页与 Shot 分组无关，跨页相邻镜头仍检查连续性。

## 字段速查

正常执行使用 SKILL 入口的普通字段约定，不另读接口或模板。显式状态建模、省图及特殊证据才查 [字段速查](fields.md)。普通保留图任务可不填 facts，由程序保存为空数组；实际可见事实、阶段和结论仍须明确。未录入省图状态依据的图保留，不能自动批准省图。

## 一次整批审查

默认新项目使用 single_pass 策略；历史项目未指定策略时保留旧上下文。新任务只看 overview 首看拼图一次，将 visible_facts 存入返回的 OBSERVATIONS.json。prepare --reuse-overviews 验证脚本/镜序/原图后将事实自动带入 WORKLIST；来源改变不复用观察。已有事实不构成自动通过，仍按脚本填写明确判断，不再次打开图片。

逐页审查包 REVIEW.pageNNN.json 保留脚本、完整要求和边界文本背景；images_to_open 只列本页分镜总览，不生成资产拼图，不重开上一页末镜。相邻连续性直接复用落盘观察。工作单和逐页包继续受文件指纹绑定，旧资产拼图收据仍兼容。

新任务加 `--concise` 使用 WORKLIST 版本4，verdict 明确覆盖三组检查，阶段及 match_level 显式填写；复用首看事实。FAIL 只写 findings，uncertain 只写 unresolved，见 [字段速查](fields.md)。程序展开全批 checks、旧七项、reason、issues 和 repair_assessments，不重复填同一错误；必要剧情、省图和阈值要求不变。

未加 --concise 的兼容入口生成版本3，每镜显式填写：

- check_groups：content（identity/scene/props）、state（key_state/continuity）、reference（composition/cleanliness），各 PASS/FAIL/uncertain。
- check_exceptions：仅异常具体项，例如 {"props":"FAIL"}。每组汇总必须与具体异常一致，不允许缺异常定位的 FAIL/uncertain。
- verdict、reference_phase、observation.visible_facts、reference 取舍；PASS 还需 match_level=0/1/2/3，分别为严格匹配及三级放宽。

三级在同一次观察中判断，全部必要剧情元素始终成立；不重新匹配或选帧。按 [图片审查规则](storyboard-review.md#动作可读性与核心表演)，核心动作关系足够识别时允许局部模糊／画外裁切，核心矛盾或构图整体排除核心表演直接 FAIL；排除上述情形后仍证据不足才 uncertain，不放大、不安排复查。PASS 默认“符合脚本”，FAIL/uncertain 写具体原因，uncertain 写需确认的信息；双侧省图理由仍明确填写。程序机械展开旧七项，版本1/2兼容。事实记录一次后复用，不自动补结论。

阶段未知不得 PASS；明显人物矛盾仍可 FAIL，即使动作阶段无法确定。不要为了让图片通过而改写脚本或要求。相邻图片只校对可见连续性，不能要求它们证明中间运动轨迹。七项检查中的动作／构图应按参考图适用范围判断，无法证明动态过程本身不构成 uncertain。

工作单绑定一次准备时的 context_fingerprint；有 overview_manifest 时还检查总览清单、各页哈希及逐镜原图对应，变化须重新准备。旧工作单无该字段仍兼容。原图证据包含 path、sha256、observation、visible_facts、interpretation；工具展开时附回原绑定。完整审查采用 review_schema=6、reference_policy_version=5、source_kind=provided、source_fingerprint。不得填写视频时间、视频 SHA256、映射或 absent。全批 checks 为 shot／continuity／story；boundary_checks 为空，相邻图的可见连续性写入逐镜检查。

涉及原资产的判断继续填写 asset_comparisons 的镜号、资产 ID、aspect、decision 和实际观察／剧情依据；版本 2 自动补齐遗漏的 asset_sha256、同镜 evidence_refs、空辅助数组及 PASS 的空 followup。已填写的绑定不被覆盖，错误绑定仍被拒绝。只有 FAIL 镜头填写 repair_assessments。issues 填镜号、可见问题、expected、actual、fix 等原有语义字段，程序补同镜 evidence 和固定 repair_target=storyboard_image，不使用 time_range。返修字段详见 [返修依据](repair-assessments.md)。

省图仍先判断剧情分组，再在合法组内选图。必须有同组双侧已通过且保留的原图、当前原资产与可推导状态依据，不循环推导，保护首尾、关键变化及必要锚点。保留为 anchor／derivable=false，未填的理由补“保留原图”；建议省图为 ai_fill／derivable=true，双侧 basis_shot_ids 和 reason 仍须明确填写；FAIL 或 uncertain 为 pending／derivable=null，理由复用问题或待核查说明。所有原图仍展示并保存，省图不删除脚本镜头，不表示生成已验证。

## 一次收尾与冻结

```text
python scripts/prepare_storyboards.py complete PROJECT.json PREPARE_INTERNAL/WORKLIST.json --output DELIVERY --run-dir FINISH_INTERNAL
```

complete 在同一锁和证据周期内恢复完整审查、核验、记录、规划、判断阈值、渲染并冻结，避免多命令重复构建上下文。一次操作内复用哈希和图片元信息，退出前重新读取全部依赖内容；同大小、同修改时间的替换也不能绕过校验。内部目录、交付目录和项目独立，失败后查看 FINISH_REPORT，修正后使用新目录重试。

新报告 delivery_format_version=3：冻结前自动比对九列与当前脚本、审查及取舍，核验逐镜原图哈希与链接、缩略图预览像素、行序、完整覆盖及交付文件集合。未达阈值校验成功后直接交付；达阈值则优先继续提示词导出，完成后再结束交付。不再次人工逐镜核对报告和图片，也不再次渲染。失败或刚修改渲染／规则时才定位检查；旧冻结报告沿用原校验能力，不覆盖升级。自动校验确认交付准确呈现已有审查，不代替最初看图。

交付只有 **01_分镜图审查.md 与 images/**（达阈值另有新视频提示词），报告标题与镜头数直接接一张九列表：分组、原镜号、镜头时长、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。不附表格前的流程说明和分组诊断；诊断保留内部。通过镜头最后一栏固定为“符合脚本”，省图依据留在专列。时长采用脚本计划时长。所有行展示缩略图并链接保存的原图；不输出漏镜统计或补帧建议。

目录约定：用户指定 case 即 DELIVERY；内部项目、INPUT、首看、准备、收尾和提示词工作单统一放在 DELIVERY 同级 `.storyboard-internal/本次任务/`，绝不嵌入交付或对外交付内部 case。overview --delivery 提前检查目录独立及已有交付内容；prepare --output 与 complete 校验项目及运行目录独立。交付目录可新建或已经存在但完全为空，不删除空目录，绝不覆盖有内容的旧交付。prepare 集中报告可独立检查的目录及字段问题；已录入的跨镜状态检查不依赖省图评估是否已填写，避免写完结论后才报冲突。

图片、脚本、原资产、要求或分组发生变化后，旧上下文、审查、可见连续性、省图依据及提示词绑定失效，须重新 prepare 并核验。工具不自动把失效当 FAIL。旧交付继续冻结，新审查写新目录，并在 repair_delivery_history 保留关联。脚本修订保留 repair_baseline_history；原交付与原输入继续保留。

## 阈值与新视频提示词

达到阈值时优先使用 complete 返回的 prompt_work／prompt_work_view／prompt_output：一次读取自包含的 work.view，集中补 preparation、必要 edits 与四组判断，直接 finish 导出到同一 case。work 绑定全部来源，工具维护 SHA 与元数据；来源改变即拒绝旧 work。旧 prompt_plan／prompt_inputs 仍保存用于兼容恢复，正常新任务不同时读取这两套视图。四组记录覆盖原九项检查，空白结论、实际说话、缺镜／错序及未解决冲突仍不能导出。仅头部格式不同的原文不再重复显示，真实视觉转换仍留原文。提示词作为独立登记且不可改写的新增交付，报告和所有图片保持原冻结清单。

按整批全部原镜号计算：一处关键剧情错误，或一处妨碍必要内容辨认的严重画面损坏，或普通明确错误至少两镜且占全批至少 20%。一镜多个问题只计一次；2/10 触发、2/11 不触发。uncertain、输入错误与合理差异不计分子；待核查、分组或省图不缩小分母。普通明确错误无需附加 affects_story=true 门槛；关键／严重损坏仍须充分剧情影响证据。未达阈值的 FAIL 继续如实保留。

未达阈值时不读取或分析原生成提示词，也不准备新提示词。只有路径保存在内部 deferred_storyboard_prompts；显式 API 文本同样延后登记，不进入审查上下文。触发后才读取原文，保存在 source_storyboard_prompts 并冻结来源，后续筛选复用该原文。文件缺失、编码错误或筛选缺项只影响提示词准备，审查报告正常完成；尚未读成功的文件可补齐后在提示词准备阶段继续读取。

达到阈值后，下一优先事项是导出整批所有镜头的新视频提示词，导出后再结束交付，用户自行生成。complete 若来源就绪，会同时写入 PROMPT.source.json、PROMPT.view.json、PROMPT.json；代理阅读视图，集中核对／修改精简计划，再用 repair_quality.py finish 导出。若缺资产风格、旧提示词筛选或纯视觉转换，报告先正常完成，FINISH_REPORT 标 prompt_status=needs_preparation，一次汇总缺项并给出 prompt_inputs 路径。PROMPT.inputs.json 保留原资产路径／SHA、需转换原文／SHA、旧提示词来源及自动选择的 input_aspect，并明确可见剧情保真范围；混用画幅不属于待确认缺项。代理据此同批补齐项目字段，再直接 repair_quality.py prepare／finish，不单独 decide 或重做仍有效的视觉判断。prepare 只刷新风格准备变化，其他证据变化须重新核验。原提示词已登记后如主动修改须重新 register 并筛选，不能当作当前来源自动替换已冻结原文。

原资产对应、已有可见逐镜内容、每镜一秒和静音要求保持。对白文字及其含义不参与提示词保真或时长检查，不要求视觉转译，也不能因此停止导出；去除说话、声音和新增文字指令，保留已有动作、表情、人物与道具关系，不新增事件。preserves_story／story_basis 仅确认已有可见内容。画幅自动按整批每镜对应图的数量选最多的显示画幅，同一比例不同分辨率合并并应用 EXIF 方向，数量并列取原镜序最先出现者；不按像素面积、时长、分组或 PASS 数加权，不询问、不裁图。混用时仅用户另有明确指定才设 storyboard_target_aspect（或 complete --target-aspect 宽:高）；自动结果不写入该覆盖字段。旧提示词保存在 source_storyboard_prompts，绑定 source_fingerprint；repair_prompt_references 的来源字段也使用 source_fingerprint，其他筛选规则不变。它仅提供与脚本相容的视觉建议，不充当图像审查证据。

编排计划绑定完整来源；原资产、图片、脚本、目标画幅、原提示词或其筛选变化后必须重新准备并核验计划。项目到提示词导出停止，由用户自行生成。

## 压缩或中断后的恢复

每页实际看图后保存工作单，不能只把观察放在聊天里。任务摘要只需 RUN.json 的绝对路径、当前阶段和下一步。恢复时不通读 PROJECT、CONTEXT、源码或冻结交付清单，不重新 extract／prepare：

```text
python scripts/prepare_storyboards.py resume PROJECT.json PREPARE_INTERNAL
python scripts/prepare_storyboards.py resume PROJECT.json PREPARE_INTERNAL --page 2
python scripts/prepare_storyboards.py resume PROJECT.json PREPARE_INTERNAL --shots S06
```

默认输出字段进度及视图路径；--page 返回一页审查包与已存记录，--shots 返回选定镜头及左右相邻镜头的当前原文、状态、原图路径、保存的判断与问题，保留整批分组背景和相关资产。两者不能同时使用，新策略 detail_queue 为空，unresolved_items 只列已有记录的疑点文字，不包含重开图片任务；历史策略兼容旧队列。涉及远处省图依据时显式补读相应镜号。恢复入口重新校验原图、脚本、资产、总览绑定及已保存上下文；来源改变即停止。记录存在不代表实际审查已经完成，更不代表 PASS。工具不自动补结论，complete 仍作全部质量校验。旧准备目录没有 REVIEW.view 时兼容 CONTEXT，也可用 --shots 得到精简视图。

prepare／complete 默认打印简报；complete 另保存 FINISH.view.json，压缩后只读此简报接着处理。完整 FINISH_REPORT、指纹及冻结文件清单照常保存。仅诊断需要时使用 --detailed。status=complete 仅表示审查报告完成；prompt_status=below_threshold 直接交付，needs_preparation／needs_semantic_review 按 prompt_plan／prompt_inputs 优先继续导出，不因压缩重跑仍有效的 complete。
