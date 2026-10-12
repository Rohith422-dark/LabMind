import type { Schemas } from "./client";

export type Citation = {
  n: number; document_id: string; chunk_id: string; doc_code: string; title: string;
  version: number; page: number | null; section: string | null; snippet: string; score: number;
};

export type ChatEvent =
  | { type: "meta"; chat_id: string; intent: string }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "safety"; note: string }
  | { type: "inventory"; lots: Schemas["LotOut"][] }
  | { type: "no_match"; gap_id: string }
  | { type: "done" }
  | { type: "error"; message: string };

export type Finding = {
  param: string; kind: string; expected_text: string; actual_text: string | null; tolerance: string;
  result: "ok" | "deviation" | "unstated";
};

export type CompareRow = {
  step_no: number | null; sop_action: string; sop_requirement: string; narrated: string | null;
  status: "followed" | "missing" | "deviation" | "out_of_order" | "confirm";
  is_critical: boolean; findings: Finding[]; flags: string[]; note: string | null;
};

export type TsQuestion = { key: string; step_no: number; question: string; answered?: boolean };
export type SopRef = { id: string; doc_code: string; version: number; title: string; status: string };

export type TsEvent =
  | { type: "stage"; stage: string }
  | { type: "session"; session_id: string; document: SopRef }
  | { type: "comparison"; rows: CompareRow[]; narrated: unknown[] }
  | { type: "questions"; questions: TsQuestion[] }
  | { type: "no_sop"; gap_id: string }
  | { type: "done" }
  | { type: "error"; message: string };

export type Diagnosis = {
  causes: { rank: number; cause: string; evidence: string; linked_step_no: number | null; guide_citation: number | null }[];
  next_actions: string[];
  deviation_advice: string | null;
};

export type DiagnoseResult = {
  session_id: string; document: SopRef; diagnosis: Diagnosis; warnings: string[];
  citations: Citation[]; comparison: CompareRow[];
};

export type ExternalResult = Schemas["ExternalOut"];
export type DemoQuestion = {
  role: string; question: string; kind: "answerable" | "not_covered" | "troubleshoot_narration";
  expected_doc_code?: string; expected_page?: number; symptom?: string;
};
