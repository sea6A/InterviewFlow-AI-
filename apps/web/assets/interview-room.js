// 正式面试房间页脚本。
//
// 这个文件是前端实时交互的核心，主要负责：
// 1. 建立 WebSocket 与后端通信
// 2. 采集麦克风音频并切成 16k PCM 小块上传
// 3. 播放 DashScope Realtime 返回的语音分片
// 4. 展示用户转写、AI 文本、评分、追问
// 5. 管理“两级打断状态机”

const roomConfigRaw = sessionStorage.getItem("interview-room-config");

if (!roomConfigRaw) {
  window.location.href = "./index.html";
}

// 上一个页面会把 sessionId / apiBase 等信息放进 sessionStorage。
// 这里是房间页启动时的唯一入口配置。
const roomConfig = JSON.parse(roomConfigRaw || "{}");

const questionTextEl = document.getElementById("questionText");
const candidateTranscriptEl = document.getElementById("candidateTranscript");
const assistantTranscriptEl = document.getElementById("assistantTranscript");
const roomStatusEl = document.getElementById("roomStatus");
const roomWsBadge = document.getElementById("roomWsBadge");
const roomPhaseBadge = document.getElementById("roomPhaseBadge");
const roomMicBadge = document.getElementById("roomMicBadge");
const roomInterruptBadge = document.getElementById("roomInterruptBadge");
const imageInput = document.getElementById("imageInput");
const sendImageBtn = document.getElementById("sendImageBtn");
const imageHintEl = document.getElementById("imageHint");
const scoreCompletenessEl = document.getElementById("scoreCompleteness");
const scoreStarEl = document.getElementById("scoreStar");
const scoreJobMatchEl = document.getElementById("scoreJobMatch");
const scoreClarityEl = document.getElementById("scoreClarity");
const scoreSpeechEl = document.getElementById("scoreSpeech");
const scoreTipsEl = document.getElementById("scoreTips");
const starMissingTagsEl = document.getElementById("starMissingTags");
const turnFeedbackSummaryEl = document.getElementById("turnFeedbackSummary");
const turnFeedbackStrengthsEl = document.getElementById("turnFeedbackStrengths");
const turnFeedbackWeakPointsEl = document.getElementById("turnFeedbackWeakPoints");
const turnTrainingPlanEl = document.getElementById("turnTrainingPlan");
const improvedAnswerExampleEl = document.getElementById("improvedAnswerExample");
const logEl = document.getElementById("log");
const roomJobTitleEl = document.getElementById("roomJobTitle");
const roomSessionSummaryEl = document.getElementById("roomSessionSummary");
const roomSessionIdEl = document.getElementById("roomSessionId");
const roomResumeSummaryEl = document.getElementById("roomResumeSummary");
const roomKeywordTagsEl = document.getElementById("roomKeywordTags");
const roomFocusTagsEl = document.getElementById("roomFocusTags");

const connectBtn = document.getElementById("connectBtn");
const startMicBtn = document.getElementById("startMicBtn");
const stopMicBtn = document.getElementById("stopMicBtn");
const interruptBtn = document.getElementById("interruptBtn");

let ws = null;
let audioContext = null;
let mediaStream = null;
let mediaSource = null;
let processorNode = null;
let isCapturing = false;
let chunkIndex = 0;

// playbackCursorTime 用来做一个非常轻量的播放队列：
// 新音频分片不是立刻抢占播放，而是接在上一个分片后面。
let playbackCursorTime = 0;
let activePlaybackSources = [];

// 下面这些变量属于“本地状态机”的一部分。
// 它们共同决定：当前是否在说话、是否可能触发打断、何时自动提交回答。
let silenceSince = null;
let hasSpokenInCurrentTurn = false;
let isStoppingAnswer = false;
let interruptState = "idle";
let isAssistantSpeaking = false;

function setChipTone(element, tone = "") {
  element.classList.remove("ok", "warn");

  if (tone === "ok") {
    element.classList.add("ok");
  } else if (tone === "warn") {
    element.classList.add("warn");
  }
}

function appendLog(label, payload) {
  const text = `[${new Date().toLocaleTimeString()}] ${label}\n${typeof payload === "string" ? payload : JSON.stringify(payload, null, 2)}\n\n`;
  logEl.textContent += text;
  logEl.scrollTop = logEl.scrollHeight;
}

function setWsState(text, tone = "") {
  roomWsBadge.textContent = text;
  setChipTone(roomWsBadge, tone);
}

function setRoomPhase(phase) {
  roomPhaseBadge.textContent = phase;
  const tone = phase === "speaking" || phase === "listening" ? "ok" : phase === "thinking" ? "warn" : "";
  setChipTone(roomPhaseBadge, tone);

  // speaking 代表后端 / Realtime 正在输出 AI 语音。
  // 这个状态是“两级打断”第一级判断的重要依据。
  isAssistantSpeaking = phase === "speaking";

  if (phase === "listening" && interruptState === "confirmed") {
    roomStatusEl.textContent = "AI 已停止当前发言，轮到你继续说。";
  }
}

function setMicState(text, tone = "") {
  roomMicBadge.textContent = text;
  setChipTone(roomMicBadge, tone);
}

function setInterruptState(state, tone = "") {
  interruptState = state;
  roomInterruptBadge.textContent = `interrupt: ${state}`;
  roomInterruptBadge.classList.remove("ok", "warn");

  if (tone === "ok" || state === "confirmed") {
    roomInterruptBadge.classList.add("ok");
  } else if (tone === "warn" || state === "possible_interrupt") {
    roomInterruptBadge.classList.add("warn");
  }
}

function mapStarMissingLabel(part) {
  const normalized = String(part || "").toLowerCase();
  if (normalized === "situation") {
    return "Situation 缺失";
  }
  if (normalized === "task") {
    return "Task 缺失";
  }
  if (normalized === "action") {
    return "Action 缺失";
  }
  if (normalized === "result") {
    return "Result 缺失";
  }
  return normalized || "未知缺失项";
}

function renderStarMissing(parts = []) {
  starMissingTagsEl.innerHTML = "";

  if (!parts.length) {
    const tag = document.createElement("span");
    tag.className = "tag muted";
    tag.textContent = "STAR 结构较完整";
    starMissingTagsEl.appendChild(tag);
    return;
  }

  parts.forEach((part) => {
    const tag = document.createElement("span");
    tag.className = "tag warn";
    tag.textContent = mapStarMissingLabel(part);
    starMissingTagsEl.appendChild(tag);
  });
}

function renderTagGroup(container, items = [], emptyText = "暂无内容") {
  container.innerHTML = "";

  if (!items.length) {
    const tag = document.createElement("span");
    tag.className = "tag muted";
    tag.textContent = emptyText;
    container.appendChild(tag);
    return;
  }

  items.forEach((item) => {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = item;
    container.appendChild(tag);
  });
}

function hydrateRoomBrief() {
  const safeJobTitle = roomConfig.jobTitle || "未命名岗位";
  const safeResumeSummary = roomConfig.resumeSummary || "首页未提供简历摘要。";

  roomJobTitleEl.textContent = safeJobTitle;
  roomSessionSummaryEl.textContent = safeResumeSummary;
  roomSessionIdEl.textContent = roomConfig.sessionId || "未创建";
  roomResumeSummaryEl.textContent = safeResumeSummary;
  renderTagGroup(roomKeywordTagsEl, roomConfig.keywords || [], "等待岗位关键词");
  renderTagGroup(roomFocusTagsEl, roomConfig.focusAreas || [], "等待训练焦点");

  document.title = `${safeJobTitle} · AI 面试房间`;
}

function renderTextList(container, items = [], emptyText = "暂无内容") {
  container.innerHTML = "";

  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = emptyText;
    container.appendChild(li);
    return;
  }

  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    container.appendChild(li);
  });
}

function renderTurnFeedback(feedback = null) {
  if (!feedback) {
    turnFeedbackSummaryEl.textContent = "等待本轮回答结束后生成复盘反馈。";
    renderTextList(turnFeedbackStrengthsEl, [], "回答完成后，这里会列出本轮表现亮点。");
    renderTextList(turnFeedbackWeakPointsEl, [], "回答完成后，这里会列出需要加强的地方。");
    renderTextList(turnTrainingPlanEl, [], "系统会根据本轮表现生成下一步训练建议。");
    improvedAnswerExampleEl.textContent = "回答完成后，这里会生成一个更贴近面试场景的参考说法。";
    return;
  }

  turnFeedbackSummaryEl.textContent = feedback.summary || "本轮复盘已生成。";
  renderTextList(turnFeedbackStrengthsEl, feedback.strengths || [], "这一轮暂未提炼出明确亮点。");
  renderTextList(turnFeedbackWeakPointsEl, feedback.weakPoints || [], "这一轮暂未发现明显短板。");
  renderTextList(turnTrainingPlanEl, feedback.nextTrainingPlan || [], "继续保持当前回答节奏。");
  improvedAnswerExampleEl.textContent =
    feedback.improvedAnswerExample || "系统暂未生成改进版回答示例。";
}

function updateButtons() {
  const wsReady = ws && ws.readyState === WebSocket.OPEN;
  connectBtn.disabled = wsReady;
  startMicBtn.disabled = !wsReady || isCapturing;
  stopMicBtn.disabled = !wsReady || !isCapturing;
  interruptBtn.disabled = !wsReady;
}

async function ensureAudioContext() {
  // AudioContext 需要懒初始化，
  // 因为很多浏览器要求在用户交互后才能真正启动音频上下文。
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }

  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }

  return audioContext;
}

function floatTo16BitPCM(floatArray) {
  // 浏览器麦克风拿到的是 Float32 PCM，范围通常在 -1 到 1。
  // 后端这里约定传 16-bit PCM，所以要先压成 Int16。
  const output = new Int16Array(floatArray.length);
  for (let i = 0; i < floatArray.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, floatArray[i]));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
  // 浏览器录音采样率通常是 44.1k 或 48k，
  // 这里要降到后端约定的 16k。
  if (outputSampleRate >= inputSampleRate) {
    return buffer;
  }

  const sampleRateRatio = inputSampleRate / outputSampleRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);

  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
    let accum = 0;
    let count = 0;

    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i += 1) {
      accum += buffer[i];
      count += 1;
    }

    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }

  return result;
}

function pcm16ToBase64(int16Array) {
  const bytes = new Uint8Array(int16Array.buffer);
  let binary = "";
  const chunkSize = 0x8000;

  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}

function base64ToInt16Array(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

async function playAudioDelta(deltaBase64) {
  // DashScope Realtime 会不断返回音频分片。
  // 这里把每个分片转换成 AudioBuffer，并按时间顺序排队播放。
  const context = await ensureAudioContext();
  const pcm16 = base64ToInt16Array(deltaBase64);
  const float32 = new Float32Array(pcm16.length);

  for (let i = 0; i < pcm16.length; i += 1) {
    float32[i] = pcm16[i] / 0x8000;
  }

  const buffer = context.createBuffer(1, float32.length, 24000);
  buffer.copyToChannel(float32, 0);

  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);
  activePlaybackSources.push(source);

  const startAt = Math.max(context.currentTime + 0.03, playbackCursorTime);
  source.start(startAt);
  playbackCursorTime = startAt + buffer.duration;
  roomStatusEl.textContent = "AI 正在语音输出...";

  source.onended = () => {
    activePlaybackSources = activePlaybackSources.filter((item) => item !== source);
  };
}

function stopAssistantAudioPlayback() {
  // 这里是前端本地“立即停播”的入口。
  // 它常用于：
  // - 手动点击打断
  // - 收到服务端 interrupt.confirmed 后真正停播
  activePlaybackSources.forEach((source) => {
    try {
      source.stop();
    } catch (error) {
      void error;
    }
  });

  activePlaybackSources = [];
  playbackCursorTime = audioContext ? audioContext.currentTime : 0;
}

function sendJson(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    appendLog("WS send", "当前 WebSocket 不可用");
    return false;
  }

  ws.send(JSON.stringify(payload));
  appendLog("WS send", payload);
  return true;
}

function connectRoom() {
  // 把 http://127.0.0.1:3001 这种地址改成 ws://...
  const wsBase = roomConfig.apiBase
    .replace("http://", "ws://")
    .replace("https://", "wss://");

  ws = new WebSocket(`${wsBase}/ws/interview/${roomConfig.sessionId}`);
  setWsState("WS 连接中", "warn");
  setInterruptState("idle");
  roomStatusEl.textContent = "正在建立 WebSocket 和 Realtime 房间连接...";
  updateButtons();

  ws.onopen = () => {
    setWsState("WS 已连接", "ok");
    roomStatusEl.textContent = "房间已连接，AI 会自动发起第一轮问题。";
    appendLog("WS open", { sessionId: roomConfig.sessionId });
    updateButtons();
  };

  ws.onmessage = async (event) => {
    try {
      const payload = JSON.parse(event.data);
      appendLog("WS event", payload);

      if (payload.type === "session.connected" || payload.type === "room.phase.changed") {
        setRoomPhase(payload.phase);
      }

      if (payload.type === "interviewer.question") {
        questionTextEl.textContent = payload.text || "暂无问题";
      }

      if (payload.type === "transcript.final") {
        candidateTranscriptEl.textContent = payload.text || "没有识别到文本";
      }

      if (payload.type === "assistant.transcript.done") {
        assistantTranscriptEl.textContent = payload.text || "暂无助手文本";
      }

      if (payload.type === "assistant.audio.delta" && payload.deltaBase64) {
        await playAudioDelta(payload.deltaBase64);
      }

      // 这是“两级打断”的第二级结果：
      // 只有服务端 semantic_vad 真正确认形成新轮次后，
      // 前端才在这里统一执行停播和状态切换。
      if (payload.type === "interrupt.confirmed") {
        stopAssistantAudioPlayback();
        setInterruptState("confirmed", "ok");
        roomStatusEl.textContent = payload.message || "服务端已确认本轮打断，AI 当前回复已停止。";
      }

      if (payload.type === "score.updated") {
        scoreCompletenessEl.textContent = payload.scoreCard.completeness;
        scoreStarEl.textContent = payload.scoreCard.star;
        scoreJobMatchEl.textContent = payload.scoreCard.jobMatch;
        scoreClarityEl.textContent = payload.scoreCard.clarity;
        scoreSpeechEl.textContent = payload.scoreCard.speech;
        renderStarMissing(payload.scoreCard.starMissing || []);

        scoreTipsEl.innerHTML = "";
        (payload.scoreCard.improvementTips || []).forEach((tip) => {
          const li = document.createElement("li");
          li.textContent = tip;
          scoreTipsEl.appendChild(li);
        });
      }

      if (payload.type === "turn.feedback.generated") {
        renderTurnFeedback(payload.feedback || null);
      }

      if (payload.type === "context.image.received") {
        imageHintEl.textContent = payload.message || "图片上下文已发送。";
      }

      if (payload.type === "provider.error") {
        setInterruptState("idle");
        roomStatusEl.textContent = `发生错误：${payload.message}`;
      }
    } catch (error) {
      appendLog("WS raw", event.data);
      if (error instanceof Error) {
        appendLog("WS parse error", error.message);
      }
    }
  };

  ws.onerror = () => {
    setWsState("WS 错误", "warn");
    setInterruptState("idle");
    roomStatusEl.textContent = "WebSocket 出现错误。";
    updateButtons();
  };

  ws.onclose = () => {
    setWsState("WS 已关闭", "warn");
    setRoomPhase("finished");
    setInterruptState("idle");
    roomStatusEl.textContent = "WebSocket 已关闭。";
    appendLog("WS close", "connection closed");
    updateButtons();
  };
}

async function startMicrophone() {
  try {
    const context = await ensureAudioContext();
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });

    mediaSource = context.createMediaStreamSource(mediaStream);
    processorNode = context.createScriptProcessor(4096, 1, 1);
    processorNode.onaudioprocess = (event) => {
      if (!isCapturing || !ws || ws.readyState !== WebSocket.OPEN) {
        return;
      }

      const inputData = event.inputBuffer.getChannelData(0);
      let energy = 0;
      for (let i = 0; i < inputData.length; i += 1) {
        energy += inputData[i] * inputData[i];
      }
      const rms = Math.sqrt(energy / inputData.length);
      const looksLikeSpeech = rms > 0.018;

      // 两级打断的第一级：
      // 只做“可能打断”的本地判断，不直接停播。
      if (isAssistantSpeaking && looksLikeSpeech && interruptState === "idle") {
        setInterruptState("possible_interrupt", "warn");
        roomStatusEl.textContent = "检测到你可能想打断 AI，正在继续上传音频，等待服务端 semantic_vad 确认。";
      }

      if (!isAssistantSpeaking && interruptState === "possible_interrupt") {
        setInterruptState("idle");
      }

      // 一个很轻量的本地静音检测：
      // 只要用户已经说过话，然后持续静音一小段时间，就自动提交本轮回答。
      if (rms > 0.015) {
        hasSpokenInCurrentTurn = true;
        silenceSince = null;
      } else if (hasSpokenInCurrentTurn) {
        if (silenceSince === null) {
          silenceSince = Date.now();
        } else if (Date.now() - silenceSince > 1400) {
          stopAnswer("auto");
          return;
        }
      }

      const downsampled = downsampleBuffer(inputData, context.sampleRate, 16000);
      const pcm16 = floatTo16BitPCM(downsampled);
      const payload = {
        type: "audio.chunk",
        sessionId: roomConfig.sessionId,
        chunkId: `chunk_${(chunkIndex += 1)}`,
        mimeType: "audio/pcm",
        sampleRate: 16000,
        payloadBase64: pcm16ToBase64(pcm16),
      };

      ws.send(JSON.stringify(payload));
    };

    mediaSource.connect(processorNode);
    processorNode.connect(context.destination);

    isCapturing = true;
    hasSpokenInCurrentTurn = false;
    silenceSince = null;
    isStoppingAnswer = false;
    if (interruptState !== "confirmed") {
      setInterruptState("idle");
    }
    setMicState("录音中", "ok");
    roomStatusEl.textContent =
      "正在回答，音频已实时发送到后端。如果 AI 正在讲话，你开口时会先进入 possible_interrupt，等待 semantic_vad 确认。";
    updateButtons();
  } catch (error) {
    roomStatusEl.textContent = `麦克风启动失败：${error instanceof Error ? error.message : String(error)}`;
  }
}

function stopMicResources() {
  // 把录音相关节点和轨道统一释放掉。
  if (processorNode) {
    processorNode.disconnect();
    processorNode.onaudioprocess = null;
    processorNode = null;
  }

  if (mediaSource) {
    mediaSource.disconnect();
    mediaSource = null;
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
}

function stopAnswer(reason = "manual") {
  if (!isCapturing || isStoppingAnswer) {
    return;
  }

  isStoppingAnswer = true;
  isCapturing = false;
  stopMicResources();
  setMicState("已停止", "warn");
  setInterruptState("idle");
  roomStatusEl.textContent =
    reason === "auto"
      ? "检测到你已经说完，已自动提交回答，等待 AI 评分和追问。"
      : "已结束回答，等待 AI 评分和追问。";
  updateButtons();

  sendJson({
    type: "answer.commit",
    sessionId: roomConfig.sessionId,
    turnId: `turn_${Date.now()}`,
  });
}

function interruptAssistant() {
  // 手动打断是“用户明确意图”，所以可以立即本地停播，
  // 然后再通知后端去 cancel 当前 response。
  stopAssistantAudioPlayback();
  setInterruptState("confirmed", "ok");
  sendJson({
    type: "assistant.interrupt",
    sessionId: roomConfig.sessionId,
    reason: "manual_stop",
  });
  roomStatusEl.textContent = "已尝试手动打断 AI 当前回复。";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const base64 = result.includes(",") ? result.split(",")[1] : result;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function sendImageContext() {
  // 多模态扩展入口：把图片转成 base64 发给后端。
  // 当前常用于上传简历截图、架构图或岗位图片。
  const file = imageInput.files?.[0];
  if (!file) {
    imageHintEl.textContent = "请先选择一张图片。";
    return;
  }

  try {
    const imageBase64 = await fileToBase64(file);
    const ok = sendJson({
      type: "image.frame",
      sessionId: roomConfig.sessionId,
      mimeType: file.type || "image/png",
      imageBase64,
    });

    if (ok) {
      imageHintEl.textContent = `已发送图片：${file.name}`;
    }
  } catch (error) {
    imageHintEl.textContent = `图片发送失败：${error instanceof Error ? error.message : String(error)}`;
  }
}

connectBtn.addEventListener("click", connectRoom);
startMicBtn.addEventListener("click", startMicrophone);
stopMicBtn.addEventListener("click", () => stopAnswer("manual"));
interruptBtn.addEventListener("click", interruptAssistant);
sendImageBtn.addEventListener("click", sendImageContext);

hydrateRoomBrief();
setWsState("WS 未连接");
setMicState("麦克风待命");
setInterruptState("idle");
renderStarMissing([]);
renderTurnFeedback(null);
updateButtons();
