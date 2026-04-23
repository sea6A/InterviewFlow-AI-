"""
训练反馈与会后复盘生成器。

这个模块现在负责两类输出：
1. `generate_turn_feedback()`：每轮回答结束后的即时训练反馈
2. `generate()`：整场面试结束后的总复盘

这样项目就不再只是“一次性对话”，而是形成持续训练闭环：
- 每轮有反馈
- 每轮有薄弱点
- 每轮有下一步训练建议
- 会后还有总报告
"""

import json
import re

from app.schemas.interview import InterviewSessionSnapshot, InterviewTurn
from app.schemas.report import SessionReport, TurnFeedback
from app.services.qwen.dashscope_client import DashScopeClient


class ReportGenerator:
    """
    训练反馈与复盘生成器。
    """

    def __init__(self, ai_client: DashScopeClient) -> None:
        self.ai_client = ai_client

    async def generate_turn_feedback(
        self,
        session: InterviewSessionSnapshot,
        turn: InterviewTurn,
    ) -> TurnFeedback:
        """
        生成单轮即时训练反馈。

        这是“训练闭环”的核心方法之一：
        - 用户刚答完
        - 系统已经拿到了评分
        - 这里再进一步生成“人能直接拿来练”的反馈
        """

        score_snapshot = {
            "completeness": turn.score_card.completeness if turn.score_card else None,
            "star": turn.score_card.star if turn.score_card else None,
            "jobMatch": turn.score_card.job_match if turn.score_card else None,
            "clarity": turn.score_card.clarity if turn.score_card else None,
            "speech": turn.score_card.speech if turn.score_card else None,
            "starMissing": turn.score_card.star_missing if turn.score_card else [],
            "summary": turn.score_card.summary if turn.score_card else "",
            "improvementTips": turn.score_card.improvement_tips if turn.score_card else [],
        }

        prompt = "\n".join(
            [
                "你是一名中文面试训练教练。",
                "请基于候选人的本轮问题、回答、评分结果、简历和岗位 JD，生成一份简洁但有训练价值的单轮复盘。",
                "你的输出必须帮助候选人马上知道：",
                "1. 这轮答得好的地方",
                "2. 最主要的薄弱点",
                "3. 下一轮专项训练该怎么练",
                "4. 如果重答一次，应该怎么答得更好",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                'JSON 格式必须包含：{"summary":"一句话复盘","strengths":["优点1","优点2"],"weakPoints":["薄弱点1","薄弱点2"],"nextTrainingPlan":["训练建议1","训练建议2","训练建议3"],"improvedAnswerExample":"一段改进版回答"}',
            ]
        )

        turn_payload = {
            "question": turn.question,
            "answer": turn.answer,
            "followUpReason": turn.follow_up_reason,
            "scoreCard": score_snapshot,
            "resumeProfile": session.resume_profile.model_dump(mode="json") if session.resume_profile else None,
            "jobProfile": session.job_profile.model_dump(mode="json") if session.job_profile else None,
        }

        raw_feedback = await self.ai_client.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(turn_payload, ensure_ascii=False)},
            ]
        )

        parsed = self._try_parse_json_object(raw_feedback)
        if parsed:
            return TurnFeedback(
                turn_id=turn.turn_id,
                summary=str(parsed.get("summary", "本轮回答已完成，建议继续针对薄弱点做专项训练。")).strip()
                or "本轮回答已完成，建议继续针对薄弱点做专项训练。",
                strengths=[str(item).strip() for item in parsed.get("strengths", []) if str(item).strip()][:4]
                or ["回答已经提供了部分有效信息。"],
                weak_points=[str(item).strip() for item in parsed.get("weakPoints", parsed.get("weak_points", [])) if str(item).strip()][:4]
                or ["回答还可以进一步补充关键细节。"],
                next_training_plan=[
                    str(item).strip()
                    for item in parsed.get("nextTrainingPlan", parsed.get("next_training_plan", []))
                    if str(item).strip()
                ][:4]
                or ["围绕当前问题继续补充量化结果、技术细节和个人贡献。"],
                improved_answer_example=str(
                    parsed.get("improvedAnswerExample", parsed.get("improved_answer_example", raw_feedback))
                ).strip()
                or raw_feedback,
            )

        return TurnFeedback(
            turn_id=turn.turn_id,
            summary="本轮回答已完成，建议继续针对薄弱点做专项训练。",
            strengths=["回答已经提供了部分有效信息。"],
            weak_points=["回答还可以进一步补充关键细节。"],
            next_training_plan=["围绕当前问题继续补充量化结果、技术细节和个人贡献。"],
            improved_answer_example=raw_feedback,
        )

    async def generate(self, session: InterviewSessionSnapshot) -> SessionReport:
        """
        生成整场会话的总复盘。
        """

        prompt = "\n".join(
            [
                "你是一名中文面试复盘助手。",
                "请基于候选人简历、目标岗位 JD 和完整面试记录，生成结构化复盘报告。",
                "你的分析必须回答这些问题：",
                "1. 候选人的优势是否真的贴合目标岗位",
                "2. 回答里有哪些信息与简历经历能互相印证",
                "3. 哪些岗位关键词覆盖不足或表达不够有说服力",
                "4. 下一轮训练应该优先补什么",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                'JSON 格式必须包含：{"overallScore":80,"strengths":["优点1","优点2"],"weaknesses":["不足1","不足2"],"followUpSuggestions":["建议1","建议2"],"improvedAnswerExample":"一段改进版回答","nextTrainingPlan":["训练1","训练2","训练3"]}',
            ]
        )

        summary = await self.ai_client.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": session.model_dump_json()},
            ]
        )

        parsed = self._try_parse_json_object(summary)
        if parsed:
            return SessionReport(
                report_id=f"report_{session.session_id}",
                session_id=session.session_id,
                overall_score=int(parsed.get("overallScore", parsed.get("overall_score", 78))),
                strengths=[str(item) for item in parsed.get("strengths", [])][:4]
                or ["回答表达自然，基础沟通感较好。"],
                weaknesses=[str(item) for item in parsed.get("weaknesses", [])][:4]
                or ["岗位关键词覆盖仍不够集中。"],
                follow_up_suggestions=[
                    str(item) for item in parsed.get("followUpSuggestions", parsed.get("follow_up_suggestions", []))
                ][:4]
                or ["继续围绕项目细节、指标结果和个人贡献做追问训练。"],
                improved_answer_example=str(
                    parsed.get("improvedAnswerExample", parsed.get("improved_answer_example", summary))
                ).strip()
                or summary,
                next_training_plan=[
                    str(item) for item in parsed.get("nextTrainingPlan", parsed.get("next_training_plan", []))
                ][:4]
                or [
                    "专项训练：项目背景与业务目标表述",
                    "专项训练：技术取舍与性能优化案例",
                    "专项训练：围绕 JD 关键词做针对性表达",
                ],
            )

        return SessionReport(
            report_id=f"report_{session.session_id}",
            session_id=session.session_id,
            overall_score=78,
            strengths=["回答表达自然，基础沟通感较好。"],
            weaknesses=["岗位关键词覆盖仍不够集中。"],
            follow_up_suggestions=["继续围绕项目细节、指标结果和个人贡献做追问训练。"],
            improved_answer_example=summary,
            next_training_plan=[
                "专项训练：项目背景与业务目标表述",
                "专项训练：技术取舍与性能优化案例",
                "专项训练：围绕 JD 关键词做针对性表达",
            ],
        )

    def _try_parse_json_object(self, raw_text: str) -> dict:
        """
        从模型输出中提取 JSON 对象。
        """

        try:
            parsed = json.loads(raw_text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_text, re.S)
            if not match:
                return {}

            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
