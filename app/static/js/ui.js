/* ==========================================================================
   ui.js — formatting, status vocabulary, icons and small render helpers.
   Icons are inline SVG in the Phosphor outline style (no emoji, no icon font).
   ========================================================================== */

/* --- Escaping -------------------------------------------------------------
   Filenames and API messages are interpolated into HTML, so they get escaped
   at the single point where they enter markup. */
export function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* --- Formatters ---------------------------------------------------------- */

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}

export function formatDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

export function formatNumber(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("en-US");
}

/** SQLite writes naive UTC timestamps; treat a missing zone as UTC. */
function parseTimestamp(value) {
  if (!value) return null;
  let s = String(value).trim().replace(" ", "T");
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatRelative(value) {
  const d = parseTimestamp(value);
  if (!d) return "—";
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 604800) return `${Math.round(diff / 86400)} d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatAbsolute(value) {
  const d = parseTimestamp(value);
  return d ? d.toLocaleString() : "—";
}

/* --- Status vocabulary ---------------------------------------------------
   The API lowercases job status but leaves document status uppercase, so
   everything is normalised here before it reaches a template. */

const TERMINAL = new Set(["done", "failed", "cancelled"]);

export function isTerminal(jobStatus) {
  return TERMINAL.has(String(jobStatus || "").toLowerCase());
}

export function isActive(jobStatus) {
  const s = String(jobStatus || "").toLowerCase();
  return s !== "" && !TERMINAL.has(s);
}

const JOB_TONE = {
  queued: "idle",
  retrying: "warn",
  running: "active",
  processing: "active",
  ocr_pending: "active",
  ocr_processing: "active",
  generating_text: "active",
  uploading: "active",
  done: "ok",
  failed: "error",
  cancelled: "idle",
};

const DOC_TONE = {
  uploaded: "idle",
  processing: "active",
  completed: "ok",
  failed: "error",
};

export function jobTone(status) {
  return JOB_TONE[String(status || "").toLowerCase()] || "idle";
}

export function docTone(status) {
  return DOC_TONE[String(status || "").toLowerCase()] || "idle";
}

export function humanise(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .toUpperCase();
}

export function badge(text, tone, { dot = true } = {}) {
  return `<span class="badge badge-${tone}">${
    dot ? '<span class="badge-dot" aria-hidden="true"></span>' : ""
  }${esc(humanise(text) || "—")}</span>`;
}

/* --- Pipeline phases -----------------------------------------------------
   The service exposes ten JobStage values. Ten steps is more than a rail can
   read at a glance, so they collapse into the five phases an operator cares
   about. Order matches app/constants/statuses.py. */

export const PHASES = [
  { key: "validate", label: "Validate", stages: ["validation", "s3_upload_original"] },
  { key: "inspect", label: "Inspect", stages: ["page_inspection"] },
  { key: "extract", label: "Extract", stages: ["native_extraction"] },
  { key: "ocr", label: "OCR", stages: ["ocr_processing"] },
  {
    key: "finalise",
    label: "Finalise",
    stages: ["text_aggregation", "txt_generation", "s3_upload_txt", "completed"],
  },
];

export function phaseIndexForStage(stage) {
  const s = String(stage || "").toLowerCase();
  const i = PHASES.findIndex((p) => p.stages.includes(s));
  return i === -1 ? 0 : i;
}

/** Per-phase state for the rail: done | current | failed | todo. */
export function phaseStates(job) {
  const status = String(job.status || "").toLowerCase();
  const stage = String(job.stage || "").toLowerCase();

  if (status === "done" || stage === "completed") return PHASES.map(() => "done");

  const current = stage === "failed" ? phaseIndexForStage(job.last_stage) : phaseIndexForStage(stage);

  return PHASES.map((_, i) => {
    if (i < current) return "done";
    if (i > current) return "todo";
    if (status === "failed" || stage === "failed") return "failed";
    return isTerminal(status) ? "done" : "current";
  });
}

/* --- Icons ---------------------------------------------------------------
   Outline set, 24px viewBox, currentColor, stroke 1.75. Decorative by
   default; callers that need a name pass a title through `label`. */

const PATHS = {
  fileText:
    '<path d="M14 3v5h5M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M9 13h6M9 17h4"/>',
  tray: '<path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3M12 4v10m0 0 4-4m-4 4-4-4"/>',
  download: '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5"/>',
  copy:
    '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/>',
  check: '<path d="M5 13l4.5 4.5L19 7"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  warning: '<path d="M12 9v5M12 17.5h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  arrowLeft: '<path d="M19 12H5m0 0 6-6m-6 6 6 6"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.7-6M20 4v5h-5"/>',
  prohibit: '<circle cx="12" cy="12" r="9"/><path d="M6 18 18 6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
  pulse: '<path d="M2 12h4l2.5-7 3.5 14 3-7h7"/>',
  database:
    '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  drive: '<rect x="2" y="7" width="20" height="10" rx="2"/><path d="M6 12h.01M10 12h6"/>',
  eye: '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/><circle cx="12" cy="12" r="2.8"/>',
  gear:
    '<circle cx="12" cy="12" r="3"/><path d="M12 2.5 13 5l2.6-.6 1.3 2.3-1.8 2 1.8 2-1.3 2.3-2.6-.6-1 2.5h-2l-1-2.5-2.6.6L5.1 12.7l1.8-2-1.8-2 1.3-2.3L9 7l1-2.5h2Z"/>',
  scan: '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M4 12h16"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
};

export function icon(name, { size = 20, label = null, className = "" } = {}) {
  const d = PATHS[name];
  if (!d) return "";
  const a11y = label
    ? `role="img" aria-label="${esc(label)}"`
    : 'aria-hidden="true" focusable="false"';
  return `<svg ${a11y} class="${esc(className)}" width="${size}" height="${size}" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
}

/* --- Toasts -------------------------------------------------------------- */

const ICON_FOR_KIND = { error: "warning", ok: "check", info: "pulse" };

export function toast(message, { kind = "info", code = null, ttl = 6000 } = {}) {
  const stack = document.getElementById("toasts");
  if (!stack) return;

  const el = document.createElement("div");
  el.className = "toast";
  el.dataset.kind = kind;
  /* role=alert so failures are announced, not only coloured. */
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.innerHTML = `
    <span style="color: var(--${kind === "error" ? "danger" : kind === "ok" ? "ok" : "accent-text"}); flex: none;">
      ${icon(ICON_FOR_KIND[kind] || "pulse")}
    </span>
    <span style="flex: 1; min-width: 0;">
      ${esc(message)}
      ${code ? `<br><span class="toast-code">${esc(code)}</span>` : ""}
    </span>`;

  stack.appendChild(el);
  window.setTimeout(() => el.remove(), ttl);
}

/* --- Misc helpers ------------------------------------------------------- */

export function shortId(uuid, head = 8) {
  const s = String(uuid || "");
  return s.length > head ? `${s.slice(0, head)}…` : s || "—";
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function skeletonRows(count, height = "1rem") {
  return Array.from(
    { length: count },
    () => `<div class="skeleton" style="height:${height}"></div>`
  ).join("");
}


/* --- Page classification -------------------------------------------------
   The four PageType values from app/constants/statuses.py, in the order they
   appear in a legend: cheapest path first. */

export const PAGE_TYPES = [
  { key: "NATIVE_TEXT", label: "Native text", note: "read from the PDF text layer" },
  { key: "IMAGE_BASED", label: "Image based", note: "sent to the vision model" },
  { key: "MIXED", label: "Mixed", note: "text layer plus significant imagery" },
  { key: "EMPTY", label: "Empty", note: "no text and no imagery" },
];

const PAGE_TYPE_LABEL = Object.fromEntries(PAGE_TYPES.map((t) => [t.key, t.label]));

export function pageTypeLabel(key) {
  return PAGE_TYPE_LABEL[key] || humanise(key);
}

/** Tooltip text for one page cell — the non-colour carrier of the same fact. */
export function pageCellTitle(page) {
  const bits = [`Page ${page.page_number}`, pageTypeLabel(page.page_type)];
  if (page.ocr_used) bits.push("OCR");
  const status = String(page.status || "").toUpperCase();
  if (status === "FAILED") bits.push(`failed${page.error_code ? `: ${page.error_code}` : ""}`);
  else if (status !== "DONE") bits.push(status.toLowerCase());
  if (page.text_character_count) bits.push(`${formatNumber(page.text_character_count)} chars`);
  return bits.join(" · ");
}
