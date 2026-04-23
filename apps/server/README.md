# Server 模块说明

服务端 Python + FastAPI，更贴近千问 Realtime Python 示例，也更方便直接接 `dashscope` SDK。

## 推荐目录

- `app/main.py`：FastAPI 入口，提供 REST 和 WebSocket
- `app/services/interview`：面试主流程与 Realtime 会话桥接
- `app/services/report`：复盘报告生成
- `app/services/qwen`：阿里千问 / DashScope 文本模型适配层
- `app/schemas`：Pydantic 数据模型
- `app/core/config.py`：环境变量配置

## 关键原则

- 前端永远不直连 DashScope
- 所有 prompt 和模型切换都在服务端管理
- Realtime 会话通过服务端桥接，便于鉴权、日志和状态管理
- 评分和报告尽量异步执行

## 启动方式

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 3001
```

## 本地调试建议

- 先复制项目根目录的 `.env.example` 为 `.env`
- 把 `DASHSCOPE_API_KEY` 改成你自己的 Key
- 浏览器可先直接打开 `apps/web/demo-client.html`
- 如果前端端口不是 `3000`，记得同步修改 `APP_ALLOWED_ORIGINS`
