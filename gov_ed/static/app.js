/* 共享工具：API、提示、时钟、格式化。三个页面共用。 */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ESI_META = {
  1: { label: "立即抢救", short: "抢救", cls: "esi-1", dot: "esi-l1" },
  2: { label: "高危 · 10 分钟内", short: "高危", cls: "esi-2", dot: "esi-l2" },
  3: { label: "紧急 · 30 分钟内", short: "紧急", cls: "esi-3", dot: "esi-l3" },
  4: { label: "亚紧急 · 60 分钟内", short: "亚紧急", cls: "esi-4", dot: "esi-l4" },
  5: { label: "非紧急 · 2 小时内", short: "非紧急", cls: "esi-5", dot: "esi-l5" },
};
const TONE_NAME = { neutral: "常规", anxious: "焦虑", angry: "暴躁", skeptical: "质疑" };

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function escapeHTML(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let toastHost = null;
function toast(message, kind = "") {
  if (!toastHost) {
    toastHost = document.createElement("div");
    toastHost.className = "toast-host";
    document.body.appendChild(toastHost);
  }
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  toastHost.appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity .3s";
    setTimeout(() => node.remove(), 320);
  }, 3200);
}

function esiBadge(level, size = "") {
  const meta = ESI_META[level] || { cls: "", short: "?" };
  return `<span class="esi-badge ${meta.cls} ${size}">${level ?? "?"}</span>`;
}
function esiChip(level) {
  const meta = ESI_META[level] || { label: "待定", dot: "" };
  return `<span class="esi-chip ${meta.dot}">ESI ${level ?? "?"} · ${meta.short || ""}</span>`;
}
function statusChip(status) {
  const map = { done: "完成", warn: "需注意", critical: "高危", watching: "监测中" };
  return `<span class="status st-${status || "done"}">${map[status] || status}</span>`;
}

function startClock(el) {
  const tick = () => {
    const d = new Date();
    el.textContent = d.toTimeString().slice(0, 8);
  };
  tick();
  setInterval(tick, 1000);
}

function clockOf(iso) {
  if (!iso) return "--:--";
  const m = String(iso).match(/(\d{1,2}):(\d{2})/);
  return m ? `${m[1].padStart(2, "0")}:${m[2]}` : String(iso);
}

function waitText(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes <= 0) return "立即";
  if (minutes < 60) return `${minutes} 分钟`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制到剪贴板", "ok");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    toast("已复制", "ok");
  }
}

/* 提示音：接管台来新工单时用（浏览器要求先有一次用户交互） */
let audioCtx = null;
function beep(times = 2) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    let t = audioCtx.currentTime;
    for (let i = 0; i < times; i++) {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.value = i % 2 ? 660 : 880;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + 0.24);
      t += 0.28;
    }
  } catch { /* 静音也不影响功能 */ }
}
