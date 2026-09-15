# 内部数据与用户交付

从 assets/example-project.json 建立内部项目文件，与交付目录分开。路径相对于项目 JSON，也可用绝对路径。模型参数独立保存，不写进脚本。

- schema_version: 1、title、source_script：原始依据。
- assets: id, kind, description, path；kind 为 character/scene/prop。默认资产输入模式下，组中用到的每份资产都有本地图片。资产图不能自动当成最终分镜图。
- shots: id, script, scene_id, continuity_id, duration, asset_ids, required_result；编号唯一，数组为原顺序，duration 是计划秒数。
- 每镜 requirements：见 [镜头要求](shot-requirements.md)，内部定稿版本、关键帧与持久状态继承；旧项目可逐镜补齐，保留历史成果。
- reference: 兼容的生成输入设置 mode: anchor|ai_fill, path, role, reason。默认资产模式不用它判断最终是否配图，board 才是最终图状态。
- groups: id, shot_ids, reason, version，可有 prompt_notes。必须连续覆盖全部原镜头且不重复，只用于内部生成。
- config: delivery_mode: storyboard_images、video_input_mode: assets、aspect_ratio、max_repair_rounds（默认 3）、max_submissions（样例 0）、可选 budget_cny。图片和视频提交共用额度。
- board_mappings：代理核对后的候选帧、时间与匹配状态。
- 每镜 board.selected：所选图片路径、哈希、来源和理由；history 保存替换前版本；omission 保存无需单独配图的依据。
- board_reviews：绑定图片、脚本、资产和相邻图片的审查；repairs 和 repair_round 记录有限返修。
- tasks：原任务 ID、请求与下载结果，支持恢复。选择或修改最终图片不会使来源视频失效。

输入记录见 [审查与修复](review.md)。图像成功下载后经 select 进入待审状态，不能只修改 reference.path 代替最终选择。改图片使自身及相邻审查失效，也使依赖该图的省图决定失效；改剧情或资产使相应图片验收失效。历史结果保留，不清空记录绕过额度。

## 交付

previs.py render 和 storyboard.py render 均只输出分镜说明.md 与 images/ 中的分镜图片，按镜头顺序内嵌显示；使用本地图片绝对路径，便于在 Codex 中直接查看。转移交付文件夹后需重新渲染或更新图片链接。开头简述镜头数、计划总时长与完成情况；逐镜列出编号、计划时长、脚本、图片和必要状态。时间是脚本计划值，不是取图视频的实际时间。

默认每镜配图。没找到是“待补图”，有叙事依据允许省略才是“无需单独配图”。没有选择的资产图/输入图不冒充完成分镜图。允许交付待检查的最佳结果，但说明问题，不假称全部完成。

使用独立、干净的交付目录。工具遇到旧视频或内部记录会要求换目录，避免混入附件；历史交付留在内部。用户文档不链接中间视频、时间戳索引、模型参数、规则、费用假设、JSON 或详细审查记录。
