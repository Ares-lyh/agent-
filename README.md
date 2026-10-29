# 音乐创作主 Agent 系统

本项目将需求单交给主 Agent 规划，再由作词 Agent 创作歌词。人工批准歌词后，音频 Agent 制定编曲方案并调用音乐生成网关；人工试听批准后输出本地发行物料包。项目不调用真实发行平台。

## 安装和启动

建议 Python 3.10 或更高版本，在项目目录使用独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m src.cli serve --port 8000
```

打开 http://127.0.0.1:8000 。Windows 也可以执行 `./start_studio.ps1`，它只使用项目的 .venv，不会混用其他 Python。

网页启动使用真实创作入口，要求文本与音乐服务配置齐全且关闭 Mock。需求模板自动分配新项目 ID，并清空演示署名、版权确认和封面，正式物料由项目方补齐。启动请求在保存 checkpoint 后返回 HTTP 202，后台调用真实规划和作词服务，页面显示阶段进度；生成完成停在歌词人工审核，批准后再推进真实音乐生成。失败原因会保留，重启后可以恢复原任务。

工作台顶部显示当前服务配置；每个工程分别显示已有歌词和音频的实际来源。历史 `mock-music-synthesizer` 音轨标注为离线演示，缺少可核对来源的旧产物标注为“来源未核实”。切换真实服务不会改变旧产物的来源标记。刷新浏览器以加载前端修复。

复制 .env.example 后填写自己的配置；已有 .env 不应覆盖。密钥不进入产物、日志或 Git。

## 项目结构与文件说明

本项目采用严格分层的模块化架构，遵循“契约单一起源（Pydantic）”、“状态机硬门禁”与“版本不可变隔离”原则。整体目录结构如下：

```text
├── AGENTS.md                  # 工程治理红线规约 (R1-R7)
├── README.md                  # 项目全景使用与架构文档
├── REQUIREMENTS.md            # 系统功能需求与工程规格说明
├── pyproject.toml             # Python 项目构建与依赖声明
├── requirements-lock.txt      # 依赖确定性版本锁定清单
├── run_tests.py               # 自动化全量测试运行入口
├── start_studio.ps1           # Windows 本地虚拟环境一键启动脚本
├── .env.example               # 环境变量配置模板
├── docs/                      # 架构规范、PRD 与评审记录
│   ├── prd/                   # 产品需求文档
│   ├── specs/                 # 技术架构蓝图设计
│   └── reviews/               # 迭代评审与安全核验记录
├── fixtures/                  # 测试与演示素材
│   ├── briefs/                # 示例歌曲需求单 (JSON)
│   └── covers/                # 示例封面图片
├── release-package/           # 本地交付发行物料包输出目录
├── scripts/                   # 运维、测试与验收脚本
├── storage/                   # 本地运行时项目工作区与断点
├── tests/                     # 自动化测试套件 (20 个测试模块)
└── src/                       # 核心业务实现代码
    ├── cli.py                 # CLI 命令行入口
    ├── config.py              # 全局配置管理
    ├── agents/                # 多智能体编排层 (Master/Lyrics/Audio)
    ├── core/                  # 状态机、断点与 LangGraph 引擎
    ├── models/                # Pydantic 强类型契约单一起源
    ├── services/              # LLM 调用、打包器与本地合成器
    ├── tools/                 # ACEMusic 客户端、通用网关与声学质检
    ├── utils/                 # 音频转码、原子写入与安全锁
    └── web/                   # Web Studio 工作台 (FastAPI + 原生前端)
```

### 1. 根目录与工程治理文件
- `AGENTS.md`：核心工程治理规约，明确定义七大核心红线（R1 契约单一起源、R2 代码级门禁防注入、R3 零假数据、R4 不可逆版本自增、R5 完备性门禁与降级、R6 本地边界严禁外发、R7 原子断点与幂等性）以及状态机流转准则。
- `README.md`：项目核心说明文档，涵盖系统架构、快速开始、项目目录结构与文件职责、模型配置、人工审核工作流、需求版权规范及不可变发行包机制。
- `REQUIREMENTS.md`：系统功能需求与技术约束规范，详细阐述系统状态机、门禁逻辑、交付物料规范及验收准则。
- `pyproject.toml`：现代 Python 项目打包配置文件，声明包元数据、核心运行时依赖（FastAPI、LangGraph、Pydantic、Click、Uvicorn 等）、开发环境依赖及 CLI 命令行入口（`music-creator`）。
- `requirements-lock.txt`：生产环境依赖精确锁定清单，保障跨操作系统与环境构建的完全一致性与确定性。
- `run_tests.py`：快捷测试启动器，自动调用 `pytest` 执行系统全量测试套件并格式化输出测试结果。
- `start_studio.ps1`：Windows PowerShell 自动化拉起脚本，强制绑定项目的独立虚拟环境（`.venv`），一键启动 Web Studio 工作台。
- `.env.example`：环境变量模板文件，详尽罗列文本 LLM（DeepSeek/Codex/OpenAI）与音乐生成服务（ACEMusic/音乐网关）所需的配置参数与开关。
- `.gitignore`：Git 版本控制排除规则，防止敏感私有密钥（`.env`）、虚拟环境（`.venv`）、运行时断点与构建缓存进入仓库。

### 2. 核心源码架构 (`src/`)

#### 2.1 入口与配置
- `src/cli.py`：基于 Click 的全功能命令行交互入口。包含 `run`（启动创作链路）、`status`（状态查看）、`approve`（人工审核批准/驳回）、`resume`（断点继续）、`export`（打包导出物料）、`rights`（版权署名补全）和 `serve`（启动 Web 工作台）等核心指令。
- `src/config.py`：系统全局配置中心（`Settings`），通过 `dotenv` 统一解析环境变量，管理文本模型/音乐服务 API 密钥、端点、存储路径、超时时间与重试上限。

#### 2.2 智能体层 (`src/agents/`)
- `src/agents/base.py`：所有 Agent 的抽象基类 `BaseAgent`，并提供具备指数退避与随机抖动的弹性网络重试装饰器 `retry_with_backoff`。
- `src/agents/master_agent.py`：主协调智能体（`MasterAgent`）。驱动全生命周期调度，协调需求校验、作词、音频生成、人工审核中断恢复与发行封包，将状态图流转统一交由 LangGraph 引擎驱动。
- `src/agents/lyrics_agent.py`：作词智能体（`LyricsAgent`）。根据需求单生成歌词草稿；内置词律自检工具进行格律整齐度与韵母检测；支持五言/七言硬校验，在未达到约束时触发有限次数的自省修正；产物采用不可变自增版本写入（`vN.json`）。
- `src/agents/audio_agent.py`：音频与编曲智能体（`AudioAgent`）。执行严格的人工歌词批准门禁校验；结合需求单与人工批注推导音乐参数（BPM、调性、人声设定）；生成编曲方案（`vN_comp.json`）并调用音乐服务生成音轨；经过声学质量检测与格式标准化后原子发布（`vN_audio.wav`）。

#### 2.3 核心控制流与状态机 (`src/core/`)
- `src/core/state_machine.py`：有限状态机（`StateMachine`）与生命周期状态枚举（`ProjectState`）。硬编码定义合法状态跃迁集合，确保系统只能沿规定路径单向流转，坚决阻断越权跳级。
- `src/core/checkpoint.py`：原子断点引擎（`CheckpointManager`）。基于项目 ID 管理存储目录，采用写临时文件后原子替换（Atomic Rename）的方式维护 `checkpoint.json`，确保断电或崩溃后无损恢复。
- `src/core/graph.py`：基于 LangGraph 的确定性状态图引擎（`MusicGraphEngine`）。将规划、作词、歌词人工审核中断（`interrupt`）、音频生成、音频试听审核中断与发行打包组织为状态图节点，实现任务持久化与断点唤醒。
- `src/core/graph_checkpoint.py`：轻量级 SQLite 图状态保存器（`SQLiteGraphSaver`），持久化保存 LangGraph 图的运行点与线程状态，支持服务重启后从精确中断点继续。
- `src/core/graph_state.py`：LangGraph 状态图执行契约定义（`MusicGraphState` 基础引用）。
- `src/core/security.py`：安全防御与防 Prompt 注入模块。提供注入特征检测（`detect_prompt_injection`）与不可信需求单数据 XML 沙箱包装（`sanitize_and_wrap_prompt`），在代码层防御诱导跳过审核的恶意指令。
- `src/core/exceptions.py`：系统领域异常定义，包括工作流门禁越权（`WorkflowGateViolationError`）、物料缺失（`MaterialIncompleteError`）、音频损坏（`AudioCorruptedError`）、模型限流（`RateLimitExceededError`）等。

#### 2.4 Pydantic 契约单一起源 (`src/models/`)
- `src/models/common.py`：系统数据契约基类 `Contract`（基于 Pydantic BaseModel）及通用生成参数 `GenerationParameters`。
- `src/models/brief.py`：需求单数据契约 `Brief` 与异常检测结果模型 `BriefAnomaly`，提供时长文本转换及多维度逻辑冲突扫描。
- `src/models/plan.py`：主 Agent 任务分解模型 `TaskPlan`，记录曲风、情绪、时长、目标受众及各阶段执行指标。
- `src/models/lyrics.py`：歌词数据契约 `Lyrics`、歌词段落 `LyricsSection`，并支持导出为标准排版的 Markdown。
- `src/models/composition.py`：编曲工程方案模型 `Composition` 与音频物理参数契约 `AudioMetadata`（采样率、位深、声道、时长、SHA256、生成参数）。
- `src/models/approval.py`：人工审核记录 `ApprovalRecord` 与项目防篡改审核账本 `ApprovalLedger`，强行绑定审核阶段、结果、审核人与目标物料哈希。
- `src/models/manifest.py`：发行包核心清单契约 `Manifest` 与物料凭据 `MaterialFile`，承载发行状态判定（`package_ready` / `package_needs_info`）、所有物料的 SHA-256 哈希列表及缺失物料警报。
- `src/models/vocals.py`：人声需求模型 `VocalRequirements` 与音频生成意图 `AudioGenerationIntent`（包含主唱性别、人声风格及生成提示词）。
- `src/models/music.py`：音乐生成协议通用任务状态与交互模型。
- `src/models/workflow.py`：工作流断点持久化模型 `ProjectCheckpoint`、待定操作记录 `PendingOperation` 与图状态 `MusicGraphState`。
- `src/models/provenance.py`：物料真实出处溯源模型，标注离线合成、ACEMusic 或网关生成等真实来源信息。
- `src/models/report.py`：系统执行事件 `ExecutionEvent` 与全流程审计报告契约 `RunReport`。
- `src/models/api.py`：Web API 前后端交互的请求体与响应体数据契约。
- `src/models/acemusic.py`：ACEMusic 专属协议数据契约，严格映射其 Chat Completions 接口的请求与响应格式。

#### 2.5 业务领域服务 (`src/services/`)
- `src/services/llm_service.py`：大语言模型服务（`LLMService`）。封装兼容 OpenAI 规范的 `/chat/completions` 调用，通过结构化 JSON 提示与 Pydantic 解析生成任务计划、歌词及编曲方案；支持离线 Mock 模式。
- `src/services/mock_music_model.py`：本地离线音乐合成模型（`MockMusicModel`）。通过纯 Python 算法生成标准和弦音轨与合法 RIFF/WAVE 文件头，并可模拟 429 限流、超时、静音与延迟等网络弹性场景。
- `src/services/real_music_service.py`：真实外部音乐生成服务的工厂与客户端调度器。
- `src/services/packager.py`：发行物料打包器（`ReleasePackager`）。负责构建结构化的不可变版本发行包（`release-package/<project_id>/vN/`），严密执行物料完备性门禁（音频、封面、版权、审核记录、哈希一致性）及 ZIP 打包。
- `src/services/vocal_direction.py`：人声方向解析器（`resolve_vocals`）。根据需求单中的人声要求及人工审核批注，动态合并并推导出精确的音乐模型提示词。
- `src/services/provenance.py`：产物真实性与出处溯源校验服务，核查音频与歌词的生成凭据，杜绝假数据冒充真实产物。
- `src/services/reporter.py`：执行报告生成器，生成可供项目方核查的 `run_report.json` 与 `run_report.md`。

#### 2.6 专业工具与分析 (`src/tools/`)
- `src/tools/acemusic_api.py`：ACEMusic 原生接口适配客户端。构造规范的生成提示词，处理 `/v1/chat/completions` 同步调用，解析 Base64 音频并转存为本地文件。
- `src/tools/music_api_tool.py`：通用音乐网关客户端（`RealMusicEngineClient`）。支持 `POST /generate`、`GET /tasks/{id}` 轮询协议、幂等键重试与网络异常恢复。
- `src/tools/rhyme_tool.py`：歌词韵律分析工具。提取汉字拼音韵母，分析押韵分布、韵脚归纳及五言/七言等格律整齐度。
- `src/tools/acoustic_qc_tool.py`：声学质量检测工具（`inspect_acoustic_quality`）。检测音频波形的 RMS 平均能量、静音片段占比、爆音削顶与有效播放时长，拦截劣质或损坏音轨。

#### 2.7 通用工具库 (`src/utils/`)
- `src/utils/audio_utils.py`：音频底层处理工具。解析 WAV 头部元数据（RIFF、fmt、data），检查采样率（44.1kHz）、位深（16-bit）和声道，并调用 FFmpeg 将非标音频转码为标准 PCM。
- `src/utils/cover_utils.py`：专辑封面图片检查与处理工具，验证封面格式与尺寸合法性。
- `src/utils/hash_utils.py`：哈希工具，提供文件与字符串的 SHA-256 计算，保障物料与审核记录防篡改。
- `src/utils/persistence.py`：原子存储核心工具。提供跨进程排他锁（`project_lock`）、原子文件写操作（`atomic_write`）、只增不覆盖版本号计算（`next_version`）及原子发布（`publish`）。

#### 2.8 Web 协同工作台 (`src/web/`)
- `src/web/app.py`：基于 FastAPI 构建的轻量级后端。提供需求模板导入、项目启动、状态轮询、歌词审核/打回、音频试听流输出、音频审核/打回及发行物料包导出的全部 RESTful 接口。
- `src/web/jobs.py`：Web 后台异步任务管理器，支持在独立执行线程中推进生成链路，提供任务进度轮询与状态追踪。
- `src/web/static/index.html`：Web 工作台单页应用（SPA）骨架，呈现服务配置看板、项目时间线、双栏歌词对比视图、音频播放器及审核表单。
- `src/web/static/app.js`：前端交互控制脚本，处理与后端的异步 API 通信、长轮询同步状态、音频波形加载与动态模态框交互。
- `src/web/static/style.css`：前端视觉样式表，采用现代暗黑工业风（Dark Minimalist）与玻璃拟态（Glassmorphism）设计系统。

### 3. 素材与测试夹具 (`fixtures/`)
- `fixtures/briefs/song_001.json`：标准中文流行情歌需求单示例，包含完整的人声设定、版权声明与时长要求。
- `fixtures/briefs/song_002.json`：带有多维度约束与严格格律要求的需求单示例。
- `fixtures/briefs/song_003.json`：精简配置与边缘测试需求单。
- `fixtures/briefs/acceptance_demo.json`：用于本地全流程自动化验收测试的基准需求单。
- `fixtures/covers/cover_01.png`、`cover_02.png`：用于发行物料包封包测试的标准正方形封面图片。

### 4. 辅助与运维脚本 (`scripts/`)
- `scripts/check_music_connection.py`：音乐生成服务连通性只读探测脚本。测试 ACEMusic / 音乐网关的鉴权状态和模型可用性，绝不消耗实际额度生成歌曲。
- `scripts/check_text_connection.py`：文本 LLM 连通性测试脚本，通过极小 JSON 请求校验 API 连通性，且日志绝不泄露私有密钥。
- `scripts/create_demo_package.py`：本地端到端演示物料包一键生成脚本，利用 Mock 模式全自动跑通 `acceptance_demo` 项目并输出标准物料包。
- `scripts/verify_live_text_workflow.py`：真实文本大模型链路验证脚本，驱动 Master Agent 完成需求解析与歌词生成并停留在待审核阶段。

### 5. 自动化测试套件 (`tests/`)
- `tests/conftest.py`：pytest 全局配置与夹具，提供安全的独立临时测试目录与 Mock 服务环境隔离。
- `tests/test_acemusic_api.py`：验证 ACEMusic 专属协议请求封装、Base64 音频转码、错误码处理与缓存机制。
- `tests/test_audio_agent.py`：测试音频智能体的编曲方案生成、人声提示词合成以及人工歌词批准门禁校验。
- `tests/test_brief_validation.py`：测试需求单字段完整性校验与时长/风格冲突异常探测逻辑。
- `tests/test_business_regressions.py`：核心业务红线综合回归测试（不可逆版本自增、防篡改哈希绑定、越权流转阻断等）。
- `tests/test_checkpoint_resume.py`：测试原子断点保存与中途异常退出后的无损续传恢复。
- `tests/test_cli_e2e.py`：测试 CLI 命令行各个子命令（`run`, `status`, `approve`, `resume`, `export`, `rights`）的端到端调用。
- `tests/test_durable_graph.py`：测试 LangGraph 持久化执行图、人工中断、检查点写入与恢复。
- `tests/test_graph_engine.py`：测试状态图引擎节点调度、条件边路由与合法流转校验。
- `tests/test_lyrics_agent.py`：测试作词智能体的生成逻辑、押韵/节拍自检及多轮自省修改。
- `tests/test_packaging_gate.py`：测试发行包门禁机制，验证缺失封面/版权/音频时必须降级为 `package_needs_info`。
- `tests/test_prompt_injection.py`：测试防 Prompt 注入机制对诱导绕过审核恶意提示词的检测与沙箱防御。
- `tests/test_provenance.py`：测试产物真实来源标记与 Mock 离线演示识别防伪。
- `tests/test_real_music_service.py`：测试真实音乐网关调用、幂等键重放与网络容错。
- `tests/test_state_machine.py`：测试有限状态机的合法转移与非法跳级硬阻断。
- `tests/test_text_service.py`：测试文本模型调用、JSON 结构化输出保证与格式异常回退。
- `tests/test_tools.py`：测试词律分析工具与声学质量检验工具的算法准确性。
- `tests/test_vocal_direction.py`：测试人声配置推导、主唱风格解析与提示词动态拼接。
- `tests/test_web_api.py`：测试 Web 后端各 API 端点（需求提交、审核、恢复、物料包导出等）的功能正确性。
- `tests/test_web_jobs.py`：测试 Web 后台异步作业的生命周期管理与并发安全。

### 6. 文档与产物存储 (`docs/`, `release-package/`, `storage/`)
- `docs/prd/`：产品需求文档目录，包含系统原始 PRD（`music_creator_agent_prd.md`）与多 Agent 架构重构治理 PRD（`multi_agent_music_refactor_prd.md`）。
- `docs/specs/`：技术规格说明目录，包含系统技术架构蓝图（`music_creator_agent_blueprint.md`）与多 Agent 重构架构契约（`multi_agent_music_refactor_blueprint.md`）。
- `docs/reviews/`：迭代记录与安全审计报告，包含历史重构、ACEMusic 接入、人声定制及安全修复备忘录。
- `release-package/`：最终发行交付物料包输出根目录，每个项目以 `<project_id>/vN/` 格式独立归档，包含 `manifest.json`、`lyrics.md`、`composition.json`、`audio.wav`、`cover.png`、`approvals.json` 等完整交付物。
- `storage/projects/`：运行时工程工作区，持久化存放各项目的 `checkpoint.json`、`plan.json`、`approvals.json`、各版本歌词目录（`lyrics/`）及音频目录（`audio/`）。

## 文本模型与音乐模型

文本模型读取以下两组配置之一，优先级为 DEEPSEEK → CODEX → OPENAI。CODEX 组仅是兼容环境变量名称，不调用 Codex CLI：

```dotenv
CODEX_API_KEY=填写本地密钥
CODEX_BASE_URL=填写服务商的OpenAI兼容v1地址
CODEX_MODEL=gpt-6.1-sol
USE_MOCK_LLM=false
```

保留自己服务商实际支持的模型名称。文本模型使用 /chat/completions 生成任务计划、歌词和编曲方案，所有业务结果均通过 Pydantic 验证。请求失败或 JSON 不合格会阻断并留存可恢复任务，不会自动返回固定歌词冒充成功。

**文本模型配置不能代替音乐音频生成服务。** 没有音乐网关时，流程可以到达歌词待审，歌词批准后生成音频会明确提示配置缺失：

```dotenv
MUSIC_PROVIDER=gateway
REAL_MUSIC_API_KEY=音乐网关的密钥
REAL_MUSIC_BASE_URL=https://your-music-gateway.example/v1
FFMPEG_PATH=ffmpeg
```

当前适配的是明确的音乐网关协议，不声称原生兼容所有 Suno、MiniMax 或 Udio 接口：

- POST /generate：输入 prompt、tags、title、duration、make_instrumental；支持幂等键 Idempotency-Key。
- 返回合法音频二进制、audio_url，或 task_id。
- GET /tasks/{task_id}：返回 status 和完成时的 audio_url。
- 任务 ID 在轮询前写入 checkpoint，resume 继续原任务；网关需要支持同一幂等键重放，才能避免提交响应丢失后的重复计费。
- 非标准 WAV 通过 ffmpeg 转为 44.1kHz、16-bit、双声道 PCM；必须通过全量帧检查、声学检查和时长校验。
- 支持提交阶段限流/网络重试、轮询超时和恢复；生产错误不会切换到本地合成器。

服务商的实际 API 与上述协议不同时，需要部署协议转换网关或增加对应适配器。真实歌曲的音质和内容仍由人工试听审核。

### ACEMusic 原生接口

项目已支持 ACEMusic 的音乐 Chat Completions 协议，可直接使用其控制台获取的密钥：

```dotenv
MUSIC_PROVIDER=acemusic
REAL_MUSIC_BASE_URL=https://api.acemusic.ai
REAL_MUSIC_API_KEY=填写本地ACEMusic密钥
ACEMUSIC_MODEL=acemusic/acestep-v1.5-turbo
```

该适配器调用 `/v1/chat/completions`，把**已人工批准的歌词**放入专门的 lyrics 字段，编曲方案放入 messages；关闭 sample_mode/use_format，避免服务端重写已审歌词。传递时长、BPM、调性、歌词语言，并请求 WAV；返回 Base64 音频或音频 URL 后统一做转码、声学与时长检查。系统自带 imageio-ffmpeg 转码依赖，不需要额外配置本机 PATH；也可通过 FFMPEG_PATH 指定外部 FFmpeg。

只读验证鉴权和所选模型，不生成歌曲：

```powershell
.\.venv\Scripts\python.exe scripts/check_music_connection.py
```

ACEMusic 当前公开的是同步生成协议，未在所核对的文档中承诺幂等键或任务结果查询。系统会先在 checkpoint 记录提交标记，收到完整响应后将其缓存在该版本旁；转码或本地提交中断时复用缓存，不重复调用。若网络中断且无法确定远端是否已生成，会暂停自动重发，并保留任务供核查，避免重复消耗额度。服务明确返回 429 时可稍后 resume。

切换 `.env` 后需要重启工作台。模型列表报告的零价格字段不代表无限配额，实际账号额度与服务可用性以 ACEMusic 为准。协议依据：[ACE-Step 官方音乐 API 文档](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/Openrouter_API_DOC.md)。

仅用于离线演示、自动化验收时，显式设置：

```dotenv
USE_MOCK_LLM=true
MUSIC_PROVIDER=mock
```

Mock 使用模板歌词和本地合成和弦，生成符合需求时长的 WAV，manifest.is_mock=true，界面标注离线演示。它不是按歌词演唱的真实歌曲。生产环境默认 MUSIC_PROVIDER=unconfigured，配置不足会报错。

## 工作流与人工审核

```text
new → lyrics_ready → lyrics_approved → audio_ready → audio_approved
    → package_ready | package_needs_info
```

```powershell
.\.venv\Scripts\python.exe -m src.cli run --brief fixtures/briefs/song_001.json
.\.venv\Scripts\python.exe -m src.cli status song_001
.\.venv\Scripts\python.exe -m src.cli approve --project song_001 --stage lyrics --reviewer 制作人
.\.venv\Scripts\python.exe -m src.cli resume song_001
.\.venv\Scripts\python.exe -m src.cli approve --project song_001 --stage audio --reviewer 制作人
.\.venv\Scripts\python.exe -m src.cli export --project song_001
```

拒绝并传入修改意见：

```powershell
.\.venv\Scripts\python.exe -m src.cli approve --project song_001 --stage lyrics --reject --feedback "副歌更克制"
.\.venv\Scripts\python.exe -m src.cli approve --project song_001 --stage audio --reject --feedback "速度减半，突出吉他"
```

修改意见进入对应生成输入。作词会进行有次数上限的词律反思；明确的严格格律不合格时阻断。音频重做分配新版本，保留旧文件，并重新等待试听批准。

LangGraph 包含规划、歌词、音频、打包与两个人工审核中断节点；SQLite 持久化图执行位置，checkpoint.json 原子保存业务状态、审核账本、待执行任务、版本和错误。人工审核结果只由 Python 与显式操作写入，模型没有批准权限。每个项目使用跨进程锁串行化变更。

同一项目 ID、同一需求单再次运行会复用进度；需求内容改变时要求新 ID。封面与版权信息通过专用操作更新。

## 需求单与版权信息

人声目标可在需求单中显式填写，例如：

```json
"vocals": {"lead": "female", "style": "空灵、轻盈、气声、清晰中文咬字"}
```

`lead` 可取 female、male、mixed、unspecified。未填写时会从 references、constraints 推导；本次音频的人工修改意见可覆盖主唱目标。人声要求直接写入音乐生成提示词，不能只依赖编曲摘要。每个真实音频版本保存生成目标和最终提示词，便于核对；旧版未填写 vocals 的需求哈希保持兼容。

ACEMusic 公开协议通过 caption 提示词控制女声/男声，没有在本适配器中虚构 gender 参数。女声、空灵音色和歌词准确性属于试听审核内容；WAV、时长及声学检查通过不代表这些创作目标已经满足。对不符合目标的音频使用“打回重调音频”，填写清楚要求后生成新版本，不覆盖旧版本。歌词结构摘要是创作设想，不是成品音色检测报告。

参见 fixtures/briefs/。原始字段外增加：

- artist_name：真实艺人或项目署名，不使用 audience 代替。
- copyright_statement：项目方提供的版权、原创和采样授权声明。
- rights_confirmed：经人工审查后设为 true。

缺少署名或经确认的版权声明，包状态为 needs_info。可以在 Web 的需求单详情中补齐，或使用：

```powershell
.\.venv\Scripts\python.exe -m src.cli rights --project song_001 --artist "项目署名" --statement "已审查的版权及采样声明" --confirm
.\.venv\Scripts\python.exe -m src.cli export --project song_001
```

示例需求单的声明仅用于演示验收，不证明任何真实作品的商业版权。

## 不可变版本与发行包

歌词为 lyrics/vN.json，音频与方案为 audio/vN_audio.wav、audio/vN_comp.json。历史产物通过独占发布写入，存在则不能替换。审核绑定项目 ID、版本、文件哈希，音频还绑定编曲与已批准歌词。

新发行包位置：

```text
release-package/<project_id>/vN/
  manifest.json
  lyrics.md
  composition.json
  audio.wav
  cover.png
  approvals.json
  brief.json
  lyrics.json
  composition-source.json
  README.md
```

每次导出自增包版本。缺失、损坏、审核不匹配、版权缺失或哈希异常都会降级为 package_needs_info；已有 ready 项目重验失败也会降级。歌词与编曲源文件也随包保存，用于独立复核审核绑定。ZIP 原样压缩受检目录，不重新排版歌词，不从其他项目取封面或 manifest。

已有旧版平铺 release-package/ 物料保留，后续输出不会覆盖。旧审核记录没有内容哈希的，需要重新显式批准歌词并重做/审核音频；系统不会自动把旧记录升级为有效批准。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe run_tests.py
.\.venv\Scripts\python.exe scripts/check_text_connection.py
```

测试自动切换至临时目录和显式 Mock，不修改真实作品或示例发行包。覆盖正常流程、第三次版本碰撞、并发运行、真实崩溃窗口、驳回恢复、审核后篡改、缺物料、ZIP 哈希一致性、声学坏样本和网关协议。

check_text_connection.py 会使用本地密钥发送一个最小 JSON 请求；只输出配置模型、主机和成功/失败，不输出密钥。verify_live_text_workflow.py 可对真实模型验证规划与作词，并停在 lyrics_ready，不自动批准。

本地完整验收示例由 scripts/create_demo_package.py 生成，默认项目名 acceptance_demo；审核者标记为自动化验收，manifest 标注 Mock，不等同于真实制作人的审美批准。

## 工程边界与 AI 使用记录

本仓库的代码、文档和回归测试由 AI 辅助修改。本次自动化检查验证契约、门禁、版本、恢复与文件一致性；不能代替制作人的歌词和音频审美审核，也不能代替权利人的版权确认。改动记录见 docs/reviews/。

官方结构化输出参考：https://developers.openai.com/api/docs/guides/structured-outputs 。
