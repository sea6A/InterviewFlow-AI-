import type {
  InterviewSessionSnapshot,
  RoomPhase,
  ScoreCard,
  ServerRealtimeEvent,
} from "../../../../../packages/shared/src/interview";

export interface InterviewRoomState {
  session: InterviewSessionSnapshot | null;
  phase: RoomPhase;
  liveTranscript: string;
  finalTranscript: string;
  latestQuestion: string;
  latestAssistantTranscript: string;
  latestScore?: ScoreCard;
  latestAudioUrl?: string;
  latestAudioDelta?: string;
  providerError?: string;
}

export const initialInterviewRoomState: InterviewRoomState = {
  session: null,
  phase: "idle",
  liveTranscript: "",
  finalTranscript: "",
  latestQuestion: "",
  latestAssistantTranscript: "",
};

export function reduceInterviewRoomEvent(
  state: InterviewRoomState,
  event: ServerRealtimeEvent,
): InterviewRoomState {
  switch (event.type) {
    case "session.connected":
      return {
        ...state,
        phase: event.phase,
      };
    case "room.phase.changed":
      return {
        ...state,
        phase: event.phase,
      };
    case "transcript.partial":
      return {
        ...state,
        liveTranscript: event.text,
      };
    case "transcript.final":
      return {
        ...state,
        liveTranscript: "",
        finalTranscript: event.text,
      };
    case "interviewer.question":
      return {
        ...state,
        latestQuestion: event.text,
      };
    case "score.updated":
      return {
        ...state,
        latestScore: event.scoreCard,
      };
    case "assistant.audio.ready":
      return {
        ...state,
        latestAudioUrl: event.audioUrl,
      };
    case "assistant.audio.delta":
      return {
        ...state,
        latestAudioDelta: event.deltaBase64,
      };
    case "assistant.transcript.done":
      return {
        ...state,
        latestAssistantTranscript: event.text,
      };
    case "provider.error":
      return {
        ...state,
        providerError: event.message,
      };
    default:
      return state;
  }
}
