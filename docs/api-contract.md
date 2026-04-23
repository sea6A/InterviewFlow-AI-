# API 与事件协议

## 1. REST API

### `POST /api/v1/resumes/analyze`

用途：

- 上传简历
- 返回结构化简历摘要
- 抽取项目、技能、经历亮点

说明：

- 当前实现使用“原始文件字节流上传”
- 文件名建议通过查询参数 `?filename=` 传递
- 前端应先对原始文件名做 `encodeURIComponent`
- 后端会自动解码；旧的 `X-Filename-Encoded` / `X-Filename` 仍保留兜底
- `Content-Type` 使用浏览器自动附带的文件类型即可
- `txt/md/json` 可直接解析
- `pdf/docx` 需要安装 `pypdf` / `python-docx`

请求体：

```json
{
  "fileUrl": "https://object-storage/resume.pdf"
}
```

响应体：

```json
{
  "resumeProfile": {
    "resume_id": "resume_123",
    "summary": "3 年后端开发经验，熟悉 Java、Spring Boot、Redis、MySQL",
    "strengths": ["高并发", "微服务", "缓存设计"],
    "projects": [
      {
        "name": "智能客服平台",
        "highlights": ["性能优化", "SLA 提升"]
      }
    ]
  },
  "extractedTextPreview": "简历文本预览...",
  "warnings": []
}
```

### `POST /api/v1/jobs/analyze`

用途：

- 输入岗位 JD
- 抽取职责、技能关键词、面试关注点

请求体：

```json
{
  "job_text": "后端开发工程师\n负责核心接口开发..."
}
```

响应体：

```json
{
  "jobProfile": {
    "job_id": "job_123",
    "title": "后端开发工程师",
    "seniority": "junior",
    "keywords": ["Python", "FastAPI", "Redis", "MySQL"],
    "focus_areas": ["项目经验", "技术取舍", "性能优化"]
  },
  "normalizedTextPreview": "JD 文本预览...",
  "warnings": []
}
```

### `POST /api/v1/sessions`

用途：

- 创建一次面试练习 session

### `GET /api/v1/sessions/:sessionId/report`

用途：

- 获取单次练习的复盘报告

## 2. WebSocket

连接地址：

`/ws/interview?sessionId=<id>`

## 3. Client -> Server 事件

### `session.start`

```json
{
  "type": "session.start",
  "sessionId": "sess_001",
  "provider": "dashscope",
  "voice": "Ethan",
  "outputModalities": ["audio", "text"]
}
```

### `audio.chunk`

```json
{
  "type": "audio.chunk",
  "sessionId": "sess_001",
  "chunkId": "chunk_01",
  "mimeType": "audio/pcm",
  "sampleRate": 16000,
  "payloadBase64": "..."
}
```

### `realtime.session.configure`

```json
{
  "type": "realtime.session.configure",
  "sessionId": "sess_001",
  "provider": "dashscope",
  "model": "qwen3.5-omni-plus-realtime",
  "voice": "Ethan",
  "instructions": "你是一位中文 AI 面试官",
  "outputModalities": ["audio", "text"]
}
```

### `answer.commit`

```json
{
  "type": "answer.commit",
  "sessionId": "sess_001",
  "turnId": "turn_003"
}
```

### `image.frame`

```json
{
  "type": "image.frame",
  "sessionId": "sess_001",
  "mimeType": "image/png",
  "imageBase64": "..."
}
```

### `assistant.interrupt`

```json
{
  "type": "assistant.interrupt",
  "sessionId": "sess_001",
  "reason": "candidate_barge_in"
}
```

说明：

- 前端本地会先进入 `possible_interrupt`
- 不会立刻停播 AI
- 等服务端 `semantic_vad` 确认形成新 turn 后，再通过 `interrupt.confirmed` 真正完成打断

## 4. Server -> Client 事件

### `session.connected`

```json
{
  "type": "session.connected",
  "sessionId": "sess_001",
  "provider": "dashscope",
  "phase": "listening"
}
```

### `transcript.partial`

```json
{
  "type": "transcript.partial",
  "sessionId": "sess_001",
  "turnId": "turn_003",
  "text": "我在上一个项目里主要负责"
}
```

### `transcript.final`

```json
{
  "type": "transcript.final",
  "sessionId": "sess_001",
  "turnId": "turn_003",
  "text": "我在上一个项目里主要负责支付链路稳定性优化。"
}
```

### `interviewer.question`

```json
{
  "type": "interviewer.question",
  "sessionId": "sess_001",
  "turnId": "turn_004",
  "text": "如果线上接口超时率突然升高，你会怎么排查？",
  "followUpReason": "候选人刚才提到做过性能优化，但没有说明定位路径和量化指标。"
}
```

### `score.updated`

```json
{
  "type": "score.updated",
  "sessionId": "sess_001",
  "turnId": "turn_003",
  "scoreCard": {
    "completeness": 76,
    "star": 68,
    "jobMatch": 80,
    "clarity": 72,
    "speech": 70,
    "starMissing": ["result", "action"]
  }
}
```

说明：

- `score.updated` 的评分会结合当前问题、简历内容和岗位 JD 一起判断
- `jobMatch` 不再只是看回答本身是否顺畅，也会看是否覆盖岗位关键词、是否与简历经历相互印证
- `starMissing` 用于可视化显示 STAR 哪些部分仍然缺失，帮助用户快速理解该补哪一段

### `turn.feedback.generated`

```json
{
  "type": "turn.feedback.generated",
  "sessionId": "sess_001",
  "turnId": "turn_003",
  "feedback": {
    "summary": "这轮回答基本覆盖了问题核心，但项目结果量化不足。",
    "strengths": ["项目背景说明比较清楚", "能主动提到自己的具体动作"],
    "weakPoints": ["结果没有量化", "岗位关键词覆盖还不够完整"],
    "nextTrainingPlan": ["下一轮重点补结果指标", "练习把 Redis 优化收益讲清楚"],
    "improvedAnswerExample": "当时系统高峰期延迟明显上升，我负责定位瓶颈并引入 Redis 缓存热点数据。优化后接口平均响应时间下降约 35%，峰值错误率也明显回落。"
  }
}
```

- `turn.feedback.generated` 是训练闭环的核心事件，每轮回答结束后都会立即返回
- `summary` 用来快速概括这一轮表现
- `strengths` 和 `weakPoints` 帮助用户理解“哪里做得好、哪里需要补”
- `nextTrainingPlan` 会直接衔接下一轮专项训练建议
- `improvedAnswerExample` 用于给用户一个更接近真实面试场景的参考回答

### `assistant.audio.ready`

```json
{
  "type": "assistant.audio.ready",
  "sessionId": "sess_001",
  "turnId": "turn_004",
  "audioUrl": "https://object-storage/tts/turn_004.mp3"
}
```

### `assistant.audio.delta`

```json
{
  "type": "assistant.audio.delta",
  "sessionId": "sess_001",
  "turnId": "turn_004",
  "deltaBase64": "..."
}
```

### `assistant.transcript.done`

```json
{
  "type": "assistant.transcript.done",
  "sessionId": "sess_001",
  "turnId": "turn_004",
  "text": "你刚才提到压测前后延迟变化，能再说说你做了哪些关键优化吗？"
}
```

### `room.phase.changed`

```json
{
  "type": "room.phase.changed",
  "sessionId": "sess_001",
  "phase": "thinking"
}
```

### `interrupt.confirmed`

```json
{
  "type": "interrupt.confirmed",
  "sessionId": "sess_001",
  "source": "semantic_vad",
  "message": "semantic_vad 已确认用户开启了新的有效轮次，已中断当前 AI 回复。"
}
```

### `provider.error`

```json
{
  "type": "provider.error",
  "sessionId": "sess_001",
  "message": "DashScope API Key 缺失",
  "retryable": false
}
```

### `context.image.received`

```json
{
  "type": "context.image.received",
  "sessionId": "sess_001",
  "message": "已收到图片上下文，后续提问会结合图片内容。"
}
```

### `report.ready`

```json
{
  "type": "report.ready",
  "sessionId": "sess_001",
  "reportId": "rep_001"
}
```
