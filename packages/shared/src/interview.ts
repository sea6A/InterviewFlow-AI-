export type SessionStatus =
  | "created"
  | "ready"
  | "in_progress"
  | "paused"
  | "finished";

export type Role = "system" | "assistant" | "candidate";

export type RealtimeProvider = "dashscope" | "server-orchestrated";

export type RoomPhase =
  | "idle"
  | "connecting"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "finished";

export interface ResumeProfile {
  resumeId: string;
  summary: string;
  strengths: string[];
  projects: Array<{
    name: string;
    highlights: string[];
  }>;
}

export interface JobProfile {
  jobId: string;
  title: string;
  seniority: "intern" | "junior" | "middle" | "senior";
  keywords: string[];
  focusAreas: string[];
}

export interface TranscriptSegment {
  id: string;
  sessionId: string;
  turnId: string;
  role: Role;
  text: string;
  isFinal: boolean;
  createdAt: string;
}

export interface ScoreCard {
  completeness: number;
  star: number;
  jobMatch: number;
  clarity: number;
  speech: number;
  summary: string;
  improvementTips: string[];
}

export interface InterviewTurn {
  turnId: string;
  turnIndex: number;
  question: string;
  answer?: string;
  followUpReason?: string;
  scoreCard?: ScoreCard;
}

export interface InterviewSessionSnapshot {
  sessionId: string;
  status: SessionStatus;
  realtimeProvider?: RealtimeProvider;
  resumeProfile?: ResumeProfile;
  jobProfile?: JobProfile;
  currentTurn?: InterviewTurn;
  turns: InterviewTurn[];
}

export type ClientRealtimeEvent =
  | {
      type: "session.start";
      sessionId: string;
      provider?: RealtimeProvider;
      instructions?: string;
      voice?: string;
      outputModalities?: Array<"audio" | "text">;
    }
  | {
      type: "audio.chunk";
      sessionId: string;
      chunkId: string;
      mimeType: string;
      payloadBase64: string;
      sampleRate?: 16000 | 24000;
    }
  | {
      type: "answer.commit";
      sessionId: string;
      turnId: string;
    }
  | {
      type: "assistant.interrupt";
      sessionId: string;
      reason: "candidate_barge_in" | "manual_stop";
    }
  | {
      type: "realtime.session.configure";
      sessionId: string;
      provider: "dashscope";
      model: string;
      voice: string;
      instructions: string;
      outputModalities: Array<"audio" | "text">;
    }
  | {
      type: "realtime.response.create";
      sessionId: string;
      response: {
        modalities: Array<"audio" | "text">;
        prompt?: string;
      };
    };

export type ServerRealtimeEvent =
  | {
      type: "session.connected";
      sessionId: string;
      provider: RealtimeProvider;
      phase: RoomPhase;
    }
  | {
      type: "transcript.partial";
      sessionId: string;
      turnId: string;
      text: string;
    }
  | {
      type: "transcript.final";
      sessionId: string;
      turnId: string;
      text: string;
    }
  | {
      type: "interviewer.question";
      sessionId: string;
      turnId: string;
      text: string;
    }
  | {
      type: "score.updated";
      sessionId: string;
      turnId: string;
      scoreCard: ScoreCard;
    }
  | {
      type: "assistant.audio.ready";
      sessionId: string;
      turnId: string;
      audioUrl: string;
    }
  | {
      type: "assistant.audio.delta";
      sessionId: string;
      turnId: string;
      deltaBase64: string;
    }
  | {
      type: "assistant.transcript.done";
      sessionId: string;
      turnId: string;
      text: string;
    }
  | {
      type: "room.phase.changed";
      sessionId: string;
      phase: RoomPhase;
    }
  | {
      type: "provider.error";
      sessionId: string;
      message: string;
      retryable: boolean;
    }
  | {
      type: "report.ready";
      sessionId: string;
      reportId: string;
    };
