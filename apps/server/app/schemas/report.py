from pydantic import BaseModel, Field


class TurnFeedback(BaseModel):
    """
    单轮回答后的即时训练反馈。

    这份对象和 SessionReport 的区别是：
    - SessionReport：整场面试结束后的总复盘
    - TurnFeedback：每一轮回答结束后的“小复盘”
    """

    turn_id: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    next_training_plan: list[str] = Field(default_factory=list)
    improved_answer_example: str


class SessionReport(BaseModel):
    report_id: str
    session_id: str
    overall_score: int
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)
    improved_answer_example: str
    next_training_plan: list[str] = Field(default_factory=list)
