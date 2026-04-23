import json
import re
import time

from app.schemas.interview import (
    JobAnalysisResponse,
    JobProfile,
    ResumeAnalysisResponse,
    ResumeProfile,
    ResumeProject,
)
from app.services.intake.document_text_extractor import DocumentTextExtractor
from app.services.qwen.dashscope_client import DashScopeClient


class ProfileAnalysisService:
    """
    把“原始简历 / 原始 JD 文本”变成结构化画像。

    整体流程是：
    1. 文件提取文本
    2. 调用千问抽取结构化字段
    3. 如果模型没有严格返回 JSON，就用本地兜底逻辑
    """

    def __init__(
        self,
        ai_client: DashScopeClient,
        extractor: DocumentTextExtractor | None = None,
    ) -> None:
        self.ai_client = ai_client
        self.extractor = extractor or DocumentTextExtractor()

    async def analyze_resume(
        self,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> ResumeAnalysisResponse:
        """
        解析简历文件。

        这里返回的 resume_profile 后续会直接喂给：
        - 会话创建
        - 实时追问
        - 上下文化评分
        - 面试报告
        """

        extracted_text, warnings = self.extractor.extract(filename, content_type, file_bytes)
        prompt = "\n".join(
            [
                "你是一名中文简历解析助手。",
                "请从简历文本中抽取最适合技术面试上下文化分析的结构化信息。",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                'JSON 格式必须包含：{"summary":"不超过120字的摘要","strengths":["优势1","优势2","优势3"],"projects":[{"name":"项目名","highlights":["亮点1","亮点2","亮点3"]}]}',
                "summary 要尽量概括候选人的年限、主要技术栈和项目方向。",
                "strengths 控制在 3 个以内，偏面试表达，不要写得像宣传文案。",
                "projects 只保留最值得在面试中追问的 1 到 3 个项目。",
                "如果信息不足，也要尽量基于原文给出合理抽取。",
                f"简历原文：\n{extracted_text}",
            ]
        )

        raw_result = await self.ai_client.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": extracted_text},
            ]
        )
        parsed = self._try_parse_json_object(raw_result)
        resume_profile = self._build_resume_profile(parsed, extracted_text)

        return ResumeAnalysisResponse(
            resume_profile=resume_profile,
            extracted_text_preview=extracted_text[:600],
            warnings=warnings,
        )

    async def analyze_job_text(self, job_text: str) -> JobAnalysisResponse:
        """
        把 JD 文本抽成岗位画像。

        解析结果会直接进入 job_profile，
        后续用于面试开场、追问、jobMatch 评分和报告总结。
        """

        normalized_text = self._normalize_job_text(job_text)
        prompt = "\n".join(
            [
                "你是一名中文岗位 JD 分析助手。",
                "请从岗位描述中抽取结构化岗位画像，供 AI 面试系统使用。",
                "请严格返回 JSON，不要输出代码块，不要输出额外解释。",
                'JSON 格式必须包含：{"title":"岗位名称","seniority":"intern|junior|middle|senior","keywords":["关键词1","关键词2"],"focusAreas":["关注点1","关注点2"]}',
                "keywords 应该优先保留技术栈、能力要求、业务方向词。",
                "focusAreas 应该是面试真正要追问的点，比如项目经验、系统设计、性能优化、沟通协作。",
                f"JD 原文：\n{normalized_text}",
            ]
        )

        raw_result = await self.ai_client.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": normalized_text},
            ]
        )
        parsed = self._try_parse_json_object(raw_result)
        job_profile = self._build_job_profile(parsed, normalized_text)

        return JobAnalysisResponse(
            job_profile=job_profile,
            normalized_text_preview=normalized_text[:600],
            warnings=[],
        )

    def _build_resume_profile(self, parsed: dict, extracted_text: str) -> ResumeProfile:
        """
        把模型 JSON 或本地兜底数据变成统一的 ResumeProfile。
        """

        if parsed:
            projects: list[ResumeProject] = []
            for item in parsed.get("projects", [])[:3]:
                if not isinstance(item, dict):
                    continue
                project_name = str(item.get("name", "")).strip()
                if not project_name:
                    continue
                projects.append(
                    ResumeProject(
                        name=project_name,
                        highlights=[str(highlight).strip() for highlight in item.get("highlights", []) if str(highlight).strip()][:3],
                    )
                )

            return ResumeProfile(
                resume_id=f"resume_{int(time.time() * 1000)}",
                summary=str(parsed.get("summary", "")).strip() or self._fallback_resume_summary(extracted_text),
                strengths=[str(item).strip() for item in parsed.get("strengths", []) if str(item).strip()][:3],
                projects=projects or self._fallback_resume_projects(extracted_text),
            )

        return ResumeProfile(
            resume_id=f"resume_{int(time.time() * 1000)}",
            summary=self._fallback_resume_summary(extracted_text),
            strengths=self._fallback_resume_strengths(extracted_text),
            projects=self._fallback_resume_projects(extracted_text),
        )

    def _build_job_profile(self, parsed: dict, normalized_text: str) -> JobProfile:
        if parsed:
            seniority = str(parsed.get("seniority", "junior")).strip().lower()
            if seniority not in {"intern", "junior", "middle", "senior"}:
                seniority = self._fallback_seniority(normalized_text)

            return JobProfile(
                job_id=f"job_{int(time.time() * 1000)}",
                title=str(parsed.get("title", "")).strip() or self._fallback_job_title(normalized_text),
                seniority=seniority,  # type: ignore[arg-type]
                keywords=[str(item).strip() for item in parsed.get("keywords", []) if str(item).strip()][:8]
                or self._fallback_keywords(normalized_text),
                focus_areas=[str(item).strip() for item in parsed.get("focusAreas", []) if str(item).strip()][:5]
                or self._fallback_focus_areas(normalized_text),
            )

        return JobProfile(
            job_id=f"job_{int(time.time() * 1000)}",
            title=self._fallback_job_title(normalized_text),
            seniority=self._fallback_seniority(normalized_text),  # type: ignore[arg-type]
            keywords=self._fallback_keywords(normalized_text),
            focus_areas=self._fallback_focus_areas(normalized_text),
        )

    def _fallback_resume_summary(self, text: str) -> str:
        """
        当模型返回不稳定时，用前几行文字拼一个可用摘要。
        """

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "；".join(lines[:3])[:120] or "候选人已有相关项目经历，建议面试时重点追问项目背景、技术方案与量化结果。"

    def _fallback_resume_strengths(self, text: str) -> list[str]:
        known_tokens = self._fallback_keywords(text)
        if not known_tokens:
            return ["项目经历可追问", "技术栈信息待澄清"]
        return [f"具备 {token} 相关经验" for token in known_tokens[:3]]

    def _fallback_resume_projects(self, text: str) -> list[ResumeProject]:
        """
        没有结构化项目时，尽量从类似“项目名/项目经历”行里捞出 1-2 个项目。
        """

        project_lines: list[str] = []
        for line in text.splitlines():
            clean = line.strip(" -•\t")
            if clean and ("项目" in clean or clean.lower().startswith("project")):
                project_lines.append(clean[:80])

        if not project_lines:
            return [
                ResumeProject(
                    name="核心项目经历待补充",
                    highlights=["建议在面试中继续追问项目背景、技术方案与结果指标。"],
                )
            ]

        projects: list[ResumeProject] = []
        for project_line in project_lines[:2]:
            projects.append(
                ResumeProject(
                    name=project_line,
                    highlights=["建议进一步追问个人贡献", "建议进一步追问量化结果"],
                )
            )
        return projects

    def _normalize_job_text(self, job_text: str) -> str:
        normalized = job_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        if not normalized:
            raise ValueError("JD 文本为空，无法解析。")
        return normalized

    def _fallback_job_title(self, text: str) -> str:
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                return clean[:60]
        return "目标岗位待确认"

    def _fallback_seniority(self, text: str) -> str:
        lowered = text.lower()
        if "实习" in text or "intern" in lowered:
            return "intern"
        if "高级" in text or "资深" in text or "senior" in lowered:
            return "senior"
        if "中级" in text or "3-5年" in text or "middle" in lowered:
            return "middle"
        return "junior"

    def _fallback_keywords(self, text: str) -> list[str]:
        """
        这里不是做高精度 NLP，只做一个 Demo 足够稳的关键词兜底。
        """

        candidates = [
            "Python",
            "Java",
            "Go",
            "FastAPI",
            "Django",
            "Flask",
            "Spring Boot",
            "Redis",
            "MySQL",
            "PostgreSQL",
            "MongoDB",
            "Kafka",
            "RocketMQ",
            "微服务",
            "系统设计",
            "性能优化",
            "高并发",
            "接口设计",
            "云原生",
            "Docker",
            "Kubernetes",
        ]

        found: list[str] = []
        lowered = text.lower()
        for candidate in candidates:
            if candidate.lower() in lowered and candidate not in found:
                found.append(candidate)

        return found[:8] or ["项目经验", "技术取舍", "结果量化"]

    def _fallback_focus_areas(self, text: str) -> list[str]:
        keywords = self._fallback_keywords(text)
        focus_areas: list[str] = []

        if any(item in keywords for item in ["FastAPI", "Flask", "Django", "Spring Boot", "接口设计"]):
            focus_areas.append("后端接口设计")
        if any(item in keywords for item in ["Redis", "Kafka", "RocketMQ", "微服务"]):
            focus_areas.append("分布式与系统稳定性")
        if any(item in keywords for item in ["高并发", "性能优化", "MySQL", "PostgreSQL"]):
            focus_areas.append("性能优化与数据库设计")

        focus_areas.extend(["项目经验", "技术取舍"])

        # 去重，同时保留原顺序。
        deduplicated: list[str] = []
        for item in focus_areas:
            if item not in deduplicated:
                deduplicated.append(item)
        return deduplicated[:5]

    def _try_parse_json_object(self, raw_text: str) -> dict:
        """
        统一处理模型偶尔多说话的问题：
        - 优先直接 json.loads
        - 失败就从文本里尽量截取一个 JSON 对象
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
