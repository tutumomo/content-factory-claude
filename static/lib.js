export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const state = {
  META: null,
  SETTINGS: null,
  pollTimer: null,
  onRoute: null,
  onStatusRefresh: null,
};

export async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  const text = await r.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!r.ok) throw new Error(data?.detail || text || r.statusText);
  return data;
}

export function toast(msg) {
  const t = $("#toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 3500);
}

export const fileUrl = (p) => (p ? `/files/${p}?t=${Date.now() >> 12}` : "");
export const fmtName = (f) => (f === "long" ? "長片" : "短片");
export const when = (t) => (t ? new Date(t * 1000).toLocaleString("zh-TW", { hour12: false }) : "");

export function fmtShortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function relDay(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const b = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((b - a) / 86400000);
  if (diff === 0) return "今天";
  if (diff === 1) return "明天";
  if (diff === -1) return "昨天";
  if (diff > 1 && diff <= 14) return `${diff} 天後`;
  if (diff < -1 && diff >= -14) return `${-diff} 天前`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function compactNum(n) {
  const v = Number(n) || 0;
  if (v >= 100000000) return (v / 100000000).toFixed(1).replace(/\.0$/, "") + "億";
  if (v >= 10000) return (v / 10000).toFixed(1).replace(/\.0$/, "") + "萬";
  if (v >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return v.toLocaleString("zh-TW");
}

export function statusPill(ep) {
  const META = state.META;
  if (ep.status === "waiting") {
    return `<span class="pill waiting">等你：${esc(META?.wait_label?.[ep.waiting_for] || ep.waiting_for)}</span>`;
  }
  const map = { queued: "排隊中", running: "agent 處理中", done: "已核准", error: "出錯" };
  return `<span class="pill ${esc(ep.status)}">${map[ep.status] || esc(ep.status)}</span>`;
}

export function stepper(ep) {
  const META = state.META;
  const i = META.stages.indexOf(ep.stage);
  return `<div class="steps">${META.stages.map((s, k) =>
    `<span class="${k < i || ep.status === "done" ? "done" : k === i ? "cur" : ""}">${esc(META.stage_label[s])}</span>`
  ).join("")}</div>`;
}

export function miniSteps(ep) {
  const META = state.META;
  const i = META.stages.indexOf(ep.stage);
  return `<div class="mini-steps" title="${esc(META.stage_label[ep.stage] || ep.stage)}">${META.stages.map((_, k) =>
    `<i class="${k < i || ep.status === "done" ? "done" : k === i ? "cur" : ""}"></i>`
  ).join("")}</div>`;
}

export function getNavLayout() {
  const cls = $("#app")?.classList.contains("layout-side") ? "side" : "top";
  return cls;
}

export async function applyNavLayout(mode, persist = false) {
  const next = mode === "side" ? "side" : "top";
  const appEl = $("#app");
  if (appEl) {
    appEl.classList.toggle("layout-side", next === "side");
    appEl.classList.toggle("layout-top", next === "top");
  }
  try { localStorage.setItem("cf_nav_layout", next); } catch {}
  const btn = $("#btn-layout");
  if (btn) {
    btn.textContent = next === "top" ? "◧" : "⬒";
    btn.title = next === "top" ? "切換為左側邊欄導覽" : "切換為頂部單行導覽";
  }
  if (persist) {
    try {
      const s = state.SETTINGS || await api("/api/settings");
      s.ui = { ...(s.ui || {}), nav_layout: next };
      state.SETTINGS = await api("/api/settings", { method: "PUT", body: s });
    } catch { /* ignore transient network failure */ }
  }
}

let activeEscHandler = null;

export function closeModal() {
  const root = $("#modal-root");
  if (root) root.innerHTML = "";
  if (activeEscHandler) {
    window.removeEventListener("keydown", activeEscHandler);
    activeEscHandler = null;
  }
}

export function openModal({ title, bodyHtml, footHtml = "", width = 640, onMount }) {
  closeModal();
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop" id="m-backdrop">
    <div class="modal" style="width:min(${width}px, 100%)" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>${esc(title)}</h2>
        <button type="button" class="btn icon-btn sm" id="m-close" aria-label="關閉">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footHtml ? `<div class="modal-foot">${footHtml}</div>` : ""}
    </div>
  </div>`;
  $("#m-close").onclick = closeModal;
  $("#m-backdrop").onclick = (e) => { if (e.target.id === "m-backdrop") closeModal(); };
  activeEscHandler = (e) => { if (e.key === "Escape") closeModal(); };
  window.addEventListener("keydown", activeEscHandler);
  if (onMount) onMount($("#modal-root"));
}
