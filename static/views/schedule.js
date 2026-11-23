import { $, $$, api, esc, fileUrl, fmtName, fmtShortDate, openModal, closeModal, relDay, statusPill, toast } from "../lib.js?v=20261123a";

const WEEK = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"];
const MONTHS = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"];

let curYear = new Date().getFullYear();
let curMonth = new Date().getMonth();

function toDayKey(val) {
  if (!val) return "";
  if (val instanceof Date) {
    return `${val.getFullYear()}-${String(val.getMonth() + 1).padStart(2, "0")}-${String(val.getDate()).padStart(2, "0")}`;
  }
  const m = String(val).match(/^(\d{4}-\d{2}-\d{2})/);
  if (m) return m[1];
  const d = new Date(val);
  return Number.isNaN(d.getTime()) ? "" : toDayKey(d);
}

function timePart(schedule) {
  const m = String(schedule || "").match(/T(\d{2}:\d{2})/);
  return m ? m[1] : "20:00";
}

export async function viewSchedule(main) {
  const [eps, ideas] = await Promise.all([api("/api/episodes"), api("/api/ideas")]);

  const ideaCountByDay = new Map();
  for (const it of ideas) {
    if (!it.found) continue;
    const k = toDayKey(new Date(it.found * 1000));
    ideaCountByDay.set(k, (ideaCountByDay.get(k) || 0) + 1);
  }

  const openTimeEditor = (ep) => {
    const curVal = ep.schedule ? ep.schedule.slice(0, 16) : `${toDayKey(new Date())}T20:00`;
    openModal({
      title: `設定排期：${ep.package_choice?.title || ep.topic}`,
      width: 420,
      bodyHtml: `
        <label>預計發布時間</label>
        <input id="sc-dt" type="datetime-local" value="${esc(curVal)}">
        <p class="muted" style="margin-top:8px">提示：在月曆上也可以直接把集數拖曳到任何一天。</p>`,
      footHtml: `
        ${ep.schedule ? `<button type="button" class="btn danger" id="sc-clear" style="margin-right:auto">清除排期</button>` : ""}
        <button type="button" class="btn" id="sc-cancel">取消</button>
        <button type="button" class="btn primary" id="sc-save">儲存排期</button>`,
      onMount: (root) => {
        $("#sc-cancel", root).onclick = closeModal;
        $("#sc-clear", root) && ($("#sc-clear", root).onclick = async () => {
          await api(`/api/episodes/${encodeURIComponent(ep.id)}/schedule`, { method: "PATCH", body: { schedule: null } });
          ep.schedule = null;
          closeModal();
          toast("已清除排期");
          render();
        });
        $("#sc-save", root).onclick = async () => {
          const val = $("#sc-dt", root).value;
          if (!val) return toast("請選擇日期與時間");
          await api(`/api/episodes/${encodeURIComponent(ep.id)}/schedule`, { method: "PATCH", body: { schedule: val } });
          ep.schedule = val;
          closeModal();
          toast("已更新排期");
          render();
        };
      },
    });
  };

  const render = () => {
    const firstDow = new Date(curYear, curMonth, 1).getDay();
    const cells = [];
    for (let i = 0; i < 42; i++) {
      cells.push(new Date(curYear, curMonth, i - firstDow + 1));
    }
    const rows = cells[28].getMonth() !== curMonth
      ? cells.slice(0, 28)
      : cells[35].getMonth() === curMonth
        ? cells
        : cells.slice(0, 35);

    const byDay = new Map();
    for (const ep of eps) {
      if (!ep.schedule) continue;
      const k = toDayKey(ep.schedule);
      if (!k) continue;
      if (!byDay.has(k)) byDay.set(k, []);
      byDay.get(k).push(ep);
    }
    for (const arr of byDay.values()) {
      arr.sort((a, b) => String(a.schedule).localeCompare(String(b.schedule)));
    }

    const prefix = `${curYear}-${MONTHS[curMonth]}`;
    const todayKey = toDayKey(new Date());
    const monthScheduled = [...byDay.entries()]
      .filter(([k]) => k.startsWith(prefix))
      .reduce((n, [, arr]) => n + arr.length, 0);
    const monthIdeas = [...ideaCountByDay.entries()]
      .filter(([k]) => k.startsWith(prefix))
      .reduce((n, [, c]) => n + c, 0);
    const approvedCount = eps.filter((e) => e.status === "done").length;

    const nowIso = `${todayKey}T00:00`;
    const scheduledAll = eps
      .filter((e) => e.schedule)
      .sort((a, b) => String(a.schedule).localeCompare(String(b.schedule)));
    const nextUp = scheduledAll.find((e) => e.schedule >= nowIso) || scheduledAll[0] || null;
    const unscheduled = eps.filter((e) => !e.schedule);

    main.innerHTML = `
      <div class="page-head">
        <div><h1>排期</h1><p class="sub">把右邊待排期集數拖進月曆任一天，或在日格之間拖曳改期。</p></div>
      </div>
      <div class="sched-wrap">
        <section class="card cal-card" style="margin-bottom:0">
          <div class="cal-head">
            <div class="cal-title">${curYear} 年 ${MONTHS[curMonth]} 月</div>
            <div class="cal-stats">
              <span>本月排期 <b>${monthScheduled}</b></span>
              <span>已核准 <b>${approvedCount}</b></span>
              <span>本月靈感 <b>${monthIdeas}</b></span>
            </div>
            <span class="grow"></span>
            <div class="row" style="gap:6px">
              <button type="button" class="btn sm" id="cal-prev">◀</button>
              <button type="button" class="btn sm" id="cal-today">今天</button>
              <button type="button" class="btn sm" id="cal-next">▶</button>
            </div>
          </div>
          <div class="cal-weeks">${WEEK.map((w) => `<span>${w}</span>`).join("")}</div>
          <div class="cal-grid">
            ${rows.map((d) => {
              const key = toDayKey(d);
              const inMonth = d.getMonth() === curMonth;
              const isToday = key === todayKey;
              const posts = byDay.get(key) || [];
              const ideaCnt = ideaCountByDay.get(key) || 0;
              return `<div class="cal-cell ${inMonth ? "" : "is-out"} ${isToday ? "is-today" : ""}" data-day="${key}">
                <div class="cal-day-head">
                  <span>${d.getDate()}</span>
                  ${ideaCnt ? `<span class="idea-pip" title="當天記了 ${ideaCnt} 條靈感">💡${ideaCnt}</span>` : ""}
                </div>
                ${posts.map((ep) => `
                  <div class="cal-chip ${esc(ep.status)}" draggable="true" data-drag-ep="${esc(ep.id)}" data-open-ep="${esc(ep.id)}" title="${esc(ep.package_choice?.title || ep.topic)}">
                    ${ep.thumb ? `<img src="${fileUrl(ep.thumb)}" alt="" draggable="false">` : ""}
                    <div class="cal-chip-txt">
                      <time>${esc(timePart(ep.schedule))}</time>
                      <span>${esc(ep.package_choice?.title || ep.topic)}</span>
                    </div>
                  </div>`).join("")}
              </div>`;
            }).join("")}
          </div>
        </section>

        <aside class="sched-side">
          <div class="card next-up" style="margin-bottom:0">
            <h3 style="margin-bottom:8px">下一支要發</h3>
            ${nextUp ? `
              <a href="#/ep/${encodeURIComponent(nextUp.id)}" style="text-decoration:none;display:block">
                ${nextUp.thumb ? `<img src="${fileUrl(nextUp.thumb)}" alt="" style="width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:7px;margin-bottom:8px">` : ""}
                <b>${esc(nextUp.package_choice?.title || nextUp.topic)}</b>
                <div class="row" style="margin-top:6px;gap:6px">
                  <span class="pill accent">${esc(relDay(nextUp.schedule))}・${esc(fmtShortDate(nextUp.schedule))}</span>
                  ${statusPill(nextUp)}
                </div>
              </a>
              <div class="row" style="margin-top:10px">
                <button type="button" class="btn sm" data-edit-sched="${esc(nextUp.id)}">調整時間</button>
              </div>
            ` : `<div class="muted">尚未安排發布時間。從下方拖曳集數到月曆即可排期。</div>`}
          </div>

          <div class="drop-clear" id="drop-clear">把已排期集數拖到這裡可清除排期</div>

          <div class="card" style="margin-bottom:0">
            <div class="row" style="margin-bottom:10px">
              <h3 class="grow" style="margin:0">待排期（${unscheduled.length}）</h3>
            </div>
            ${unscheduled.length ? unscheduled.map((ep) => `
              <div class="unsched-item" draggable="true" data-drag-ep="${esc(ep.id)}">
                <div class="row" style="gap:8px;align-items:flex-start">
                  ${ep.thumb ? `<img src="${fileUrl(ep.thumb)}" alt="" draggable="false" style="width:48px;height:32px;object-fit:cover;border-radius:4px;flex:none">` : ""}
                  <div class="grow">
                    <a href="#/ep/${encodeURIComponent(ep.id)}" style="text-decoration:none;font-weight:600;font-size:13.5px">${esc(ep.package_choice?.title || ep.topic)}</a>
                    <div class="row" style="margin-top:4px;gap:4px">
                      <span class="pill">${fmtName(ep.format)}</span>
                      ${statusPill(ep)}
                    </div>
                  </div>
                </div>
                <div class="row" style="margin-top:6px">
                  <span class="muted grow" style="font-size:11.5px">拖到月曆排期</span>
                  <button type="button" class="btn sm" data-edit-sched="${esc(ep.id)}">🕒 設定時間</button>
                </div>
              </div>`).join("") : `<div class="muted">所有集數都已排期。</div>`}
          </div>
        </aside>
      </div>
    `;

    $("#cal-prev", main).onclick = () => {
      const d = new Date(curYear, curMonth - 1, 1);
      curYear = d.getFullYear(); curMonth = d.getMonth(); render();
    };
    $("#cal-next", main).onclick = () => {
      const d = new Date(curYear, curMonth + 1, 1);
      curYear = d.getFullYear(); curMonth = d.getMonth(); render();
    };
    $("#cal-today", main).onclick = () => {
      const d = new Date();
      curYear = d.getFullYear(); curMonth = d.getMonth(); render();
    };

    $$("[data-open-ep]", main).forEach((el) => {
      el.onclick = () => { location.hash = `#/ep/${encodeURIComponent(el.dataset.openEp)}`; };
    });

    $$("[data-edit-sched]", main).forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const ep = eps.find((x) => x.id === b.dataset.editSched);
        if (ep) openTimeEditor(ep);
      };
    });

    $$("[data-drag-ep]", main).forEach((el) => {
      el.ondragstart = (e) => {
        e.dataTransfer.setData("text/cf-ep", el.dataset.dragEp);
        e.dataTransfer.effectAllowed = "move";
      };
    });

    $$(".cal-cell[data-day]", main).forEach((cell) => {
      cell.ondragover = (e) => {
        e.preventDefault();
        cell.classList.add("is-over");
      };
      cell.ondragleave = (e) => {
        if (!cell.contains(e.relatedTarget)) cell.classList.remove("is-over");
      };
      cell.ondrop = async (e) => {
        e.preventDefault();
        cell.classList.remove("is-over");
        const eid = e.dataTransfer.getData("text/cf-ep");
        const ep = eps.find((x) => x.id === eid);
        if (!ep) return;
        const nextSched = `${cell.dataset.day}T${timePart(ep.schedule)}`;
        await api(`/api/episodes/${encodeURIComponent(eid)}/schedule`, {
          method: "PATCH",
          body: { schedule: nextSched },
        });
        ep.schedule = nextSched;
        toast(`已排期至 ${cell.dataset.day}`);
        render();
      };
    });

    const clearZone = $("#drop-clear", main);
    if (clearZone) {
      clearZone.ondragover = (e) => { e.preventDefault(); clearZone.classList.add("is-over"); };
      clearZone.ondragleave = () => clearZone.classList.remove("is-over");
      clearZone.ondrop = async (e) => {
        e.preventDefault();
        clearZone.classList.remove("is-over");
        const eid = e.dataTransfer.getData("text/cf-ep");
        const ep = eps.find((x) => x.id === eid);
        if (!ep || !ep.schedule) return;
        await api(`/api/episodes/${encodeURIComponent(eid)}/schedule`, {
          method: "PATCH",
          body: { schedule: null },
        });
        ep.schedule = null;
        toast("已清除排期");
        render();
      };
    }
  };

  render();
}
