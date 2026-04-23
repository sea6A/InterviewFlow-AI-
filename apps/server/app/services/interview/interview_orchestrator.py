"""
面试编排器：整场 AI 面试的“业务大脑”。

这版实现的重点是“两阶段动态追问”：
1. 先分析用户上一轮回答，得到结构化缺口分析
2. 再根据缺口选择追问策略，并生成下一轮问题

这样就不是“回答 -> 直接问下一题”的黑盒过程，
而是更接近真实面试官的半结构化追问：
- 先判断你有没有答到点上
- 再判断你缺的是关键词、STAR、量化结果还是技术细节
- 最后围绕缺口继续追问
"""

from dataclasses import dataclass
import json
import re

from app.schemas.interview import (
    InterviewSessionSnapshot,
    InterviewTurn,
    RealtimeProvider,
    RealtimeSessionBootstrap,
    ScoreCard,
)
from app.services.qwen.dashscope_client import DashScopeClient


@dataclass
class AnswerAnalysis:
    """
    用户单轮回答的结构化分析结果。

    这是“两阶段动态追问”的第一阶段输出。
    有了这份分析，第二阶段才能更稳定地做策略分流。
    """

    answered_question: bool
    completeness_level: str
    keyword_covered: list[str]
    keyword_missing: list[str]
    star_missing: list[str]
    risk_flags: list[str]
    evidence_strength: str
    next_focus: str
    suggested_strategy: str
    analysis_summary: str


class InterviewOrchestrator:
    """
    面试编排器。

    对外最重要的方法还是 `handle_candidate_answer()`，
    但内部已经升级为两阶段：

    - 第一阶段：分析回答
    - 第二阶段：按策略生成追问
    """

    def __init__(
        self,
        ai_client: DashScopeClient,
        realtime_model: str,
        realtime_voice: str,
    ) -> None:
        self.ai_client = ai_client
        self.realtime_model = realtime_model
        self.realtime_voice = realtime_voice

    def build_realtime_bootstrap(
        self,
        session: InterviewSessionSnapshot,
    ) -> RealtimeSessionBootstrap:
        """
        为整场 Realtime 会话生成长期系统设定。
        """

        return RealtimeSessionBootstrap(
            provider=RealtimeProvider.DASHSCOPE,
            model=self.realtime_model,
            voice=self.realtime_voice,
            output_modalities=["audio", "text"],
            instructions="\n".join(
                [
                    "你是一位专业、自然、略带鼓励感的中文 AI 面试官。",
                    "你的任务不是闲聊，而是围绕候选人的简历、目标岗位和实时回答做结构化追问。",
                    "你需要根据候选人回答是否完整、是否覆盖岗位关键词、是否有 STAR 结构来动态决定下一轮追问。",
                    "如果回答空泛，请继续追问背景、动作、技术取舍、量化结果和复盘。",
                    "每次回复尽量控制在一到两句话，像真实面试官，不要长篇讲解。",
                    self._build_context_block(session),
                ]
            ),
        )

    def build_opening_prompt(self, session: InterviewSessionSnapshot) -> str:
        """
        生成第一轮问题。
        """

        return "\n".join(
            [
                "请作为中文技术面试官开始第一轮面试。",
                self._build_context_block(session),
                "先给出一句自然的欢迎语，然后提出第一道问题。",
                "第一题优先从候选人简历中最相关的项目经历切入，并和岗位 JD 重点能力建立联系。",
                "如果简历信息较少，可以问自我介绍，但要尽量引导候选人往岗位相关经历上展开。",
                "总长度控制在两句话内。",
            ]
        )

    async def handle_candidate_answer(
        self,
        session: InterviewSessionSnapshot,
        candidate_answer: str,
    ) -> tuple[InterviewTurn, ScoreCard]:
        """
        处理用户本轮回答。

        这一步现在的真实流程是：
        1. 并行生成“结构化分析”和“评分”
        2. 根据分析结果选追问策略
        3. 再生成下一轮问题
        """

        analysis_prompt = self._build_answer_analysis_prompt(session, candidate_answer)
        scorer_prompt = self._build_scorer_prompt(session, candidate_answer)

        analysis_raw_text, score_raw_text = await self._gather_analysis_and_score(
            analysis_prompt,
            scorer_prompt,
            candidate_answer,
        )

        analysis = self._parse_answer_analysis(analysis_raw_text)
        score_card = self._parse_score_card(score_raw_text)
        score_card.star_missing = analysis.star_missing

        strategy_name, strategy_reason = self._select_follow_up_strategy(analysis)
        follow_up_generation_prompt = self._build_follow_up_generation_prompt(
            session=session,
            answer=candidate_answer,
            analysis=analysis,
            strategy_name=strategy_name,
            strategy_reason=strategy_reason,
        )

        follow_up_raw_text = await self.ai_client.chat(
            [
                {"role": "system", "content": follow_up_generation_prompt},
                {"role": "user", "content": candidate_answer},
            ]
        )

        follow_up_question, model_follow_up_reason = self._parse_follow_up(follow_up_raw_text)
        combined_reason = model_follow_up_reason or strategy_reason
        if model_follow_up_reason and model_follow_up_reason != strategy_reason:
            combined_reason = f"{strategy_reason}；{model_follow_up_reason}"

        next_turn = InterviewTurn(
            turn_id=f"turn_{len(session.turns) + 1}",
            turn_index=len(session.turns) + 1,
            question=follow_up_question,
            follow_up_reason=combined_reason,
        )
        return next_turn, score_card

    async def _gather_analysis_and_score(
        self,
        analysis_prompt: str,
        scorer_prompt: str,
        candidate_answer: str,
    ) -> tuple[str, str]:
        """
        并行生成：
        - 第一阶段的结构化分析
        - 当前轮的评分结果
        """

        import asyncio

        analysis_task = self.ai_client.chat(
            [
                {"role": "system", "content": analysis_prompt},
                {"role": "user", "content": candidate_answer},
            ]
        )
        score_task = self.ai_client.chat(
            [
                {"role": "system", "content": scorer_prompt},
                {"role": "user", "content": candidate_answer},
            ]
        )
        return await asyncio.gather(analysis_task, score_task)

    def _build_answer_analysis_prompt(
        self,
        session: InterviewSessionSnapshot,
        answer: str,
    ) -> str:
        """
        第一阶段：分析用户回答。

        这一步不直接让模型问下一题，而是先要求它返回结构化分析。
        """

        current_question = self._get_current_question(session)
        recent_turns = self._format_recent_turns(session)
        keywords = session.job_profile.keywords if session.job_profile else []
        keyword_hint = "、".join(keywords) if keywords else "暂无岗位关键词"

        return "\n".join(
            [
                "你是一名技术面试回答分析助手。",
                "请先分析候选人的回答质量，再为下一轮追问提供结构化依据。",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                self._build_context_block(session),
                f"当前问题：{current_question}",
                f"候选人的本轮回答：{answer}",
                f"最近轮次摘要：\n{recent_turns}",
                f"本轮重点关注的岗位关键词：{keyword_hint}",
                "请判断：",
                "1. 是否真的回答了当前问题",
                "2. 回答完整度处于 low / medium / high 哪个级别",
                "3. 已覆盖了哪些岗位关键词，缺了哪些岗位关键词",
                "4. STAR 结构里缺少哪些部分，可选值只用 situation/task/action/result",
                "5. 风险点有哪些，比如空泛、缺少量化、缺少个人贡献、与简历不够一致",
                "6. 下一轮最该补的焦点是什么",
                "7. 更适合采用哪类追问策略",
                'JSON 格式必须包含：{"answeredQuestion":true,"completenessLevel":"medium","keywordCovered":["Redis"],"keywordMissing":["微服务"],"starMissing":["result"],"riskFlags":["结果不够量化"],"evidenceStrength":"medium","nextFocus":"补充性能优化后的量化结果","suggestedStrategy":"ask_for_metrics","analysisSummary":"候选人基本答到了题目，但量化结果和岗位关键词覆盖仍不足"}',
            ]
        )

    def _build_follow_up_generation_prompt(
        self,
        session: InterviewSessionSnapshot,
        answer: str,
        analysis: AnswerAnalysis,
        strategy_name: str,
        strategy_reason: str,
    ) -> str:
        """
        第二阶段：根据分析结果和追问策略生成下一轮问题。

        注意这里和旧版的区别：
        - 旧版：直接从回答生成下一题
        - 新版：先带上“分析结果 + 已选策略”，再让模型生成下一题
        """

        current_question = self._get_current_question(session)
        recent_turns = self._format_recent_turns(session)
        analysis_snapshot = self._format_analysis_snapshot(analysis)

        return "\n".join(
            [
                "你是一位专业但自然的中文技术面试官。",
                "现在你已经拿到了上一轮回答的结构化分析结果，请根据分析结果生成下一轮追问。",
                self._build_context_block(session),
                f"当前问题：{current_question}",
                f"候选人的本轮回答：{answer}",
                f"最近轮次摘要：\n{recent_turns}",
                f"第一阶段分析结果：\n{analysis_snapshot}",
                f"已选择的追问策略：{strategy_name}",
                f"选择这项策略的原因：{strategy_reason}",
                "请确保下一轮问题满足：",
                "1. 只问一个问题",
                "2. 问题短、准、像真实面试官",
                "3. 问题必须紧贴当前回答缺口，而不是突然跳题",
                "4. 如果策略是 ask_for_metrics，就重点追问结果和指标",
                "5. 如果策略是 ask_for_keyword_gap，就重点追问岗位关键词覆盖不足的能力",
                "6. 如果策略是 ask_for_personal_contribution，就重点追问个人动作与技术决策",
                "7. 如果策略是 clarify_original_question，就回到原问题核心",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                'JSON 格式必须是：{"question":"下一轮追问","followUpReason":"为什么要追问这一点"}',
            ]
        )

    def _build_scorer_prompt(
        self,
        session: InterviewSessionSnapshot,
        answer: str,
    ) -> str:
        """
        评分 prompt。

        评分仍然单独保留，因为它和“动态追问分析”是两个目标：
        - 分析是为了决定下一题
        - 评分是为了反馈与报告
        """

        current_question = self._get_current_question(session)
        recent_turns = self._format_recent_turns(session)
        return "\n".join(
            [
                "你是一名面试评分助手。",
                "请对候选人的本轮回答做上下文化分析，不要脱离简历和岗位单独评分。",
                "评分时必须结合四个参考系：",
                "1. 当前问题问的是什么",
                "2. 候选人的简历背景是否支持这份回答",
                "3. 目标岗位 JD 关键能力是否被覆盖",
                "4. 回答本身是否完整、清晰、结构化",
                self._build_context_block(session),
                f"当前问题：{current_question}",
                f"候选人的本轮回答：{answer}",
                f"最近轮次摘要：\n{recent_turns}",
                "请从 completeness、star、jobMatch、clarity、speech 五个维度给出 0-100 分。",
                "其中 jobMatch 需要特别考虑岗位关键词覆盖度、技术栈对齐度、资历匹配度。",
                "如果回答和简历存在轻微不一致，summary 或 improvementTips 要明确指出需要补充或澄清。",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                'JSON 格式必须包含：{"completeness":80,"star":75,"jobMatch":78,"clarity":74,"speech":72,"summary":"一句中文总结","improvementTips":["建议1","建议2","建议3"]}',
            ]
        )

    def _select_follow_up_strategy(self, analysis: AnswerAnalysis) -> tuple[str, str]:
        """
        根据第一阶段分析结果做“策略分流”。

        这里是半结构化面试的关键：
        不是让模型随便问，而是先明确当前更适合哪类追问。
        """

        if not analysis.answered_question:
            return "clarify_original_question", "候选人还没有正面回答当前问题，需要先拉回题干核心。"

        if "result" in analysis.star_missing or any("量化" in flag or "结果" in flag for flag in analysis.risk_flags):
            return "ask_for_metrics", "回答缺少量化结果或最终产出，需要继续追问指标与结果。"

        if "action" in analysis.star_missing or any("个人贡献" in flag or "个人动作" in flag for flag in analysis.risk_flags):
            return "ask_for_personal_contribution", "回答里个人动作和决策不够明确，需要追问你具体做了什么。"

        if analysis.keyword_missing:
            return "ask_for_keyword_gap", f"岗位关键词仍有缺口，优先补足：{'、'.join(analysis.keyword_missing[:3])}。"

        if analysis.completeness_level == "low" or any("空泛" in flag or "细节不足" in flag for flag in analysis.risk_flags):
            return "ask_for_technical_detail", "回答仍然偏空泛，需要继续追问技术细节和具体过程。"

        return "deepen_success_case", "当前回答基本完整，下一轮可以继续往更深的技术细节或复盘层面追问。"

    def _build_context_block(self, session: InterviewSessionSnapshot) -> str:
        """
        统一构造“简历 + JD”上下文块。
        """

        return "\n".join(
            [
                self._format_resume_context(session),
                self._format_job_context(session),
            ]
        )

    def _format_resume_context(self, session: InterviewSessionSnapshot) -> str:
        if session.resume_profile is None:
            return "候选人简历：暂无简历信息。"

        strengths = "、".join(session.resume_profile.strengths) or "暂无明确优势标签"
        project_lines: list[str] = []
        for project in session.resume_profile.projects[:3]:
            highlights = "、".join(project.highlights) or "暂无项目亮点"
            project_lines.append(f"- {project.name}：{highlights}")

        projects_block = "\n".join(project_lines) if project_lines else "- 暂无项目记录"
        return "\n".join(
            [
                "候选人简历上下文：",
                f"简历摘要：{session.resume_profile.summary}",
                f"候选人优势标签：{strengths}",
                f"核心项目：\n{projects_block}",
            ]
        )

    def _format_job_context(self, session: InterviewSessionSnapshot) -> str:
        if session.job_profile is None:
            return "目标岗位 JD：暂无岗位信息。"

        keywords = "、".join(session.job_profile.keywords) or "暂无关键词"
        focus_areas = "、".join(session.job_profile.focus_areas) or "暂无重点关注项"
        return "\n".join(
            [
                "目标岗位 JD 上下文：",
                f"岗位名称：{session.job_profile.title}",
                f"职级要求：{session.job_profile.seniority}",
                f"岗位关键词：{keywords}",
                f"面试关注点：{focus_areas}",
            ]
        )

    def _get_current_question(self, session: InterviewSessionSnapshot) -> str:
        if session.current_turn and session.current_turn.question.strip():
            return session.current_turn.question.strip()
        return "暂无明确问题，请按岗位相关度理解为当前正在考察候选人最相关的项目能力。"

    def _format_recent_turns(self, session: InterviewSessionSnapshot, limit: int = 3) -> str:
        if not session.turns:
            return "- 暂无历史轮次"

        lines: list[str] = []
        for turn in session.turns[-limit:]:
            answer_text = turn.answer or "候选人尚未回答"
            lines.append(
                "\n".join(
                    [
                        f"- 第 {turn.turn_index} 轮",
                        f"  问题：{turn.question}",
                        f"  回答：{answer_text}",
                    ]
                )
            )
        return "\n".join(lines)

    def _format_analysis_snapshot(self, analysis: AnswerAnalysis) -> str:
        """
        把第一阶段分析结果转成易读文本，给第二阶段 prompt 使用。
        """

        return "\n".join(
            [
                f"- answeredQuestion: {analysis.answered_question}",
                f"- completenessLevel: {analysis.completeness_level}",
                f"- keywordCovered: {'、'.join(analysis.keyword_covered) or '无'}",
                f"- keywordMissing: {'、'.join(analysis.keyword_missing) or '无'}",
                f"- starMissing: {'、'.join(analysis.star_missing) or '无'}",
                f"- riskFlags: {'、'.join(analysis.risk_flags) or '无'}",
                f"- evidenceStrength: {analysis.evidence_strength}",
                f"- nextFocus: {analysis.next_focus}",
                f"- suggestedStrategy: {analysis.suggested_strategy}",
                f"- analysisSummary: {analysis.analysis_summary}",
            ]
        )

    def _parse_answer_analysis(self, raw_text: str) -> AnswerAnalysis:
        """
        解析第一阶段分析结果。
        """

        parsed = self._try_parse_json_object(raw_text)

        if parsed:
            answered_question = bool(parsed.get("answeredQuestion", parsed.get("answered_question", True)))
            completeness_level = str(parsed.get("completenessLevel", parsed.get("completeness_level", "medium"))).strip().lower()
            if completeness_level not in {"low", "medium", "high"}:
                completeness_level = "medium"

            star_missing = [
                str(item).strip().lower()
                for item in parsed.get("starMissing", parsed.get("star_missing", []))
                if str(item).strip()
            ]
            star_missing = [item for item in star_missing if item in {"situation", "task", "action", "result"}]

            return AnswerAnalysis(
                answered_question=answered_question,
                completeness_level=completeness_level,
                keyword_covered=[
                    str(item).strip()
                    for item in parsed.get("keywordCovered", parsed.get("keyword_covered", []))
                    if str(item).strip()
                ][:8],
                keyword_missing=[
                    str(item).strip()
                    for item in parsed.get("keywordMissing", parsed.get("keyword_missing", []))
                    if str(item).strip()
                ][:8],
                star_missing=star_missing[:4],
                risk_flags=[
                    str(item).strip()
                    for item in parsed.get("riskFlags", parsed.get("risk_flags", []))
                    if str(item).strip()
                ][:5],
                evidence_strength=str(parsed.get("evidenceStrength", parsed.get("evidence_strength", "medium"))).strip().lower() or "medium",
                next_focus=str(parsed.get("nextFocus", parsed.get("next_focus", "继续补足当前问题里的核心缺口"))).strip()
                or "继续补足当前问题里的核心缺口",
                suggested_strategy=str(parsed.get("suggestedStrategy", parsed.get("suggested_strategy", "ask_for_technical_detail"))).strip()
                or "ask_for_technical_detail",
                analysis_summary=str(parsed.get("analysisSummary", parsed.get("analysis_summary", "候选人回答存在可继续追问的信息缺口"))).strip()
                or "候选人回答存在可继续追问的信息缺口",
            )

        return AnswerAnalysis(
            answered_question=True,
            completeness_level="medium",
            keyword_covered=[],
            keyword_missing=[],
            star_missing=["result"],
            risk_flags=["结果不够量化"],
            evidence_strength="medium",
            next_focus="补充结果、指标和技术细节",
            suggested_strategy="ask_for_metrics",
            analysis_summary=raw_text.strip() or "候选人回答存在可继续追问的信息缺口",
        )

    def _parse_follow_up(self, raw_text: str) -> tuple[str, str | None]:
        parsed = self._try_parse_json_object(raw_text)
        if parsed:
            question = str(parsed.get("question", "")).strip()
            reason = str(parsed.get("followUpReason", parsed.get("follow_up_reason", ""))).strip()
            if question:
                return question, reason or None

        fallback_question = raw_text.strip() or "你刚才提到这个项目，请具体讲讲你当时是怎么做技术取舍的？"
        return fallback_question, None

    def _parse_score_card(self, raw_text: str) -> ScoreCard:
        parsed = self._try_parse_json_object(raw_text)
        if parsed:
            return ScoreCard(
                completeness=int(parsed.get("completeness", 75)),
                star=int(parsed.get("star", 70)),
                job_match=int(parsed.get("jobMatch", parsed.get("job_match", 78))),
                clarity=int(parsed.get("clarity", 74)),
                speech=int(parsed.get("speech", 72)),
                summary=str(parsed.get("summary", raw_text)).strip() or raw_text,
                improvement_tips=[
                    str(item)
                    for item in parsed.get("improvementTips", parsed.get("improvement_tips", []))
                ][:3]
                or [
                    "补充项目背景和目标，让回答和简历经历对齐。",
                    "增加与你目标岗位关键词相关的技术细节与量化结果。",
                    "按 STAR 结构重组答案，突出个人动作与业务结果。",
                ],
            )

        return ScoreCard(
            completeness=75,
            star=70,
            job_match=78,
            clarity=74,
            speech=72,
            summary=raw_text,
            improvement_tips=[
                "补充项目背景和目标，让回答和简历经历对齐。",
                "增加与你目标岗位关键词相关的技术细节与量化结果。",
                "按 STAR 结构重组答案，突出个人动作与业务结果。",
            ],
        )

    def _try_parse_json_object(self, raw_text: str) -> dict:
        """
        尝试从模型输出中抽取 JSON 对象。
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
