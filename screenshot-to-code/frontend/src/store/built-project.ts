export type BuiltSourceFile = { path: string; content: string };
export type BuiltCheck = { id: string; status: string; message: string };
export type BuiltCandidate = {
  candidate_name?: string; engine?: string; engine_version?: string; agent_run_id?: string;
  provider?: string; model?: string; tools?: { type?: string; name?: string; ok?: boolean }[];
  files: BuiltSourceFile[]; checks?: BuiltCheck[]; build_details?: string;
  revision?: { kind: string }; previous_candidate?: BuiltCandidate;
};
export type BuiltProjectRun = {
  run_id: string; status: string; error: string | null; model_requests: number; repairs: number;
  result: BuiltCandidate | null;
};
