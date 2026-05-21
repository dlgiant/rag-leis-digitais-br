// Phase 11.1 — server-side helper for calling the backend `/v1/admin/*`
// from Astro page frontmatter. Uses the Clerk JWT from Astro.locals.
//
// Browser-side code should NOT import this — it would leak the
// server-only path. Browser-side code calls `/api/admin/...` instead
// (same-origin proxy in src/pages/api/admin/[...path].ts).

// Resolve the backend URL with defensive normalization. Common
// paste-from-editor failure modes that all break `new URL()`:
//   - Trailing newline (from text editors that auto-newline pastes)
//   - Embedded newline / carriage return (multi-line paste collapsed
//     into one env var)
//   - Trailing slash (changes path-joining semantics)
//   - Zero-width characters (BOM, U+200B) from copy/paste artifacts
// Strip ALL whitespace (not just leading/trailing) — a URL can't
// legally contain whitespace anywhere. Surface the resolved value
// in errors so deploy bugs are diagnosable from one log line.
function resolveBackendUrl(): string {
  const raw = process.env.RAG_BACKEND_URL ?? "";
  // Strip every whitespace char (incl. embedded \n, \r, \t) AND
  // common zero-width chars that copy/paste tools add silently.
  // ALSO normalize Unicode dashes — Notion/Google Docs/Slack/etc.
  // auto-convert ASCII hyphens (U+002D) to U+2010/U+2013/U+2014
  // during copy-paste. Visually identical, but Node's URL parser
  // punycode-encodes them into "xn--..." hostnames that don't
  // resolve in DNS → ENOTFOUND.
  const cleaned = raw
    .replace(/[\s​‌‍﻿]+/g, "")
    .replace(/[‐‑‒–—―−﹣－]/g, "-");
  const candidate = cleaned || "https://rag-leis-digitais-br.fly.dev";
  return candidate.replace(/\/+$/, "");
}

const BACKEND_URL = resolveBackendUrl();

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

  /** Friendly, non-leaking message for end users (lawyer, etc.) */
  userMessage(): string {
    if (this.status === 0) return "Não foi possível contatar o backend. Tente novamente em alguns instantes.";
    if (this.status === 401) return "Sessão expirada. Saia e entre novamente.";
    if (this.status === 403) return "Seu e-mail não está autorizado para esta área.";
    if (this.status === 404) return "Recurso não encontrado.";
    if (this.status === 429) return "Limite de requisições atingido. Tente novamente em um minuto.";
    if (this.status >= 500) return "Backend indisponível. Verifique o status do serviço.";
    return `Erro ${this.status}.`;
  }

  /** Full diagnostic message — internal infrastructure detail, do not show by default. */
  verboseMessage(): string {
    return `${this.status}: ${this.bodyText}`;
  }
}

/**
 * Decide whether the current request wants verbose error detail.
 *
 * Two toggles, either enables verbose:
 *   - `?debug=1` query param on the page URL (ad-hoc; no redeploy)
 *   - `RAG_VERBOSE_ERRORS=true` env var (persistent override)
 *
 * Default (neither set): friendly, non-leaking error messages only.
 * Internal URLs, env-var names, Node error codes never reach the
 * browser unless verbose is explicitly on.
 */
export function isVerbose(url: URL): boolean {
  if (url.searchParams.get("debug") === "1") return true;
  if (process.env.RAG_VERBOSE_ERRORS === "true") return true;
  return false;
}

/**
 * Format a thrown error for display, respecting verbose mode.
 * `e` may be an AdminApiError (preferred) or any thrown value.
 */
export function formatError(e: unknown, verbose: boolean): string {
  if (e instanceof AdminApiError) {
    return verbose ? e.verboseMessage() : e.userMessage();
  }
  if (verbose) {
    return e instanceof Error ? e.message : String(e);
  }
  return "Erro inesperado. Tente novamente.";
}

export async function adminFetch<T = unknown>(
  path: string,
  opts: AdminFetchOptions,
): Promise<T> {
  const urlString = `${BACKEND_URL}/v1/admin/${path.replace(/^\//, "")}`;
  let url: URL;
  try {
    url = new URL(urlString);
  } catch (e) {
    throw new AdminApiError(
      0,
      `Invalid backend URL ${JSON.stringify(urlString)} (BACKEND_URL resolved to ${JSON.stringify(BACKEND_URL)}; raw env var was ${JSON.stringify(process.env.RAG_BACKEND_URL ?? null)}). Check Vercel project Environment Variables.`,
    );
  }
  if (opts.query) {
    for (const [k, v] of Object.entries(opts.query)) {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, String(v));
      }
    }
  }
  let resp: Response;
  try {
    resp = await fetch(url.href, {
      method: opts.method ?? "GET",
      headers: {
        Authorization: `Bearer ${opts.token}`,
        "Content-Type": "application/json",
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    // Node 20's fetch throws "fetch failed" with the actual cause
    // (ECONNREFUSED, ENOTFOUND, AbortError, TLS error, etc.) in
    // err.cause. Surface it so deploy debugging doesn't require
    // SSH into the runtime.
    const err = e as Error & { cause?: { code?: string; message?: string; name?: string } };
    const causeCode = err.cause?.code ?? err.cause?.name ?? "unknown";
    const causeMsg = err.cause?.message ?? "";
    throw new AdminApiError(
      0,
      `fetch failed → ${url.href} (cause: ${causeCode}${causeMsg ? `: ${causeMsg.slice(0, 200)}` : ""})`,
    );
  }
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
