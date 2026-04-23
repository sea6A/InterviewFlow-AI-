# AI 面试陪练官 - 项目骨架

这是一个面向求职训练场景的实时语音多模态 AI 面试陪练平台骨架，基于阿里千问 / DashScope 能力设计，目标是先把项目讲清楚、分层清楚、接口清楚，后续再逐步补全真实业务实现。

## 1. 推荐技术栈

### 前端

- Next.js + React
- Web Audio API / MediaRecorder 采集麦克风
- WebSocket 负责浏览器与后端的实时事件同步
- Tailwind CSS 或 CSS Modules 构建面板式训练界面

### 后端

- FastAPI 作为主服务框架
- Python `dashscope` SDK 管理千问 Realtime 会话
- REST API 管理简历、JD、会话、报告
- SQLAlchemy + Alembic 管理 PostgreSQL
- Redis 管理实时 session 状态和短期缓存
- MinIO / OSS 存储录音、截图、报告附件

### AI 能力层

- DashScope Compatible Chat Completions
- DashScope Realtime WebSocket `wss://dashscope.aliyuncs.com/api-ws/v1/realtime`

## 2. 当前的实时语音方案

现在项目统一使用阿里千问 / DashScope：

- `DashScope Realtime`：负责实时语音通话、实时转录、助手音频流式返回
- `DashScope Chat`：负责会后评分、结构化总结、报告生成、非实时补充分析

也就是说，面试房间实时体验由 Realtime 模型承接，而“训练闭环”和“结构化评分”仍然放在现有编排层里。

主链路变成：

`Browser -> WebSocket -> Interview Server -> DashScope Realtime`

同时服务端还能并行触发：

`Interview Server -> DashScope scoring/report pipeline`

这样做的好处是：

- 实时对话延迟更低
- 不破坏你现有的评分/报告架构
- 更适合面试项目里讲“多模型协作”和“多角色编排”
- 以后要替换成别的 Realtime Provider，只需要换 adapter

## 3. 目标模块

### 业务模块

- 主面试官 Agent
- 评分与复盘 Agent
- 简历解析模块
- 岗位 JD 分析模块
- STAR 结构检测模块
- 追问策略模块
- 训练报告生成模块

### 核心页面

- 练习首页
- 面试房间页
- 历史记录页
- 单次报告详情页

## 4. 建议目录

```text
apps/
  web/
    src/
      features/interview/
  server/
    app/
      services/
        interview/
        report/
        qwen/
      schemas/
      core/
    requirements.txt
packages/
  shared/
    src/
docs/
  architecture.md
  api-contract.md
  roadmap.md
.env.example
.gitignore
README.md
```

## 5. 系统主链路

1. 用户上传简历、填写目标岗位 JD。
2. 后端先做简历摘要和 JD 要点抽取。
3. 用户进入面试房间，浏览器采集麦克风音频。
4. 前端通过 WebSocket 推送音频块或结束标记给后端。
5. 后端桥接到 DashScope Realtime 会话，拿到实时转录与流式语音回复。
6. 主面试官通过 Realtime instructions 维持自然面试节奏。
7. 用户回答完成后，评分 Agent 并行产出结构化评分、STAR 检测、关键词覆盖分析。
8. 会后或关键轮次可继续调用 DashScope Chat 生成深度反馈与复盘。
9. 会话结束后生成复盘报告并落库。

## 6. DashScope 接口映射

### 对话模型

- 用途：主面试官提问、动态追问、评分反馈、报告总结
- 接口：`POST /compatible-mode/v1/chat/completions`
- 推荐模型：`qwen-plus` 或你实际使用的千问文本模型

## 7. DashScope Realtime 接入

你提供的示例代码已经被映射成项目里的 Realtime 适配层，关键位置如下：

- `packages/shared/src/interview.ts`
  - 增加了 Realtime 会话配置、音频增量、最终转录、连接状态事件
- `apps/server/app/services/interview/dashscope_realtime_adapter.py`
  - 负责把 DashScope 原始事件映射成项目统一事件
- `apps/server/app/services/interview/realtime_session_service.py`
  - 负责启动、转发、关闭一次实时面试会话
- `apps/server/app/services/interview/interview_orchestrator.py`
  - 负责生成面试场景下的 Realtime session instructions

你给的 Python 示例里最核心的三件事，在项目里分别对应：

- `conv.update_session(...)`
  - 对应 `buildRealtimeBootstrap()` 和 `createSessionInitMessage()`
- `conv.append_audio(...)`
  - 对应客户端 `audio.chunk` 事件和 adapter 的 `forwardAudioChunk()`
- `on_event(response)`
  - 对应 adapter 的 `mapProviderEvent()`

## 8. MVP 优先级

### 第一阶段

- 简历上传
- JD 输入
- 单轮音频转文本
- AI 面试官提问
- 追问生成
- 基础评分面板
- 会后报告
- 最小调试页 `apps/web/demo-client.html`

### 第二阶段

- 中途打断
- 实时分段字幕
- 历史记录回放
- 针对薄弱项生成专项训练

### 第三阶段

- 多岗位模板
- 英语面试模式
- 可视化数据看板
- 外部 MCP 连接器

## 9. 下一步怎么继续

如果你要继续往下做，我建议下一步直接补三件事：

1. 把浏览器录音改成 16k PCM chunk 推流，而不是一次性上传整段。
2. 给 FastAPI WebSocket 加 session 鉴权、断线重连和 Redis 状态同步。
3. 把评分链路放到回答完成后异步执行，再补 PostgreSQL 持久化。

这样最容易快速做出一个能演示的 Demo。
