# 图片审查的返修证据

在同一次看图中填写，每个确认 FAIL 恰有一条 repair_assessment；PASS／uncertain 不填，无 FAIL 用空数组。不增加逐镜判断。prepare_storyboards.py complete 冻结前集中检查，不自动填判断、引文或修正。

```json
{"shot_id":"S03","critical":true,"critical_kind":"wrong_transfer_result","affects_story":true,"script_quote":"男孩接住钥匙，女孩松手","issue_ids":["I03"],"impact":"结束阶段仍由女孩持钥匙，交接结果相反","correction":"在该参考阶段呈现男孩拿稳钥匙、女孩松手，保留其他脚本内容","preserves_script":true}
```

critical 与 affects_story 显式布尔。script_quote 是同镜 script 的逐字非空片段；issue_ids 唯一且均属本镜。impact 写具体影响；correction 只恢复原意，preserves_script=true。同镜 issues 绑定有效原图与 SHA256，repair_target=storyboard_image，不填写时间。不能借邻镜证据或凭提示词证明画面问题。

关键问题还需 affects_story=true，critical_kind 为 missing_key_node／wrong_actor／broken_causality／wrong_transfer_result／explicit_key_requirement，并说明关键作用。普通外观、表演或构图差异无剧情影响且无明确严格要求，不制造 FAIL。阶段不清或关键内容无法辨认先放大／澄清，仍不足则 uncertain，不猜修复。

严重画面损坏仅在妨碍脚本必需内容辨认的确认 FAIL、affects_story=true 时填写：

```json
{"severe_visual_damage":{"damage_description":"交接手部与钥匙破碎为杂色块","obscured_content":"无法辨认必要的持物关系","image_sha256":"同镜原图SHA256"}}
```

image_sha256 须在本镜 evidence_sha256 且有同镜 evidence，issue_ids 至少关联一个同镜问题。无 time_range；轻微瑕疵不使用此分支。工具验证结构及绑定，严重程度、关键性和修复保真仍来自实际判断。

阈值按整批全部脚本镜头：关键剧情错误一镜，或上述严重损坏一镜，或普通明确 FAIL 至少两镜且占比至少 20%。普通错误无额外 affects_story=true 门槛。同镜多问题去重；2/10 触发、2/11 不触发。uncertain、输入问题与合理差异不计分子；省图、待核查或分组不改分母。未触发的 FAIL 仍原样留在报告。

correction 优先已有动作、表情、位置、道具与结果，不引入台词／OS／VO 或新动作。证据引文保留内部；必要纯视觉转换在阈值触发后与资产风格、原提示词筛选同批完成，见 [提示词规则](auto-repair.md)。要求或来源变化后重新核验，旧交付另存不覆盖。
