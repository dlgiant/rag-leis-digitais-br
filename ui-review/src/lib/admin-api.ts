// Phase 11.1 — server-side helper for calling the backend `/v1/admin/*`
// from Astro page frontmatter. Uses the Clerk JWT from Astro.locals.
//
// Browser-side code should NOT import this — it would leak the
// server-only path. Browser-side code calls `/api/admin/...` instead
// (same-origin proxy in src/pages/api/admin/[...path].ts).

const BACKEND_URL =
  process.env.RAG_BACKEND_URL || "https://rag-leis-digitais-br.fly.dev";

export interface AdminFetchOptions {
  token: string;
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined>;
}

export class AdminApiError extends Error {
  constructor(public status: number, public bodyText: string) {
    super(`admin API ${status}: ${bodyText.slice(0, 200)}`);
  }
}

export async function adminFetch<T = unknown>(
  path: string,
  opts: AdminFetchOptions,
): Promise<T> {
  const url = new URL(`${BACKEND_URL}/v1/admin/${path.replace(/^\//, "")}`);
  if (opts.query) {
    for (const [k, v] of Object.entries(opts.query)) {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, String(v));
      }
    }
  }
  const resp = await fetch(url.href, {
    method: opts.method ?? "GET",
    headers: {
      Authorization: `Bearer ${opts.token}`,
      "Content-Type": "application/json",
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new AdminApiError(resp.status, text);
  }
  return (await resp.json()) as T;
}

// Shape of what /v1/admin/eval/queries returns
export interface EvalQueryRow {
  id: string;
  query: string;
  qtype: string | null;
  core_urns: string[];
  supporting_urns: string[];
  notes: string | null;
}

export interface EvalQueriesListResponse {
  total: number;
  limit: number;
  offset: number;
  qtype_filter: string | null;
  rows: EvalQueryRow[];
  viewer: { email: string; is_operator: boolean };
}

// Shape of /v1/admin/eval/queries/{id}
export interface ChunkSummary {
  urn: string;
  document_urn: string;
  label: string;
  nav: string;
  caput: string | null;
  text: string;
  kind: string;
}

export interface EvalQueryDetailResponse extends EvalQueryRow {
  gold_chunks: ChunkSummary[];
  missing_urns: string[];
  viewer: { email: string; is_operator: boolean };
}
