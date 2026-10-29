# 多 Agent 作词作曲业务审阅（2026-10-28）

> 本文记录修复前问题；后续处理及验证结果见 [修复记录](music-business-fixes-2026-10-28.md)。

审阅结论：项目具备三角色分工和正常路径演示能力，但尚未满足完整业务验收。原始需求允许 Mock 音乐模型；因此“默认 Mock”本身不是原始需求缺陷，但当前实现仍违反审核、历史版本保护、完备性降级和断点恢复等硬性要求。若按仓库中标为 DRAFT 的 v2 重构 PRD 衡量，真实音乐生成、自纠反馈和持久化图编排也尚未完成。

本次只审阅并记录问题，没有修改业务代码、已有歌曲或原有发行包。未调用真实付费模型；真实服务的音质、接口兼容性与在线成功率不在本次已验证范围内。

## 验证依据与范围

- 依据：AGENTS.md、REQUIREMENTS.md、v2 重构 PRD/蓝图，以及 src/、tests/、README、pyproject.toml 和当前示例发行包。
- 将 src、tests、fixtures 和测试依赖的 song_001 数据复制到独立临时工作区，强制使用 Mock，执行现有完整测试套件：**43 项通过**。
- 在该临时副本补充执行 20 项定向检查，覆盖审核绕过、版本碰撞、崩溃窗口、ZIP 校验、审核与版本绑定、真实模型路由、声学边界和驳回反馈。
- 测试运行时：Python 3.9.7、pytest 6.2.4、Pydantic 2.12.3、LangGraph 0.6.11、FastAPI 0.116.1。pytest 版本低于项目 dev 依赖声明的最低版本，因此这次结果不能替代按声明依赖创建干净环境的安装验收。
- 默认命令 python 指向另一套 Python 3.10，其中没有 LangGraph；本次使用已安装 LangGraph 的 Anaconda Python，通过进程内 PATH 配置加载其 SSL 依赖，并关闭无关 pytest 插件自动加载。
- 现有部分测试使用默认 release-package/ 并依赖已有 song_001，直接在原目录运行会写入示例发行包；本次通过完整临时副本隔离了这些副作用。

## 业务能力对照

| 业务能力 | 当前情况 | 判定 |
| --- | --- | --- |
| Brief 读取与结构校验 | 有 Pydantic Brief 和三类异常提示；同 ID 新 Brief 未与原始哈希比对 | 部分满足 |
| 主 Agent 规划与分派 | 能生成并保存 TaskPlan；执行路径固定，计划不驱动实际依赖调度 | v1 正常路径具备，v2 不完整 |
| 作词子 Agent | 有真实 LLM 请求、结构化歌词、分段及词律工具；失败会回退为固定模板 | 部分满足 |
| 作词自检与反思重写 | 词律结果只追加到摘要，没有把不合格结论送回模型重写 | v2 未完成 |
| 歌词人工审核 | 正常批准/驳回存在；其他入口可绕过；审核未绑定内容哈希 | 不满足完整门禁 |
| 作曲方案与音频 | 正常 Mock 路径生成合法 WAV 和方案；主入口固定注入 Mock | v1 演示具备，v2 未完成 |
| 音频驳回修改 | 能新增版本，但反馈没有传入音频生成，Mock 复现为相同文件哈希 | 修改闭环不完整 |
| 音频完整性与质量检查 | 能挡住空文件和明显坏头；不能挡住截断数据、零帧 WAV、严重削顶 | 部分满足 |
| 歌词/音频版本保护 | 只处理一次碰撞；第三次指定 v1 会覆盖 v2；恢复后版本可能错位 | 不满足 R4 |
| 中断与恢复 | checkpoint 单文件使用原子替换；初始化、产物提交和驳回反馈存在未保护窗口 | 不满足 R7 全程恢复 |
| 标准本地发行包 | 正常导出有目录、manifest 和部分校验；ZIP 是另一条不经过门禁的拼装路径 | 不满足完整交付 |
| 缺料和哈希异常降级 | 部分音频/缺封面场景已实现；缺歌词会抛异常，已 ready 项目无法降级 | 不满足 R5 |
| 外部发行边界 | 本次代码检查未发现真实发行平台调用 | 符合 R6 的当前范围 |
| Web 工作台 | 列表、试听、审核、导出存在；完整音频接口失效，下载与正式导出结果不同 | 部分满足 |

## 需要优先修复的问题

### P1-01：音频驳回入口可在歌词未审核时调用作曲

位置：[graph.py:286](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:286)、[audio_agent.py:45](C:/Users/Administrator/Desktop/沿长科技/src/agents/audio_agent.py:45)。

音频批准分支检查了状态，音频驳回分支没有检查当前阶段，直接传入 is_lyrics_approved=True 并生成音频。底层 AudioAgent 的批准参数还默认是 True。

复现：start 得到 lyrics_ready，接着 approve_stage(project_id, "audio", approved=False)，结果进入 audio_ready，生成 v2 音频，而审核账本中没有歌词批准记录。该方法可通过 CLI 和 Web 调用。

影响：违反 R2 和“歌词批准前禁止调用作曲 Agent”的业务门禁。

修复方向：审核入口先校验动作与当前状态；音频生成应核对当前歌词版本的有效批准记录，不能仅信任调用方布尔值。批准、驳回、重做都应经过统一状态转换逻辑。

### P1-02：版本保护只自增一次，可能覆盖已审核的 v2

位置：[lyrics_agent.py:32](C:/Users/Administrator/Desktop/沿长科技/src/agents/lyrics_agent.py:32)、[audio_agent.py:60](C:/Users/Administrator/Desktop/沿长科技/src/agents/audio_agent.py:60)。

目标版本存在时只增加一次，没有继续检查新版本是否也已经存在。歌词和音频实现都有这一逻辑。

复现：生成 v1，驳回产生 v2，再批准 v2；随后直接指定 v1 重新生成，实际写入已有 v2。复现中 v2 文件哈希发生变化，账本仍表示 v2 已批准。

此外，node_step 返回请求版本而非产物真实版本；graph.resume 也忽略 generate 返回的真实版本。遇到崩溃遗留文件后，两者会脱节。

影响：违反 R4，审核记录可能指向已被覆盖的内容。

修复方向：统一版本分配，遍历/计算未占用版本，使用独占创建和项目锁；checkpoint、产物 JSON 与文件名统一使用实际分配版本。

### P1-03：ZIP 下载绕过审核，并可能混入其他项目的 manifest

位置：[app.py:325](C:/Users/Administrator/Desktop/沿长科技/src/web/app.py:325)、[app.py:376](C:/Users/Administrator/Desktop/沿长科技/src/web/app.py:376)、[packager.py:34](C:/Users/Administrator/Desktop/沿长科技/src/services/packager.py:34)。

download_package 只检查项目存在，直接从工作目录拼 ZIP；它没有调用正式导出与完备性校验。manifest 和备用封面直接读取共享 release-package/，也不核对所属项目。

复现一：仅有 lyrics_ready 的项目也返回 HTTP 200 的“发行物料包”，其中 manifest.project_id 实际属于另一个项目。

复现二：已正常导出 ready 的项目再下载 ZIP，ZIP 中 lyrics.md 的 SHA-256 与随包 manifest 声明不一致，因为下载接口重新排版了歌词。

影响：违反审核前禁止最终打包和发行包哈希一致性的约定。共享输出目录还会导致项目互相覆盖，自定义导出目录也无法被下载接口正确读取。

修复方向：发行包按项目、包版本隔离；ZIP 仅压缩已经通过相同门禁验证的包目录，压缩前复核全部清单文件，禁止重新生成或从其他目录兜底取物料。

### P1-04：审核没有绑定项目、版本和内容，修改后仍能 ready

位置：[approval.py:21](C:/Users/Administrator/Desktop/沿长科技/src/models/approval.py:21)、[packager.py:144](C:/Users/Administrator/Desktop/沿长科技/src/services/packager.py:144)。

is_stage_approved 只看该阶段最后一条记录的 approved，不检查 target_version、project_id 或产物哈希。signature_hash 没有实际写入和验证。歌词导出会为当前内容重算哈希，因此无法发现审核后的修改。

复现：

- 歌词批准后修改歌词 JSON，最终包仍是 ready，integrity_issues 为空。
- 将歌词、音频批准记录的 target_version 都改成 v999，实际导出 v1，仍是 ready。
- 向打包器传入不同项目的歌词、作曲方案和审核账本，仍可 ready。
- 封面只判断路径存在；0 字节 cover.png 也可以 ready。

影响：R1 契约一致性和 R5 物料审核、完整性保证不足。

修复方向：审核时记录 project_id、stage、version、artifact_sha256；打包核对所有产物关联关系及已审哈希，并解析、验证封面内容。

### P1-05：初始化及产物提交之间的崩溃无法无损恢复

位置：[graph.py:182](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:182)、[graph.py:340](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:340)、[checkpoint.py:44](C:/Users/Administrator/Desktop/沿长科技/src/core/checkpoint.py:44)。

start 在规划和歌词全部成功后才首次保存 checkpoint；单个 checkpoint 的原子替换不能保证 brief、plan、歌词、音频、审核账本和状态的一致提交。驳回意见先写 approvals.json，生成成功后才更新 checkpoint，也没有持久化待重试操作。

复现一：plan 已落盘，歌词生成抛异常后，checkpoint 不存在；resume 抛 ProjectNotFoundError。

复现二：音频 v1 已写完，在 checkpoint 更新前抛异常；重启 resume 会再生成 v2，但 checkpoint.audio_version 仍是 v1。

影响：违反 R7；可能重复付费、产生孤立版本，或显示/审核旧文件。

修复方向：开始就持久化 new；阶段开始时持久化操作 ID、目标版本、反馈、远端 task_id，结束时原子提交产物引用；恢复时识别已成功任务和已落盘产物。每项目需要串行化或并发锁。

### P1-06：缺料和重新校验失败不能稳定降级到 package_needs_info

位置：[master_agent.py:101](C:/Users/Administrator/Desktop/沿长科技/src/agents/master_agent.py:101)、[master_agent.py:121](C:/Users/Administrator/Desktop/沿长科技/src/agents/master_agent.py:121)、[state_machine.py:29](C:/Users/Administrator/Desktop/沿长科技/src/core/state_machine.py:29)。

歌词、作曲 JSON 在打包前由 loader 强制读取；文件缺失直接抛异常。已 package_ready 项目的合法转换集合只允许 package_ready，无法在重验失败后降级。

复现一：删除已审核项目的歌词文件再导出，抛 FileNotFoundError，状态仍是 audio_approved。

复现二：正常导出 ready 后篡改音频，再次导出时新 manifest 为 needs_info，但状态转换抛 WorkflowGateViolationError，checkpoint 继续保留 package_ready。

影响：违反 R5；磁盘 manifest 和项目状态相互矛盾。

修复方向：缺失和损坏物料统一转为结构化校验结果；允许重验失败后受控降级，包与 checkpoint 一致提交。

### P1-07：生产主入口固定使用 Mock，真实音乐生成未形成闭环

位置：[master_agent.py:43](C:/Users/Administrator/Desktop/沿长科技/src/agents/master_agent.py:43)、[music_api_tool.py:36](C:/Users/Administrator/Desktop/沿长科技/src/tools/music_api_tool.py:36)、[music_api_tool.py:68](C:/Users/Administrator/Desktop/沿长科技/src/tools/music_api_tool.py:68)。

MasterAgent 总是给 AudioAgent 注入传入模型或 MockMusicModel。CLI 和 Web 都从该主入口进入，因此 AudioAgent 根据 MUSIC_PROVIDER 构造真实客户端的逻辑被跳过。

复现：将 settings.MUSIC_PROVIDER 设为 suno，MasterAgent.audio_agent.client 仍然是 MockMusicModel。另行直接执行新客户端的 Mock 分支，会因给 generate_synthetic_wav 传入不存在的 bpm 参数而抛 TypeError。

其他静态缺口：没有 API Key 时新客户端会自动走 Mock；旧适配器远端错误会回退合成但仍记录所选商业 provider；两套客户端并存；真实路径没有音频转码，提交阶段 429 没有接上当前重试装饰器；轮询 task_id 没有在等待前写 checkpoint。

Mock 音频默认最多 15 秒，是重复合成和弦，不包含按歌词演唱的音轨；系统没有将时长与 brief 的 180/210 秒等目标做交付校验。

影响：原始需求允许 Mock，但 v2 的真实音乐创作、异步任务恢复和真实产出目标不成立。不能把合法 WAV 等同于符合 Brief 的完整歌曲。

修复方向：统一模型工厂和适配器；显式区分测试与生产模式；生产失败需报错并保留重试凭证，记录真实来源；选择实际音乐供应商后完成真实调用、转码、时长和作品内容验收。

### P1-08：“生成完整音频”接口当前报 500，且实现会覆盖当前版本

位置：[app.py:518](C:/Users/Administrator/Desktop/沿长科技/src/web/app.py:518)、[app.py:543](C:/Users/Administrator/Desktop/沿长科技/src/web/app.py:543)。

接口使用 master.audio_agent.music_model，而 AudioAgent 已改成 client 属性。复现请求 /audio/generate_full?duration=10 返回 HTTP 500，异常为 AttributeError。

该接口还允许 audio_approved/package_ready 状态，在同一个当前版本路径写音频和作曲 JSON，未分配新版本、未撤销旧审核。即使只修正属性访问，也会触发 R4 和审核内容绑定问题。

修复方向：纳入统一重做工作流，分配新版本、持久化任务并重新进入 audio_ready；不得直接修改批准版本。

### P1-09：WAV 和声学质检可放过截断数据和严重削顶

位置：[audio_utils.py:78](C:/Users/Administrator/Desktop/沿长科技/src/utils/audio_utils.py:78)、[acoustic_qc_tool.py:72](C:/Users/Administrator/Desktop/沿长科技/src/tools/acoustic_qc_tool.py:72)、[acoustic_qc_tool.py:97](C:/Users/Administrator/Desktop/沿长科技/src/tools/acoustic_qc_tool.py:97)。

基础检查只读取头部参数，没有校验声明帧数与真实数据长度。声学检查只查看最多 50,000 帧，计算 clipping_ratio 后没有用于拒绝，也没有强制采样率、声道、位深和正时长。

复现：8kHz 单声道、100% 削顶的 WAV 两套检查都判有效；44 字节零帧 WAV 也判有效；将声称有 1 秒音频的文件截断到 84 字节，两套检查仍判有效。

影响：合法文件头不能保证实际音轨完整；不满足损坏音频拦截和 v2 声学质检约定。

修复方向：检查全量帧长和 RIFF 数据一致性、正时长、交付音频规格与时长容差；按分段或全量统计静音/削顶，显式执行质量阈值。

### P1-10：音频驳回意见只记账，未参与重新生成

位置：[graph.py:288](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:288)、[graph.py:305](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:305)、[audio_agent.py:39](C:/Users/Administrator/Desktop/沿长科技/src/agents/audio_agent.py:39)。

音频审核反馈记录在账本里，但 AudioAgent.generate 没有 feedback 输入，调用模型时没有附带修改要求。Mock 歌词回退生成器同样没有使用 feedback，只调整标题版本字样。

复现：音频驳回并要求“减半速度、移除打击乐”，生成 v2 与 v1 的音频 SHA-256 完全相同。Mock 歌词要求重写后，各段歌词行也保持相同。

影响：版本增加不等于按用户意见完成修改；缺少作词作曲的业务反馈闭环。

修复方向：将审核意见、待修改产物及需要调整的音乐参数作为强类型输入，生成器和真实模型提示都必须使用；验证修改内容而非只验证版本变化。

## 进一步缺漏

### P2-01：LangGraph 目前只承载初始化两步，v2 编排未完成

位置：[graph.py:45](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:45)、[graph.py:48](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:48)、[graph.py:126](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:126)。

- START 只连 plan_node，再连 lyrics_node，然后 END；audio_node 和 package_node 没有可达入口。
- approve/resume 实际通过命令式分支直接调用子 Agent，没有 v2 约定的 HITL interrupt、条件路由或持久化图恢复。
- MemorySaver 只存内存，不是跨进程持久化 Checkpointer。
- 计划保存为文件后不参与执行依赖校验；TaskPlan.stages 允许空列表。
- _node_package 引用了未定义的 ledger；当前节点不可达掩盖了该错误。
- 作词工具是固定后处理调用，结果没有引发反思重写；词律未知字使用 ord(char) % 8 分组，不能作为可靠的押韵判断。

当前架构可以作为受控顺序多 Agent 工作流的骨架；若按 v2 文档验收，需要补上实际调度、自纠和持久化恢复，而不只是保留节点名称。

### P2-02：R1 契约约束未贯彻到接口和节点间

位置：[graph_state.py:7](C:/Users/Administrator/Desktop/沿长科技/src/core/graph_state.py:7)、[app.py:56](C:/Users/Administrator/Desktop/沿长科技/src/web/app.py:56)、[composition.py:26](C:/Users/Administrator/Desktop/沿长科技/src/models/composition.py:26)。

MusicGraphState 使用 TypedDict 和大量 Dict[str, Any]；Web brief、响应、编曲段落、模型参数和审核快照仍存在弱类型透传。一些 Pydantic 契约位于 core/services/tools/web 而非统一 src/models。状态、版本、哈希和阶段字段缺少枚举/格式约束与跨模型关联验证。

### P2-03：真实 LLM 失败被模板回退掩盖，Brief 约束未完整传递

位置：[llm_service.py:64](C:/Users/Administrator/Desktop/沿长科技/src/services/llm_service.py:64)、[llm_service.py:179](C:/Users/Administrator/Desktop/沿长科技/src/services/llm_service.py:179)、[llm_service.py:299](C:/Users/Administrator/Desktop/沿长科技/src/services/llm_service.py:299)。

规划失败被 pass，作词请求多次失败后回退固定的三类中文模板；任意其他主题落到“霓虹夜行”。回退元数据不能准确反映真实模型来源。作词真实请求未包含时长和平台等需求信息；Mock 的 language 字段可以写成其他语种，而内容依然为中文。

需要明确生产失败与演示回退的行为，记录调用错误、重试次数、模型来源，并在作词输入中完整提供影响歌曲结构的 Brief 信息。

### P2-04：幂等、发行元数据和审计记录仍不完整

位置：[graph.py:147](C:/Users/Administrator/Desktop/沿长科技/src/core/graph.py:147)、[packager.py:154](C:/Users/Administrator/Desktop/沿长科技/src/services/packager.py:154)、[master_agent.py:165](C:/Users/Administrator/Desktop/沿长科技/src/agents/master_agent.py:165)。

- 同 project_id 的新 Brief 不比较内容/哈希，直接返回旧结果；复现为主题已改变但计划仍为旧主题，且未提示冲突。
- 没有独立艺人/项目署名输入，artist_name 使用 audience，导致“18-25 岁……”成为艺人名。
- 版权声明由系统无条件合成，没有可审查的版权归属、采样授权和人工确认输入，无法覆盖“缺少版权声明必须 needs_info”的业务场景。
- package_version 固定 v1.0.0，同目录重新导出覆盖旧包。
- 运行报告在最后重新构造事件时间，不能还原真实执行时序；last_error 等字段没有形成真实错误留痕。
- 当前仓库示例 release-package/ 的 manifest 属于 test_graph_e2e，状态 needs_info、缺 cover.png，不能作为标准完整 ready 示例交付。

### P2-05：安装声明和测试隔离需要补齐

位置：[pyproject.toml:11](C:/Users/Administrator/Desktop/沿长科技/pyproject.toml:11)、[tests/test_web_api.py:19](C:/Users/Administrator/Desktop/沿长科技/tests/test_web_api.py:19)、[tests/test_graph_engine.py:23](C:/Users/Administrator/Desktop/沿长科技/tests/test_graph_engine.py:23)。

- Web 用到 fastapi、uvicorn、python-multipart；Web 测试用到 httpx，但依赖声明未列出它们。
- Web 测试依赖仓库中已经有 song_001，且新建测试项目没有全量隔离；部分恢复/图测试直接使用默认输出目录，已有示例包会被覆盖。
- 音频版本测试只检查 v1→v2，没有第三次碰撞；所谓崩溃恢复测试是在完整阶段结束后重建实例，没有模拟写文件与保存 checkpoint 之间的真实失败窗口。
- 新音乐客户端测试仅检查初始化，没有执行其会抛 TypeError 的生成分支；现有套件也未覆盖完整音频、ZIP 一致性、审核版本匹配和 ready 状态降级。

## 建议实施顺序与验收标准

1. **先修审核与物料可信性**：所有作曲入口必须核对当前歌词批准；下载与导出共用门禁；审核绑定项目、版本、内容哈希。验收应包含待审项目直接调用驳回/下载、错版本账本、审核后篡改和跨项目输入。
2. **修版本与恢复**：统一版本分配、不可变产物、每项目锁、阶段事务和持久化任务 ID。验收至少覆盖三次版本碰撞、并发提交、初始化崩溃、音频落盘后崩溃及驳回生成失败后的恢复。
3. **修完备性与交付**：缺失/损坏材料稳定降级；ready 可重验降级；按项目和包版本保存，ZIP 原样压缩受检文件。验收应对全部随包文件逐一比对 manifest，并核对 checkpoint 状态。
4. **完成创作功能**：统一真实供应商适配，把作词/作曲反馈送入生成；完成转码、时长和音频数据校验。v2 验收需要实际供应商生成一首符合 Brief 的完整作品，并验证重试恢复。
5. **补工程交付**：集中契约，补依赖与真实事件审计，修复 UI 失效操作，隔离测试目录，重新生成完整 ready 示例包并更新文档中的能力描述。

当前适合作为继续开发的原型；上述 P1 问题关闭前，不应给出“全部业务功能符合、R1–R7 已满足、生产级验收通过”的结论。
