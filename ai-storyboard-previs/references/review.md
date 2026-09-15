# 匹配、分镜图审查与有限修复

验收对象是最终分镜图片，视频是取图素材。音轨、实际视频总长和不影响取图的转场不作为交付门槛。检查所有图片对脚本的覆盖、人物和道具连续性，以及图序能否说明主要事件；静帧不能证明完整动作或硬切正确。

## 匹配

media.py extract 使用实际帧 PTS 保存图片哈希、时间、候选切点与 evidence.json。它不判断镜头语义。代理先看候选图，对照脚本与前后镜头再填匹配记录。每镜保留若干候选并按实际时间升序排列，各镜候选也按脚本顺序；乱序的视频可以标 uncertain，无法匹配的镜头单独补图，不硬套时间。

```json
{
  "group_id": "G01", "video_sha256": "ACTUAL-VIDEO-HASH",
  "evidence_file": "evidence/G01/evidence.json",
  "shots": [
    {"shot_id":"S01","status":"matched","observation":"实际可见女孩持钥匙，男孩在门旁",
     "candidates":[{"path":"evidence/G01/frames/frame_0001.png","time":0.1}]},
    {"shot_id":"S02","status":"uncertain","observation":"当前稀疏帧未见手部特写，需要回看","candidates":[]},
    {"shot_id":"S03","status":"absent","observation":"回看全组并加密抽帧后未见男孩接住钥匙的结果",
     "full_rescan":true,"candidates":[]}
  ]
}
```

记录必须覆盖该组全部镜头，路径/时间用实际提取结果。matched 是定位成功，不是图片通过；absent 必须确实回看、加密检查，uncertain 不触发付费重试。必要时重复 extract --dense-step 0.1 并重新匹配；保存旧证据，不能把计划切点当实际位置。

## 选图与修图

```json
{"shot_id":"S01","path":"evidence/G01/frames/frame_0001.png","source":{"kind":"frame","time":0.1},"reason":"此帧清楚建立人物与持物位置"}
```

source.kind 可为 frame/generated/edited/provided/illustration。frame 必须属于当前匹配候选；generated/edited 需 source.request_id，绑定同镜的成功图片任务及真实下载文件。provided 为用户给定的分镜图；illustration 只用于明确标注的构图示意，不能通过正式验收。所有来源选择后都要检查。

单镜主图默认一张，能说明构图和关键状态；若必须呈现多个状态，可在内部保留多张并由代理补充在同一镜头的 Markdown 下，不拆改原镜头编号。渲染器自动输出主图，额外图片也只复制图片附件，不附视频。

## 图片审查

先运行 context PROJECT.json S01 取得当前图片哈希与上下文指纹，实际读图后填写：

context 还会给出 [已解析镜头要求](shot-requirements.md)。expected 以目标关键帧的阶段与状态为依据；不得拿交接后的持物状态否定交接前的正确图片。核对 must_have/must_not_have，遮挡导致看不清则 uncertain。设计状态变化后，沿状态继承关系复查后续受影响镜头；已选图片仍保留，不因旧审查过期直接登记付费返修。

```json
{
  "shot_id":"S01", "image_sha256":"ACTUAL-IMAGE-HASH", "fingerprint":"CURRENT-CONTEXT-FINGERPRINT",
  "checks":{"identity":"PASS","scene":"PASS","props":"PASS","composition":"PASS",
            "key_state":"PASS","continuity":"uncertain","cleanliness":"PASS"},
  "expected":"按脚本，女孩持红挂件钥匙，男孩尚未接到",
  "observation":"实际图中女孩右侧可见钥匙，男孩手中没有钥匙",
  "problems":[], "uncertainties":["下一镜未选图，暂无法检查衔接"]
}
```

检查分别为身份外观、场景空间、道具数量状态、构图景别、关键动作状态、前后连续性、清晰度与字幕/水印等瑕疵。画面不显示不等于道具消失；确认同实体、可见属性、连续事件、正确基线及是否有脚本授权变化后再报错。不得把未来持物状态提前用于前镜。

全部 checks PASS、无问题或疑点且相邻图已选择/有省图依据才能 PASS。修改本图、邻图、脚本或资产后旧审查失效；留存历史以便恢复最佳版本。脚本只能验证记录和文件关系，不能证明代理实际看过图片。最后按原序通看所有图，确认关键剧情结果可读。

## 省图与修复

默认最终逐镜配图。允许某镜不单独配图时使用：

```json
{"shot_id":"S02","reason":"前后两图已说明此处简单过渡，保留脚本即可","context_evidence":"具体写出前后图已表达的内容","preserves_story":true}
```

工具禁止省掉关键结果、叙事转折或关键状态变化。此判断独立于旧 ai_fill；视频漏镜不自动批准省图。无需配图的镜头仍保留编号、脚本和计划时长。

修复批次：

```json
{"operations":[{"shot_id":"S01","action":"edit_image","reason":"仅修正钥匙挂件颜色，人物与构图保持"}]}
```

action 可为 rematch/edit_image/generate_image/regenerate_group。rematch 先补证据，不计付费轮次；其他操作必须来自当前图 FAIL 或已确认缺失的必要图。regenerate_group 额外写 why_not_image_repair，说明整体失配或逐图补齐代价为何不合适。一个关键错误就可能需要修复，不根据 bad_num 数量机械重做。

先登记 repair，再按生成说明提交相应图片/视频请求。每批付费返修计一轮，默认最多三轮；任务额度与预算还会在提交端检查。图片修复不提高来源视频版本、不要求重做视频；重生成组才提高该组版本。必要拆组在 repair 后用 previs.py split PROJECT.json G01 S03，重建模型请求。

保留通过图，重生成的组也只替换其中未通过的图。新图优于旧图才保留为最终选择；若更差，用 `storyboard.py restore PROJECT.json RESTORE.json` 恢复历史版本，输入如 `{"shot_id":"S01","history_index":0}`。恢复会核对原文件哈希并保留原始来源，不虚构新匹配；复查恢复图片与当前相邻图。到上限保留最佳可用图并标注问题。来源视频可能仍漏镜，但最终图片已单独补齐时可以交付，不再修来源视频。

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

代码独立实现，不复制其整个技能。采用其状态基线、可见证据与局部修复思想，改为最终分镜图验收、视频候选匹配及图片补齐；以源脚本而非生成提示词作为最高叙事依据。模拟案例只验证流程与记录，不宣称真实视频理解已被证明。
