# 系统架构说明

## 1. 总体分层

### 前端层

- 上传简历与 JD
- 面试房间
- 实时字幕
- 评分面板
- 追问记录
- 报告详情

### 实时通信层

- 浏览器采集麦克风
- WebSocket 上报音频块和控制事件
- 服务端桥接 DashScope Realtime WebSocket
- WebSocket 下发字幕、追问、评分和音频增量结果

### Agent 编排层

- `InterviewerAgent`：负责出题和追问
- `ScoringAgent`：负责结构化评分
- `StrategyEngine`：决定何时追问、何时切题
- `ContextAssembler`：组装简历、JD、历史回答上下文
- `RealtimeSessionService`：负责 Realtime provider 会话生命周期

### 工具层

- `ResumeAnalyzer`
- `JobAnalyzer`
- `StarDetector`
- `AnswerScorer`
- `SpeechMetrics`

### 数据层

- PostgreSQL：用户、会话、题目、回答、评分、报告
- Redis：实时状态、会话缓存、中断标记
- 对象存储：录音文件、TTS 文件、截图

## 2. 推荐服务拆分

### Web App

- 负责页面展示和麦克风采集
- 不直接调用第三方大模型平台
- 所有密钥和 AI 编排都走后端

### Interview API

- 提供 REST 接口
- 提供 WebSocket 实时会话
- 桥接 DashScope Realtime
- 调用 DashScope 文本模型做评分和报告
- 管理评分和报告生成

推荐框架：

- FastAPI
- Python `dashscope` SDK
- asyncio + WebSocket

### Async Worker

- 处理会后报告生成
- 处理长音频转写
- 处理训练建议汇总

## 3. 一次完整会话的数据流

```text
用户上传简历/JD
  -> ResumeAnalyzer / JobAnalyzer
  -> 创建 interview session
  -> 前端进入面试房间
  -> 前端上传音频块
  -> DashScope Realtime 转录与语音回复
  -> 前端播放语音增量并展示字幕
  -> StrategyEngine 判断是否继续追问
  -> ScoringAgent 异步输出分项评分
  -> 会话结束
  -> ReportGenerator 汇总完整复盘报告
```

## 4. 为什么设计成“逻辑多角色”

不一定真的要做多 Agent 运行时，但在项目讲解时，把职责拆成多角色很有优势：

- 更容易解释系统可扩展性
- 更容易描述不同 prompt 的职责边界
- 更容易把“主流程生成”和“结构化评分”分离
- 后续真的上 LangGraph / workflow engine 也方便迁移

## 5. 推荐的 prompt 分工

### 主面试官 Agent

职责：

- 根据岗位方向出题
- 根据上一轮回答做动态追问
- 控制语气更接近真人面试官
- 避免一次输出过长

### 评分 Agent

职责：

- 对回答做结构化打分
- 检测 STAR 是否完整
- 抽取关键词覆盖
- 给出“改进版回答”

### 策略引擎

职责：

- 判断是“继续追问”还是“切下一题”
- 判断某个回答是否偏题
- 判断回答是否过短、过泛、缺少量化结果

## 6. 数据模型建议

### users

- id
- name
- email
- target_role
- created_at

### interview_sessions

- id
- user_id
- resume_id
- jd_id
- status
- started_at
- ended_at
- final_score

### interview_turns

- id
- session_id
- turn_index
- question_text
- answer_text
- follow_up_reason
- duration_ms

### score_cards

- id
- session_id
- turn_id
- completeness_score
- star_score
- job_match_score
- clarity_score
- speech_score
- suggestions_json

### reports

- id
- session_id
- strengths
- weaknesses
- improved_answer
- next_training_plan

## 7. 性能与工程重点

- 浏览器音频最好转成 16k PCM chunk 后再推送给 Realtime provider
- 音频播放建议支持增量 buffer，避免等整段返回
- 评分与主流程可以并行，避免阻塞下一轮问题
- 实时会话状态放 Redis，避免单机内存绑定
- 录音与报告异步落库，保证房间交互更顺畅
