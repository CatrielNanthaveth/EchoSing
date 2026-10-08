// Friendly aliases for the types generated from the backend's OpenAPI contract
// (`npm run gen:api` regenerates schema.d.ts; never edit it by hand).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SongSummary = Schemas["SongSummary"];
export type SongPage = Schemas["SongPage"];
export type SongDetail = Schemas["SongDetail"];
export type LyricLine = Schemas["LyricLine"];
export type Word = Schemas["Word"];
export type PitchResponse = Schemas["PitchResponse"];
export type SessionCreate = Schemas["SessionCreate"];
export type SessionCreated = Schemas["SessionCreated"];
export type SessionResults = Schemas["SessionResults"];
export type SessionTotals = Schemas["SessionTotals"];
export type LineReport = Schemas["LineReport"];
export type LinePractice = Schemas["LinePractice"];
export type LineAnalysis = Schemas["LineAnalysis"];
export type LineAttempt = Schemas["LineAttempt"];
export type PracticeWord = Schemas["PracticeWord"];
export type LineDiagnostics = Schemas["LineDiagnostics"];
export type WordDiagnostics = Schemas["WordDiagnostics"];

// Real-time protocol (docs/ws-protocol.md).
export type LinePitchMessage = Schemas["LinePitchMessage"];
export type FinishMessage = Schemas["FinishMessage"];
export type ClientMessage = LinePitchMessage | FinishMessage;
export type ReadyMessage = Schemas["ReadyMessage"];
export type LineScoreMessage = Schemas["LineScoreMessage"];
export type ErrorMessage = Schemas["ErrorMessage"];
export type SessionSummaryMessage = Schemas["SessionSummaryMessage"];
export type ServerMessage =
  ReadyMessage | LineScoreMessage | ErrorMessage | SessionSummaryMessage;
