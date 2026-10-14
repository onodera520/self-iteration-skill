# 字段速查

正常任务先用本表及精简输入模板填写，不为了找字段遍历脚本。保留 prepare 生成的工作单结构和指纹；不要自己重建 WORKLIST。

| 位置 | 必填与易错点 |
| --- | --- |
| INPUT facts | entity 精确匹配 assets[].id；attribute、value、status、critical、phase、source 齐全。status=known/unknown；phase=static/before/after；source={kind:script/asset/inference, ref:具体出处}。没有对应资产的要求放 requirements，不造实体 |
| INPUT requirements | status=ready；keyframe={phase:entry/action/exit, description:当前参考阶段}；provenance=[{field:所支持字段, status:observed/user_provided/script/assumed/unknown, source:具体出处}]。provenance.status 与 facts.source.kind 不是同一组枚举；过程图不强制终态，参见审查规则 |
| WORKLIST 每镜 | verdict=PASS/FAIL/uncertain；reference_phase=entry/action/exit/unknown；observation.visible_facts 为非空字符串数组，实际观察须支撑检查与阶段 |
| 每镜 checks | 七个键 identity、scene、props、composition、key_state、continuity、cleanliness，值均为 PASS/FAIL/uncertain。关键状态键是 key_state，不是 action；全批 checks 另用 shot、continuity、story |
| FAIL / uncertain | 两者必须写非空 reason，不能只在 issues 写问题；uncertain 另写具体 followup。PASS 的 reason 与空 followup 由程序补 |
| reference | 保留 anchor/false/空 basis_shot_ids；省图 ai_fill/true/同组双侧依据及非空 reason；FAIL 或 uncertain 用 pending/null，不省图 |
| issues 每项 | id、shot_ids、severity=low/medium/high/critical、problem、expected、actual、fix；asset_ids、asset_comparison_ids 即使无关联也填 []。不要遗漏 problem。v2 自动补同镜 evidence 和 repair_target |
| FAIL 的返修依据 | 每镜一条 repair_assessments，字段和短例见 [返修依据](repair-assessments.md)；原文引文、影响与修正由代理判断，不能只填 issue_ids |
| asset_comparisons | 每项 id、shot_id、asset_id、aspect=wardrobe/appearance/prop/scene、decision；PASS 填实际 stable_matches；FAIL 填 stable_conflicts=[{feature,expected,observed,environment_exclusion}] 并关联 issue；uncertain 填必要但不可见的 unobservable_features 与 followup。人物对照另填 story_requirement，非 PASS 还填 story_impact。v2 补哈希、同镜证据及未用的辅助空数组，不能代填实际判断 |

一次填写完再 complete，不增加独立的重复预检轮次。使用原图路径；确需复制原图时保留原扩展名与字节，不把 WebP 复制后统一命名成 PNG。若输入本身后缀异常，先定位真实解码问题，保留原文件，不把改名当作格式转换，也不把输入问题计为剧情 FAIL。
