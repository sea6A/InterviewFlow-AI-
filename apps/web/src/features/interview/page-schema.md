# 面试房间页面草图

## 页面布局

### 左侧主区域

- 当前题目卡片
- 实时字幕
- Realtime 连接状态
- 面试官追问记录

### 右侧辅助区域

- 评分面板
- STAR 检测
- 岗位关键词覆盖
- 语速与停顿统计

### 底部操作区

- 开始录音
- 结束回答
- 打断 AI
- 重连 Realtime
- 重播问题
- 结束面试

## 页面状态

- `idle`
- `connecting`
- `recording`
- `transcribing`
- `thinking`
- `speaking`
- `finished`

## 页面展示重点

- 当前状态必须显眼，方便演示
- 要区分“浏览器正在录音”和“DashScope Realtime 已连上”
- 每轮问题和追问要卡片化展示
- 分数不只显示总分，要显示分维度得分
- 会后报告入口要明显

## Realtime 接入说明

- 浏览器负责采集 16k PCM 音频
- 前端通过 WebSocket 把 base64 音频块传给本项目后端
- 后端再桥接到 DashScope Realtime WebSocket
- DashScope 返回：
  - 用户输入转录完成事件
  - 助手音频增量事件
  - 助手文本转录完成事件
- 本项目前端继续消费统一后的 `ServerRealtimeEvent`
