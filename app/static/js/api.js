/* ==========================================================================
   api.js — thin client over the docxy REST API.
   Every endpoint returns the {success, data, error} envelope, so unwrapping
   and error normalisation happen in exactly one place.
   ========================================================================== */

const BASE = "/api/v1";

/** An API failure carrying the service's own error code and request id. */
export class ApiError extends Error {
  constructor(message, { code = "UNKNOWN", requestId = null, status = 0, details = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.requestId = requestId;
    this.status = status;
    this.details = details;
  }
}

/* Plain-language text for the codes in app/constants/errors.py. The service
   already sends a readable message; these add the "what to do" half. */
const HINTS = {
  INVALID_PDF_FORMAT: "Only PDF files are accepted — check the file really is a PDF.",
  FILE_TOO_LARGE: "Reduce the file size or raise MAX_UPLOAD_SIZE_MB.",
  EXCEEDS_PAGE_LIMIT: "Split the document or raise MAX_PAGES_PER_DOCUMENT.",
  PDF_CORRUPTED: "The file could not be opened as a PDF.",
  PDF_ENCRYPTED: "Remove the password from the PDF and upload again.",
  JOB_NOT_FOUND: "This job is no longer in the database.",
  MAX_RETRIES_EXCEEDED: "The job exhausted its attempts and will not retry on its own.",
  INVALID_STATE_TRANSITION: "The job has already moved past this action.",
  OCR_DISABLED: "Vision OCR is off — image-based pages keep whatever native text they had.",
  GROQ_RATE_LIMITED: "The Groq quota is spent for this window; the limiter will resume automatically.",
  STORAGE_ERROR: "The file could not be read from storage.",
  SERVICE_UNAVAILABLE: "The service is not accepting work right now.",
};

export function hintFor(code) {
  return HINTS[code] || null;
}

async function request(path, { method = "GET", headers = {}, body = null, signal } = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body, signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Could not reach the service. Is it still running?", {
      code: "NETWORK_ERROR",
    });
  }

  const requestId = res.headers.get("X-Request-ID");
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    /* Non-JSON body (e.g. a proxy error page) — fall through to the status check. */
  }

  if (!res.ok) {
    const e = payload && payload.error ? payload.error : {};
    throw new ApiError(e.message || `Request failed with status ${res.status}`, {
      code: e.code || "HTTP_ERROR",
      requestId: e.request_id || requestId,
      status: res.status,
      details: e.details || null,
    });
  }

  /* Health endpoints are unenveloped; API endpoints are enveloped. */
  return payload && Object.prototype.hasOwnProperty.call(payload, "data") ? payload.data : payload;
}

export const api = {
  listDocuments({ limit = 25, offset = 0, status = null, signal } = {}) {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) q.set("status", status);
    return request(`/documents?${q}`, { signal });
  },

  getDocument(uuid, { signal } = {}) {
    return request(`/documents/${encodeURIComponent(uuid)}`, { signal });
  },

  getText(uuid, { signal } = {}) {
    return request(`/documents/${encodeURIComponent(uuid)}/text`, { signal });
  },

  getPages(uuid, { limit = 2000, offset = 0, signal } = {}) {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return request(`/documents/${encodeURIComponent(uuid)}/pages?${q}`, { signal });
  },

  getJob(jobId, { signal } = {}) {
    return request(`/jobs/${encodeURIComponent(jobId)}`, { signal });
  },

  getJobLogs(jobId, { limit = 100, offset = 0, signal } = {}) {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return request(`/jobs/${encodeURIComponent(jobId)}/logs?${q}`, { signal });
  },

  retryJob(jobId) {
    return request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
  },

  cancelJob(jobId) {
    return request(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  },

  getSettings({ signal } = {}) {
    return request("/settings", { signal });
  },

  /** /health/ready sits outside /api/v1 and is not enveloped. */
  async getReady({ signal } = {}) {
    try {
      const res = await fetch("/health/ready", { signal });
      return await res.json();
    } catch (err) {
      if (err.name === "AbortError") throw err;
      return { status: "unreachable", checks: {} };
    }
  },

  downloadUrl(uuid, fileType) {
    return `${BASE}/documents/${encodeURIComponent(uuid)}/download?file_type=${fileType}`;
  },

  /**
   * Upload via XHR rather than fetch — fetch cannot report upload progress,
   * and a 50 MB PDF on a slow link needs a real percentage, not a spinner.
   */
  upload(file, { idempotencyKey = null, onProgress = null } = {}) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/documents`);
      if (idempotencyKey) xhr.setRequestHeader("Idempotency-Key", idempotencyKey);

      if (onProgress) {
        xhr.upload.addEventListener("progress", (ev) => {
          if (ev.lengthComputable) onProgress(ev.loaded / ev.total);
        });
      }

      xhr.addEventListener("load", () => {
        let payload = null;
        try {
          payload = JSON.parse(xhr.responseText);
        } catch {
          /* handled below */
        }
        if (xhr.status >= 200 && xhr.status < 300 && payload && payload.data) {
          resolve(payload.data);
          return;
        }
        const e = (payload && payload.error) || {};
        reject(
          new ApiError(e.message || `Upload failed with status ${xhr.status}`, {
            code: e.code || "HTTP_ERROR",
            requestId: e.request_id || xhr.getResponseHeader("X-Request-ID"),
            status: xhr.status,
            details: e.details || null,
          })
        );
      });

      xhr.addEventListener("error", () =>
        reject(new ApiError("The upload connection failed.", { code: "NETWORK_ERROR" }))
      );
      xhr.addEventListener("abort", () =>
        reject(new ApiError("Upload cancelled.", { code: "ABORTED" }))
      );

      xhr.send(form);
    });
  },
};
