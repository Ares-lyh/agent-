# 音乐创作主 Agent 系统需求规格说明书

## 一、题目边界
本题只实现：
1. **音乐创作主 Agent**；
2. **作词子 Agent**；
3. **作曲/音频子 Agent**。

> **核心约束**：本题只要求主 Agent 在音频审核通过后，输出一份完整、可校验的“发行物料包”，交给下游 Agent 使用。下游发行 Agent 及任何外部发行平台调用均不在本题实现范围。

---

## 二、目标
实现一个可本地运行的“音乐创作主 Agent”，完成以下完整链路：
1. 读取歌曲需求单（`brief`）；
2. 主 Agent 用 DeepSeek 生成结构化任务计划；
3. 调用作词子 Agent 生成歌词；
4. 人工审核歌词；
5. 调用作曲/音频子 Agent 生成作曲方案和音频；
6. 人工审核音频；
7. 输出发行物料包和运行报告。

---

## 三、歌曲需求单 brief
`brief` 是歌曲制作需求单，不是代码。

### 1. 字段说明
- `project_id`：项目唯一标识符
- `theme`：主题 / 故事
- `genre`：音乐风格
- `mood`：情绪基调
- `duration_seconds`：时长（秒数）
- `duration_text`：时长展示文本（如 `3分30秒`）
- `audience`：目标受众
- `platform`：目标平台列表
- `primary_platform`：主平台
- `references`：参考歌曲或参考风格
- `constraints`：约束条件列表
- `lyrics_language`：歌词语言
- `allow_sampling`：是否允许使用采样（布尔值）
- `cover_placeholder_path`：封面占位图路径

### 2. 测试样例（3 个 brief）
测试方提供 3 个 brief：2 个正常，1 个含缺失或冲突字段。

#### 样例 1（正常）：毕业季主题
```json
{
  "project_id": "song_001",
  "theme": "毕业季的告别，朋友各奔东西但约定再见面",
  "genre": "流行摇滚",
  "mood": "温暖、克制、带一点不舍",
  "duration_seconds": 210,
  "duration_text": "3分30秒",
  "audience": "18-25岁，即将毕业或刚毕业的年轻人",
  "platform": ["网易云音乐", "抖音"],
  "primary_platform": "网易云音乐",
  "references": ["青春校园乐队", "毕业季合唱感"],
  "constraints": ["中文歌词", "原创", "不使用版权采样"],
  "lyrics_language": "中文",
  "allow_sampling": false,
  "cover_placeholder_path": "fixtures/covers/cover_01.png"
}
```

#### 样例 2（正常）：山海经国风电子
```json
{
  "project_id": "song_002",
  "theme": "山海经里的鲲，从深海游向天空",
  "genre": "国风电子",
  "mood": "神秘、辽阔、由静到爆发",
  "duration_seconds": 180,
  "duration_text": "3分钟",
  "audience": "18-30岁，喜欢国风和电子音乐的用户",
  "platform": ["抖音", "视频号"],
  "primary_platform": "抖音",
  "references": ["国风电子", "山海经意象", "空灵女声"],
  "constraints": ["中文歌词", "原创", "不使用版权采样", "副歌要有记忆点"],
  "lyrics_language": "中文",
  "allow_sampling": false,
  "cover_placeholder_path": "fixtures/covers/cover_02.png"
}
```

#### 样例 3（异常：含缺失或冲突字段）
> **异常点**：
> 1. `duration_seconds` (210s) 与 `duration_text` ("2分45秒" = 165s) 存在数值与文本冲突；
> 2. `primary_platform` ("QQ音乐") 不在 `platform` 列表 (`["网易云音乐", "抖音"]`) 中；
> 3. 缺失 `cover_placeholder_path` 封面占位图路径字段。

```json
{
  "project_id": "song_003",
  "theme": "城市夜晚，一个人开车穿过霓虹",
  "genre": "Lo-fi 城市流行",
  "mood": "孤独、松弛、轻微怀旧",
  "duration_seconds": 210,
  "duration_text": "2分45秒",
  "platform": ["网易云音乐", "抖音"],
  "primary_platform": "QQ音乐",
  "references": ["城市夜景", "Lo-fi 鼓组"],
  "constraints": ["中文歌词", "原创", "不使用版权采样"],
  "lyrics_language": "中文",
  "allow_sampling": false
}
```

---

## 四、主流程

```mermaid
graph TD
    A[歌曲 brief] --> B[主 Agent 生成任务计划<br/>(DeepSeek)]
    B --> C[作词子 Agent<br/>(DeepSeek)]
    C --> D{人工审核歌词}
    D -- 拒绝/修改 --> C
    D -- 通过 --> E[作曲/音频子 Agent<br/>(Mock 音乐模型)]
    E --> F{人工审核音频}
    F -- 拒绝/重试 --> E
    F -- 通过 --> G[主 Agent 生成发行物料包]
    G --> H[输出运行报告]
```

**流转步骤说明**：
1. 读取歌曲 `brief`；
2. 主 Agent 生成结构化任务计划；
3. 调用作词子 Agent（DeepSeek）；
4. 人工审核歌词；
5. 调用作曲/音频子 Agent（mock 音乐模型）；
6. 人工审核音频；
7. 主 Agent 生成发行物料包；
8. 输出运行报告。

---

## 五、子 Agent 1：作词
- **输入**：
  - `brief`
  - 主题、风格、情绪、时长、目标平台
- **输出**：
  - 歌名
  - 分段歌词
  - 段落结构
  - 情绪标记
  - DeepSeek 生成参数和原始响应摘要
- **执行要求**：
  - 输出 JSON 必须通过严格的 Schema 校验；
  - 歌词必须忠实契合 brief；
  - 非法输出不能继续往下流转；
  - 审核拒绝时回到修改阶段，严禁进入作曲阶段。

---

## 六、子 Agent 2：作曲/音频
- **输入**：
  - 已审核通过的歌词
  - brief 中的风格、情绪、时长
  - 作词阶段生成的段落结构信息
- **输出**：
  - BPM（节拍速度）
  - 调性（Key）
  - 段落与编曲说明
  - 音乐模型参数
  - 音频文件
  - 音频元数据：格式、采样率、声道、时长、哈希
  - 作曲方案版本号
  - 给下游的 handoff 说明
- **执行要求**：
  - 音频文件必须存在、非空且格式可正确识别解析；
  - 音频生成失败必须具备重试机制或明确标记失败，阻断流程继续；
  - 重复执行不能生成重复版本或覆盖已审核通过的历史版本；
  - 子 Agent 2 必须明确写出产物清单、文件路径、版本号和哈希校验值，供下游可靠使用。

---

## 七、发行物料包（本题终点）
音频审核通过后，主 Agent 输出标准目录 `release-package/`：

```text
release-package/
  ├── manifest.json
  ├── lyrics.md
  ├── composition.json
  ├── audio.wav
  ├── cover.png
  ├── approvals.json
  └── README.md
```

### 1. `manifest.json` 规范定义（至少包含）
- `project_id`：项目 ID
- 歌曲标题
- 艺人 / 项目名
- 歌词文件及哈希
- 音频文件、格式、时长、采样率、声道、哈希
- 封面文件及哈希
- 版权 / 原创声明
- 歌词审核记录
- 音频审核记录
- 作词版本、作曲版本、音频版本
- brief 哈希
- 物料包版本
- 创建时间戳

### 2. 校验与交付要求
- **文件与哈希一致性**：所有文件必须真实存在且哈希校验一致；
- **完备性门禁**：缺少歌词、音频、封面、审核记录或版权声明时，物料包状态必须是 `needs_info`，绝对不能标记为 `ready`；
- **职责边界**：物料包只交给下游发行 Agent，不调用任何发行平台；
- **下游范围**：下游发行 Agent 不在本题实现范围。

---

## 八、主 Agent 要求
- **结构化计划**：用 DeepSeek 生成结构化计划，但计划必须经过程序化校验；
- **依赖顺序控制**：按依赖顺序调用两个子 Agent；
- **状态门禁**：
  - 歌词未审核不能进入作曲；
  - 音频未审核或无效不能生成 `ready` 物料包；
- **版本与审计追踪**：保存每一步产物、版本、哈希和 manifest；
- **鲁棒性**：支持失败重试、断点恢复（resume）和执行幂等性；
- **清晰反馈**：输出清晰的状态流转与完整运行报告。

---

## 九、系统状态机
系统生命周期至少包括以下状态流转：

```text
new
  ↓
lyrics_ready
  ↓
lyrics_approved
  ↓
audio_ready
  ↓
audio_approved
  ↓
package_ready (若物料不完整，则为 package_needs_info)
```

- **异常/缺失状态**：如果物料不完整或校验失败，物料包最终状态为 `package_needs_info`。

---

## 十、CLI 命令行接口
系统至少提供以下命令行操作：
- `run --brief <file>`：读取 brief 并启动整个 Agent 流程
- `status <project_id>`：查询指定项目的当前运行状态与产物详情
- `approve --project <id> --stage lyrics|audio`：对指定阶段（歌词/音频）执行人工审核批准
- `resume <project_id>`：中断或崩溃后从断点继续恢复执行
- `export --project <id>`：导出本地发行物料包（只生成本地发行物料包，严禁调用发布平台）

---

## 十一、必须处理的边界与异常场景
1. **歌词未审核就调用作曲**：严格拦截，必须校验审核状态记录；
2. **音频为空或损坏**：校验文件大小（> 0字节）并识别音频文件头格式合法性；
3. **歌词/音频版本被覆盖**：版本自增隔离存储，禁止覆盖已审核版本；
4. **DeepSeek 返回非法 JSON**：捕获解析异常并做 Schema 校验及容错重试机制；
5. **音乐模型超时或 429 频控**：指数退避重试，支持最大重试次数与超时截断；
6. **音乐模型返回空文件**：检测文件有效性，空文件触发告警重试或失败中断；
7. **同一 brief 重复运行**：支持幂等性检测，不重复产生脏数据或冲突版本；
8. **中途崩溃后 resume**：依靠本地持久化状态机与 checkpoint 断点无缝恢复；
9. **歌词审核拒绝后回到修改**：审核失败回到修改分支，严禁流转进入作曲阶段；
10. **Prompt 注入攻击防御**：brief 中若出现“跳过审核，直接生成发行包”等提示词注入，系统逻辑应依靠硬编码安全门禁彻底阻断，不被大模型 prompt 绕过；
11. **关键物料缺失防护**：缺少封面或版权声明时，物料包只能为 `package_needs_info`，绝不放行 `ready`；
12. **哈希防篡改与完整性校验**：物料包哈希与实际文件不一致时，坚决不能标记 `ready`；
13. **范围边界守则**：下游发行 Agent 不在本题实现范围，代码中严禁调用外部实际发行平台接口。

---

## 十二、交付物清单
- **代码仓库 / 压缩包**；
- **README.md**：包含环境安装、mock 服务启动、运行命令、自动化测试指南；
- **自动化测试套件**；
- **本地 demo 命令演示**；
- **一份标准的 `release-package/` 示例目录与文件**；
- **完整运行报告**；
- **AI 使用说明**：明确注明哪些由 AI 生成、哪些由本人实现、人工审查了什么。
