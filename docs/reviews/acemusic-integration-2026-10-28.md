# ACEMusic 原生音乐接口接入记录

日期：2026-10-28。

## 本地配置

- MUSIC_PROVIDER=acemusic。
- REAL_MUSIC_BASE_URL=https://api.acemusic.ai。
- ACEMUSIC_MODEL=acemusic/acestep-v1.5-turbo。
- 用户提供的密钥仅保存至被 Git 忽略的本地 .env；未写入本文、示例、测试或发行物料。
- 原有 GPT 配置保留，用于规划、作词与编曲方案。

## 接口证据

对 `/v1/models` 的实际鉴权查询返回 HTTP 200，包含所选模型，output_modalities 包含 audio；pricing.prompt、pricing.completion、pricing.request 均为字符串 `0`。这些字段不能证明无限额度，实际限额以服务账号为准。

公开 `/health` 可访问；该服务的协议为音乐 Chat Completions，而非项目原先的 POST /generate、GET /tasks 通用网关。

请求和响应实现依据：[ACE-Step 官方 OpenRouter API 文档](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/Openrouter_API_DOC.md)。

## 实现

- 增加集中 Pydantic 请求/响应契约和专用 acemusic 适配器。
- POST /v1/chat/completions：编曲说明放入 messages；已批准歌词以带结构标签的纯歌词放入 lyrics，关闭 sample_mode、use_format 和服务端 CoT 重写选项。
- 传递模型、时长、BPM、调性、歌词语言，优先请求 WAV；解析 `choices[0].message.audio[].audio_url.url` 中的音频 Base64 或 HTTP 下载地址。
- 安装 imageio-ffmpeg，未配置外部 FFmpeg 时使用随依赖提供的执行文件。加入实际 MP3→标准 WAV 的本地测试。
- 保留原有歌词批准门禁、音频声学检查、时长检查、版本隔离、试听批准和发行包门禁。
- 同步接口调用前持久化请求标记；完整响应缓存至该版本的临时产物旁。转码/提交中断后复用缓存，避免重复生成。
- 文档未承诺同步接口结果查询或服务端幂等。网络中断且远端结果不确定时阻止自动重发，保留任务供核查；明确 429 拒绝可稍后恢复。
- 新增 scripts/check_music_connection.py：只读验证鉴权及模型，不创建歌曲。

## 验证范围

- 使用本地密钥实际执行连接检查：status=connected，song_generated=false。
- 本次没有提交真实歌曲生成，没有自动批准任何歌词、音频或新增发行包。
- 自动化测试覆盖原生请求、歌词绑定、音频 Base64/URL、模型与错误处理、响应缓存恢复、未知结果不重发、MP3 转码以及完整项目既有回归。
- 最终完整测试：97 项通过，0 失败、0 错误、0 跳过；pip check 通过。完整结果见 [JUnit XML](acemusic-verification-2026-10-28.xml)。

修改 .env 后，正在运行的工作台需要重启才能加载新配置。下一首作品应由用户显式审核歌词后，再推进真实音频生成。
