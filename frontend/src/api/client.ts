import axios from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const api = axios.create({ baseURL: API_BASE_URL });

// FastAPI's `detail` is usually a string, but a 422 validation error sends
// a list of {type, loc, msg, input} objects -- React can't render that
// directly, so every page should format errors through this helper.
export function formatApiError(err: any): string {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === 'string' ? d : d.msg ?? JSON.stringify(d))).join('; ');
  }
  if (detail) return JSON.stringify(detail);
  return err?.message ?? 'Unknown error';
}

// DEMO-ONLY organisation context: every request carries the selected
// organisation/user as headers instead of a real auth token. See
// src/context/DemoContext.tsx and backend app/core/demo_context.py.
export function setDemoHeaders(organisationId: string | null, userId: string | null) {
  if (organisationId) api.defaults.headers.common['X-Organisation-Id'] = organisationId;
  else delete api.defaults.headers.common['X-Organisation-Id'];

  if (userId) api.defaults.headers.common['X-User-Id'] = userId;
  else delete api.defaults.headers.common['X-User-Id'];
}

// Phase 9 Stage 2: real JWT auth, coexisting with the demo headers above.
// The backend prioritises a Bearer token over X-Organisation-Id/X-User-Id
// whenever one is present (app/core/demo_context.py) -- so once logged
// in, this silently supersedes the demo-context headers with no other
// frontend change required.
const TOKEN_STORAGE_KEY = 'clarivue_access_token';

export function setAuthToken(token: string | null) {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    delete api.defaults.headers.common['Authorization'];
  }
}

export function clearAuthToken() {
  setAuthToken(null);
  onUnauthorized?.();
}

export async function fetchAuthenticatedImage(url: string, signal: AbortSignal): Promise<Blob> {
  const token = getStoredAuthToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  else {
    // Retain local demo-mode support. Production with REQUIRE_JWT_AUTH=true
    // always takes the Bearer branch.
    const common = api.defaults.headers.common as Record<string, string | undefined>;
    if (common['X-Organisation-Id']) headers.set('X-Organisation-Id', common['X-Organisation-Id']);
    if (common['X-User-Id']) headers.set('X-User-Id', common['X-User-Id']);
  }
  const response = await fetch(url, { headers, signal });
  if (response.status === 401 && token) clearAuthToken();
  if (!response.ok) throw new Error(`Image request failed (${response.status}).`);
  return response.blob();
}

export function getStoredAuthToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export type AuthUser = { id: string; name: string; email: string; role: string; organisation_id: string };
export type LoginResponse = { access_token: string; token_type: string; expires_in: number; user: AuthUser };

export const authApi = {
  login: (email: string, password: string) => api.post<LoginResponse>('/api/auth/login', { email, password }),
  logout: () => api.post('/api/auth/logout'),
  me: () => api.get<AuthUser>('/api/auth/me'),
};

// A 401 means the stored token is missing/invalid/expired -- clear it so
// the app falls back to (or the user is prompted back to) a clean state,
// rather than every page silently re-sending a dead token forever.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401 && getStoredAuthToken()) {
      clearAuthToken();
    }
    return Promise.reject(err);
  },
);

export type Organisation = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
};

export type DemoUser = {
  id: string;
  organisation_id: string;
  name: string;
  email: string;
  role: 'admin' | 'creator' | 'reviewer';
  created_at: string;
  updated_at: string;
};

// Phase 7 Stage 2: a real, database-driven dashboard. Every field below is
// computed server-side from actual MongoDB records for the active
// organisation -- see backend/app/routers/dashboard.py.

export type SubmissionStatusCounts = {
  total: number;
  draft: number;
  pending_review: number;
  changes_requested: number;
  approved: number;
  rejected: number;
  with_ai_findings: number;
};

export type OpenIssuesSummary = {
  open_total: number;
  by_severity: { high: number; medium: number; low: number };
};

export type ReviewStatsSummary = {
  pending: number;
  completed: number;
  currently_approved: number;
  currently_rejected: number;
};

export type RecentActivityEntry = {
  id: string;
  action: string;
  actor_name: string | null;
  submission_id: string | null;
  submission_title: string | null;
  created_at: string;
};

export type DashboardSummary = {
  guideline_docs: number;
  brand_facts: number;
  terminology: number;
  claim_policies: number;
  assets: number;
  submissions: SubmissionStatusCounts;
  issues: OpenIssuesSummary;
  reviews: ReviewStatsSummary;
  recent_activity: RecentActivityEntry[];
};

export const ACTIVITY_ACTION_LABELS: Record<string, string> = {
  submission_created: 'Submission created',
  submission_submitted: 'Submitted for review',
  submission_resubmitted: 'Resubmitted for review',
  submission_analyzed: 'AI analysis completed',
  submission_approved: 'Approved',
  submission_rejected: 'Rejected',
  submission_changes_requested: 'Changes requested',
  finding_accepted: 'Suggestion accepted',
  finding_dismissed: 'Suggestion dismissed',
};

export type GuidelineDoc = {
  id: string;
  organisation_id: string;
  title: string;
  filename: string;
  uploaded_by: string;
  page_count: number;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  created_at: string;
  updated_at: string;
};

export type GuidelineChunk = {
  id: string;
  doc_id: string;
  page: number;
  chunk_index: number;
  text: string;
  embedding: number[] | null;
};

export type BrandFact = {
  id: string;
  organisation_id: string;
  subject: string;
  attribute: string;
  value: string;
  unit: string | null;
  valid_from: string;
  valid_to: string | null;
  source_doc_id: string | null;
  page: number | null;
  quote: string | null;
};

export type Terminology = {
  id: string;
  organisation_id: string;
  preferred_term: string;
  banned_variants: string[];
  reason: string;
};

export type ClaimPolicy = {
  id: string;
  organisation_id: string;
  pattern: string;
  status: 'approved' | 'needs_evidence' | 'banned';
  required_disclaimer: string | null;
};

export type Asset = {
  id: string;
  organisation_id: string;
  type: 'logo' | 'colour';
  name: string;
  status: 'approved' | 'deprecated';
  file_path: string | null;
  hex_value: string | null;
};

export const demoApi = {
  organisations: () => api.get<Organisation[]>('/api/demo/organisations'),
  usersFor: (orgId: string) => api.get<DemoUser[]>(`/api/demo/organisations/${orgId}/users`),
};

export const dashboardApi = {
  summary: () => api.get<DashboardSummary>('/api/dashboard/summary'),
};

// Phase 8 Stage 1: analytics over existing findings/guideline data.
export type FindingCategoryCount = { category: string; severity: string; count: number };
export type TerminologyViolation = { terminology_id: string; preferred_term: string | null; count: number };
export type ClaimPolicyViolation = { claim_policy_id: string; pattern: string | null; count: number };

export type AnalyticsSummary = {
  findings_by_category: FindingCategoryCount[];
  top_terminology_violations: TerminologyViolation[];
  top_claim_policy_violations: ClaimPolicyViolation[];
  insufficient_evidence_count: number;
  unembedded_guideline_chunks: number;
};

export const analyticsApi = {
  summary: () => api.get<AnalyticsSummary>('/api/analytics/summary'),
};

export const guidelinesApi = {
  list: () => api.get<GuidelineDoc[]>('/api/guidelines'),
  get: (id: string) => api.get<GuidelineDoc>(`/api/guidelines/${id}`),
  chunks: (id: string) => api.get<GuidelineChunk[]>(`/api/guidelines/${id}/chunks`),
  upload: (file: File, title?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (title) form.append('title', title);
    return api.post<GuidelineDoc>('/api/guidelines', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  remove: (id: string) => api.delete(`/api/guidelines/${id}`),
};

export const brandFactsApi = {
  list: () => api.get<BrandFact[]>('/api/brand-facts'),
  create: (data: Partial<BrandFact>) => api.post<BrandFact>('/api/brand-facts', data),
  update: (id: string, data: Partial<BrandFact>) => api.patch<BrandFact>(`/api/brand-facts/${id}`, data),
  remove: (id: string) => api.delete(`/api/brand-facts/${id}`),
};

export const terminologyApi = {
  list: () => api.get<Terminology[]>('/api/terminology'),
  create: (data: Partial<Terminology>) => api.post<Terminology>('/api/terminology', data),
  update: (id: string, data: Partial<Terminology>) => api.patch<Terminology>(`/api/terminology/${id}`, data),
  remove: (id: string) => api.delete(`/api/terminology/${id}`),
};

export const claimPoliciesApi = {
  list: () => api.get<ClaimPolicy[]>('/api/claim-policies'),
  create: (data: Partial<ClaimPolicy>) => api.post<ClaimPolicy>('/api/claim-policies', data),
  update: (id: string, data: Partial<ClaimPolicy>) => api.patch<ClaimPolicy>(`/api/claim-policies/${id}`, data),
  remove: (id: string) => api.delete(`/api/claim-policies/${id}`),
};

export type SubmissionStatus = 'draft' | 'pending_review' | 'changes_requested' | 'approved' | 'rejected';

export type Submission = {
  id: string;
  organisation_id: string;
  title: string;
  creator_id: string;
  current_revision: number;
  status: SubmissionStatus;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Revision = {
  id: string;
  organisation_id: string;
  submission_id: string;
  version: number;
  content: string;
  content_type: string;
  author_id: string;
  image_path: string | null;
  created_at: string;
  updated_at: string;
};

export type SampleAd = { title: string; content: string };

export type DiffLine = { type: 'equal' | 'added' | 'removed'; text: string };

export type DiffResult = { from_version: number; to_version: number; diff: DiffLine[] };

// Human-facing label for each status -- the spec calls for "pending_review"
// to read as "Submitted" in the UI without introducing a new status value.
export const SUBMISSION_STATUS_LABELS: Record<SubmissionStatus, string> = {
  draft: 'Draft',
  pending_review: 'Submitted',
  changes_requested: 'Changes Requested',
  approved: 'Approved',
  rejected: 'Rejected',
};

// --- Phase 6: evidence validation, AI-powered correction suggestions, and
// accept/dismiss. Mirrors the backend's app/models/finding.py exactly --
// EvidenceStatus is a separate dimension from Verdict, never confused
// with it (see that file's docstrings).

export type FindingCategory = 'fact' | 'terminology' | 'claim' | 'tone' | 'visual' | 'accessibility';
export type FindingSeverity = 'high' | 'medium' | 'low';
export type Verdict = 'contradicted' | 'outdated' | 'unsupported' | 'verified' | 'needs_review';
export type FindingSourceType = 'rule' | 'llm' | 'vision';
export type FindingDecisionStatus = 'open' | 'accepted' | 'dismissed';
export type EvidenceStatus = 'supported' | 'contradicted' | 'insufficient' | 'needs_review';

export type EvidenceReference = {
  status: EvidenceStatus;
  reason: string;
  source_type: string | null;
  source_id: string | null;
  guideline_doc_id: string | null;
  guideline_doc_title: string | null;
  page: number | null;
  source_text: string | null;
  quote: string | null;
  quote_verified: boolean;
  unavailable: boolean;
};

export type CorrectionSuggestion = {
  corrected_span: string | null;
  rationale: string;
  requires_human_review: boolean;
  source: FindingSourceType;
  generated_at: string;
  model: string | null;
};

export type Finding = {
  id: string;
  organisation_id: string;
  revision_id: string;
  category: FindingCategory;
  severity: FindingSeverity;
  span_text: string;
  explanation: string;
  verdict: Verdict;
  evidence_record_type: string | null;
  evidence_record_id: string | null;
  evidence_quote: string | null;
  suggestion: string | null;
  source: FindingSourceType;
  status: FindingDecisionStatus;
  dismiss_reason: string | null;
  evidence: EvidenceReference | null;
  correction: CorrectionSuggestion | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AICheckOutcome = { check: string; reason: string };

export type AnalysisReport = {
  submission_id: string;
  revision_id: string;
  revision_version: number;
  findings_count: number;
  ai_available: boolean;
  ai_checks_completed: string[];
  ai_checks_unavailable: AICheckOutcome[];
  used_cache: boolean;
};

export const FINDING_VERDICT_LABELS: Record<Verdict, string> = {
  contradicted: 'Contradicted',
  outdated: 'Outdated',
  unsupported: 'Unsupported',
  verified: 'Verified',
  needs_review: 'Needs Review',
};

export const EVIDENCE_STATUS_LABELS: Record<EvidenceStatus, string> = {
  supported: 'Supported',
  contradicted: 'Evidence Conflicts',
  insufficient: 'Insufficient Evidence',
  needs_review: 'Needs Review',
};

// --- Phase 7: reviewer approve/reject/request-changes + review history.
// Deliberately separate from accepting/dismissing an AI correction
// suggestion (Phase 6) -- that is a decision about one finding's proposed
// text, this is the reviewer's decision on the submission as a whole.

export type ReviewDecision = 'approved' | 'rejected' | 'changes_requested';

export type Review = {
  id: string;
  organisation_id: string;
  submission_id: string;
  revision_id: string;
  reviewer_id: string;
  decision: ReviewDecision;
  comment: string | null;
  created_at: string;
  updated_at: string;
};

export const REVIEW_DECISION_LABELS: Record<ReviewDecision, string> = {
  approved: 'Approved',
  rejected: 'Rejected',
  changes_requested: 'Changes Requested',
};

export const submissionsApi = {
  list: () => api.get<Submission[]>('/api/submissions'),
  get: (id: string) => api.get<Submission>(`/api/submissions/${id}`),
  content: (id: string) => api.get<Revision>(`/api/submissions/${id}/content`),
  samples: () => api.get<SampleAd[]>('/api/submissions/samples'),
  create: (title: string, content: string, content_type = 'text/plain') =>
    api.post<Submission>('/api/submissions', { title, content, content_type }),
  uploadPdf: (file: File, title?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (title) form.append('title', title);
    return api.post<Submission>('/api/submissions/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadImage: (file: File, title?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (title) form.append('title', title);
    return api.post<Submission>('/api/submissions/upload-image', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  // Query params, not headers: an <img src=...> can't attach custom headers.
  imageUrl: (submissionId: string, version: number) =>
    `${API_BASE_URL}/api/submissions/${submissionId}/revisions/${version}/image`,
  updateDraft: (id: string, data: { title?: string; content?: string }) =>
    api.patch<Submission>(`/api/submissions/${id}/draft`, data),
  submit: (id: string) => api.post<Submission>(`/api/submissions/${id}/submit`),
  revise: (id: string, content: string) =>
    api.post<{ submission: Submission; revision: Revision }>(`/api/submissions/${id}/revise`, { content }),
  revisions: (id: string) => api.get<Revision[]>(`/api/submissions/${id}/revisions`),
  revision: (id: string, version: number) => api.get<Revision>(`/api/submissions/${id}/revisions/${version}`),
  compare: (id: string, fromVersion: number, toVersion: number) =>
    api.get<DiffResult>(`/api/submissions/${id}/compare`, { params: { from_version: fromVersion, to_version: toVersion } }),

  // Phase 5: AI-assisted + rule-based analysis.
  analyze: (id: string) => api.post<AnalysisReport>(`/api/submissions/${id}/analyze`),
  findings: (id: string) => api.get<Finding[]>(`/api/submissions/${id}/findings`),

  // Phase 6: evidence validation, correction suggestions, accept/dismiss.
  evidence: (submissionId: string, findingId: string, refresh = false) =>
    api.get<EvidenceReference>(`/api/submissions/${submissionId}/findings/${findingId}/evidence`, { params: { refresh } }),
  generateSuggestion: (submissionId: string, findingId: string, refresh = false) =>
    api.post<Finding>(`/api/submissions/${submissionId}/findings/${findingId}/suggestion`, undefined, { params: { refresh } }),
  acceptSuggestion: (submissionId: string, findingId: string) =>
    api.post<{ finding: Finding; preview_content: string | null }>(`/api/submissions/${submissionId}/findings/${findingId}/accept`),
  dismissSuggestion: (submissionId: string, findingId: string, reason?: string) =>
    api.post<Finding>(`/api/submissions/${submissionId}/findings/${findingId}/dismiss`, reason ? { reason } : {}),

  // Phase 7: reviewer decisions + review history.
  approve: (id: string, comment?: string) =>
    api.post<{ submission: Submission; review: Review }>(`/api/submissions/${id}/approve`, comment ? { comment } : {}),
  reject: (id: string, comment: string) =>
    api.post<{ submission: Submission; review: Review }>(`/api/submissions/${id}/reject`, { comment }),
  requestChanges: (id: string, comment: string) =>
    api.post<{ submission: Submission; review: Review }>(`/api/submissions/${id}/request-changes`, { comment }),
  reviews: (id: string) => api.get<Review[]>(`/api/submissions/${id}/reviews`),
};

export const assetsApi = {
  list: () => api.get<Asset[]>('/api/assets'),
  createColour: (data: { name: string; status: string; hex_value: string }) =>
    api.post<Asset>('/api/assets', { type: 'colour', ...data }),
  uploadLogo: (file: File, name: string, status: string) => {
    const form = new FormData();
    form.append('file', file);
    form.append('name', name);
    form.append('status', status);
    return api.post<Asset>('/api/assets/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  update: (id: string, data: Partial<Asset>) => api.patch<Asset>(`/api/assets/${id}`, data),
  remove: (id: string) => api.delete(`/api/assets/${id}`),
  // Query params, not headers: an <img src=...> can't attach custom headers.
  fileUrl: (id: string) => `${API_BASE_URL}/api/assets/${id}/file`,
};
