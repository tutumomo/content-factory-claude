// v=20261124d busts the browser module cache after UI changes
import { $, $$, api, applyNavLayout, esc, getNavLayout, state } from "./lib.js?v=20261124d";
import { openNewEpisodeModal, openSettingsModal } from "./modals.js?v=20261124d";
import { viewContent } from "./views/content.js?v=20261124d";
import { viewEpisode } from "./views/episode.js?v=20261124d";
import { viewIdeas } from "./views/ideas.js?v=20261124d";
import { viewInsights } from "./views/insights.js?v=20261124d";
import { viewSchedule } from "./views/schedule.js?v=20261124d";
import { viewStyle } from "./views/style.js?v=20261124d";

const main = $("#main");

const WORKER_LABEL = {
  radar: "雷達掃描中",
  episode: "處理一集中",
  insights_analyze: "復盤分析中",
};

const PROVIDER_LABEL = {
  claude_cli: "Claude CLI",
  openai: "OpenAI 相容",
  mock: "示範模式",
};

const ROUTE_ALIASES = {
  review: "content",
  episodes: "content",
  radar: "ideas",
  prefs: "style",
  channel: "style",
};

function comfyItem(c) {
  // ComfyUI only matters when the visuals chain actually uses it; a red dot with nothing
  // asking for it reads as a defect, so say "not used" instead.
  const detail = esc(c?.detail || "");
  if (!c) return `<div class="st-item" title="未回報狀態"><span class="dot"></span>ComfyUI <b>未知</b></div>`;
  if (c.ok) {
    const h3 = c.h3_enabled ? ` <span class="muted">· H3</span>` : "";
    return `<div class="st-item" title="${detail}"><span class="dot ok"></span>ComfyUI <b>就緒</b>${h3}</div>`;
  }
  if (!c.needed) {
    return `<div class="st-item" title="${detail}"><span class="dot"></span>ComfyUI <b>未使用</b></div>`;
  }
  const what = c.chain?.includes("h3video") ? "影片與生圖" : "生圖";
  return `<div class="st-item" title="${detail}"><span class="dot bad"></span>ComfyUI <b>未就緒</b> <span class="muted">（${what}會退回字卡）</span></div>`;
}

async function refreshStatus() {
  try {
    const [h, eps] = await Promise.all([api("/api/health"), api("/api/episodes")]);
    const waiting = eps.filter((e) => e.status === "waiting").length;
    $("#badge-review").textContent = waiting || "";
    const kind = h.worker.current?.kind;
    const cur = kind ? (WORKER_LABEL[kind] || "處理中") : "閒置";
    const qTxt = h.worker.queued ? `（排隊 ${h.worker.queued}）` : "";
    $("#status").innerHTML = `
      <div class="st-item" title="${esc(h.tts.detail || "")}"><span class="dot ${h.tts.ok ? "ok" : "bad"}"></span>配音 <b>${h.tts.needs_voice_ref ? "缺參考聲音" : (h.tts.ok ? "就緒" : "未就緒")}</b></div>
      ${comfyItem(h.comfy)}
      <div class="st-item"><span class="dot ok"></span>LLM <b>${esc(PROVIDER_LABEL[h.provider] || h.provider)}</b></div>
      <div class="st-item">agent：<b>${cur}</b>${qTxt}</div>`;
  } catch { /* server restarting */ }
}

async function route() {
  clearInterval(state.pollTimer);
  const raw = location.hash.slice(2) || "content";
  const [path, qs] = raw.split("?");
  let [name, arg] = path.split("/");
  const params = new URLSearchParams(qs || "");

  if (name === "new") {
    location.hash = "#/content";
    await viewContent(main);
    openNewEpisodeModal({
      topic: params.get("topic") || "",
      format: params.get("format") || "short",
    });
    return;
  }
  if (name === "settings") {
    location.hash = "#/content";
    await viewContent(main);
    openSettingsModal();
    return;
  }
  if (ROUTE_ALIASES[name]) name = ROUTE_ALIASES[name];

  const navKey = name === "ep" ? "content" : name;
  $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === navKey));

  try {
    if (name === "ideas") await viewIdeas(main);
    else if (name === "schedule") await viewSchedule(main);
    else if (name === "insights") await viewInsights(main);
    else if (name === "style") await viewStyle(main);
    else if (name === "ep" && arg) await viewEpisode(main, decodeURIComponent(arg));
    else {
      $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === "content"));
      await viewContent(main);
    }
  } catch (e) {
    main.innerHTML = `<div class="card">載入失敗：${esc(e.message)}</div>`;
  }
  refreshStatus();
}

state.onRoute = route;
state.onStatusRefresh = refreshStatus;

$("#btn-new").onclick = () => openNewEpisodeModal();
$("#btn-settings").onclick = () => openSettingsModal();
$("#btn-layout").onclick = () => {
  const next = getNavLayout() === "top" ? "side" : "top";
  applyNavLayout(next, true);
};

(async () => {
  const [meta, settings] = await Promise.all([api("/api/meta"), api("/api/settings")]);
  state.META = meta;
  state.SETTINGS = settings;
  const savedLocal = (() => {
    try { return localStorage.getItem("cf_nav_layout"); } catch { return null; }
  })();
  const initialLayout = savedLocal || settings?.ui?.nav_layout || "top";
  applyNavLayout(initialLayout, false);

  window.addEventListener("hashchange", route);
  await route();
  setInterval(refreshStatus, 5000);
})();
