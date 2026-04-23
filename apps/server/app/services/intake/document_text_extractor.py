from pathlib import Path
import re


class DocumentTextExtractor:
    """
    把用户上传的文件转成“模型可读的纯文本”。

    这层故意单独拆出来，是因为“文件解析”与“LLM 抽取结构化字段”
    是两件不同的事：
    - 这里负责读文件
    - 上层分析服务负责理解文本

    这样后面如果你想换 OCR、接对象存储、做缓存，改动会更小。
    """

    def extract(self, filename: str, content_type: str, file_bytes: bytes) -> tuple[str, list[str]]:
        """
        返回：
        - 解析后的纯文本
        - 警告信息列表

        这里不直接抛出所有格式问题，而是尽量给调用方一个明确结果。
        真正无法处理的格式，再抛出更清晰的错误。
        """

        if not file_bytes:
            raise ValueError("上传内容为空，无法解析。")

        suffix = Path(filename or "resume.txt").suffix.lower()
        warnings: list[str] = []

        if suffix in {".txt", ".md", ".csv", ".json"}:
            text = self._decode_text_bytes(file_bytes)
            return self._normalize_text(text), warnings

        if suffix == ".pdf":
            text = self._extract_pdf_text(file_bytes)
            return self._normalize_text(text), warnings

        if suffix == ".docx":
            text = self._extract_docx_text(file_bytes)
            return self._normalize_text(text), warnings

        # 对未知后缀，先尽量按文本处理。
        # 这样像没有扩展名的纯文本文件，也能先跑通。
        try:
            text = self._decode_text_bytes(file_bytes)
            warnings.append(f"未识别的文件类型 {content_type or suffix or 'unknown'}，已按纯文本尝试解析。")
            return self._normalize_text(text), warnings
        except UnicodeDecodeError as exc:
            raise ValueError(
                "当前只支持 txt/md/json，或在安装 pypdf / python-docx 后支持 pdf/docx。"
            ) from exc

    def _decode_text_bytes(self, file_bytes: bytes) -> str:
        """
        文本文件常见编码兜底。

        很多中文简历不是 UTF-8，所以这里按几个常见编码逐个尝试。
        """

        encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
        last_error: UnicodeDecodeError | None = None

        for encoding in encodings:
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "unknown decode error")

    def _extract_pdf_text(self, file_bytes: bytes) -> str:
        """
        PDF 解析做成懒加载：
        - 环境装了 pypdf，就正常解析
        - 没装时，给出非常明确的错误提示
        """

        try:
            from io import BytesIO

            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("解析 PDF 需要安装 pypdf：`python -m pip install pypdf`。") from exc

        reader = PdfReader(BytesIO(file_bytes))
        page_texts: list[str] = []
        for page in reader.pages:
            page_texts.append(page.extract_text() or "")

        text = "\n".join(page_texts).strip()
        if not text:
            raise ValueError("PDF 已读取，但没有提取到可用文字，可能是扫描件，需要后续接 OCR。")
        return text

    def _extract_docx_text(self, file_bytes: bytes) -> str:
        """
        DOCX 同样使用懒加载。
        """

        try:
            from io import BytesIO

            from docx import Document
        except ImportError as exc:
            raise ValueError(
                "解析 DOCX 需要安装 python-docx：`python -m pip install python-docx`。"
            ) from exc

        document = Document(BytesIO(file_bytes))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
        if not text:
            raise ValueError("DOCX 已读取，但没有提取到可用文字。")
        return text

    def _normalize_text(self, text: str) -> str:
        """
        做轻量清洗，让提示词输入更稳定。

        这里不做激进处理，只做：
        - 换行统一
        - 连续空白压缩
        - 去掉首尾空白
        """

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        normalized = normalized.strip()

        if not normalized:
            raise ValueError("文件已读取，但内容为空或无法识别。")
        return normalized
