/* ==========================================================================
   app.js — router, polling scheduler and view renderers.
   ========================================================================== */

import { api, ApiError, hintFor } from "./api.js";
import * as U from "./ui.js";

const $ = (sel, root = document) => root.querySelector(sel);

const VIEWS = ["workspace", "documents", "document", "service"];

const state = {
  route: { name: "workspace", param: null },
  settings: null,
  health: null,
  /** Newest page of documents, used by both the workspace and the ledger. */
  list: { items: [], total: 0, limit: 25, offset: 0, status: "" },
  detail: {
    uuid: null, row: null, doc: null, text: null, logs: [],
    pages: [], pageSummary: null, wrap: true, textLoaded: false,
  },
  signatures: {},
  uploading: false,
};

/* Re-rendering a table every 1.2 s would restart entrance animations and steal
   focus, so each region only repaints when its data actually changed. */
function changed(key, value) {
  const sig = JSON.stringify(value);
  if (state.signatures[key] === sig) return false;
  state.signatures[key] = sig;
  return true;
}

function reportError(err, fallback) {
  if (err && err.name === "AbortError") return;
  const isApi = err instanceof ApiError;
  const message = isApi ? err.message : fallback || "Something went wrong.";
  const hint = isApi ? hintFor(err.code) : null;
  U.toast(hint ? `${message} ${hint}` : message, {
    kind: "error",
    code: isApi && err.code !== "HTTP_ERROR" ? err.code : null,
  });
}

/* ==========================================================================
   Theme
   ========================================================================== */

function applyTheme(dark) {
  document.documentElement.classList.toggle("dark", dark);
  const btn = $("#theme-toggle");
  btn.setAttribute("aria-pressed", String(dark));
  $("#theme-icon").innerHTML = U.icon(dark ? "sun" : "moon");
  btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
  try {
    localStorage.setItem("docxy-theme", dark ? "dark" : "light");
  } catch {
    /* private mode — the class is still applied for this session */
  }
}

/* ==========================================================================
   Shared fragments
   ========================================================================== */

function pageGrid(processed, total, { active, pages = null }) {
  /* One cell per page reads beautifully up to a few hundred; past that the
     meter already carries the information, so the grid is dropped. */
  if (!total || total > 240) return "";

  /* When per-page rows are available, each cell is coloured by how that page
     was actually classified rather than merely "done / not done". */
  const byNumber = new Map((pages || []).map((pg) => [pg.page_number, pg]));

  let cells = "";
  for (let i = 0; i < total; i += 1) {
    const pg = byNumber.get(i + 1);
    if (pg) {
      const failed = String(pg.status || "").toUpperCase() === "FAILED";
      cells += `<span class="page-cell" data-type="${U.esc(pg.page_type)}"` +
        (failed ? ' data-failed="true"' : "") +
        ` title="${U.esc(U.pageCellTitle(pg))}"></span>`;
    } else {
      const cls = i < processed ? " is-done" : active && i === processed ? " is-current" : "";
      cells += `<span class="page-cell${cls}"></span>`;
    }
  }
  return `<div class="page-grid mt-5" role="img"
    aria-label="${processed} of ${total} pages extracted">${cells}</div>`;
}

function stageRail(row) {
  const states = U.phaseStates({ status: row.job_status, stage: row.job_stage });
  const steps = U.PHASES.map(
    (p, i) => `<div class="rail-step" data-state="${states[i]}">${U.esc(p.label)}</div>`
  ).join("");
  return `<div class="rail" role="list" aria-label="Pipeline phase">${steps}</div>`;
}

function errorNote(row) {
  if (!row.error_code) return "";
  const hint = hintFor(row.error_code);
  return `<div class="mt-5 p-4 rounded-lg" role="alert"
    style="background: var(--danger-wash); border: 1px solid var(--danger)">
    <p class="mono" style="color: var(--danger)">${U.esc(row.error_code)}</p>
    <p class="mt-1 text-[0.875rem]">${U.esc(row.error_message || "The job failed.")}</p>
    ${hint ? `<p class="mt-1 text-[0.8125rem]" style="color: var(--muted-fg)">${U.esc(hint)}</p>` : ""}
  </div>`;
}

function jobActions(row) {
  const status = String(row.job_status || "").toLowerCase();
  if (!row.job_id) return "";
  const buttons = [];
  if (status === "failed") {
    buttons.push(
      `<button class="btn btn-ghost btn-sm" data-act="retry" data-job="${U.esc(row.job_id)}">
         ${U.icon("refresh", { size: 16 })}Retry</button>`
    );
  }
  if (U.isActive(row.job_status)) {
    buttons.push(
      `<button class="btn btn-danger btn-sm" data-act="cancel" data-job="${U.esc(row.job_id)}">
         ${U.icon("prohibit", { size: 16 })}Cancel</button>`
    );
  }
  return buttons.join("");
}

/** The in-flight card: the pipeline made visible while it runs. */
function jobCard(row, { pages = null } = {}) {
  const active = U.isActive(row.job_status);
  const pct = Math.max(0, Math.min(100, Number(row.progress_percentage) || 0));
  return `<article class="panel" data-uuid="${U.esc(row.uuid)}">
    <header class="${active ? "scanline" : ""} flex flex-wrap items-center justify-between gap-3 px-6 py-4"
            style="border-bottom: 1px solid var(--border)">
      <div class="min-w-0">
        <a class="block font-semibold truncate hover:underline" href="#/doc/${U.esc(row.uuid)}"
           title="${U.esc(row.original_filename)}">${U.esc(row.original_filename)}</a>
        <p class="mono mt-0.5" style="color: var(--muted-fg)">${U.esc(U.shortId(row.uuid, 13))}</p>
      </div>
      <div class="flex items-center gap-2">
        ${U.badge(row.job_status, U.jobTone(row.job_status))}
        ${jobActions(row)}
      </div>
    </header>
    <div class="panel-pad">
      ${stageRail(row)}
      <div class="mt-6 flex items-baseline justify-between gap-4">
        <p class="num" style="color: var(--muted-fg)">
          ${U.esc(U.humanise(row.job_stage))} &middot;
          ${U.formatNumber(row.processed_pages)} / ${U.formatNumber(row.total_pages || row.page_count)} pages
        </p>
        <p class="num font-medium">${pct.toFixed(0)}%</p>
      </div>
      <div class="meter mt-2" role="progressbar" aria-valuenow="${pct.toFixed(0)}"
           aria-valuemin="0" aria-valuemax="100"
           aria-label="Extraction progress for ${U.esc(row.original_filename)}">
        <span style="width: ${pct}%"></span>
      </div>
      ${pageGrid(row.processed_pages, row.total_pages || row.page_count, { active, pages })}
      ${errorNote(row)}
    </div>
  </article>`;
}

/* --- Ledger table -------------------------------------------------------- */

function ledgerRow(row) {
  const active = U.isActive(row.job_status);
  const progress = active
    ? `<span class="num" style="color: var(--accent-text)">${Math.round(row.progress_percentage)}% &middot;
       ${U.esc(U.humanise(row.job_stage))}</span>`
    : row.extraction_method
    ? `<span class="num" style="color: var(--muted-fg)">${U.esc(U.humanise(row.extraction_method))}</span>`
    : `<span style="color: var(--muted-fg)">—</span>`;

  return `<tr data-uuid="${U.esc(row.uuid)}">
    <td>
      <a class="font-medium hover:underline" href="#/doc/${U.esc(row.uuid)}">${U.esc(row.original_filename)}</a>
      <span class="block mono mt-0.5" style="color: var(--muted-fg)">${U.esc(U.shortId(row.uuid, 13))}</span>
    </td>
    <td class="num hidden md:table-cell">${row.page_count ? U.formatNumber(row.page_count) : "—"}</td>
    <td class="num hidden lg:table-cell">${U.formatBytes(row.file_size_bytes)}</td>
    <td class="num hidden lg:table-cell">${row.word_count ? U.formatNumber(row.word_count) : "—"}</td>
    <td>${
      /* A document only reaches COMPLETED/FAILED through its job, so until the
         job is done the job's own state is the truthful summary — otherwise a
         running, cancelled or retrying document all still read "UPLOADED". */
      row.job_status && row.job_status !== "done"
        ? U.badge(row.job_status, U.jobTone(row.job_status))
        : U.badge(row.status, U.docTone(row.status))
    }</td>
    <td class="hidden sm:table-cell">${progress}</td>
    <td class="num" title="${U.esc(U.formatAbsolute(row.uploaded_at))}">${U.esc(U.formatRelative(row.uploaded_at))}</td>
  </tr>`;
}

function ledgerTable(items, { stagger = true, emptyAction = true } = {}) {
  if (!items.length) {
    /* On the workspace the uploader is directly above this block, so a link
       back to it would be a control that does nothing. */
    return `<div class="empty panel">
      <span style="color: var(--muted-fg)">${U.icon("fileText", { size: 28 })}</span>
      <p class="font-medium" style="color: var(--fg)">No documents yet</p>
      <p class="text-[0.875rem]">${
        emptyAction
          ? "Upload a PDF from the workspace and it will appear here."
          : "Drop a PDF above and it will appear here."
      }</p>
      ${emptyAction ? `<a class="btn btn-ghost btn-sm mt-2" href="#/">Go to workspace</a>` : ""}
    </div>`;
  }
  const rows = items
    .map((r, i) => ledgerRow(r).replace("<tr ", `<tr style="--i:${i}" `))
    .join("");
  return `<table class="ledger">
    <thead><tr>
      <th scope="col">Document</th>
      <th scope="col" class="hidden md:table-cell">Pages</th>
      <th scope="col" class="hidden lg:table-cell">Size</th>
      <th scope="col" class="hidden lg:table-cell">Words</th>
      <th scope="col">Status</th>
      <th scope="col" class="hidden sm:table-cell">Detail</th>
      <th scope="col">Added</th>
    </tr></thead>
    <tbody class="${stagger ? "stagger" : ""}">${rows}</tbody>
  </table>`;
}

/* ==========================================================================
   Workspace
   ========================================================================== */

function renderHealth() {
  const h = state.health;
  const pill = $("#service-pill");
  if (!h) return;

  const tone = h.status === "ready" ? "ok" : h.status === "degraded" ? "warn" : "error";
  pill.className = `badge badge-${tone}`;
  pill.innerHTML = `<span class="badge-dot" aria-hidden="true"></span>${U.esc(h.status)}`;

  const checks = h.checks || {};
  const rows = [
    ["database", "Database", "database", checks.database],
    ["worker", "Worker thread", "pulse", checks.worker],
    ["storage", "Storage", "drive", checks.storage],
    ["vision_ocr", "Vision OCR", "eye", checks.vision_ocr],
  ];

  const isGood = (key, v) => {
    const s = String(v || "");
    if (key === "database") return s === "ready";
    if (key === "worker") return s === "running";
    return true;
  };

  $("#health-panel").innerHTML = `<div class="grid gap-3">${rows
    .map(([key, label, ic, value]) => {
      const good = isGood(key, value);
      const dim = key === "vision_ocr" && String(value).includes("disabled");
      const color = !good ? "var(--danger)" : dim ? "var(--muted-fg)" : "var(--ok)";
      return `<div class="flex items-center justify-between gap-3">
        <span class="flex items-center gap-2.5 text-[0.875rem]">
          <span style="color: var(--muted-fg)">${U.icon(ic, { size: 18 })}</span>${U.esc(label)}
        </span>
        <span class="mono flex items-center gap-2" style="color: ${color}">
          <span class="badge-dot" aria-hidden="true"></span>${U.esc(String(value ?? "unknown"))}
        </span>
      </div>`;
    })
    .join("")}</div>`;
}

function renderLimits() {
  const s = state.settings;
  if (!s) return;

  $("#drop-sub").textContent =
    `PDF only · up to ${s.max_upload_size_mb} MB · max ${U.formatNumber(s.max_pages_per_document)} pages`;

  $("#limits-panel").innerHTML = [
    ["Format", "PDF"],
    ["Max size", `${s.max_upload_size_mb} MB`],
    ["Max pages", U.formatNumber(s.max_pages_per_document)],
    ["Native text threshold", `${U.formatNumber(s.pdf_min_text_length)} chars`],
    ["Storage", s.aws_enabled ? `S3 · ${s.aws_region}` : "Local filesystem"],
    ["Vision OCR", s.groq_enabled ? s.groq_model : "Disabled"],
  ]
    .map(([k, v]) => `<div><dt>${U.esc(k)}</dt><dd>${U.esc(v)}</dd></div>`)
    .join("");
}

function renderWorkspace() {
  const items = state.list.items;
  const active = items.filter((r) => U.isActive(r.job_status));

  const inflight = $("#inflight");
  $("#ledger-index").textContent = active.length ? "03 / LEDGER" : "02 / LEDGER";
  if (active.length) {
    inflight.hidden = false;
    $("#inflight-count").textContent = `${active.length} job${active.length > 1 ? "s" : ""}`;
    if (changed("inflight", active)) {
      $("#inflight-list").innerHTML = active
        .map((r, i) => jobCard(r).replace("<article ", `<article style="--i:${i}" `))
        .join("");
    }
  } else {
    inflight.hidden = true;
    state.signatures.inflight = null;
  }

  const recent = items.slice(0, 8);
  if (changed("recent", recent)) {
    $("#recent-wrap").innerHTML = ledgerTable(recent, { emptyAction: false });
  }
}

/* ==========================================================================
   Documents ledger
   ========================================================================== */

function renderLedger() {
  const { items, total, limit, offset, status } = state.list;

  if (changed("ledger", { items, status })) {
    $("#ledger-wrap").innerHTML = ledgerTable(items);
  }

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  $("#ledger-range").textContent = total
    ? `${from}–${to} of ${U.formatNumber(total)}`
    : "No documents";
  $("#page-prev").disabled = offset === 0;
  $("#page-next").disabled = offset + limit >= total;

  document.querySelectorAll("[data-filter]").forEach((btn) => {
    const on = btn.dataset.filter === status;
    btn.style.borderColor = on ? "var(--fg)" : "";
    btn.style.background = on ? "var(--surface-2)" : "";
    btn.setAttribute("aria-pressed", String(on));
  });
}

/* ==========================================================================
   Document detail
   ========================================================================== */

/** Page markers written by txt_service read as structure, not body copy. */
function highlightMarkers(text) {
  return U.esc(text).replace(/^(=+\s*PAGE\s+\d+\s*=+)$/gim, "<mark>$1</mark>");
}

function specRail() {
  const { doc, row } = state.detail;
  const pairs = [
    ["Document ID", doc.uuid],
    ["Job ID", row && row.job_id ? row.job_id : "—"],
    ["SHA-256", doc.file_hash],
    ["Size", U.formatBytes(doc.file_size_bytes)],
    ["Pages", doc.page_count ? U.formatNumber(doc.page_count) : "—"],
    ["Extraction", doc.extraction_method ? U.humanise(doc.extraction_method) : "—"],
    ["Characters", U.formatNumber(doc.text_character_count)],
    ["Words", U.formatNumber(doc.word_count)],
    ["Duration", U.formatDuration(doc.processing_duration_ms)],
    ["Storage", doc.storage_provider],
    ["Uploaded", U.formatAbsolute(doc.uploaded_at)],
  ];
  return `<div class="rail-sticky">
    <p class="label">Specification</p>
    <dl class="kv panel panel-pad mt-3">
      ${pairs.map(([k, v]) => `<div><dt>${U.esc(k)}</dt><dd>${U.esc(v)}</dd></div>`).join("")}
    </dl>
    <button class="btn btn-ghost btn-sm mt-4 w-full" type="button" data-act="copy-id">
      ${U.icon("copy", { size: 16 })}Copy document ID
    </button>
  </div>`;
}

/**
 * Page map — one cell per page, coloured by how the classifier actually routed
 * it. This is the project's whole premise made visible: blue pages cost
 * nothing, amber pages each cost a vision call.
 */
function pageMapPanel() {
  const { pages, pageSummary } = state.detail;
  if (!pages || !pages.length || !pageSummary) return "";

  /* Only legend the types this document actually contains. */
  const present = U.PAGE_TYPES.filter((t) => (pageSummary[t.key.toLowerCase()] || 0) > 0);

  const failed = pages.filter((pg) => String(pg.status || "").toUpperCase() === "FAILED");
  const shownFailed = failed.slice(0, 24).map((pg) => pg.page_number).join(", ");
  const failCode = failed.length ? failed[0].error_code : null;

  const cells = pages
    .map((pg) => {
      const isFailed = String(pg.status || "").toUpperCase() === "FAILED";
      return `<span class="page-cell" data-type="${U.esc(pg.page_type)}"${
        isFailed ? ' data-failed="true"' : ""
      } title="${U.esc(U.pageCellTitle(pg))}"></span>`;
    })
    .join("");

  const legend = present
    .map(
      (t) => `<span class="flex items-center gap-1.5 text-[0.75rem]" style="color: var(--muted-fg)">
        <span class="legend-swatch" data-type="${t.key}" aria-hidden="true"></span>${U.esc(t.label)}
      </span>`
    )
    .join("");

  return `<div class="panel">
    <header class="flex flex-wrap items-start justify-between gap-4 px-6 py-4"
            style="border-bottom: 1px solid var(--border)">
      <div>
        <p class="label">Page map</p>
        <p class="num mt-1" style="color: var(--muted-fg)">
          ${U.formatNumber(pageSummary.total)} pages &middot;
          ${U.formatNumber(pageSummary.native_text)} read natively &middot;
          ${U.formatNumber(pageSummary.image_based + pageSummary.mixed)} needed the vision model
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        ${legend}
        ${
          failed.length
            ? `<span class="flex items-center gap-1.5 text-[0.75rem]" style="color: var(--danger)">
                 <span class="legend-swatch" style="border-color: var(--danger); box-shadow: inset 0 0 0 1px var(--danger)" aria-hidden="true"></span>Failed
               </span>`
            : ""
        }
      </div>
    </header>
    <div class="p-6">
      <div class="page-grid page-grid-lg" role="img"
           aria-label="Classification of all ${pageSummary.total} pages: ${
             present.map((t) => `${pageSummary[t.key.toLowerCase()]} ${t.label}`).join(", ")
           }">${cells}</div>
      ${
        failed.length
          ? `<p class="mt-5 text-[0.8125rem]" role="status">
               <span style="color: var(--danger)">${U.formatNumber(failed.length)} page${
                 failed.length > 1 ? "s" : ""
               } could not be extracted</span>
               <span style="color: var(--muted-fg)"> — ${U.esc(shownFailed)}${
                 failed.length > 24 ? ` and ${failed.length - 24} more` : ""
               }${failCode ? ` (${U.esc(failCode)})` : ""}.</span>
               ${
                 failCode === "OCR_DISABLED"
                   ? `<span class="block mt-1" style="color: var(--muted-fg)">${U.esc(
                       hintFor("OCR_DISABLED") || ""
                     )}</span>`
                   : ""
               }
             </p>`
          : ""
      }
    </div>
  </div>`;
}

function textPanel() {
  const { text, textLoaded, wrap, doc } = state.detail;

  if (!textLoaded) {
    return `<div class="panel panel-pad">
      <div class="grid gap-2">${U.skeletonRows(6, "0.875rem")}</div>
    </div>`;
  }

  const body = text && text.text;
  if (!body) {
    return `<div class="panel empty">
      <span style="color: var(--muted-fg)">${U.icon("scan", { size: 28 })}</span>
      <p class="font-medium" style="color: var(--fg)">No text yet</p>
      <p class="text-[0.875rem]">
        ${String(doc.status).toUpperCase() === "FAILED"
          ? "The job failed before text was aggregated."
          : "Text appears here once the job finishes aggregating pages."}
      </p>
    </div>`;
  }

  return `<div class="panel">
    <header class="flex flex-wrap items-center justify-between gap-3 px-6 py-4"
            style="border-bottom: 1px solid var(--border)">
      <div>
        <p class="label">Extracted text</p>
        <p class="num mt-1" style="color: var(--muted-fg)">
          ${U.formatNumber(text.character_count)} chars &middot;
          ${U.formatNumber(text.word_count)} words &middot;
          ${U.formatNumber(text.page_count)} pages
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="btn btn-ghost btn-sm" type="button" data-act="wrap" aria-pressed="${wrap}">
          ${wrap ? "No wrap" : "Wrap"}
        </button>
        <button class="btn btn-ghost btn-sm" type="button" data-act="copy-text">
          ${U.icon("copy", { size: 16 })}Copy
        </button>
        <a class="btn btn-ghost btn-sm" href="${api.downloadUrl(doc.uuid, "txt")}" download>
          ${U.icon("download", { size: 16 })}TXT
        </a>
        <a class="btn btn-ghost btn-sm" href="${api.downloadUrl(doc.uuid, "pdf")}">
          ${U.icon("fileText", { size: 16 })}PDF
        </a>
      </div>
    </header>
    <div class="p-6">
      <pre class="text-view${wrap ? "" : " nowrap"}" tabindex="0"
           aria-label="Extracted text">${highlightMarkers(body)}</pre>
    </div>
  </div>`;
}

function logPanel() {
  const logs = state.detail.logs;
  if (!logs || !logs.length) return "";
  return `<div class="panel panel-pad">
    <p class="label">Job log</p>
    <div class="mt-3">
      ${logs
        .map(
          (l) => `<div class="log-row">
            <span class="log-level" data-level="${U.esc(l.level)}">${U.esc(l.level)}</span>
            <span>
              <span class="font-medium">${U.esc(l.event)}</span>
              <span style="color: var(--muted-fg)"> — ${U.esc(l.message)}</span>
              <span class="block mono mt-0.5" style="color: var(--muted-fg)">
                ${U.esc(l.stage || "")} ${U.esc(U.formatRelative(l.created_at))}
              </span>
            </span>
          </div>`
        )
        .join("")}
    </div>
  </div>`;
}

function renderDetail() {
  const { doc, row } = state.detail;
  const host = $("#document-body");

  if (!doc) {
    host.innerHTML = `<div class="grid gap-3 max-w-xl">${U.skeletonRows(5, "1.25rem")}</div>`;
    return;
  }

  const activeRow = row || { uuid: doc.uuid, original_filename: doc.original_filename };
  const showJob = row && (U.isActive(row.job_status) || row.error_code);

  host.innerHTML = `
    <a class="nav-link" href="#/documents">${U.icon("arrowLeft", { size: 16 })}<span class="ml-1.5">All documents</span></a>

    <div class="mt-5 flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-2xl lg:text-3xl break-words">${U.esc(doc.original_filename)}</h1>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          ${U.badge(doc.status, U.docTone(doc.status))}
          ${row && row.job_status ? U.badge(row.job_status, U.jobTone(row.job_status)) : ""}
          ${doc.extraction_method ? U.badge(doc.extraction_method, "idle", { dot: false }) : ""}
        </div>
      </div>
      <div class="flex flex-wrap gap-2">${jobActions(activeRow)}</div>
    </div>

    <div class="mt-9 grid gap-8 lg:grid-cols-[19rem_1fr] lg:gap-12">
      ${specRail()}
      <div class="grid gap-6 min-w-0">
        ${showJob ? jobCard(row, { pages: state.detail.pages }) : ""}
        ${pageMapPanel()}
        ${textPanel()}
        ${logPanel()}
      </div>
    </div>`;
}

/* ==========================================================================
   Service
   ========================================================================== */

function renderService() {
  const s = state.settings;
  const h = state.health || { checks: {} };
  if (!s) {
    $("#service-body").innerHTML = `<div class="grid gap-3">${U.skeletonRows(6)}</div>`;
    return;
  }

  const groups = [
    ["Runtime", "gear", [
      ["Application", s.app_name],
      ["Environment", s.app_env],
      ["Debug", s.debug ? "on" : "off"],
    ]],
    ["Readiness", "pulse", [
      ["Status", h.status || "unknown"],
      ["Database", h.checks.database || "—"],
      ["Worker", h.checks.worker || "—"],
      ["Storage", h.checks.storage || "—"],
      ["Vision OCR", h.checks.vision_ocr || "—"],
    ]],
    ["Ingest limits", "tray", [
      ["Max upload size", `${s.max_upload_size_mb} MB`],
      ["Max pages per document", U.formatNumber(s.max_pages_per_document)],
    ]],
    ["Page classification", "layers", [
      ["Min text length", `${U.formatNumber(s.pdf_min_text_length)} chars`],
      ["Min text density", String(s.pdf_min_text_density)],
      ["Min image area ratio", String(s.pdf_min_image_area_ratio)],
    ]],
    ["Worker", "refresh", [
      ["Enabled", s.worker_enabled ? "yes" : "no"],
      ["Count", String(s.worker_count)],
      ["Poll interval", `${s.worker_poll_interval_seconds} s`],
      ["Stale job timeout", `${s.job_stale_timeout_seconds} s`],
    ]],
    ["Storage", "drive", [
      ["Provider", s.aws_enabled ? "S3" : "Local filesystem"],
      ["Region", s.aws_enabled ? s.aws_region : "—"],
      ["Bucket", s.aws_enabled ? s.aws_s3_bucket || "—" : "—"],
    ]],
    ["Vision OCR", "eye", [
      ["Enabled", s.groq_enabled ? "yes" : "no"],
      ["Model", s.groq_enabled ? s.groq_model : "—"],
      ["Per second", U.formatNumber(s.groq_requests_per_second)],
      ["Per minute", U.formatNumber(s.groq_requests_per_minute)],
      ["Per day", U.formatNumber(s.groq_requests_per_day)],
      ["Min request gap", `${s.groq_min_request_gap_seconds} s`],
    ]],
    ["Text output", "fileText", [
      ["Page markers", s.txt_include_page_markers ? "included" : "omitted"],
      ["Metadata header", s.txt_include_metadata ? "included" : "omitted"],
    ]],
  ];

  $("#service-body").innerHTML = groups
    .map(
      ([title, ic, pairs], i) => `<section class="panel panel-pad" style="--i:${i}">
      <p class="label flex items-center gap-2">
        <span style="color: var(--accent-text)">${U.icon(ic, { size: 16 })}</span>${U.esc(title)}
      </p>
      <dl class="kv mt-3">
        ${pairs.map(([k, v]) => `<div><dt>${U.esc(k)}</dt><dd>${U.esc(v)}</dd></div>`).join("")}
      </dl>
    </section>`
    )
    .join("");
  $("#service-body").classList.add("stagger");
}

/* ==========================================================================
   Loaders
   ========================================================================== */

async function loadSettings() {
  try {
    state.settings = await api.getSettings();
    renderLimits();
  } catch (err) {
    reportError(err, "Could not read service settings.");
  }
}

async function loadHealth() {
  try {
    state.health = await api.getReady();
    renderHealth();
  } catch (err) {
    reportError(err, "Could not read service health.");
  }
}

async function loadList({ quiet = false } = {}) {
  const { limit, offset, status } = state.list;
  try {
    const data = await api.listDocuments({ limit, offset, status });
    state.list.items = data.items;
    state.list.total = data.total;
  } catch (err) {
    if (!quiet) reportError(err, "Could not load documents.");
    throw err;
  }
}

async function loadDetail(uuid, { quiet = false } = {}) {
  try {
    /* Full metadata (hash, storage) and the job join come from two endpoints;
       fetch them together rather than in series. */
    const [doc, list] = await Promise.all([
      api.getDocument(uuid),
      api.listDocuments({ uuid, limit: 1 }),
    ]);
    state.detail.doc = doc;
    state.detail.row = list.items[0] || null;

    const jobId = state.detail.row && state.detail.row.job_id;
    if (jobId) {
      try {
        state.detail.logs = await api.getJobLogs(jobId, { limit: 50 });
      } catch {
        state.detail.logs = [];
      }
    }

    /* Per-page rows are fetched only here, for one document at a time. The
       workspace deliberately does not fetch them: that would turn a single
       list poll into one request per in-flight document. */
    try {
      const pageData = await api.getPages(uuid);
      state.detail.pages = pageData.items;
      state.detail.pageSummary = pageData.summary;
    } catch {
      state.detail.pages = [];
      state.detail.pageSummary = null;
    }

    /* Text is only worth fetching once the document is finished. */
    const done = String(doc.status).toUpperCase() === "COMPLETED";
    if (done && !state.detail.textLoaded) {
      state.detail.text = await api.getText(uuid);
      state.detail.textLoaded = true;
    } else if (!done) {
      state.detail.textLoaded = !U.isActive(state.detail.row && state.detail.row.job_status);
    }

    renderDetail();
  } catch (err) {
    if (!quiet) reportError(err, "Could not load this document.");
    if (!state.detail.doc) {
      $("#document-body").innerHTML = `<div class="empty panel">
        <span style="color: var(--danger)">${U.icon("warning", { size: 28 })}</span>
        <p class="font-medium" style="color: var(--fg)">Document not found</p>
        <p class="text-[0.875rem]">${U.esc(uuid)}</p>
        <a class="btn btn-ghost btn-sm mt-2" href="#/documents">Back to documents</a>
      </div>`;
    }
  }
}

/* ==========================================================================
   Polling — one scheduler, interval derived from whether work is in flight
   ========================================================================== */

let pollTimer = null;

function hasActiveWork() {
  if (state.route.name === "document") {
    return !!(state.detail.row && U.isActive(state.detail.row.job_status));
  }
  return state.list.items.some((r) => U.isActive(r.job_status));
}

function schedulePoll() {
  window.clearTimeout(pollTimer);
  const delay = document.hidden ? 15000 : hasActiveWork() ? 1200 : 12000;
  pollTimer = window.setTimeout(tick, delay);
}

async function tick() {
  if (document.hidden) {
    schedulePoll();
    return;
  }
  try {
    await refreshRoute({ quiet: true });
  } catch {
    /* transient failure — the next tick retries */
  }
  schedulePoll();
}

async function refreshRoute({ quiet = false } = {}) {
  const { name, param } = state.route;
  if (name === "workspace") {
    await loadList({ quiet });
    renderWorkspace();
    await loadHealth();
  } else if (name === "documents") {
    await loadList({ quiet });
    renderLedger();
  } else if (name === "document") {
    await loadDetail(param, { quiet });
  } else if (name === "service") {
    await loadHealth();
    renderService();
  }
}

/* ==========================================================================
   Router
   ========================================================================== */

function parseHash() {
  const raw = (location.hash || "#/").replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean);
  if (!parts.length) return { name: "workspace", param: null };
  if (parts[0] === "documents") return { name: "documents", param: null };
  if (parts[0] === "service") return { name: "service", param: null };
  if (parts[0] === "doc" && parts[1]) return { name: "document", param: decodeURIComponent(parts[1]) };
  return { name: "workspace", param: null };
}

async function navigate() {
  const next = parseHash();
  const sameDoc = next.name === "document" && next.param === state.route.param;
  state.route = next;

  VIEWS.forEach((v) => {
    $(`#view-${v}`).hidden = v !== next.name;
  });

  document.querySelectorAll("[data-nav]").forEach((a) => {
    const on =
      a.dataset.nav === next.name ||
      (a.dataset.nav === "documents" && next.name === "document");
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });

  /* A fresh view starts from a clean signature set so it paints immediately. */
  state.signatures = {};

  if (next.name === "document" && !sameDoc) {
    state.detail = {
      uuid: next.param, row: null, doc: null, text: null, logs: [],
      pages: [], pageSummary: null, wrap: true, textLoaded: false,
    };
    renderDetail();
  }
  if (next.name === "service") renderService();

  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });

  await refreshRoute();
  schedulePoll();
}

/* ==========================================================================
   Upload
   ========================================================================== */

function setUploadState(busy, message = "") {
  state.uploading = busy;
  const drop = $("#drop");
  drop.classList.toggle("is-busy", busy);
  $("#file").disabled = busy;
  $("#drop-title").textContent = busy ? "Uploading…" : "Drop a PDF here, or browse";
  $("#upload-meter").hidden = !busy;
  $("#upload-status").textContent = message;
}

function validateFile(file) {
  const name = (file.name || "").toLowerCase();
  if (file.type !== "application/pdf" && !name.endsWith(".pdf")) {
    return "That is not a PDF. Only .pdf files are accepted.";
  }
  const maxMb = state.settings ? state.settings.max_upload_size_mb : null;
  if (maxMb && file.size > maxMb * 1024 * 1024) {
    return `${U.formatBytes(file.size)} exceeds the ${maxMb} MB limit.`;
  }
  if (file.size === 0) return "That file is empty.";
  return null;
}

async function handleFile(file) {
  if (!file || state.uploading) return;

  const problem = validateFile(file);
  if (problem) {
    /* Error shown next to the control it belongs to, and announced. */
    const el = $("#upload-status");
    el.textContent = problem;
    el.setAttribute("role", "alert");
    el.style.color = "var(--danger)";
    return;
  }

  const status = $("#upload-status");
  status.removeAttribute("role");
  status.style.color = "var(--muted-fg)";
  setUploadState(true, `Sending ${U.esc(file.name)}…`);

  try {
    const result = await api.upload(file, {
      /* Re-submitting the same file after a dropped connection must not create
         a second job, so every upload carries an idempotency key. */
      idempotencyKey: `ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      onProgress: (ratio) => {
        $("#upload-meter").firstElementChild.style.width = `${Math.round(ratio * 100)}%`;
      },
    });

    setUploadState(false, "");
    if (result.is_duplicate) {
      U.toast("Already extracted — showing the existing result.", { kind: "info" });
    } else {
      U.toast(`Queued ${file.name}`, { kind: "ok" });
    }

    $("#file").value = "";
    await refreshRoute();
    schedulePoll();
  } catch (err) {
    setUploadState(false, "");
    $("#file").value = "";
    reportError(err, "The upload failed.");
  }
}

/* ==========================================================================
   Events
   ========================================================================== */

function wireDropZone() {
  const drop = $("#drop");
  const input = $("#file");

  input.addEventListener("change", () => handleFile(input.files && input.files[0]));

  ["dragenter", "dragover"].forEach((type) =>
    drop.addEventListener(type, (ev) => {
      ev.preventDefault();
      if (!state.uploading) drop.classList.add("is-over");
    })
  );
  ["dragleave", "dragend"].forEach((type) =>
    drop.addEventListener(type, (ev) => {
      if (ev.target === drop || type === "dragend") drop.classList.remove("is-over");
    })
  );
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    drop.classList.remove("is-over");
    const files = ev.dataTransfer && ev.dataTransfer.files;
    if (files && files.length) handleFile(files[0]);
  });

  /* Without this the browser navigates away and opens the dropped PDF. */
  ["dragover", "drop"].forEach((type) =>
    window.addEventListener(type, (ev) => {
      if (!drop.contains(ev.target)) ev.preventDefault();
    })
  );
}

async function handleJobAction(act, jobId) {
  try {
    if (act === "retry") {
      await api.retryJob(jobId);
      U.toast("Job queued for retry.", { kind: "ok" });
    } else {
      await api.cancelJob(jobId);
      U.toast("Job cancelled.", { kind: "ok" });
    }
    await refreshRoute();
    schedulePoll();
  } catch (err) {
    reportError(err, "That action could not be applied.");
  }
}

function wireDelegates() {
  document.addEventListener("click", async (ev) => {
    const actionEl = ev.target.closest("[data-act]");
    if (actionEl) {
      const act = actionEl.dataset.act;

      if (act === "retry" || act === "cancel") {
        ev.preventDefault();
        actionEl.disabled = true;
        await handleJobAction(act, actionEl.dataset.job);
        return;
      }
      if (act === "wrap") {
        state.detail.wrap = !state.detail.wrap;
        renderDetail();
        return;
      }
      if (act === "copy-text") {
        const ok = await U.copyText((state.detail.text && state.detail.text.text) || "");
        U.toast(ok ? "Text copied." : "Copying was blocked by the browser.", {
          kind: ok ? "ok" : "error",
        });
        return;
      }
      if (act === "copy-id") {
        const ok = await U.copyText(state.detail.doc ? state.detail.doc.uuid : "");
        U.toast(ok ? "Document ID copied." : "Copying was blocked by the browser.", {
          kind: ok ? "ok" : "error",
        });
        return;
      }
    }

    /* Whole ledger rows are clickable, but the anchor inside each row is what
       keyboard and assistive tech use — so ignore clicks that already hit one. */
    const row = ev.target.closest("tr[data-uuid]");
    if (row && !ev.target.closest("a, button")) {
      location.hash = `#/doc/${encodeURIComponent(row.dataset.uuid)}`;
    }
  });

  document.querySelectorAll("[data-filter]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      state.list.status = btn.dataset.filter;
      state.list.offset = 0;
      await refreshRoute();
    })
  );

  $("#page-prev").addEventListener("click", async () => {
    state.list.offset = Math.max(0, state.list.offset - state.list.limit);
    await refreshRoute();
  });
  $("#page-next").addEventListener("click", async () => {
    if (state.list.offset + state.list.limit < state.list.total) {
      state.list.offset += state.list.limit;
      await refreshRoute();
    }
  });

  $("#refresh-health").addEventListener("click", loadHealth);

  $("#theme-toggle").addEventListener("click", () =>
    applyTheme(!document.documentElement.classList.contains("dark"))
  );

  window.addEventListener("hashchange", navigate);

  /* Polling pauses in a hidden tab and catches up the moment it is visible. */
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick();
    else schedulePoll();
  });
}

/* ==========================================================================
   Boot
   ========================================================================== */

async function boot() {
  applyTheme(document.documentElement.classList.contains("dark"));
  $("#drop-glyph").innerHTML = U.icon("tray", { size: 26 });

  wireDropZone();
  wireDelegates();

  await Promise.all([loadSettings(), loadHealth()]);
  await navigate();
}

boot();
