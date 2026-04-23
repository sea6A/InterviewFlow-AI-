export interface SessionReport {
  reportId: string;
  sessionId: string;
  overallScore: number;
  strengths: string[];
  weaknesses: string[];
  followUpSuggestions: string[];
  improvedAnswerExample: string;
  nextTrainingPlan: string[];
}
