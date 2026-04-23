# InterviewFlow AI

InterviewFlow AI 是一个面向求职训练场景的 AI 实时语音面试平台。项目围绕“实时语音交互、可打断语音 Agent、动态追问、多维度回答评估、训练闭环”展开，打通了简历解析、JD 分析、实时面试、逐轮反馈和会后复盘这条完整链路。

当前仓库是一个可运行的 MVP：后端使用 FastAPI + WebSocket，前端使用静态 HTML/CSS/JavaScript 页面；实时语音链路由 DashScope Realtime 承担，结构化分析、评分和报告生成由 DashScope 文本模型完成。

## 项目亮点

- 实时语音面试：浏览器采集麦克风音频并流式上传，服务端桥接 DashScope Realtime，返回实时转录与流式语音回复。
- 可打断语音 Agent：支持用户插话，结合前端本地检测与服务端 `semantic_vad` 确认实现更自然的打断体验。
- 动态追问机制：先分析回答质量，再根据 STAR 缺失项、关键词覆盖度、量化缺失、个人贡献不足等问题生成下一轮追问。
- 多维度回答评估：从完整度、STAR、岗位匹配度、表达清晰度、语音表现等多个维度给出评分与建议。
- 训练闭环：每轮回答后生成即时反馈，整场结束后生成完整复盘报告。
- 多模态扩展：支持在面试过程中追加图片上下文，增强问题理解和问答场景表达。

## 项目流程

1. 上传简历并抽取结构化候选人画像。
2. 输入目标岗位 JD 并提取岗位关键词与考察重点。
3. 创建面试 Session，将简历画像与岗位画像作为上下文注入。
4. 进入 WebSocket 面试房间，开始实时语音问答。
5. AI 面试官基于当前轮次回答进行动态追问。
6. 系统逐轮输出评分卡、薄弱点和训练建议。
7. 面试结束后生成复盘报告，形成训练闭环。

## 当前实现范围

当前仓库已经包含：

- 简历解析接口
- JD 分析接口
- Session 创建与查询接口
- 实时语音面试 WebSocket 房间
- DashScope Realtime 适配层
- 动态追问编排器
- 逐轮反馈与最终报告生成
- 首页与 Interview 房间 UI

当前仍属于 MVP，暂未完整落地：

- PostgreSQL 持久化
- Redis Session 管理
- 完整 React / Next.js 前端
- 自动化测试与 CI

因此，这个仓库更适合作为“可演示、可扩展的 AI 面试训练原型系统”来看待。

## 核心架构

实时交互链路：

```text
Browser
  -> FastAPI WebSocket
  -> DashScope Realtime
  -> 服务端事件映射
  -> Browser UI
```

训练分析链路：

```text
Resume / JD 输入
  -> ProfileAnalysisService
  -> Structured Profiles
  -> InterviewOrchestrator
  -> ReportGenerator
  -> Turn Feedback / Final Report
```

### 核心模块

- `apps/server/app/main.py`
  FastAPI 入口，负责 REST API、WebSocket 房间、Session 生命周期管理。
- `apps/server/app/services/intake/document_text_extractor.py`
  提取 `txt`、`md`、`json`、`pdf`、`docx` 等格式文本。
- `apps/server/app/services/intake/profile_analysis_service.py`
  将简历与 JD 转换为结构化画像。
- `apps/server/app/services/interview/dashscope_realtime_adapter.py`
  负责前端事件与 DashScope Realtime 事件之间的双向映射。
- `apps/server/app/services/interview/realtime_session_service.py`
  负责实时会话启动、转发、关闭与房间内事件协调。
- `apps/server/app/services/interview/interview_orchestrator.py`
  负责回答分析、追问策略选择和下一轮问题生成。
- `apps/server/app/services/report/report_generator.py`
  负责逐轮反馈与最终报告生成。
- `apps/server/app/services/qwen/dashscope_client.py`
  DashScope 文本能力统一封装。

### 前端页面

- `apps/web/index.html`
  首页，负责简历上传、JD 输入和 Session 创建。
- `apps/web/interview.html`
  面试房间，负责音频采集、状态展示、实时转录、评分与反馈展示。
- `apps/web/demo-client.html`
  调试页面，用于快速验证 WebSocket 和实时语音链路。

## 技术栈

### 后端

- Python
- FastAPI
- WebSocket / asyncio
- Pydantic / pydantic-settings
- DashScope SDK

### 前端

- HTML
- CSS
- JavaScript
- Web Audio API

### AI 能力

- DashScope Realtime
- DashScope Chat Models

## 目录结构

```text
apps/
  server/
    app/
      core/
      schemas/
      services/
        intake/
        interview/
        qwen/
        report/
    requirements.txt
  web/
    assets/
    src/
    index.html
    interview.html
    demo-client.html
docs/
  architecture.md
  api-contract.md
  roadmap.md
  interview-platform-qa.md
packages/
  shared/
    src/
.env.example
README.md
```

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/sea6A/InterviewFlow-AI-.git
cd InterviewFlow-AI-
```

### 2. 配置环境变量

将 `.env.example` 复制为 `.env`，并填写你的 DashScope API Key。

Linux / macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

至少需要配置：

- `DASHSCOPE_API_KEY`

常用本地默认值：

- `APP_HOST=0.0.0.0`
- `APP_PORT=3001`
- `APP_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,null`

### 3. 安装后端依赖

```bash
cd apps/server
pip install -r requirements.txt
```

### 4. 启动后端服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 3001
```

### 5. 打开前端页面

当前前端是静态页面，可以直接打开或用任意静态服务器启动：

- `apps/web/index.html`
- `apps/web/interview.html`
- `apps/web/demo-client.html`

如果前端运行在其他端口，请确保它已经被加入 `APP_ALLOWED_ORIGINS`。

## 主要接口

### REST API

- `POST /api/v1/resumes/analyze`
- `POST /api/v1/jobs/analyze`
- `POST /api/v1/sessions`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/report`

### WebSocket

- `GET /ws/interview/{session_id}`

更完整的请求和事件契约见 [docs/api-contract.md](docs/api-contract.md)。

## 这个项目的价值

这个项目并不是“给聊天机器人接一个麦克风”这么简单。它真正有意思的地方在于把两条链路拆开了：

- Realtime 链路负责低延迟语音交互
- Analysis 链路负责结构化分析、评分和训练反馈

这样做的好处是：

- 实时体验和深度分析可以分别优化
- 追问策略更可控，不只是简单续写
- 项目具备继续扩展到持久化、报告面板、多模态训练和更多 Provider 的空间

同时，这个系统形成了一个更像真实面试训练的循环：

- 提问
- 回答
- 分析回答
- 发现缺口
- 生成追问
- 给出反馈
- 汇总复盘

## 后续方向

项目后续可以继续扩展：

- Redis + PostgreSQL 持久化
- 面试历史与报告看板
- 更强的移动端适配
- 更完整的多模态上下文输入
- 更多可替换的实时语音 Provider 适配器
- 自动化测试与 CI/CD

详细规划见 [docs/roadmap.md](docs/roadmap.md)。

## 文档入口

- [docs/architecture.md](docs/architecture.md)：系统架构与模块拆分
- [docs/api-contract.md](docs/api-contract.md)：REST 与 WebSocket 协议说明
- [docs/roadmap.md](docs/roadmap.md)：后续迭代路线
- [docs/interview-platform-qa.md](docs/interview-platform-qa.md)：项目问答集，适合答辩和面试准备

## 说明

- 当前前端是静态 MVP，不是完整的 React / Next.js 工程。
- 当前 Session 状态保存在内存中，适合 Demo 和原型验证。
- 所有密钥请通过 `.env` 注入，不要直接写入源码。

## License

本项目采用 [MIT License](LICENSE)。
