# 抽帧匹配、内容校对与漏镜处理

默认用户视频＋原脚本＋资产图，不需要原生成提示词，不自动修图或补图。先保存原视频审查，再按 [自动返修](auto-repair.md) 的独立阈值和授权边界决定是否调用固定工作流一次；不得用视频错误改写脚本。不比较实际与计划时长，不据此判画面失败；聚合另按计划时长执行 15 秒上限。视频实测时长及实际 PTS 只定义检索范围和证据位置。

## 默认标准：剧情信息成立即可通过

先判断本镜要让观众理解什么，再检查当前画面是否表达了这件事。人物角色及行动主体、背景与空间关系可辨认，关键动作、结果和前后因果成立，且满足用户明确严格要求，即可 PASS。不是只要人物站在正确背景里就通过；关键事件仍须在本镜视频中有证据。

- 允许：不影响剧情的姿势、具体站位、左右画面投影、景别、视角、运镜、动作幅度和实施细节差异，以及普通外观偏差。背景装饰不必复刻，但不能错成影响剧情的地点。脚本写“中景”而画面较近，只要必要关系与信息可见，可通过。
- 必须保留：谁对谁做了什么、关键道具由谁持有、交接是否完成、必要动作结果、关键空间关系、事件顺序与必要切镜。脚本交接钥匙而视频仍未交接，不能因两人和背景正确判通过。
- 明确严格要求：用户明确要求必须精确满足的景别、站位、动作或其他特征仍须满足。脚本普通描述不自动等于严格复刻指令；它若承载剧情必需信息仍属必要要求。
- uncertain 只用于未定位镜头、剧情必需信息或明确严格要求证据不足。非关键细节看不清不触发补查；已有关键错误仍 FAIL。不能把邻镜中的关键动作当成本镜已发生，也不能把一帧重复分配给多个脚本镜头掩盖漏镜。

在现有 shot_reviews.reason 中简述剧情为何成立；有差异可在 evidence.interpretation 中说明为何无影响。FAIL 的 issues.expected/problem/actual 说明具体剧情影响或违反的严格要求，不能只写“与描述略有不同”。保留中性事实，不为通过改写原脚本、状态变化或观测。工具校验结构与证据绑定，语义判断仍由组级批量审查承担。

## 批量匹配与补查

import-video 登记原视频；media.py extract --project/--group 校对视频绑定。首轮默认稀疏抽取起止帧、少量均匀帧、切点前后和候选片段中间帧；不自动启动全片 0.5 秒采样。evidence.json 的 candidate_segments 是切点候选区间，contact_sheets 是按时间排列、每页最多 24 帧的联系表索引，均不代表真实镜头已确认。首轮按页查看完整稀疏表；增量补帧只遍历本次新增表，不重开已审旧页。脚本无时长也可抽帧；联系表仅定位，需要细节时看其对应原图。稀疏帧不能证明没有漏镜或错误转场；屏幕文字不在默认审查范围。

整组脚本先压成一行一镜的关键事件清单，对照联系表一次粗匹配，首轮每镜选 1–3 个候选；不是证据数量硬上限，关键动作需要更多证据时继续补齐。已有充分证据的镜头立即记录 matched 与观察，后续复用；不逐镜重新遍历全片。对照 requirements.py 计算的状态约束筛查已观察到的冲突，例如开伞应在追出后，候选却已撑开；没有可见事实不得声称工具自动识别到冲突。

只有 uncertain、疑似漏镜、瞬时关键动作、连续性冲突或切镜边界不清，才批量补查争议区间（必要时扩至邻镜）；定位且证据足够即停止。关键动作/转场仍需连续片段或相应视频查看证据，不能以联系表清楚为由免检。无法确认则保留 uncertain。多数镜头无法定位、剪辑极快或时间映射整体失效才可全片密查，并记录升级原因。

```text
python scripts/media.py extract INPUT.mp4 EVIDENCE_MORE --project PROJECT.json --group G01 --base-evidence EVIDENCE_DIR/evidence.json --dense-range 1.8:2.5 --dense-range 4.4:5.8
```

--dense-range 可重复，合并重叠范围后一次抽取；默认局部步长 0.2 秒，仍不清楚时收窄到极短争议范围并用 --dense-step 0.1 或更适合动作的步长。已知动作极短可直接细采，不强制多走一轮。能查看视频时优先直接看动作前后几秒；无法查看时用连续帧，不声称已看视频。无范围时显式 --dense-step 才是全片密采，仍不等于完整视觉审查。补帧继承旧帧的路径、哈希和时间，新增帧按实际 PTS 合并，只抽尚未存在的帧，不覆盖旧 evidence.json。证据依赖始终做 SHA256 验证；原视频或旧帧变化则拒绝复用。

补帧 contact_sheets 默认只展示 new_frame_paths（contact_sheet_scope: new_frames）；frames 仍包含全部旧帧和新增帧。context_contact_sheets 仅含各补查区间前后最近的少量旧帧，按需辅助连续性判断，它们不是自动确认的锚点。完整联系表用 --full-contact-sheet 显式生成，存入 full_contact_sheets 供追溯，不作为默认必看页；未新增帧时不生成新的增量表。初次无 --base-evidence 时 contact_sheets 仍是全体首轮稀疏帧。

局部加密只解决定位，不能授权 absent。确认漏镜前仍须完整回看原视频，或完成覆盖整份视频的有效连续证据复查；密采目录、范围元数据及 full_rescan 标记本身都不是视觉证明。无法覆盖或仍不确定就保持 uncertain。

### 增量补查与批量登记

带 --project/--group/--base-evidence 的已有视频补帧同时生成内部 incremental_review.json：保存补帧前有效上下文、映射草稿 mapping_draft，以及 impact 中的 primary（主要检查）、adjacent（邻接）、dependency_recheck（状态或依据依赖）、boundary_recheck（左右来源组边界）、reuse（暂可复用）。此清单是保守路由，不是视觉结论或最终交付。

1. 默认只读新增帧表和受影响镜头的现有观察；需要上下文时查看少量旧邻帧。候选瞬间不等于镜头时间范围，工具使用相邻候选之间的保守范围；未可靠定位的镜头仍纳入补查，不能仅因新帧不在猜测范围而跳过。主要检查项未必仅一个，不能强制锁死为“该镜±1”。
2. 未变图片的可见事实按 SHA256 复用；依赖未变且无新矛盾的确认镜头不重看。边界变化复核左右镜及来源组边界，状态继承、推导依据或多镜问题变化时扩展相关镜头。依赖复核先读状态和已有事实，不自动要求重开图片；矛盾或缺证才补看。脚本/资产/规则变更使相关结论失效，工具无法精确界定时保守复核整组。
3. 从 mapping_draft 取出完整映射，更新受影响行，必要时加 selections，一次 map 登记。未变行原样复用；原先有效的完整补查范围与观察可以保留，但新证据冲突须重新判断。不要将报告本身直接传给 map。
4. 一次 context --incremental-from 获取当前组上下文：incremental.reusable_observations 复用旧事实，review_draft 仅填仍可复用的逐镜记录，needs_review_rows 列需复核镜头。旧事实不等于当前结论；旧版本、旧指纹和被替换素材不能借此复活。
5. 补齐受影响行及依赖判断，根据全部有效记录更新组级 checks、coverage、issues、uncertainties、省图与边界，使用当前 context_fingerprint 一次提交完整 review。草稿不带组级通过结论，不绕过现有校验。其余镜头通过复用观察和记录完成登记，不再发生逐镜 LLM 往返。

```text
python scripts/storyboard.py map PROJECT.json MAPPING_UPDATED.json
python scripts/previs.py context PROJECT.json G01 --incremental-from EVIDENCE_MORE/incremental_review.json
python scripts/previs.py review PROJECT.json GROUP_REVIEW_UPDATED.json
```

例如只补查 S03 附近：优先查看新增证据及 S03，必要时复核 S02/S04；S01、S05–S08 在无状态/推导依赖及其他变化时复用。若 S06 的省图依赖 S03，则同时复核该依据，不能以“不相邻”为由跳过。停止条件仍是镜头定位且必要证据充分；增量流程不改变 matched/uncertain/absent、独立视觉单元、两表交付或付费限制。

一次读完整组的脚本、requirements、资产和候选，批量匹配。每张图片记录中性的 visible_facts、独立的 interpretation 与兼容摘要 observation，按 SHA256 保存复用；同哈希仅在观察遗漏或矛盾时补看。不同帧的状态不能合成同一帧事实。回看原视频取得新信息时追加实际查看范围与观察。

```json
{
  "group_id": "G01", "video_sha256": "CURRENT_VIDEO_SHA256",
  "evidence_file": "evidence/G01/evidence.json",
  "shots": [
    {"shot_id":"S01","status":"matched","observation":"女孩握唯一钥匙，男孩未接触",
     "candidates":[{"path":"ABSOLUTE_EXTRACTED_PATH","time":0.25}]},
    {"shot_id":"S02","status":"uncertain","observation":"当前未定位观察镜头，需要回看",
     "candidates":[]},
    {"shot_id":"S03","status":"matched","observation":"男孩拿稳钥匙，女孩松手",
     "candidates":[{"path":"ABSOLUTE_EXTRACTED_PATH_3","time":4.5}]}
  ]
}
```

storyboard.py map 一次登记整组。候选来自未改动的 evidence.json，实际时间按原镜序严格递增；不能调换脚本编号掩盖乱序。补查时保留未变镜头的候选和观察，提交完整组的新映射，仅重看受影响镜头及左右衔接。

**独立镜头门槛**：同一连续视频镜头不能仅凭剧情相似分配为两个脚本镜头。若后镜需要独立视觉单元、剧情必需机位、关键动作或必要切镜，必须定位相应证据；候选仍是前镜延续且没有所需单元时，填 independent_visual_unit: false 并标 uncertain，完整补查确认缺失才 absent。工具拒绝把该字段为 false 的行登记为 matched；不能一边观察“仍是上一镜/没有独立镜头”，一边省略矛盾字段并登记 matched。时间不同、帧不同本身不证明独立镜头存在。连续长镜若确实呈现不同脚本动作单元且没有必要切镜要求，可以分别对应，注明各自事件及时间；不新增“一切必须硬切”的限制，也不因非关键机位差异误报漏镜。

- **matched**：按角色、事件、必要场景/空间关系和顺序定位对应镜头，不要求姿势、景别或动作细节逐字复刻。已定位不代表内容通过；有关键错误交后续逐镜判断，不影响剧情的差异可 PASS。
- **uncertain**：无法对应本镜事件、尚未定位或必要证据不足；非关键细节不同不构成“完全不符”。先回看原视频/加密抽帧；不直接判漏镜，不批准省图，不触发付费重试。
- **absent**：完整补查原视频确认没有该镜。需 full_rescan: true、空 candidates，以及 `rescan: {"ranges":[[0,6]],"observation":"完整回看 0–6 秒，记录实际出现的镜头和缺失内容"}`。这里 6 必须换成该视频实测终点，多个范围可连续覆盖整份视频，不能留空档或缩短原视频范围。工具检查范围与绑定，实际回看由代理负责。

补查找到对应内容：将新抽帧存新证据目录，更新映射并替换原错误选帧，复查该镜与左右衔接。不把“抽错帧”误报为视频错误。完整补查后仍不能确认内容或时序时继续 uncertain，不伪造 absent。

默认在上述 MAPPING.json 顶层增加 selections 数组，元素格式见下文。一次 storyboard.py map 同时验证整组映射和所有选帧，在同一 .lock 内保存一次；任何选帧失败不保存半组。缺失/不确定镜头不选图，不必为未变选帧重复登记。旧调用仍兼容，也可在一次工具调用中顺序选帧，复用匹配判断，不逐镜调用 LLM：

```python
from previs import read, save, locked
from storyboard import select_image
with locked(project_path):
    p = read(project_path)
    for selection in read(selections_path):
        select_image(p, project_path, selection)
    save(project_path, p)
```

selection 为 `{"shot_id":"S01","path":"候选路径","source":{"kind":"frame","time":0.25},"reason":"关键状态清楚"}`；缺失或不确定镜头不强选图。匹配与观察不启动费用。

## 批量组级审查，逐镜独立结论

执行时只获取一次本组 context，保存完整结果供本次审查使用，不为每镜重新获取。已经按图片哈希记录的事实和解释直接复用，只对观察缺漏、矛盾或新帧补看；不能复用已失效的 PASS。审查表一次写完并登记；工具报多个字段错误时集中修正，非视觉格式错误不触发重新看全组。context 内部共享同组映射校验，操作结束仍完整重验依赖 SHA256；下一次命令重新建缓存。规划直接消费本次审查的取舍依据，不再重复逐镜问是否省图。

previs.py context 一次输出全组 requirements、event（初分）、planned_duration/duration_source、narrative_plan、review_scope、scene_id/continuity_id、资产及哈希、视频/帧/映射、选帧、左右来源组边界、review_schema: 5、reference_policy_version: 5、context_fingerprint 和 previous_review。串行时一次 LLM 完成全组校对、自然边界、相邻承接、整个合并区间复杂度核对、连续性与取舍依据，一次 previs.py review 保存。具备多个完整事件和子代理时，默认按 [双任务审查](parallel-review.md) 分配最多两个只读任务，复用同一脚本和工具计算的状态；主流程核对边界画面与状态、有限争议和跨任务省图依据，用 parallel_review.py commit 一次校验写回。通过镜头无新矛盾不重看；所有共享状态只由主流程修改。禁止逐镜 context/review；旧 storyboard.py 单镜 review 不代替此入口。事件划分以脚本行动目标及承接为准，不随视频错误改变；若发现事件标注有误，先修正完整事件字段并重新取得绑定上下文，再保存审查，不直接复制旧 PASS。有 narrative_plan 时，审查必须填写 grouping_checked: true；其含义是已核对批量剧情依据，不表示画面通过。串行路径仍是整理、匹配、审查三次判断；并行任务与协调会增加判断次数，不把三个阶段说成三次调用。

优先用可用视频理解能力；否则看切点前后和镜头内部连续帧。复用已有哈希观察，只补充新证据。composition 仅用“脚本 shot_size/关键帧所需剧情信息及明确严格要求 → 已有画面描述 → 满足/违反/必要证据不足”的规则，不加开放式视觉推理或审美评判。景别名称或站位不同但必要信息清楚则 PASS；裁掉必要道具/关系则按证据 FAIL 或 uncertain。遮挡、画外和特写裁切不等于道具消失。

默认已有视频模式的三项组级 checks 为 shot/continuity/story，取 PASS/FAIL/uncertain。检查人物、场景、道具、动作及结果、顺序、必要切镜和衔接。**不检查屏幕文字**（字幕、字样、标牌文字等），不做 OCR 或逐字比对，不因文字存在、缺失、错字或样式差异判 FAIL/uncertain，也不为它补帧；不能改挂在 cleanliness、props 或 story 下继续作文字验收。cleanliness 仅保留妨碍理解人物、道具和行动的非文字画面缺陷检查。不检查对白逐字一致、配音文本或对白口型同步；脚本对白、OS、VO 的剧情含义仍可帮助理解事件，人物、关键道具、动作结果与衔接仍需证据。组级失败不会自动使所有镜头失败；逐镜结论存 shot_reviews。连续性问题须定位受影响镜头，不能一面记录该镜问题一面标 PASS。另行授权的旧生成模式仍保留原有四项检查，不改变其安全约束。

以下是单镜结构示例，实际必须按原顺序填满全组及全部边界：

```json
{
  "group_id":"G01","version":1,"video_sha256":"FROM_CONTEXT","context_fingerprint":"FROM_CONTEXT",
  "grouping_checked":true,"review_schema":5,"reference_policy_version":5,
  "checks":{"shot":"PASS","continuity":"PASS","story":"PASS"},
  "coverage":{"shot_ids":["S01"],"mapping_verified":true,"limitations":[]},
  "evidence":[{"shot_id":"S01","time":0.25,"path":"EXTRACTED_PATH","sha256":"FRAME_SHA256",
               "visible_facts":["可见西装驳领","可见白色圆领内搭","外套表面有湿水反光"],
               "interpretation":"服装结构吻合；反光与雨水相容","observation":"本镜服装结构可见"}],
  "shot_reviews":[{"shot_id":"S01","verdict":"PASS","reason":"脚本内容与衔接满足",
    "identity_reason":"局部取景中持物者及行动关系可辨认，不需要证明画外人脸",
    "evidence_times":[0.25],"checks":{"identity":"PASS","scene":"PASS","props":"PASS",
    "composition":"PASS","key_state":"PASS","continuity":"PASS","cleanliness":"PASS"}}],
  "reference_assessments":[{"shot_id":"S01","decision":"anchor","derivable":false,"basis_shot_ids":[],
    "reason":"首次出场与持物基线，需要保留","evidence_times":[0.25]}],
  "asset_comparisons":[],
  "boundary_checks":[],"issues":[],"uncertainties":[]
}
```

shot_reviews 的 verdict：

- PASS：matched、有当前选帧且已包含在同镜 evidence 中、requirements ready、七项检查全 PASS，无本镜未解决问题；相关组边界也通过。即使同组其他镜头失败，本镜仍可独立通过。
- FAIL：已定位且有选帧证据，七项检查至少一项 FAIL，issues 定位本镜。差异影响角色/行动识别、关键动作结果、因果或必要空间关系，或违反用户明确严格要求，才标“该镜需重新生成”；仅非关键差异不能支持 FAIL，不计必要漏镜。
- uncertain：剧情必需信息或明确严格要求的证据不够，或镜头尚未定位；普通细节不清不构成此结论。七项 checks 必须齐全，至少一项 uncertain、没有已确认 FAIL；填写 followup、局限和需补查内容，不省图、不计数。有已确认错误时整镜仍为 FAIL，同时保留其他 uncertain 检查。
- absent：必须对应完整补查后的 absent 映射，evidence_times 为空，不得在 evidence 里伪造该镜帧，issues 说明原视频缺失内容。组 story 必须 FAIL；漏镜绝不能 PASS。

整组 PASS 仍要求全部 matched、要求 ready、三项通过、mapping_verified、每镜证据、无未决限制。不要求 actual_shots、各镜区间长度或覆盖时长验收。不可确认的剧情必需动作/必要切镜保留 limitations/uncertainties，并使受影响镜头 uncertain；不能为通过而删记录。

## 资产外观判定：剧情优先

资产用于正确理解人物、行动和剧情，不默认逐镜复刻完整五官或服装。允许不影响剧情的脸部、服装颜色、材质与款式偏差；服装类别变化也不单独判失败。用户明确要求严格一致的特征仍须满足。道具、动作结果、场景关系与连续性继续独立检查；默认不检查屏幕文字。

每镜填写简短 identity_reason，说明本镜人物及剧情关系是否成立；absent 说明无对应画面、不能判断身份。普通 PASS 复用本镜 visible_facts、interpretation、有效帧及资产，不强制 identity_scope 或逐人 wardrobe＋appearance。visible_facts 记中性可见事实，interpretation 解释其剧情意义；observation 仅兼容摘要。先考虑雨水、光照、曝光、遮挡与模糊，不把“看起来像皮衣”直接当剧情错误。

| identity | 判断与记录 |
| --- | --- |
| PASS | 人物及行动关系可辨认，偏差不影响剧情；普通远景无需证明脸、纽扣和领型 |
| FAIL | 本镜可见差异导致认错角色、行动主体错误，或破坏关键身份、伪装、换装等线索；明确严格要求被违反也需说明 |
| uncertain | 剧情必需的信息看不清，说明所需补查；普通外观细节不清不单独触发 |

asset_comparisons 默认为空列表，仅剧情相关外观要求或问题才补详细比较；prop/scene 仍保留证据门槛，差异须影响关键道具、场景关系或明确严格要求，不因背景装饰或非关键道具表象不同判失败。每条含 id/shot_id/asset_id/asset_sha256/aspect/evidence_refs/condition_factors/stable_matches/stable_conflicts/decision/unobservable_features/followup/basis_shot_ids。aspect 为 wardrobe/appearance（identity）、prop（props）或 scene（scene）。人物比较增加 story_requirement（具体剧情要求或用户明确严格要求），FAIL/uncertain 另填 story_impact（差异或不可见信息如何影响该要求），不能只写“衣服不一样”。

详细 PASS 须有适用吻合项且无剧情相关冲突；FAIL 须有非空 stable_conflicts；uncertain 须有必要不可见特征与具体 followup，不能同时声称已确认冲突。冲突逐项填写 `{"feature":"识别伪装的服装线索","expected":"脚本指定的西装伪装","observed":"本镜清晰可见机车夹克","environment_exclusion":"雨水或光照不能解释领型和扣件差异"}`，同时说明该差异如何破坏剧情识别。没有该剧情要求时，机车夹克不单独造成 FAIL。

asset_sha256 取当前 context；PASS/FAIL 须有当前资产和本镜有效证据。evidence_refs 引用本镜 evidence 的 path/sha256/精确 time，且时间列入 evidence_times，沿用当前视频、脚本和资产指纹。identity 与适用人物比较须一致：任一 FAIL 则 FAIL，否则有 uncertain 则 uncertain，否则 PASS；普通 PASS 可不填比较，但仍须有本镜事实、时间和当前资产。工具只检查结构和关联，不证明视觉描述真实。

资产问题无论写入哪个检查项，issues 均填 asset_ids 与 asset_comparison_ids，非资产问题填空列表。多镜问题逐镜、逐资产引用各自 FAIL 比较及 issue 时间范围内证据，不能借用另一镜的 FAIL。清晰邻镜可帮助解释光照与雨水，basis_shot_ids 引用同资产同方面的独立 PASS 比较，不循环引用；不能替代本镜事实。剧情必需的信息仍不清楚则 uncertain，普通外观细节不清可通过。新证据推翻旧解释时更新受影响镜头及衔接，其他问题独立保留。

所有字段在原有组级批量判断中填写，不增加逐镜往返。有效事实按 SHA256 复用，只有矛盾或必要补证才重看。回归区分“外观偏差但剧情成立”“破坏身份/行动线索”“必要剧情信息不可见”；结构化测试不是自动视觉识别或真实视觉验收。

## 可推导省图：判据与决策表

统一使用“可推导省图”，内部值仍为 ai_fill。三个字段分别回答不同问题，不互相覆盖：mapping.status 的 matched/uncertain/absent 表示是否定位；shot_reviews.verdict 表示画面检验结论；reference_assessments.decision 表示参考图取舍候选。matched 不等于 PASS，ai_fill 不等于视频有该镜，pending 本身不等于漏镜。沿用现有字段，不另建 present/absent 二值状态。

reference_assessments 按镜顺序填 decision、reason、derivable、basis_shot_ids、evidence_times。有图评估复用 shot_reviews 的同镜 evidence_times；确认漏镜则留空，引用完整补查及依据镜，不能伪造本镜证据。

“可推导”以**省去本镜独立参考图后，故事是否仍然可读、人物与因果关系是否没有歧义**为准，不要求前后画面能唯一推出本镜的手势、微表情、构图或精确动作过程。省图只是未来生成的参考图建议，脚本镜头、必要动作和时长仍保留；不能用这个标准把实际漏镜改成 matched/PASS。

在同一次组级审查中，按下列条件判断，复用已保存的观察与 reference_assessments.reason，不增字段表单或逐镜 LLM 调用：

1. **依据有效**：仅 PASS 或完整补查确认 absent 的镜头进入推导判断。basis_shot_ids 是同来源组中顺序正确、前后夹住该镜的两个已有镜头；两者各自 PASS、有当前有效选帧且 decision: anchor，相关资产图存在。缺失镜头和其他 ai_fill 不可充当依据，禁止循环推导或降级为单侧锚点。
2. **剧情状态可以承接**：读取 requirements.py 计算的完整 entry_state/exit_state 及原 state_changes，确认省图后角色、持物、关键行动与结果不产生因果断裂或歧义。不要求复原非关键表演动作的唯一过程。代理只填写入口种子和状态变化，不重写完整入口/出口，也不能把后镜状态倒灌到前镜。
3. **区分剧情节点和表演细节**：人物首次出场、钥匙交接完成、关键状态/空间变化、关键身份揭示、叙事转折等剧情节点必须保留；资产库已有该人物不代表首次出场可省。纯手部动作、手指滑过伞柄、普通微表情等不因“独立表演信息”或特写形式自动受保护。只有该动作/表情本身承载不可替代的剧情节点（如偷换钥匙、发出决定后续行动的暗号）或用户明确要求保留此图时才保护，并写明剧情影响。沿用 facts/state_changes.critical 和 intent.critical_result/narrative_turn，纯表演细节不误标为 true；required_cut 仍保留但不独自要求留图。
4. **省图后可读且无歧义**：reason 简述“前后依据镜号及可见内容 → 无本镜独立图仍能理解的事件 → 不会丢失哪个必要关系/结果”。例如 S03 持伞、目送林默 → S05 抬眼、目光转折，角色关系与剧情自然承接；S04 手指滑过伞柄只是表演细节，即使不能唯一复原手指动作，也可提出 ai_fill 候选。若抬眼本身是关键决定，仍单独保留相应锚点。不能只写“同组”“状态相同”或“AI 能生成”。

derivable 为三值：true 表示依据有效、省去独立图后故事仍可读无歧义且无必须保护的剧情节点，可提出候选；false 表示省图会让故事断裂、有歧义或已知必须保留独立图，说明原因；null 表示证据或判断不足，说明缺什么，不能把未知写成 false。不能仅因无法唯一复原表演细节填 false/null。必要首尾及用户锁定锚点仍保留。

| 逐镜 verdict | derivable | 审查 decision | 含义及后续 |
| --- | --- | --- | --- |
| PASS | true | ai_fill | 可推导省图候选，交最终规划检查锚点约束 |
| PASS | false / null | anchor | 保留已通过图片；null 仅表示推导未定，不撤销画面通过 |
| absent | true | ai_fill | 可推导省图候选；保留漏镜结论，注明未验证 |
| absent | false | pending | 必要漏镜，需补生成 |
| absent | null | pending | 推导待检查，不因未知计入必要漏镜 |
| FAIL / uncertain | 任意 | pending | 不批准省图；分别建议修正或先补证据 |

表中 decision 是**审查候选**，不是最终省图批准。planner 在确定 ≤15 秒、≤12 镜的最终聚合后，再检查组首尾、关键锚点和同组双侧依据；候选成为新组首尾、依据被分到其他组等情况必须保留。硬约束优先于候选 true：有合格图则保留；确认缺失且必须保留则为必要漏镜。null 仍为待检查，不计必要漏镜；若审查已确认必须独立保留，应写明依据并填 false，不能用 null 掩盖已知必要条件。分组通过也不能把 FAIL/absent 升为 PASS。

所有可推导省图均为“建议，未验证”。原视频该镜 PASS 只证明原画面符合脚本，不证明省去独立参考图后仍能生成。风险/信心不是验证状态，本轮不新增 confidence/risk 或“已验证”字段，不启动专项生成。工具检查字段组合、依据资格、指纹和硬约束；故事可读性与歧义判断由上述批量审查承担，不能把工具校验通过当作生成实证。

已有视频 context 的 reference_policy_version 纳入指纹。review_schema=5 与 reference_policy_version=5 均进入指纹；旧审查与依赖它的聚合失效，不能改版本号后直接复用。有效抽帧、映射和哈希可继续使用；旧自由文字 observation 不能自动转换成新版比较证据，有效事实继续复用，按剧情标准完成组级复核；不能仅改版本号恢复通过。

boundary_checks 按 context.boundaries 原顺序填 `{"shot_id":"S00","verdict":"PASS","observation":"本组首镜与前组末镜持物衔接"}`。PASS 需邻镜 matched 证据和 ready 要求；FAIL/uncertain 反映到 continuity 和本组受影响边缘镜。其他镜头可以独立通过。

FAIL/absent 的 issues 必填 id、shot_ids、time_range、severity、problem、expected、actual、evidence、repair_target、fix，以及 asset_ids 和 asset_comparison_ids（非资产问题两者均填空数组）。severity 为 low/medium/high/critical；默认 repair_target: video_shot，证据未定用 unresolved 并保持 uncertain。time_range 只是定位/回看范围。建议针对具体错误，不自动修图或重生成。

## 漏镜统计、失效与停止

审查后规划只计“确认缺失且无法省去的必要镜头”为 bad_num，每份输入视频各计一次。默认至少 2 镜且占该视频应覆盖镜头数至少 20% 才给重新生成建议。2/10 触发；2/11 与 1/3 不触发。已定位的画面错误、可推导漏镜及待检查不计数，不变更脚本覆盖范围规避阈值。

输出仅两表，阈值触发时在两表下加一句建议，不生成视频结论表。所有最终批准 ai_fill 的小分镜图栏只写“可推导生成”，不输出原图、占位图片或图片链接；图片处理栏写“建议省图，未验证”。可推导漏镜检验结果仍为“视频漏镜”，已有通过镜头仍为“检验通过”。候选被最终锚点约束拒绝时继续展示图片。省图不代表原视频完整，也不删脚本位置。

重选单镜帧：重看该镜及左右衔接，复用其他有效观察，以完整组结构重登记新指纹。替换整份视频：整份重新抽帧、匹配和审查，左右来源组只补查接壤边界并复用内部观察。脚本/资产/视频/依据图片/映射变更均使相关旧结论失效。previous_review 只供复用观察，不直接复制过期 PASS。

证据不足先补查；仍无法确认则该项交付待检查，不计入自动返修错误。组级审查同时填写 [repair_assessments](auto-repair.md#首轮整理与审查)，不增加逐镜往返；关键问题须有原文和同镜证据。先完成原视频两表快照，再计算独立返修阈值；自动返修最多每份来源一次，新视频完整独立审查。公开模型旧生成模式仍按 [生成恢复规则](generation.md) 处理：确认 FAIL 才登记 repair，再改提示词或拆组；三轮上限、预算、提交数、max_retries=1、.lock、submission_unknown 查询原任务逻辑不变，uncertain 不触发付费重试。

## 三镜验收与调用数

S01 女孩持钥匙；S02 同场景观察无关键变化；S03 钥匙交接完成。若脚本未给时长，一次整理时可分别建议 3、2、3 秒并记 inference 来源；总时长 8 秒（含建议值），不是实测时长。

| LLM 判断 | 一次输入 | 一次输出 | 后续工具 |
|---|---|---|---|
| 1 完整提取 | 完整脚本、资产、输入视频信息 | 三镜 facts/state_changes/requirements/块级来源、event、时长来源、narrative_plan | 状态计算、校验、登记视频、抽帧 |
| 2 全组匹配 | 三镜要求、全部候选及实际时间 | 三镜映射、哈希观察、选帧理由 | map、顺序 select、一次组 context |
| 3 全组校对与推导 | context、已存观察、连续帧/视频 | 三镜独立结论、三项总检查、证据、取舍、边界及 grouping_checked | 一次组 review、规则规划、两表渲染 |

上述单事件串行路径由“3 提取＋1 匹配＋3 审查”的 7 次 LLM 判断合并为 3 次；旧逐镜 context/review 共 6 次工具往返变为一次组 context＋一次组 review 共 2 次。工具抽帧、登记和渲染另计。此为调用设计，不是实测耗时；补查如实增加判断，质量优先。

正常 S01/S03 保留，S02 可推导省图且标建议/未验证。模拟 S02 漏镜时先补查，确认 absent 后若前后通过且满足推导/硬规则，可给省图建议但仍保留漏镜结论；若必要或不确定则分别计数或待检查。测试覆盖剧情等效通过、关键错误、重新抽帧纠正、混合结果、来源失效、阈值、无时长可审查但聚合待规划、建议时长及剧情三步合并；合成颜色视频只验证实际抽帧/PTS，模拟语义判断不当作真实视觉验收。

## 借鉴来源与边界

审查设计参考 [Reviewer-skill，固定提交 4c9dc937](https://github.com/onodera520/Reviewer-skill/tree/4c9dc937de3a51379928df91b2795d431c79861f)，具体采用：

| 原文件 | 本技能采用的思想 |
|---|---|
| [story-preview.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/story-preview.md) | 创作意图、关键结果与可容忍变化 |
| [continuity-review.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/continuity-review.md) | 同实体、可见性、正确基线与授权变化；状态账本 |
| [animatic-review.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/animatic-review.md) | 参考图角色、逐镜动态与序列检查、疑点补证 |
| [verdict-policy.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/verdict-policy.md) | 严重程度与修复对象分开；不确定不等于重做 |
| [generator-compatibility.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/generator-compatibility.md) | 生成分组不等于叙事场景 |
| [prepare_animatic.py](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/scripts/prepare_animatic.py) | 实际 PTS、镜头内部与切点邻域抽帧 |
| [story-preview-rubric.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/evals/story-preview-rubric.md) | 用正反例检查审查行为而非仅测试格式 |

代码独立实现，不复制其整个技能。采用其状态基线、可见证据与局部修复思想，用于视频内容与连续性审查、候选匹配及有实证依据的省图建议；以源脚本而非生成提示词作为最高叙事依据。模拟案例只验证流程与记录，不宣称真实视频理解已被证明。
