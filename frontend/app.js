const state = { game: "ssq", overview: [], stats: null, prediction: null, backtest: null, record: null, history: [] };
const charts = {};
const palette = ["#1d2430", "#c4493a", "#2f6f9f", "#2f7d57", "#a15c07", "#6d5bd0", "#8a5a44", "#4e7c8a", "#b45778", "#3f7d20", "#9c6b1f", "#55606b"];
const money = new Intl.NumberFormat("zh-CN");
const sum = (values) => values.reduce((total, value) => total + value, 0);

function draw(id, spec, height) {
  const el = document.getElementById(id);
  if (!el) return;
  if (charts[id]) charts[id].destroy();
  const view = new G2.Chart({
    container: el, autoFit: true, height: height || 320,
    paddingBottom: 34, paddingLeft: 64, paddingTop: 28, paddingRight: 16
  });
  view.options(spec);
  view.render();
  charts[id] = view;
}

const get = async (url) => {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

const balls = (ticket, zones) => `<div class="balls">${zones.map((zone) =>
  ticket[zone.key].map((n) => `<span class="ball ${zone.key === "blue" || zone.key === "back" ? "blue" : "red"}">${String(n).padStart(2, "0")}</span>`).join("")
).join("")}</div>`;

async function boot() {
  state.overview = await get("/api/overview");
  const select = document.getElementById("game");
  select.innerHTML = state.overview.map((item) => `<option value="${item.id}">${item.name}</option>`).join("");
  select.value = state.overview.some((item) => item.id === state.game) ? state.game : state.overview[0].id;
  select.onchange = () => { state.game = select.value; load(); };
  document.getElementById("sync").onclick = sync;
  document.getElementById("run-now").onclick = runSchedule;
  document.getElementById("zone").onchange = drawPreference;
  await Promise.all([load(), refreshSchedule()]);
}

async function refreshSchedule() {
  try {
    const status = await get("/api/schedule");
    const result = status.last_result && status.last_result.games
      ? Object.entries(status.last_result.games).map(([game, item]) => `${game.toUpperCase()} 最新 ${item.latest}`).join(" · ")
      : "尚未执行";
    document.getElementById("schedule").innerHTML =
      `定时任务：每天凌晨 ${String(status.hour).padStart(2, "0")}:${String(status.minute).padStart(2, "0")} 自动拉取最新开奖，并生成下期预测 · `
      + `下次 ${status.next_run || "-"} · 上次 ${status.last_run || "-"} · ${result}`
      + (status.error ? ` · <span class="negative">出错 ${status.error}</span>` : "");
  } catch (error) {
    document.getElementById("schedule").textContent = `定时任务状态读取失败：${error.message}`;
  }
}

async function runSchedule() {
  const button = document.getElementById("run-now");
  button.disabled = true;
  button.textContent = "正在执行";
  try {
    await fetch("/api/schedule/run", { method: "POST" });
    state.overview = await get("/api/overview");
    await Promise.all([load(), refreshSchedule()]);
  } finally {
    button.disabled = false;
    button.textContent = "立即执行定时任务";
  }
}

async function sync() {
  const button = document.getElementById("sync");
  button.disabled = true;
  button.textContent = "正在抓取";
  try {
    await fetch(`/api/sync/${state.game}`, { method: "POST" });
    state.overview = await get("/api/overview");
    await Promise.all([load(), refreshSchedule()]);
  } finally {
    button.disabled = false;
    button.textContent = "更新官方开奖";
  }
}

let loadToken = 0;

async function load() {
  const token = ++loadToken;
  document.getElementById("models").innerHTML = `<div class="loading">正在读取历史开奖与预测…</div>`;
  document.getElementById("table").innerHTML = `<div class="loading">正在读取全历史逐期考试结果…</div>`;
  const [history, stats, prediction] = await Promise.all([
    get(`/api/${state.game}/history?limit=180`),
    get(`/api/${state.game}/stats`),
    get(`/api/${state.game}/predict`)
  ]);
  if (token !== loadToken) return;
  Object.assign(state, { history, stats, prediction, backtest: null, record: null });
  render();
  const [backtest, record] = await Promise.all([
    get(`/api/${state.game}/backtest`),
    get(`/api/${state.game}/record`)
  ]);
  if (token !== loadToken) return;
  Object.assign(state, { backtest, record });
  render();
}

function render() {
  const meta = state.overview.find((item) => item.id === state.game);
  const latest = meta.latest;
  document.getElementById("source").innerHTML = `<a href="${meta.source_url}">${meta.source}</a> · 更新 ${meta.fetched_at || "未记录"}`;
  document.getElementById("history-note").textContent = `本地已存 ${money.format(meta.count)} 期开奖：${meta.first.issue} 至 ${latest.issue}`;
  document.getElementById("metrics").innerHTML = [
    ["最新开奖", latest.issue],
    ["开奖日期", latest.date],
    ["奖池金额", latest.pool ? `¥${money.format(latest.pool)}` : "未公布"],
    ["本期销量", latest.sales ? `¥${money.format(latest.sales)}` : "未公布"]
  ].map(([label, value]) => `<div class="metric"><span>${label}</span><b>${value}</b></div>`).join("");

  document.getElementById("recent").innerHTML = [...state.history].reverse().slice(0, 20).map((row) => `
    <div class="recent-row"><span class="fine">${row.issue}<br>${row.date}</span>${balls(row.numbers, meta.zones)}</div>`).join("");

  drawTrend();
  drawZones();
  fillZoneSelect();
  drawPreference();
  drawDisagreement();
  drawModels(meta);
  renderBacktest();
  drawRecord(meta);
  renderVerdict();
}

function renderVerdict() {
  const cards = [];
  let line = "正在读取逐期考试结果…";
  let sub = "";
  if (state.backtest) {
    const rows = state.backtest.rows;
    const random = rows.find((row) => row.model === "random");
    const best = rows.filter((row) => row.model !== "random").sort((a, b) => b.roi - a.roi)[0];
    const separates = rows.filter((row) => row.separates);
    const periods = state.backtest.periods;
    const tested = rows.filter((row) => row.model !== "random").length;
    line = `把 ${tested} 个模型放在 ${money.format(periods)} 期真实开奖上逐期考试（每期每模型买 ${state.backtest.tickets} 注、每注 ¥${state.backtest.stake}）：`
      + `成绩最好的「${best.name}」每投 1 元收回 ¥${best.roi.toFixed(2)}，闭眼乱选收回 ¥${random.roi.toFixed(2)}。`
      + (separates.length
        ? `目前有 ${separates.length} 个模型在数字上暂时「跑赢」随机，但彩票每期独立随机，这种领先是运气，继续考下去会消失。`
        : `${tested} 个模型的波动范围全部盖住随机基线——<b>没有任何一个比闭眼乱选更准</b>。`);
    sub = "逐期考试＝只用某期之前的历史预测该期，考完一期往前挪一期；这和真的连续买很多期是一回事。";
    cards.push(["已考试", `${money.format(periods)} 期`, `从 ${state.backtest.from_issue} 考到 ${state.backtest.to_issue}`]);
    cards.push(["最好成绩的模型", best.name, `每投 ¥1 收回 ¥${best.roi.toFixed(2)}`]);
    cards.push(["闭眼乱选（对照组）", `¥${random.roi.toFixed(2)}`, "每投 1 元收回的钱"]);
  }
  if (state.record) {
    const active = state.record.rows.filter((row) => row.tickets > 0);
    const bestWin = active.flatMap((row) => Object.entries(row.prizes).map(([grade, count]) => ({ grade, count, name: row.name })))
      .filter((item) => item.count > 0).sort((a, b) => b.count - a.count)[0];
    cards.push(["实盘留存已对号", `${state.record.issues.length} 期`, `待开奖 ${state.record.pending.length} 期`]);
    cards.push(["实盘最好成绩", bestWin ? `${bestWin.grade} × ${bestWin.count}` : "还没中过", bestWin ? `来自「${bestWin.name}」` : "开奖后自动核对"]);
  }
  document.getElementById("verdict-line").innerHTML = line;
  document.getElementById("verdict-sub").textContent = sub;
  document.getElementById("verdict-cards").innerHTML = cards.map(([label, value, note]) =>
    `<div class="vcard"><span>${label}</span><b>${value}</b><em>${note}</em></div>`).join("");
}

function drawTrend() {
  const rows = [...state.history].slice(-60);
  const zone = state.stats.zones[0];
  const data = rows.map((row) => ({ issue: row.issue, sum: sum(row.numbers[zone.key]) }));
  const average = sum(data.map((item) => item.sum)) / Math.max(1, data.length);
  draw("trend", {
    type: "view",
    children: [
      {
        type: "line",
        data,
        encode: { x: "issue", y: "sum" },
        style: { stroke: "#2f6f9f", lineWidth: 1.8 },
        axis: { x: { title: "期号", labelAutoRotate: true, labelFontSize: 9 }, y: { title: `${zone.label}和值` } },
        tooltip: { title: (d) => `第 ${d.issue} 期`, items: [(d) => ({ name: "号码加起来", value: d.sum })] }
      },
      {
        type: "lineY",
        data: [{ y: Number(average.toFixed(1)) }],
        encode: { y: "y" },
        style: { stroke: "#c4493a", lineDash: [5, 4], lineWidth: 1.5 }
      }
    ]
  }, 260);
}

function drawZones() {
  const host = document.getElementById("zones");
  host.innerHTML = state.stats.zones.map((zone) => {
    const waiting = [...zone.numbers].sort((a, b) => b.gap - a.gap).slice(0, 3);
    return `<div class="zone-card">
      <h3>${zone.label} · 近 ${state.stats.window} 期每个号码出现了多少次</h3>
      <div id="zone-${zone.key}" class="chart short"></div>
      <p class="fine">最久没出：${waiting.map((item) => `<b>${String(item.n).padStart(2, "0")}</b>（${item.gap} 期）`).join(" · ")}</p>
    </div>`;
  }).join("");
  state.stats.zones.forEach((zone) => {
    const numbers = [...zone.numbers].sort((a, b) => a.n - b.n);
    const span = zone.max - zone.min + 1;
    const expected = (state.stats.window * zone.count) / span;
    draw(`zone-${zone.key}`, {
      type: "view",
      children: [
        {
          type: "interval",
          data: numbers.map((item) => ({ ...item, label: String(item.n).padStart(2, "0") })),
          encode: { x: "label", y: "count" },
          style: { fill: zone.color || "#2f6f9f" },
          axis: { x: { title: "号码", labelAutoHide: true, labelFontSize: 9 }, y: { title: "出现次数" } },
          tooltip: {
            title: (d) => `号码 ${d.label}`,
            items: [
              (d) => ({ name: "近 120 期出现", value: `${d.count} 次` }),
              (d) => ({ name: "已经多少期没出", value: `${d.gap} 期` })
            ]
          }
        },
        {
          type: "lineY",
          data: [{ y: Number(expected.toFixed(1)) }],
          encode: { y: "y" },
          style: { stroke: "#c4493a", lineDash: [5, 4], lineWidth: 1.5 }
        }
      ]
    }, 260);
  });
}

function fillZoneSelect() {
  const select = document.getElementById("zone");
  const old = select.value;
  select.innerHTML = state.stats.zones.map((zone) => `<option value="${zone.key}">${zone.label}：每个模型有多偏爱这个号</option>`).join("");
  if ([...select.options].some((option) => option.value === old)) select.value = old;
}

const prefFill = (ratio) => ratio >= 1.5 ? "#c4493a" : ratio >= 1.2 ? "#2f6f9f" : ratio >= 0.95 ? "#9dc0d8" : ratio >= 0.75 ? "#cfdde8" : "#eef2f6";

function drawPreference() {
  const zoneKey = document.getElementById("zone").value;
  const zone = state.stats.zones.find((item) => item.key === zoneKey) || state.stats.zones[0];
  const span = zone.max - zone.min + 1;
  const names = Object.fromEntries(state.prediction.catalog.map((item) => [item.id, item.name]));
  const data = [];
  state.prediction.models.forEach((item) => {
    state.prediction.probabilities[item.model][zone.key].forEach((entry) => {
      data.push({
        model: names[item.model],
        label: String(entry.n).padStart(2, "0"),
        ratio: entry.p * span
      });
    });
  });
  document.getElementById("pref-legend").innerHTML = [
    ["#eef2f6", "不押（<0.75 倍）"], ["#cfdde8", "略低（0.75~0.95）"], ["#9dc0d8", "跟乱选一样（0.95~1.2）"],
    ["#2f6f9f", "偏爱（1.2~1.5）"], ["#c4493a", "强偏爱（>1.5）"]
  ].map(([color, text]) => `<span class="swatch"><i style="background:${color}"></i>${text}</span>`).join("");
  draw("pref", {
    type: "cell",
    data,
    encode: { x: "label", y: "model" },
    style: {
      inset: 1.5,
      fill: (d) => prefFill(d.ratio),
      stroke: "#fffdf8"
    },
    labels: [{ text: (d) => d.ratio.toFixed(1), fontSize: 8, fill: (d) => (d.ratio >= 1.2 ? "#ffffff" : "#3a4351") }],
    axis: {
      x: { title: `${zone.label}号码`, labelFontSize: 9 },
      y: { title: false, labelFontSize: 11 }
    },
    tooltip: {
      title: (d) => `${d.model} · 号码 ${d.label}`,
      items: [(d) => ({ name: "偏爱倍数", value: `${d.ratio.toFixed(2)} 倍（1.0＝跟乱选一样）` })]
    }
  }, Math.max(420, state.prediction.models.length * 28));
}

function drawDisagreement() {
  const probs = state.prediction.probabilities;
  const names = Object.fromEntries(state.prediction.catalog.map((item) => [item.id, item.name]));
  const models = state.prediction.models.map((item) => item.model);
  const tops = {};
  state.stats.zones.forEach((zone) => {
    const keep = zone.count + 2;
    models.forEach((model) => {
      const ranked = [...probs[model][zone.key]].sort((a, b) => b.p - a.p).slice(0, keep);
      tops[model] = (tops[model] || new Set());
      ranked.forEach((entry) => tops[model].add(`${zone.key}:${entry.n}`));
    });
  });
  const data = [];
  models.forEach((left) => models.forEach((right) => {
    const shared = [...tops[left]].filter((key) => tops[right].has(key)).length;
    const ratio = shared / Math.max(1, tops[left].size);
    data.push({ left: names[left], right: names[right], ratio, label: left === right ? "" : ratio.toFixed(2) });
  }));
  draw("disagree", {
    type: "cell",
    data,
    encode: { x: "right", y: "left" },
    style: {
      inset: 1,
      fill: (d) => (d.left === d.right ? "#1d2430" : d.ratio >= 0.7 ? "#c4493a" : d.ratio >= 0.45 ? "#2f6f9f" : d.ratio >= 0.25 ? "#9dc0d8" : "#e7eef4"),
      stroke: "#fffdf8"
    },
    labels: [{ text: (d) => d.label, fontSize: 9, fill: (d) => (d.ratio >= 0.45 ? "#ffffff" : "#3a4351") }],
    axis: { x: { title: false, labelAutoRotate: true, labelFontSize: 10 }, y: { title: false, labelFontSize: 11 } },
    tooltip: { title: (d) => `${d.left} × ${d.right}`, items: [(d) => ({ name: "最爱号码重合", value: `${Math.round(d.ratio * 100)}%` })] }
  }, Math.max(360, models.length * 26));
}

function drawModels(meta) {
  const names = Object.fromEntries(state.prediction.catalog.map((item) => [item.id, item]));
  const prediction = state.prediction;
  document.getElementById("target-issue").textContent = prediction.target_issue;
  document.getElementById("predict-note").textContent =
    `依据第 ${prediction.based_on.issue} 期（${prediction.based_on.date}）生成 · ${prediction.source === "live" ? "实盘留存" : "历史回填"} · 保存于 ${prediction.saved_at}`;
  document.getElementById("models").innerHTML = prediction.models.map((item) => `
    <article class="model"><span>${names[item.model].idea}</span><b>${names[item.model].name}</b>
      <div class="tickets">${item.tickets.map((ticket, index) => `<div class="ticket"><span class="fine">第${index + 1}注</span>${balls(ticket, meta.zones)}</div>`).join("")}</div>
    </article>`).join("");
}

function renderBacktest() {
  const host = document.getElementById("table");
  if (!state.backtest) {
    host.innerHTML = `<div class="loading">正在读取全历史逐期考试结果…</div>`;
    return;
  }
  drawBacktest();
}

function drawBacktest() {
  const report = state.backtest;
  const rows = report.rows;
  document.getElementById("periods-inline").textContent = money.format(report.periods);
  document.getElementById("backtest-note").textContent =
    `前 ${report.warmup} 期只当教材 · 考试区间 ${report.from_issue} 至 ${report.to_issue} · 每期每模型 ${report.tickets} 注`;

  const random = rows.find((row) => row.model === "random");
  const best = rows.filter((row) => row.model !== "random").sort((a, b) => b.roi - a.roi)[0];
  draw("roi", {
    type: "view",
    children: [
      {
        type: "interval",
        data: rows.map((row) => ({ name: row.name, roi: row.roi, model: row.model })),
        encode: { x: "name", y: "roi" },
        style: { fill: (d) => (d.model === "random" ? "#6b7686" : d.model === best.model ? "#c4493a" : "#2f6f9f") },
        labels: [{ text: (d) => `¥${d.roi.toFixed(2)}`, fontSize: 10, fill: "#ffffff" }],
        axis: { x: { title: "模型", labelAutoRotate: true }, y: { title: "每投 1 元收回（元）" } },
        tooltip: { title: (d) => d.name, items: [(d) => ({ name: "每投 1 元收回", value: `¥${d.roi.toFixed(2)}` })] }
      },
      {
        type: "lineY",
        data: [{ y: random.roi }],
        encode: { y: "y" },
        style: { stroke: "#c4493a", lineDash: [5, 4], lineWidth: 1.5 }
      }
    ]
  }, 320);

  const timeline = [];
  report.timeline.forEach((point) => rows.forEach((row) => {
    if (point.models[row.model] !== undefined) timeline.push({ issue: point.issue, name: row.name, cum: point.models[row.model] });
  }));
  draw("cum", {
    type: "line",
    data: timeline,
    encode: { x: "issue", y: "cum", color: "name" },
    scale: { color: { type: "ordinal", domain: rows.map((row) => row.name), range: palette } },
    style: { lineWidth: 1.6 },
    axis: { x: { title: "期号（鼠标放上去看具体是哪期）", label: false }, y: { title: "账面还剩（元）" } },
    legend: { color: { position: "top" } },
    tooltip: { title: (d) => `第 ${d.issue} 期`, items: [(d) => ({ name: d.name, value: `¥${money.format(d.cum)}` })] }
  }, 380);

  const band = rows.filter((row) => row.model !== "random")
    .map((row) => ({ name: row.name, lo: row.interval[0], hi: row.interval[1] }));
  draw("band", {
    type: "view",
    children: [
      {
        type: "interval",
        data: band,
        encode: { x: "name", y: "hi", y1: "lo" },
        style: { fill: "#8ea4b8" },
        tooltip: { items: [(d) => ({ name: "每期比乱选多赚的正常波动", value: `¥${d.lo} ~ ¥${d.hi}` })] },
        axis: { x: { title: "模型", labelAutoRotate: true }, y: { title: "每期比乱选多赚（元）" } }
      },
      {
        type: "lineY",
        data: [{ y: 0 }],
        encode: { y: "y" },
        style: { stroke: "#c4493a", lineDash: [5, 4], lineWidth: 1.5 }
      }
    ]
  }, 320);

  const prizeData = [];
  rows.forEach((row) => report.grades.forEach((grade) => {
    const count = row.prizes[grade] || 0;
    if (count) prizeData.push({ name: row.name, grade, count });
  }));
  const prizeColors = ["#7a1f1a", "#c4493a", "#d4782f", "#e0a106", "#2f7d57", "#2f6f9f", "#6d5bd0", "#8a5a44", "#55606b"];
  draw("prize-mix", {
    type: "interval",
    data: prizeData,
    encode: { x: "name", y: "count", color: "grade" },
    transform: [{ type: "stackY" }],
    scale: { color: { domain: report.grades, range: prizeColors.slice(0, report.grades.length) } },
    axis: { x: { title: "模型", labelAutoRotate: true }, y: { title: "中奖注数" } },
    legend: { color: { position: "top" } },
    tooltip: { title: (d) => d.name, items: [(d) => ({ name: d.grade, value: `${d.count} 注` })] }
  }, 340);

  const hitData = [];
  rows.forEach((row) => {
    const hist = row.hit_hist || {};
    const total = Object.values(hist).reduce((total, value) => total + value, 0) || 1;
    Object.entries(hist).forEach(([hits, count]) => {
      hitData.push({ name: row.name, hits: `${hits} 个`, share: count / total, count, model: row.model });
    });
  });
  const hitOrder = [...new Set(hitData.map((item) => item.hits))].sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  draw("hit-dist", {
    type: "interval",
    data: hitData,
    encode: { x: "hits", y: "share", color: "name" },
    transform: [{ type: "dodgeX" }],
    scale: { x: { domain: hitOrder }, color: { type: "ordinal", domain: rows.map((row) => row.name), range: palette } },
    axis: { x: { title: "一注命中几个号" }, y: { title: "占全部注数", labelFormatter: (value) => `${Math.round(value * 100)}%` } },
    legend: { color: { position: "top" } },
    tooltip: { title: (d) => `${d.name} · 命中 ${d.hits}`, items: [(d) => ({ name: "占比", value: `${(d.share * 100).toFixed(1)}%（${d.count} 注）` })] }
  }, 340);

  document.getElementById("table").innerHTML = `<h3 class="sub-title">逐期考试总账</h3><div class="wrap"><table><thead><tr>
    <th>模型</th><th>花掉</th><th>收回</th><th>每投1元收回</th><th>每期比乱选多赚（正常波动）</th><th>比乱选更准吗</th><th>中奖比例</th>${report.grades.map((grade) => `<th>${grade}</th>`).join("")}
  </tr></thead><tbody>
    ${rows.map((row) => `<tr><td>${row.name}</td><td>¥${money.format(row.spent)}</td><td>¥${money.format(row.returned)}</td>
      <td class="${row.roi >= 1 ? "positive" : "negative"}">¥${row.roi.toFixed(2)}</td>
      <td>${row.model === "random" ? "——（它就是基线）" : `¥${row.interval[0]} ~ ¥${row.interval[1]}`}</td>
      <td>${row.model === "random" ? "——" : row.separates ? (row.interval[0] > 0 ? "是（暂时领先）" : "否（比乱选还差）") : "否（没差别）"}</td>
      <td>${(row.hit_rate * 100).toFixed(2)}%</td>${report.grades.map((grade) => `<td>${row.prizes[grade] || 0}</td>`).join("")}</tr>`).join("")}
  </tbody></table></div><p class="fine">${report.note}「每期比乱选多赚」是每期相对随机对照组差额的 95% 波动范围——只要范围盖住 0，就跟乱选没区别。</p>`;
}

function drawRecord(meta) {
  const host = document.getElementById("record-table");
  if (!state.record) {
    host.innerHTML = `<div class="loading">正在读取实盘留存对号结果…</div>`;
    return;
  }
  const report = state.record;
  const names = Object.fromEntries(state.prediction.catalog.map((item) => [item.id, item.name]));
  const issues = report.issues;
  const active = report.rows.filter((row) => row.tickets > 0);
  document.getElementById("record-note").textContent =
    `已对号 ${issues.length} 期 · 待开奖 ${report.pending.length} 期 · 每模型每期 5 注`;

  if (!issues.length) {
    document.getElementById("rec-cum").innerHTML = "";
    document.getElementById("rec-hits").innerHTML = "";
    host.innerHTML = `<p class="fine">还没有能对号的记录：预测会在开奖前存好，等下一期开奖后自动比对。已存待开奖 ${report.pending.length} 期。</p>`;
    return;
  }

  const cum = [];
  issues.forEach((point) => Object.entries(point.models).forEach(([model, item]) => {
    cum.push({ issue: point.issue, name: names[model], cum: item.cumulative });
  }));
  draw("rec-cum", {
    type: "line",
    data: cum,
    encode: { x: "issue", y: "cum", color: "name" },
    scale: { color: { type: "ordinal", domain: active.map((row) => row.name), range: palette } },
    style: { lineWidth: 1.8 },
    axis: { x: { title: "开奖期号", labelAutoRotate: true }, y: { title: "账面还剩（元）" } },
    legend: { color: { position: "top" } },
    tooltip: { title: (d) => `第 ${d.issue} 期`, items: [(d) => ({ name: d.name, value: `¥${money.format(d.cum)}` })] }
  }, 260);

  const hits = [];
  issues.forEach((point) => active.forEach((row) => {
    const item = point.models[row.model];
    if (item) hits.push({ issue: point.issue, model: row.name, hits: item.best_hits, returned: item.returned });
  }));
  draw("rec-hits", {
    type: "cell",
    data: hits.map((item) => ({ ...item, label: String(item.hits) })),
    encode: { x: "issue", y: "model" },
    style: {
      inset: 1.5,
      fill: (d) => (d.hits >= 4 ? "#c4493a" : d.hits >= 3 ? "#2f6f9f" : d.hits >= 2 ? "#9dc0d8" : d.hits >= 1 ? "#cfdde8" : "#eef2f6"),
      stroke: "#fffdf8"
    },
    labels: [{ text: (d) => d.label, fontSize: 9, fill: (d) => (d.hits >= 3 ? "#ffffff" : "#3a4351") }],
    axis: { x: { title: "开奖期号", labelAutoRotate: true, labelFontSize: 9 }, y: { title: false, labelFontSize: 11 } },
    tooltip: {
      title: (d) => `第 ${d.issue} 期 · ${d.model}`,
      items: [
        (d) => ({ name: "单注最高命中", value: `${d.hits} 个号` }),
        (d) => ({ name: "该期收回", value: `¥${money.format(d.returned)}` })
      ]
    }
  }, 320);

  host.innerHTML = `<h3 class="sub-title">实盘总账</h3><div class="wrap"><table><thead><tr>
    <th>模型</th><th>号码来源</th><th>买了几注</th><th>花掉</th><th>收回</th><th>每投1元收回</th><th>中奖比例</th><th>最好成绩</th>
    ${report.grades.map((grade) => `<th>${grade}</th>`).join("")}
  </tr></thead><tbody>
    ${active.map((row) => `<tr><td>${row.name}</td><td>${row.source === "live" ? "实盘留存" : row.source === "backfill" ? "历史回填" : row.source}</td>
      <td>${row.tickets}</td><td>¥${money.format(row.spent)}</td><td>¥${money.format(row.returned)}</td>
      <td class="${row.roi >= 1 ? "positive" : "negative"}">¥${row.roi.toFixed(2)}</td>
      <td>${(row.hit_rate * 100).toFixed(2)}%</td><td>¥${money.format(row.best)}</td>
      ${report.grades.map((grade) => `<td>${row.prizes[grade] || 0}</td>`).join("")}</tr>`).join("")}
  </tbody></table></div>
  ${report.pending.length ? `<p class="fine">还没开奖、等着对号的：${report.pending.map((item) => `依据 ${item.based_on} → 第 ${item.target_issue} 期`).join(" · ")}</p>` : ""}
  <p class="fine">${report.note}</p>`;

  const compared = [...issues].reverse().filter((point) => Object.values(point.models).some((item) => item.tickets));
  document.getElementById("record-detail").innerHTML = compared.length ? `
    <h3 class="sub-title">逐注对照 · 最近 ${compared.length} 期（每期列命中最多的那一注）</h3>
    <div class="wrap"><table><thead><tr>
      <th>期号</th><th>实际开奖</th><th>命中最多的预测</th><th>来自模型</th><th>命中几个</th><th>中了什么</th><th>这注拿回</th>
    </tr></thead><tbody>
      ${compared.map((point) => {
        const flat = Object.entries(point.models).flatMap(([model, item]) =>
          (item.tickets || []).map((ticket) => ({ model, ...ticket })));
        flat.sort((a, b) => sum(b.hits) - sum(a.hits) || b.amount - a.amount);
        const best = flat[0];
        return `<tr>
          <td>${point.issue}<br><span class="fine">${point.date}</span></td>
          <td>${balls(point.numbers, meta.zones)}</td>
          <td>${best ? balls(best.ticket, meta.zones) : "——"}</td>
          <td>${best ? names[best.model] : "——"}</td>
          <td>${best ? sum(best.hits) : 0}</td>
          <td>${best ? best.prize : "未中奖"}</td>
          <td class="${best && best.amount ? "positive" : ""}">¥${money.format(best ? best.amount : 0)}</td>
        </tr>`;
      }).join("")}
    </tbody></table></div>` : "";
}

boot().catch((error) => {
  document.getElementById("models").innerHTML = `<div class="loading">数据还没准备好：${error.message}</div>`;
});
