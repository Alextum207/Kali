// Thin client for the FastAPI backend's JSON API (app/main.py's /api/scans
// routes). Used by CaseAnalysis.tsx to start and poll a scan, and by
// Dashboard.tsx to list scans.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Finding {
  id: number;
  scan_id: number;
  pattern_type: string;
  target_norm: string;
  confidence_score: number;
  evidence_data: Record<string, unknown>;
  created_at: string;
  page_id: number | null;
  page_url: string;
  screenshot_url: string | null;
}

export interface Page {
  id: number;
  scan_id: number;
  url: string;
  category: string | null;
  crawled_at: string;
}

export interface Risk {
  // app/compliance.py::aggregate_risk_score — score is 0.0-1.0, not /10.
  score: number;
  level: "niedrig" | "mittel" | "hoch";
  by_category: Record<string, number>;
}

export interface Scan {
  id: number;
  url: string;
  status: "running" | "done" | "error";
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
  risk: Risk;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`${path} -> ${res.status}`);
  }
  return res.json();
}

export const getScans = () => getJSON<Scan[]>("/api/scans");

export const getScan = (scanId: number) =>
  getJSON<{ scan: Scan; pages: Page[]; findings: Finding[] }>(`/api/scans/${scanId}`);

export const getPageFindings = (scanId: number, pageId: number) =>
  getJSON<{ scan: Scan; findings: Finding[] }>(`/api/scans/${scanId}/pages/${pageId}`);

export async function postScan(url: string, maxPages?: number): Promise<{ scan_id: number }> {
  const res = await fetch(`${API_BASE_URL}/api/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, max_pages: maxPages }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `POST /api/scans -> ${res.status}`);
  }
  return res.json();
}
