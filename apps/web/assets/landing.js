// 入口页脚本。
//
// 这个页面承担两件事：
// 1. 调用后端接口，把“原始简历文件 / 原始 JD 文本”解析成结构化画像
// 2. 创建面试 session，并把必要配置写入 sessionStorage，供 interview.html 使用

const landingMessageEl = document.getElementById("landingMessage");
const enterRoomBtn = document.getElementById("enterRoomBtn");
const analyzeResumeBtn = document.getElementById("analyzeResumeBtn");
const analyzeJobBtn = document.getElementById("analyzeJobBtn");
const resumeAnalysisPreviewEl = document.getElementById("resumeAnalysisPreview");
const jobAnalysisPreviewEl = document.getElementById("jobAnalysisPreview");

// 解析后的结构化结果会先存在这里。
// 用户后面仍然可以在表单里继续手动修改，所以：
// - parsedResumeProfile / parsedJobProfile 只是一份“初稿”
// - 最终创建 session 时，会再把表单里的最新值覆盖进去
let parsedResumeProfile = null;
let parsedJobProfile = null;

function createSessionId() {
  return `session_${Date.now()}`;
}

function splitByComma(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function getApiBase() {
  return document.getElementById("apiBase").value.trim();
}

function setLandingMessage(message) {
  landingMessageEl.textContent = message;
}

function renderResumePreview(profile, extractedTextPreview = "", warnings = []) {
  // 这里不是渲染复杂组件，而是把解析结果快速拼成一段可读文本，
  // 方便你在 Demo 阶段先确认“模型到底抽到了什么”。
  const projectLines = (profile.projects || [])
    .map((project) => {
      const highlights = (project.highlights || []).join("、") || "暂无项目亮点";
      return `- ${project.name}：${highlights}`;
    })
    .join("\n");

  const warningText = warnings.length ? `\n警告：${warnings.join("；")}` : "";
  const previewText = extractedTextPreview ? `\n文本预览：${extractedTextPreview.slice(0, 120)}...` : "";

  resumeAnalysisPreviewEl.textContent = [
    `摘要：${profile.summary || "暂无摘要"}`,
    `优势：${(profile.strengths || []).join("、") || "暂无优势标签"}`,
    `项目：\n${projectLines || "- 暂无项目信息"}`,
    warningText,
    previewText,
  ]
    .filter(Boolean)
    .join("\n");
}

function renderJobPreview(profile, normalizedTextPreview = "", warnings = []) {
  const warningText = warnings.length ? `\n警告：${warnings.join("；")}` : "";
  const previewText = normalizedTextPreview ? `\n文本预览：${normalizedTextPreview.slice(0, 120)}...` : "";

  jobAnalysisPreviewEl.textContent = [
    `岗位：${profile.title || "暂无岗位名称"}`,
    `职级：${profile.seniority || "junior"}`,
    `关键词：${(profile.keywords || []).join("、") || "暂无关键词"}`,
    `关注点：${(profile.focus_areas || []).join("、") || "暂无关注点"}`,
    warningText,
    previewText,
  ]
    .filter(Boolean)
    .join("\n");
}

async function analyzeResumeFile() {
  const apiBase = getApiBase();
  const resumeFile = document.getElementById("resumeFile").files?.[0];

  if (!resumeFile) {
    setLandingMessage("请先选择一份简历文件。");
    return;
  }

  analyzeResumeBtn.disabled = true;
  setLandingMessage("正在上传并解析简历...");

  try {
    // 这里直接把文件二进制 POST 给后端。
    // 好处是简单、直观，不依赖 multipart 解析。
    const filenameQuery = encodeURIComponent(resumeFile.name);
    const response = await fetch(`${apiBase}/api/v1/resumes/analyze?filename=${filenameQuery}`, {
      method: "POST",
      headers: {
        "Content-Type": resumeFile.type || "application/octet-stream",
      },
      body: resumeFile,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    parsedResumeProfile = data.resumeProfile;

    // 默认把摘要回填到输入框中，方便用户继续手改。
    document.getElementById("resumeSummary").value = data.resumeProfile.summary || "";
    renderResumePreview(
      data.resumeProfile,
      data.extractedTextPreview || "",
      data.warnings || [],
    );
    setLandingMessage("简历解析完成。你可以继续微调摘要，或直接去解析 JD。");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setLandingMessage(`简历解析失败：${message}`);
  } finally {
    analyzeResumeBtn.disabled = false;
  }
}

async function analyzeJobDescription() {
  const apiBase = getApiBase();
  const jobText = document.getElementById("jobDescription").value.trim();

  if (!jobText) {
    setLandingMessage("请先粘贴岗位 JD 文本。");
    return;
  }

  analyzeJobBtn.disabled = true;
  setLandingMessage("正在解析岗位 JD...");

  try {
    const response = await fetch(`${apiBase}/api/v1/jobs/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        job_text: jobText,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    parsedJobProfile = data.jobProfile;

    // 和简历一样，解析结果先回填到可编辑输入框。
    document.getElementById("jobTitle").value = data.jobProfile.title || "";
    document.getElementById("keywords").value = (data.jobProfile.keywords || []).join(", ");
    document.getElementById("focusAreas").value = (data.jobProfile.focus_areas || []).join(", ");

    renderJobPreview(
      data.jobProfile,
      data.normalizedTextPreview || "",
      data.warnings || [],
    );
    setLandingMessage("JD 解析完成。你可以继续微调岗位字段，然后进入面试房间。");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setLandingMessage(`JD 解析失败：${message}`);
  } finally {
    analyzeJobBtn.disabled = false;
  }
}

function buildResumeProfile(sessionId) {
  // 如果用户没有先点“解析简历”，也允许用手填内容直接继续。
  // 所以这里要准备一份可用的兜底 ResumeProfile。
  const manualSummary = document.getElementById("resumeSummary").value.trim();
  const baseProfile = parsedResumeProfile || {
    resume_id: `resume_${sessionId}`,
    summary: manualSummary,
    strengths: ["沟通清晰", "学习能力强"],
    projects: [
      {
        name: "AI 面试陪练官",
        highlights: ["完成 FastAPI 后端骨架", "接入 DashScope Realtime 语音链路"],
      },
    ],
  };

  return {
    ...baseProfile,
    resume_id: baseProfile.resume_id || `resume_${sessionId}`,
    summary: manualSummary || baseProfile.summary,
  };
}

function buildJobProfile(sessionId) {
  // 和简历同理：没有点“解析 JD”时，也允许手工填。
  const manualTitle = document.getElementById("jobTitle").value.trim();
  const manualKeywords = splitByComma(document.getElementById("keywords").value);
  const manualFocusAreas = splitByComma(document.getElementById("focusAreas").value);

  const baseProfile = parsedJobProfile || {
    job_id: `job_${sessionId}`,
    title: manualTitle || "后端开发工程师",
    seniority: "junior",
    keywords: manualKeywords,
    focus_areas: manualFocusAreas.length ? manualFocusAreas : ["项目经验", "技术取舍"],
  };

  return {
    ...baseProfile,
    job_id: baseProfile.job_id || `job_${sessionId}`,
    title: manualTitle || baseProfile.title,
    keywords: manualKeywords.length ? manualKeywords : baseProfile.keywords || [],
    focus_areas:
      manualFocusAreas.length ? manualFocusAreas : baseProfile.focus_areas || [],
  };
}

async function enterInterviewRoom() {
  const apiBase = getApiBase();
  const sessionId = createSessionId();

  // 这里组装的是最终进入面试房间的“结构化上下文”。
  // 后端后续的追问、评分、报告，都会基于它工作。
  const sessionPayload = {
    session_id: sessionId,
    resume_profile: buildResumeProfile(sessionId),
    job_profile: buildJobProfile(sessionId),
  };

  enterRoomBtn.disabled = true;
  setLandingMessage("正在创建会话并准备跳转...");

  try {
    const response = await fetch(`${apiBase}/api/v1/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(sessionPayload),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorText}`);
    }

    // 这里把少量前端需要用到的配置放入 sessionStorage。
    // interview.html 打开后，会从这里读取 apiBase 和 sessionId。
    sessionStorage.setItem(
      "interview-room-config",
      JSON.stringify({
        apiBase,
        sessionId,
        jobTitle: sessionPayload.job_profile.title,
        resumeSummary: sessionPayload.resume_profile.summary,
        keywords: sessionPayload.job_profile.keywords,
        focusAreas: sessionPayload.job_profile.focus_areas,
      }),
    );

    window.location.href = "./interview.html";
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const extraHint =
      message === "Failed to fetch"
        ? "。这通常表示后端没启动，或者当前前端端口没有被后端跨域放行。请先重启后端后再试。"
        : "";
    setLandingMessage(`创建失败：${message}${extraHint}`);
    enterRoomBtn.disabled = false;
  }
}

analyzeResumeBtn.addEventListener("click", analyzeResumeFile);
analyzeJobBtn.addEventListener("click", analyzeJobDescription);
enterRoomBtn.addEventListener("click", enterInterviewRoom);
