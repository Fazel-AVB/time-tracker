// The Time Tracker page: four tabs sharing one week selector.
//
// Every change is sent to the local server (tracker/web/app.py) right away,
// so there is no Save button for the table and nothing is lost when the tab
// is closed. The server does the rules (tracker/service.py); this file only
// draws what it returns and sends what you type.
//
// DOM is built with h() and textContent, never innerHTML with data, so a
// subject called "<b>" shows as typed.
"use strict";

const TOKEN = document.querySelector('meta[name="tt-token"]').content;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// app.py: /api/ping keeps the idle watchdog (launcher.py, IDLE_EXIT_SECONDS
// = 600) from stopping the server while this tab is open. Must stay well
// under 600 s; browsers run background-tab timers about once a minute at most.
const HEARTBEAT_MS = 60_000;
const COLUMNS = ["Subject", "Low Label", "High Label"];  // tracker/suggestions.py SUGGESTION_FIELDS
const PIE_COLORS = ["#7C3AED", "#3B82F6", "#06B6D4", "#A78BFA", "#60A5FA", "#818CF8", "#2563EB", "#8B5CF6"];
const MET_COLORS = { 0: "#6D28D9", 1: "#2563EB", 2: "#7C3AED" };

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style") Object.assign(el.style, v);
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

class ServerStopped extends Error {}

async function api(method, path, body) {
  let resp;
  try {
    resp = await fetch(path, {
      method,
      headers: { "X-TT-Token": TOKEN, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    showStopped();
    throw new ServerStopped("The app is not running");
  }
  if (resp.status === 403) {
    // The token changes at every start: this tab belongs to an earlier run.
    throw new Error("This page is from an earlier start of the app. Reload the page (F5).");
  }
  const isJson = (resp.headers.get("Content-Type") || "").includes("json");
  const data = isJson ? await resp.json() : await resp.blob();
  if (!resp.ok) throw new Error((isJson && data.error) || `Error ${resp.status}`);
  return data;
}

async function download(path, filename) {
  const blob = await api("GET", path);
  const a = h("a", { href: URL.createObjectURL(blob), download: filename });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// Runs an action and reports its error on the page instead of the console.
async function safely(fn) {
  try { return await fn(); } catch (e) {
    if (!(e instanceof ServerStopped)) flash(e.message, "err");
    return undefined;
  }
}

function flash(text, kind = "info", extra = null, sticky = false) {
  const box = document.getElementById("flash");
  const msg = h("div", { class: `msg ${kind}` }, h("span", { class: "grow" }, text), extra,
    h("button", { class: "iconbtn", title: "Close", "aria-label": "Close", onclick: () => msg.remove() }, "✕"));
  box.replaceChildren(msg);
  if (!sticky && kind !== "err") setTimeout(() => msg.remove(), 6000);
}

function fmtHours(x) {  // same as tracker/analytics.py fmt_hours
  if (!x) return "—";
  const total = Math.round(x * 60), hrs = Math.floor(total / 60), mins = total % 60;
  if (hrs && mins) return `${hrs}h ${String(mins).padStart(2, "0")}m`;
  return hrs ? `${hrs}h` : `${mins}m`;
}

function parseDate(iso) { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); }
function isoDate(dt) { return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`; }
function addDays(iso, n) { const d = parseDate(iso); d.setDate(d.getDate() + n); return isoDate(d); }
function mondayOf(dt) { const d = new Date(dt); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return isoDate(d); }
function fmtDay(iso, opts = { month: "short", day: "2-digit" }) { return parseDate(iso).toLocaleDateString("en-US", opts); }
function weekRange(start) {
  return `${fmtDay(start)} – ${fmtDay(addDays(start, 6), { month: "short", day: "2-digit", year: "numeric" })}`;
}

function info(text) { return h("div", { class: "info" }, text); }

// <details> that stays open or closed across re-renders.
const openPanels = new Set();  // ids of panels you opened; all start closed
function panel(id, title, body, forceOpen = false) {
  const d = h("details", { class: "panel", open: forceOpen || openPanels.has(id) }, h("summary", {}, title), h("div", { class: "body" }, body));
  d.addEventListener("toggle", () => (d.open ? openPanels.add(id) : openPanels.delete(id)));
  return d;
}

function remember(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } }
function recall(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } }

// ---------------------------------------------------------------------------
// state, navigation
// ---------------------------------------------------------------------------

const TABS = ["table", "report", "reflection", "goals"];
const state = { tab: "table", week: mondayOf(new Date()), dirty: false };

function readHash() {
  // #<tab>/<monday>, e.g. #report/2026-09-21, so a reload keeps the place.
  const [tab, week] = location.hash.slice(1).split("/");
  if (TABS.includes(tab)) state.tab = tab;
  if (/^\d{4}-\d{2}-\d{2}$/.test(week || "")) state.week = mondayOf(parseDate(week));
}

function go(tab, week) {
  if (state.dirty && !confirm("Your reflection has unsaved changes. Leave without saving?")) return;
  state.dirty = false;
  state.tab = tab || state.tab;
  state.week = week || state.week;
  history.replaceState(null, "", `#${state.tab}/${state.week}`);
  render();
}

async function render() {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  TABS.forEach((t) => (document.getElementById(`tab-${t}`).hidden = t !== state.tab));
  document.getElementById("week-label").textContent = weekRange(state.week);
  document.getElementById("this-week").hidden = state.week === mondayOf(new Date());
  const renderers = { table: renderTable, report: renderReport, reflection: renderReflection, goals: renderGoals };
  await safely(() => renderers[state.tab](document.getElementById(`tab-${state.tab}`)));
}

function renderBanner(season) {
  document.getElementById("banner").replaceChildren(
    h("div", { class: "banner", style: { background: season.gradient, borderColor: season.border, color: season.text_color } },
      h("div", { class: "left" },
        h("span", { class: "emoji" }, season.emoji),
        h("div", {},
          h("span", { class: "tag", style: { background: season.tag_bg, color: season.tag_color } }, season.name), h("br"),
          h("span", { class: "title" }, `Week of ${season.week_label}`))),
      h("span", { class: "deco" }, season.decorations)));
}

// ---------------------------------------------------------------------------
// end-of-week export prompt (shown above every tab)
// ---------------------------------------------------------------------------

let canOpenFolder = false;

async function renderExportPrompt() {
  const box = document.getElementById("export-prompt");
  const { pending } = await api("GET", "/api/export");
  if (!pending) { box.replaceChildren(); return; }
  const more = pending.more ? ` (${pending.more} more after this)` : "";
  const answer = (action) => safely(async () => {
    const res = await api("POST", "/api/export", { week: pending.week_start, action });
    if (res.path) {
      flash(`Report saved to ${res.path}`, "ok",
        canOpenFolder ? h("button", { class: "btn small", onclick: () => safely(() => api("POST", "/api/open-exports")) }, "Open folder") : null, true);
    }
    await renderExportPrompt();
  });
  box.replaceChildren(h("div", { class: "card prompt" },
    h("span", { class: "grow" }, h("b", {}, `The week of ${weekRange(pending.week_start)} has ended.`), ` Export its report to Excel?${more}`),
    h("button", { class: "btn primary", onclick: () => answer("export") }, "Export"),
    h("button", { class: "btn", onclick: () => answer("skip") }, "Not this week")));
}

// ---------------------------------------------------------------------------
// Weekly Table tab
// ---------------------------------------------------------------------------

let tableView = null;  // last /api/week answer; the New-subject boxes read suggestions from it

async function renderTable(root) {
  const view = await api("GET", `/api/week?week=${state.week}`);
  tableView = view;
  renderBanner(view.season);
  root.replaceChildren(
    h("h3", {}, "Weekly Activity Table"),
    view.subjects.length ? weekGrid(view) : info("No subjects yet. Add your first one under New subject below."),
    panel("new-subject", "➕ New subject", newSubjectForm(), !view.subjects.length),
    view.subjects.length ? panel("manage", "🗂 Manage subjects", manageSubjects(view)) : null,
    h("h3", {}, "Log time"),
    view.subjects.length ? logTimeForm(view) : info("Add a subject with New subject above to get started."),
    h("h3", {}, "Entries this week"),
    entriesList(view),
  );
}

function weekGrid(view) {
  const footCells = view.day_totals.map((t) => h("td", { "data-foot": "" }, t.toFixed(2)));
  const weekTotal = h("td", {}, view.week_total.toFixed(2));
  const caption = h("span", { class: "muted" });
  const setCaption = (total) => {
    caption.textContent = `Week total: ${fmtHours(total)} · Type hours into a day (saved when you leave the cell). ` +
      "Type over a name or label to change it for this week. 🗑 removes a row from this week only.";
  };
  setCaption(view.week_total);

  const rows = view.rows.map((r) => {
    const totalCell = h("td", { class: "total" }, r.total.toFixed(2));
    const texts = {};
    const onRename = () => safely(async () => {
      const [name, low, high] = ["name", "low", "high"].map((k) => texts[k].value.trim());
      if (name === r.name && low === r.low && high === r.high) return;
      if (!name || !low || !high) {
        texts.name.value = r.name; texts.low.value = r.low; texts.high.value = r.high;
        throw new Error("Subject, Low Label and High Label can't be empty. To take a row out of this week, use 🗑.");
      }
      await api("PUT", `/api/week/rows/${r.id}`, { week: state.week, name, low, high });
      await render();
    });
    for (const [k, cls] of [["name", "name"], ["low", "label"], ["high", "label"]]) {
      texts[k] = h("input", { class: cls, value: r[k], "aria-label": `${k} of ${r.name}`, onchange: onRename,
        onkeydown: (e) => { if (e.key === "Escape") { e.target.value = r[k]; e.target.blur(); } } });
    }
    const dayInputs = r.days.map((v, i) => h("input", {
      class: "day", type: "number", min: 0, max: 24, step: 0.25, value: v ? String(v) : "",
      placeholder: "0", "aria-label": `${r.name} ${DAYS[i]}`,
      onchange: (e) => safely(async () => {
        const input = e.target;
        const hours = input.value === "" ? 0 : Number(input.value);
        input.classList.remove("bad", "saved");
        try {
          const res = await api("PUT", "/api/week/cell", { week: state.week, subject_id: r.id, day: i, hours });
          // Only totals are redrawn, so the cursor stays where you are typing.
          totalCell.textContent = res.row_total.toFixed(2);
          res.day_totals.forEach((t, j) => (footCells[j].textContent = t.toFixed(2)));
          weekTotal.textContent = res.week_total.toFixed(2);
          setCaption(res.week_total);
          void input.offsetWidth;  // restart the "saved" flash animation
          input.classList.add("saved");
        } catch (err) { input.classList.add("bad"); throw err; }
      }),
    }));
    const remove = h("button", {
      class: "iconbtn", title: "Remove from this week", "aria-label": `Remove ${r.name} from this week`,
      onclick: () => safely(async () => {
        const total = Number(totalCell.textContent);
        if (total > 0 && !confirm(`Remove "${r.name} · ${r.low}" from this week? Its ${fmtHours(total)} this week are deleted; other weeks keep theirs.`)) return;
        await api("DELETE", `/api/week/rows/${r.id}?week=${state.week}`);
        await render();
      }),
    }, "🗑");
    return h("tr", {}, h("td", {}, texts.name), h("td", {}, texts.low), h("td", {}, texts.high),
      dayInputs.map((inp) => h("td", {}, inp)), totalCell, h("td", {}, remove));
  });

  const table = h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, h("th", {}, "Subject"), h("th", {}, "Low Label"), h("th", {}, "High Label"),
      view.days.map((d) => h("th", { class: "num" }, d.abbr, h("span", { class: "date" }, fmtDay(d.date)))),
      h("th", { class: "num" }, "Total"), h("th", {}))),
    h("tbody", {}, rows.length ? rows : h("tr", {}, h("td", { colspan: 12, class: "muted" },
      "No rows this week yet. Add one under New subject below (subjects used last week appear here automatically)."))),
    h("tfoot", {}, h("tr", {}, h("td", { colspan: 3, class: "caption" }, "DAILY TOTAL"), footCells, weekTotal, h("td", {}))));

  return h("div", {},
    h("div", { class: "table-wrap" }, table),
    h("div", { class: "below-table" }, caption,
      h("button", { class: "btn small", onclick: () => safely(() => download(`/api/week/xlsx?week=${state.week}`, `timesheet_${state.week}.xlsx`)) }, "⬇ Download as Excel")));
}

// One text box with earlier values that match by case-insensitive starts-with.
// Clicking a value fills it in; typing a new value is allowed; ✕ hides a value
// from the suggestions (the server keeps the subjects that use it).
// Ported from the Streamlit custom component tracker/new_subject_picker.py (v0.1).
function combo(column, onInput) {
  const input = h("input", { placeholder: "Type or pick…", autocomplete: "off", "aria-label": column });
  const list = h("ul", { class: "combo-list", hidden: true });
  let active = -1;
  const options = () => (tableView && tableView.suggestions[column]) || [];
  const matches = () => { const q = input.value.trim().toLowerCase(); return options().filter((o) => o.toLowerCase().startsWith(q)); };
  const close = () => { list.hidden = true; active = -1; };
  const pick = (v) => { input.value = v; close(); onInput(); };
  const draw = () => {
    const items = matches();
    list.hidden = false;
    if (!items.length) {
      list.replaceChildren(h("li", { class: "combo-empty" }, input.value.trim() ? "New value" : "No saved values yet"));
      return;
    }
    list.replaceChildren(...items.map((opt, i) => {
      // preventDefault on mousedown keeps focus in the input, so blur does
      // not close the list before the click lands.
      const x = h("button", {
        class: "iconbtn", type: "button", title: `Remove "${opt}" from the suggestions`, "aria-label": `Remove ${opt}`,
        onmousedown: (e) => { e.preventDefault(); e.stopPropagation(); },
        onclick: (e) => {
          e.stopPropagation();
          safely(async () => {
            await api("POST", "/api/suggestions/hide", { column, value: opt });
            tableView.suggestions[column] = options().filter((o) => o !== opt);
            draw();
          });
        },
      }, "✕");
      return h("li", { class: `combo-item${i === active ? " active" : ""}`, onmousedown: (e) => e.preventDefault(), onclick: () => pick(opt) },
        h("span", {}, opt), x);
    }));
  };
  input.addEventListener("focus", () => { active = -1; draw(); });
  input.addEventListener("input", () => { active = -1; draw(); onInput(); });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", (e) => {
    const items = matches();
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, items.length - 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); draw(); }
    else if (e.key === "Enter" && !list.hidden && active >= 0 && items[active]) { e.preventDefault(); pick(items[active]); }
    else if (e.key === "Escape") close();
  });
  return { input, el: h("div", { class: "combo" }, input, list) };
}

function newSubjectForm() {
  const add = h("button", { class: "btn primary", disabled: true }, "Add to this week");
  // Enabled only when every box has text, so the server never gets a half-filled subject.
  const refresh = () => (add.disabled = !boxes.every((b) => b.input.value.trim()));
  const boxes = COLUMNS.map((c) => combo(c, refresh));
  add.addEventListener("click", () => safely(async () => {
    const [name, low, high] = boxes.map((b) => b.input.value.trim());
    await api("POST", "/api/week/rows", { week: state.week, name, low, high });
    await render();
  }));
  return h("div", { class: "stack" },
    h("p", { class: "muted" }, "Type to filter your earlier values (starts-with, any case) or type a new one. " +
      "✕ removes a value from the suggestions only; subjects and hours that use it are kept."),
    h("div", { class: "form-row" }, boxes.map((b, i) => h("label", { class: "field" }, COLUMNS[i], b.el)), add));
}

function manageSubjects(view) {
  return h("div", {},
    h("p", { class: "muted" }, "✕ deletes a subject in all weeks, with all its hours, and removes its names from the suggestions. " +
      "Goals linked to it are kept but unlinked. To drop a row from one week only, use 🗑 in the table."),
    h("ul", { class: "subject-list" }, view.subjects.map((s) => h("li", {},
      h("span", { class: "grow" }, h("b", {}, s.name), ` · ${s.low || "—"} · ${s.high || "—"}`),
      h("span", { class: "muted" }, s.entries ? `${s.entries} entries, ${fmtHours(s.hours)}` : "unused"),
      h("button", {
        class: "iconbtn", title: "Delete this subject everywhere", "aria-label": `Delete ${s.name} everywhere`,
        onclick: () => safely(async () => {
          // Logged hours would go with it, so ask first.
          if (s.entries && !confirm(`Delete "${s.name} · ${s.low} · ${s.high}" and its ${s.entries} entries (${fmtHours(s.hours)}) in ALL weeks? This cannot be undone.`)) return;
          await api("DELETE", `/api/subjects/${s.id}`);
          await render();
        }),
      }, "✕")))));
}

function subjectSelect(subjects, selected) {
  return h("select", {}, subjects.map((s) => h("option", { value: s.id, selected: s.id === selected }, s.label)));
}

function logTimeForm(view) {
  const today = isoDate(new Date());
  const clamped = today < view.week_start ? view.week_start : today > view.week_end ? view.week_end : today;
  const subj = subjectSelect([...view.subjects].sort((a, b) => a.label.localeCompare(b.label)));
  const day = h("input", { type: "date", value: clamped, min: view.week_start, max: view.week_end });
  const hours = h("input", { type: "number", min: 0.25, max: 24, step: 0.25, value: "1" });
  const notes = h("input", { placeholder: "optional" });
  const addBtn = h("button", { class: "btn primary", onclick: () => safely(async () => {
    const label = subj.selectedOptions[0].textContent;
    await api("POST", "/api/entries", { subject_id: Number(subj.value), date: day.value, hours: Number(hours.value), notes: notes.value });
    flash(`Logged ${fmtHours(Number(hours.value))} for ${label} on ${fmtDay(day.value, { weekday: "short", month: "short", day: "numeric" })}.`, "ok");
    await render();
  }) }, "Add entry");
  return h("div", { class: "card" }, h("div", { class: "form-row" },
    h("label", { class: "field grow2" }, "Subject", subj), h("label", { class: "field" }, "Date", day),
    h("label", { class: "field" }, "Duration (hours)", hours), h("label", { class: "field grow2" }, "Notes", notes), addBtn));
}

function entriesList(view) {
  if (!view.entries.length) return info("No entries for this week.");
  const body = h("tbody");
  const row = (e) => h("tr", {},
    h("td", {}, `${e.subject} · ${e.low}`),
    h("td", {}, fmtDay(e.date, { weekday: "short", month: "short", day: "2-digit" })),
    h("td", { class: "num" }, fmtHours(e.hours)),
    h("td", {}, e.notes || "—"),
    h("td", { class: "num" },
      h("button", { class: "btn small", onclick: (ev) => ev.target.closest("tr").replaceWith(editRow(e)) }, "Edit"), " ",
      h("button", { class: "btn small danger", onclick: () => safely(async () => {
        await api("DELETE", `/api/entries/${e.id}`);
        await render();
      }) }, "Delete")));
  const editRow = (e) => {
    const subj = subjectSelect(view.subjects, e.subject_id);
    const day = h("input", { type: "date", value: e.date });
    const hours = h("input", { type: "number", min: 0.25, max: 24, step: 0.25, value: String(e.hours) });
    const notes = h("input", { value: e.notes });
    const tr = h("tr", {}, h("td", {}, subj), h("td", {}, day), h("td", {}, hours), h("td", {}, notes),
      h("td", { class: "num" },
        h("button", { class: "btn small primary", onclick: () => safely(async () => {
          await api("PUT", `/api/entries/${e.id}`, { subject_id: Number(subj.value), date: day.value, hours: Number(hours.value), notes: notes.value });
          flash("Entry updated.", "ok");
          await render();
        }) }, "Save"), " ",
        h("button", { class: "btn small", onclick: () => tr.replaceWith(row(e)) }, "Cancel")));
    return tr;
  };
  body.append(...view.entries.map(row));
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Subject"), h("th", {}, "Date"), h("th", { class: "num" }, "Hours"), h("th", {}, "Notes"), h("th", {}))),
    body));
}

// ---------------------------------------------------------------------------
// Weekly Report tab
// ---------------------------------------------------------------------------

const reportOpts = { level: recall("tt-level", "high"), history: recall("tt-history", 8) };

async function renderReport(root) {
  const r = await api("GET", `/api/report?week=${state.week}&level=${reportOpts.level}&history=${reportOpts.history}`);
  renderBanner(r.season);
  const Level = r.level === "high" ? "High" : "Low";
  const seg = h("span", { class: "seg" }, ["high", "low"].map((lv) => h("button", {
    "aria-pressed": String(lv === r.level),
    onclick: () => { reportOpts.level = lv; remember("tt-level", lv); render(); },
  }, lv === "high" ? "High" : "Low")));
  const histVal = h("b", {}, String(r.history_weeks));
  const slider = h("input", { type: "range", min: 2, max: 26, value: String(r.history_weeks),
    oninput: (e) => (histVal.textContent = e.target.value),
    onchange: (e) => { reportOpts.history = Number(e.target.value); remember("tt-history", reportOpts.history); render(); } });
  const controls = h("div", { class: "controls" },
    h("span", {}, "Label level ", seg),
    h("span", {}, "History for averages: ", slider, " ", histVal, " weeks"));

  if (!r.has_entries) {
    root.replaceChildren(controls, info("No entries for this week. Go to the Weekly Table tab to log some time."));
    return;
  }

  const d = r.delta_vs_prev;
  const tiles = h("div", { class: "tiles" },
    tile("Total hours", fmtHours(r.total)),
    tile("vs previous week", fmtHours(Math.abs(d)), h("span", { class: d >= 0 ? "up" : "down" }, `${d >= 0 ? "↑" : "↓"} ${fmtHours(Math.abs(d))}`)),
    tile("Top activity", r.top.label, `${r.top.hours.toFixed(1)}h`),
    tile("Least activity", r.least ? r.least.label : "—", r.least ? `${r.least.hours.toFixed(1)}h` : ""));

  const barEl = h("div", { class: "chart" });
  const series = [{ name: "This week", color: "#7C3AED", values: r.comparison.map((c) => c.hours) }];
  if (r.has_history) series.push({ name: `Avg last ${r.history_weeks}w`, color: "#60A5FA", values: r.comparison.map((c) => c.avg) });
  Charts.bars(barEl, r.comparison.map((c) => c.label), series);

  let trendEl;
  if (r.trend.length >= 2) {
    trendEl = h("div", { class: "chart" });
    Charts.line(trendEl, r.trend.map((t) => fmtDay(t.week_start)), r.trend.map((t) => t.hours), "#7C3AED");
  } else trendEl = info("Log more weeks of data to see a trend.");

  const pieEl = h("div", { class: "chart", style: { maxWidth: "320px", margin: "0 auto" } });
  Charts.donut(pieEl, r.by_subject.map((s) => s.subject), r.by_subject.map((s) => s.hours), PIE_COLORS);
  const subjTable = h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Subject"), h("th", { class: "num" }, "Hours"))),
    h("tbody", {}, r.by_subject.map((s, i) => h("tr", {},
      h("td", {}, h("span", { class: "swatch", style: { background: PIE_COLORS[i % PIE_COLORS.length] } }), s.subject),
      h("td", { class: "num" }, fmtHours(s.hours)))))));

  const fmtDelta = (c) => {
    if (c.pct === null) return "no history";
    const sign = c.diff >= 0 ? "+" : "";
    return `${sign}${c.diff.toFixed(1)}h (${sign}${Math.round(c.pct)}%)`;
  };
  const comparison = r.has_history
    ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, `${Level} Label`), h("th", { class: "num" }, "This week"), h("th", { class: "num" }, "Long-term avg"), h("th", { class: "num" }, "Delta"))),
      h("tbody", {}, r.comparison.map((c) => h("tr", {}, h("td", {}, c.label), h("td", { class: "num" }, fmtHours(c.hours)),
        h("td", { class: "num" }, fmtHours(c.avg)), h("td", { class: "num" }, fmtDelta(c)))))))
    : info(`No history found in the last ${r.history_weeks} weeks. Long-term averages appear once you have logged more than one week.`);

  root.replaceChildren(controls, tiles, h("blockquote", {}, r.narrative),
    h("div", { class: "two" },
      h("div", {}, h("h3", {}, `Hours by ${Level}-Level Label`), barEl),
      h("div", {}, h("h3", {}, "Weekly Trend"), trendEl)),
    h("h3", {}, "Subject Breakdown"),
    h("div", { class: "two" }, pieEl, subjTable),
    h("h3", {}, `${Level}-Level Label — Current vs Long-Term Average`), comparison,
    h("p", {}, h("button", { class: "btn small", onclick: () => safely(() => download(`/api/report/csv?week=${state.week}`, `timesheet_${state.week}.csv`)) }, "⬇ Download week as CSV")));
}

function tile(k, v, d) { return h("div", { class: "tile" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), d ? h("div", { class: "d" }, d) : null); }

// ---------------------------------------------------------------------------
// Reflection tab
// ---------------------------------------------------------------------------

async function renderReflection(root) {
  const r = await api("GET", `/api/reflection?week=${state.week}`);
  renderBanner(r.season);
  const area = (label, value, placeholder) => {
    const t = h("textarea", { placeholder, oninput: () => (state.dirty = true) });
    t.value = value;
    return [t, h("label", { class: "field" }, label, t)];
  };
  const [s, sl] = area("Strengths — what went well?", r.strengths, "e.g. Stayed focused in the mornings, made good progress on the paper...");
  const [w, wl] = area("Weaknesses — what could have gone better?", r.weaknesses, "e.g. Too many interruptions, did not start writing early enough...");
  const [p, pl] = area("Plan for next week", r.plan, "e.g. Block 2h/day for deep work, finish section 3 of the paper...");
  const save = h("button", { class: "btn primary", onclick: () => safely(async () => {
    await api("PUT", "/api/reflection", { week: state.week, strengths: s.value, weaknesses: w.value, plan: p.value });
    state.dirty = false;
    flash("Reflection saved.", "ok");
  }) }, "Save reflection");

  const goals = r.next_goals.length
    ? h("ul", { class: "goal-list" }, r.next_goals.map((g) => h("li", {},
      h("span", {}, g.description),
      h("span", { class: "muted" }, g.target_hours ? `Target: ${fmtHours(g.target_hours)}` : "Qualitative"),
      h("span", { class: "muted" }, `Subject: ${g.subject || "—"}`),
      h("button", { class: "btn small danger", onclick: () => safely(async () => {
        await api("DELETE", `/api/goals/${g.id}`);
        await render();
      }) }, "Delete"))))
    : info("No goals set for next week yet.");

  const desc = h("input", { placeholder: "e.g. Write 2h/day on the manuscript" });
  const target = h("input", { type: "number", min: 0, max: 168, step: 0.5, value: "0" });
  const link = h("select", {}, h("option", { value: "" }, "(none)"), r.subjects.map((x) => h("option", { value: x.id }, x.label)));
  const gnotes = h("input", { placeholder: "optional" });
  const addGoal = h("button", { class: "btn primary", onclick: () => safely(async () => {
    await api("POST", "/api/goals", { week: r.next_week_start, description: desc.value, target_hours: Number(target.value) || null,
      subject_id: link.value ? Number(link.value) : null, notes: gnotes.value });
    flash(`Goal added for the week of ${fmtDay(r.next_week_start)}.`, "ok");
    openPanels.add("add-goal");
    await render();
  }) }, "Add goal");

  root.replaceChildren(
    h("h3", {}, "Reflect on this week"),
    h("p", { class: "muted" }, "Saved per week; together they become a lasting self-review record."),
    h("div", { class: "card stack" }, sl, wl, pl, save),
    h("h3", {}, `Goals for next week (${weekRange(r.next_week_start)})`),
    h("p", { class: "muted" }, "Quantitative goals appear on the Goal Review tab next week. Link a goal to a subject to have it evaluated from your logged hours."),
    goals,
    panel("add-goal", "Add a goal for next week", h("div", { class: "form-row" },
      h("label", { class: "field grow2" }, "Goal description", desc),
      h("label", { class: "field" }, "Target hours (0 = qualitative)", target),
      h("label", { class: "field grow2" }, "Link to subject (enables auto-evaluation)", link),
      h("label", { class: "field" }, "Notes", gnotes), addGoal)));
}

// ---------------------------------------------------------------------------
// Goal Review tab
// ---------------------------------------------------------------------------

async function renderGoals(root) {
  const r = await api("GET", `/api/goals/review?week=${state.week}`);
  renderBanner(r.season);
  if (!r.goals.length) {
    root.replaceChildren(info("No goals were set for this week. Set them on the Reflection tab of the previous week."));
    return;
  }
  const labels = r.met_labels;
  const cards = r.goals.map((g) => {
    const o = g.outcome;
    // A saved evaluation always wins; the suggestion only pre-selects the
    // outcome of goals nobody has evaluated yet.
    const chosen = o ? o.met : g.suggested ?? 0;
    const details = [
      g.target_hours ? `Target: ${fmtHours(g.target_hours)}` : null,
      g.subject ? `Subject: ${g.subject}` : null,
      g.subject && g.actual_hours !== null ? `Logged: ${fmtHours(g.actual_hours)}` : null,
      g.notes ? `Notes: ${g.notes}` : null,
    ].filter(Boolean).join(" · ");
    const [badgeColor, badgeText] = o ? [MET_COLORS[o.met], labels[o.met]]
      : g.suggested !== null ? [MET_COLORS[g.suggested], `Suggested: ${labels[g.suggested]}`] : ["#9CA3AF", "Not evaluated"];
    const name = `met-${g.id}`;
    const radios = h("div", { class: "radios" }, [0, 1, 2].map((v) =>
      h("label", {}, h("input", { type: "radio", name, value: v, checked: v === chosen }), labels[v])));
    const actual = h("input", { type: "number", min: 0, max: 168, step: 0.25,
      value: String((o && o.actual_hours !== null ? o.actual_hours : g.actual_hours) ?? 0) });
    const notes = h("input", { value: o ? o.notes : "" });
    const save = h("button", { class: "btn primary", onclick: () => safely(async () => {
      const met = Number(radios.querySelector("input:checked").value);
      await api("PUT", `/api/goals/${g.id}/outcome`, { met, actual_hours: Number(actual.value) || null, notes: notes.value });
      flash("Evaluation saved.", "ok");
      await render();
    }) }, "Save evaluation");
    return h("div", { class: "card stack" },
      h("div", { class: "goal-head" }, h("div", {}, h("b", {}, g.description), details ? h("div", { class: "muted" }, details) : null),
        h("span", { class: "badge", style: { background: badgeColor } }, badgeText)),
      h("div", { class: "field" }, "Outcome", radios),
      h("div", { class: "form-row" }, h("label", { class: "field" }, "Actual hours", actual), h("label", { class: "field grow2" }, "Evaluation notes", notes), save));
  });

  const s = r.summary;
  const summary = s
    ? h("div", { class: "stack" },
      h("div", { class: "tiles" }, tile("Goals evaluated", String(s.evaluated)), tile("Met", String(s.met)), tile("Partial", String(s.partial)), tile("Not met", String(s.not_met))),
      s.verdict ? info(s.verdict) : h("p", { class: "muted" }, `${s.evaluated} of ${s.total} goals evaluated so far.`))
    : h("p", { class: "muted" }, "Evaluate goals above to see a summary.");

  root.replaceChildren(h("h3", {}, `Goals for this week (${r.goals.length})`), h("div", { class: "stack" }, cards),
    h("h3", {}, "Summary"), summary,
    h("p", { class: "muted" }, "To set goals for next week, go to the Reflection tab."));
}

// ---------------------------------------------------------------------------
// start
// ---------------------------------------------------------------------------

function showStopped() { document.getElementById("stopped").hidden = false; }

async function start() {
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
  document.getElementById("prev").addEventListener("click", () => go(null, addDays(state.week, -7)));
  document.getElementById("next").addEventListener("click", () => go(null, addDays(state.week, 7)));
  document.getElementById("this-week").addEventListener("click", () => go(null, mondayOf(new Date())));
  document.getElementById("quit").addEventListener("click", async () => {
    if (!confirm("Stop Time Tracker? Everything is already saved.")) return;
    await api("POST", "/api/quit").catch(() => {});
    showStopped();
  });
  window.addEventListener("beforeunload", (e) => { if (state.dirty) e.preventDefault(); });

  readHash();
  const meta = await safely(() => api("GET", "/api/info"));
  if (meta) {
    canOpenFolder = meta.can_open_folder;
    document.getElementById("footer").textContent = `Time Tracker ${meta.version} · data: ${meta.db} · reports: ${meta.exports}`;
    if (meta.notice) flash(meta.notice, "info", null, true);
  }
  await safely(renderExportPrompt);
  await go();

  setInterval(() => fetch("/api/ping").catch(showStopped), HEARTBEAT_MS);
}

start();
