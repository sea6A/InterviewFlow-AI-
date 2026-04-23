# Web 模块说明

推荐用 Next.js 实现三个主要页面：

- `/`：上传简历、输入目标岗位、开始练习
- `/interview/[sessionId]`：实时面试房间
- `/reports/[reportId]`：复盘报告页

## 前端重点

- 录音权限处理
- WebSocket 重连
- TTS 播放队列
- 中断状态管理
- 字幕与评分的低延迟刷新

## 当前调试页

- `apps/web/demo-client.html` 已支持：
- 创建会话
- 建立 WebSocket
- 麦克风采集
- 16k PCM 音频推流
- `answer.commit`
- `assistant.interrupt`
- 助手音频分片播放

## 当前正式静态页

- `apps/web/index.html`：项目入口页，负责创建会话并跳转
- `apps/web/interview.html`：正式面试房间页
- `apps/web/assets/landing.js`：入口页逻辑
- `apps/web/assets/interview-room.js`：房间页逻辑
- `apps/web/assets/app.css`：共享样式
