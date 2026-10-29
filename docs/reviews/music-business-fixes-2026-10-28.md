# 多 Agent 音乐业务修复与验证记录

日期：2026-10-28。对应 [原审阅报告](music-business-review-2026-10-28.md)。

## 修复范围

本次修复覆盖原审阅报告中的 10 项 P1 和 5 项 P2。已有作品、审核记录和旧版平铺发行包未覆盖；新增完整验收示例位于 release-package/acceptance_demo/v1/。

| 原问题 | 实际改动与验证 |
| --- | --- |
| P1-01 未审核歌词可通过驳回入口作曲 | 审核动作先校验当前阶段；AudioAgent 必须核对当前歌词项目、版本和批准哈希，默认布尔值不能授权。回归覆盖 CLI/HTTP 和图节点。 |
| P1-02 第三次版本碰撞覆盖历史 | 统一扫描最大版本、独占发布、项目跨进程锁；实际版本写入 checkpoint。回归检查第三次歌词/音频生成与历史字节保持。 |
| P1-03 ZIP 绕过门禁、跨项目取 manifest | 新包按项目/版本隔离；下载只压缩 checkpoint 指向的受检目录，不再重建歌词或从共享根目录兜底取文件；下载前逐项校验。 |
| P1-04 审核未绑定内容 | 审核账本绑定 project_id、version、artifact_sha256；音频同时绑定编曲文件哈希，编曲绑定已批准歌词。随包保存源 JSON，支持独立审核验证。封面实际解码验证。 |
| P1-05 崩溃无法恢复 | checkpoint 原子保存初始 Brief 快照、待执行操作、目标版本、反馈、远端 task_id 和产物提交哈希；SQLite 保存图位置与 pending writes。覆盖计划落盘、音轨发布、编曲提交、包目录改名和元数据镜像等崩溃窗口。 |
| P1-06 缺料和 ready 重验无法降级 | 缺失/损坏材料统一生成 needs_info 清单；允许 ready 重验降级，checkpoint 与新包状态一致；旧包版本保留。 |
| P1-07 主入口固定 Mock、真实路由失效 | 主入口使用配置模型工厂，生产默认 unconfigured；新旧音乐入口统一到同一严格网关。缺配置、限流、超时或音频错误不会变成 Mock 成功。加入任务 ID 恢复、幂等键、转码与协议测试。 |
| P1-08 完整音频接口 500/覆盖已审文件 | 复用正式生成或驳回流程，创建新版本并回到 audio_ready；不再访问不存在的 music_model 属性，不原地写已审文件。 |
| P1-09 WAV 检查放过截断/零帧/削顶 | 全量检查实际帧长、正时长、规格、RIFF 数据长度；全轨统计静音/削顶并执行阈值；检查需求时长。 |
| P1-10 反馈只记账 | 作词输入带原稿和审核意见；韵律工具结果触发有上限的反思重写；音频输入带修改要求和模型编曲方案。Mock 也记录修改来源并改变演示结果。 |
| P2-01 图拓扑和持久化不完整 | 规划、作词、音频、打包节点均有可达路由；两个原生 interrupt 人工关卡；SQLite Checkpointer 跨实例恢复；计划依赖和阶段顺序经过程序验证。 |
| P2-02 弱契约分散 | 业务契约集中 src/models，包括 graph state、checkpoint、操作、审核、编曲段落、模型参数、质检、公开请求/响应和报告。 |
| P2-03 文本失败被模板掩盖 | 生产规划/作词失败阻断，结构化结果重试并验证；保留 .env 配置模型名称与地址；传递时长、平台、受众、约束；演示模式明确标注，不冒充真实模型。 |
| P2-04 幂等和元数据缺漏 | 同项目变更 Brief 报冲突；新增艺人署名、人工版权确认与 CLI/Web 补齐操作；包版本自增；运行报告使用真实持久化事件时间；新增 ready 验收示例。 |
| P2-05 安装和测试隔离 | 补齐 Web、multipart、Pillow、拼音与 HTTP 测试依赖；建立独立 .venv 并成功按 pyproject 安装；锁定依赖清单；所有测试自动使用临时目录和显式 Mock。 |
   
## 验证结果

- 干净环境：Python 3.10.11，Pydantic 2.14.1，LangGraph 1.2.18，FastAPI 0.162.0，pytest 9.2.0。
- 最终完整测试：83 项通过，0 失败、0 错误、0 跳过。完整自动化结果见 [JUnit XML](verification-2026-10-28.xml)，包括原有正常路径和新增异常/恢复/协议回归。
- pip check 通过，Python compileall 通过，前端 app.js 语法检查通过。
- 实际使用本地 .env 的 gpt-6.1-sol 完成最小 JSON 连通测试；进一步生成 6 阶段计划和 4 段歌词，结果通过业务模型校验，停在 lyrics_ready，没有批准或调用音频 Agent。
- acceptance_demo 使用显式 Mock，经 CLI 审核命令形成 ready 包；审核者标记为 Automated Acceptance Demo，manifest.is_mock=true。这验证本地工作流和物料完整性，不代表真实歌曲或人工审美认可。
- 真实音乐网关用可控 HTTP session 验证提交、下载、限流、超时、任务恢复、幂等键和生产失败阻断；未对实际音乐供应商生成歌曲。

## 必须区分的配置与验证边界

现有 .env 仅提供 CODEX_API_KEY、CODEX_BASE_URL 和 CODEX_MODEL。其 GPT 文本调用已验证可用，可以承担主 Agent 规划、作词和编曲方案；这些字段没有提供音乐生成服务的地址或凭据。

因此，真实歌曲产出的最后验收仍依赖一个已开通、符合 README 协议的音乐网关及对应授权。当前代码在此条件缺失时明确阻断并保留可恢复任务，不会把本地合成音轨当成真实歌曲交付。未声明原生兼容所有 Suno/MiniMax 服务商或取得商业音质保证。

采用 OpenAI Docs 技能核对结构化 JSON 请求；已读取 [官方结构化输出文档](https://developers.openai.com/api/docs/guides/structured-outputs)。第三方服务的实际兼容性以本次接口测试和后续真实供应商验收为准。

## 运行与复核

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/check_text_connection.py
.\.venv\Scripts\python.exe scripts/create_demo_package.py
.\start_studio.ps1
```

新的包目录包含 lyrics.json 和 composition-source.json，作为审核时源文件的副本；composition.json 将音频路径规范化为包内 audio.wav。所有随包材料都在 manifest 中有文件哈希。

旧审核记录不具备绑定哈希时需要制作人重新显式审核，不会自动补签。没有执行任何外部发行或发布操作。
