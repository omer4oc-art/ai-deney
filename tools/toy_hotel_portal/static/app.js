(function () {
  "use strict";

  var hasDom = typeof window !== "undefined" && typeof document !== "undefined";
  var debugMode = hasDom ? new URLSearchParams(window.location.search).get("debug") === "1" : false;
  var warnedEmptyOccupancy = false;
  var lastAskOutput = "";
  var lastAskFormat = "md";
  var lastAskContentType = "text/markdown";
  var lastAskQuestion = "";
  var lastAskResponse = null;
  var lastAskRunId = "";
  var askTraceExpanded = false;

  function byId(id) {
    if (!hasDom) {
      return null;
    }
    return document.getElementById(id);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function toMmDd(isoDate) {
    var raw = String(isoDate || "");
    if (raw.length >= 10) {
      return raw.slice(5, 10);
    }
    return "00-00";
  }

  function wireNav() {
    var dashboardLink = byId("nav-dashboard");
    var checkinLink = byId("nav-checkin");
    if (dashboardLink) {
      dashboardLink.addEventListener("click", function (event) {
        event.preventDefault();
        window.location.href = "/";
      });
    }
    if (checkinLink) {
      checkinLink.addEventListener("click", function (event) {
        event.preventDefault();
        window.location.href = "/checkin";
      });
    }
  }

  function toIsoDate(d) {
    var year = d.getFullYear();
    var month = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function setDefaultRange() {
    var startInput = byId("start-date");
    var endInput = byId("end-date");
    if (!startInput || !endInput) {
      return;
    }
    if (startInput.value && endInput.value) {
      return;
    }
    var today = new Date();
    var start = new Date(today.getTime());
    start.setDate(today.getDate() - 13);
    if (!startInput.value) {
      startInput.value = toIsoDate(start);
    }
    if (!endInput.value) {
      endInput.value = toIsoDate(today);
    }
  }

  async function fetchJson(url, options) {
    var resp = await fetch(url, options || {});
    var text = await resp.text();
    var body = {};
    if (text) {
      try {
        body = JSON.parse(text);
      } catch (err) {
        body = { detail: text };
      }
    }
    if (!resp.ok) {
      throw new Error(body.detail || ("request failed: " + resp.status));
    }
    return body;
  }

  function extractFilename(contentDisposition, fallback) {
    if (!contentDisposition) {
      return fallback;
    }
    var match = /filename=\"?([^\";]+)\"?/i.exec(contentDisposition);
    if (!match || !match[1]) {
      return fallback;
    }
    return match[1];
  }

  async function downloadExport(start, end) {
    var query = "start=" + encodeURIComponent(start) + "&end=" + encodeURIComponent(end);
    var resp = await fetch("/api/export?" + query, { method: "GET" });
    if (!resp.ok) {
      var errText = await resp.text();
      throw new Error(errText || ("request failed: " + resp.status));
    }

    var blob = await resp.blob();
    var defaultName = "toy_portal_" + start + "_" + end + ".csv";
    var filename = extractFilename(resp.headers.get("content-disposition"), defaultName);
    var downloadUrl = window.URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(downloadUrl);
  }

  function renderChart(occupancy) {
    var chart = byId("occupancy-chart");
    var template = byId("occupancy-bar-template");
    if (!chart || !template) {
      return 0;
    }

    var days = occupancy && Array.isArray(occupancy.days) ? occupancy.days : [];
    chart.innerHTML = "";

    if (!days.length) {
      if (!warnedEmptyOccupancy) {
        console.warn("occupancy payload has no days to render");
        warnedEmptyOccupancy = true;
      }
      var placeholder = template.content.firstElementChild.cloneNode(true);
      var placeholderBar = placeholder.querySelector("[data-bar-fill]");
      var placeholderTooltip = placeholder.querySelector(".bar-tooltip");
      var placeholderLabel = placeholder.querySelector(".bar-label");
      placeholder.dataset.date = "";
      placeholder.dataset.barValue = "0";
      placeholder.dataset.barLabel = "00-00";
      if (placeholderTooltip) {
        placeholderTooltip.textContent = "0";
      }
      if (placeholderLabel) {
        placeholderLabel.textContent = "00-00";
      }
      if (placeholderBar) {
        placeholderBar.style.height = "0%";
      }
      chart.appendChild(placeholder);
      return 1;
    }

    var maxOccupiedRaw = 0;
    days.forEach(function (day) {
      var occupied = Number((day && day.occupied_rooms) || 0);
      if (occupied > maxOccupiedRaw) {
        maxOccupiedRaw = occupied;
      }
    });
    var maxOccupied = Math.max(1, maxOccupiedRaw);
    var heightSamples = [];
    var rendered = 0;
    days.forEach(function (day) {
      var el = template.content.firstElementChild.cloneNode(true);
      var bar = el.querySelector("[data-bar-fill]");
      var tooltip = el.querySelector(".bar-tooltip");
      var label = el.querySelector(".bar-label");
      var occupied = Number((day && day.occupied_rooms) || 0);
      var labelText = toMmDd(day && day.date);
      // Scale by the peak day for readability, while occupancy % still uses absolute room capacity.
      var heightPct = maxOccupiedRaw > 0 ? clamp((occupied / maxOccupied) * 95, 0, 100) : 0;

      if (bar) {
        bar.style.height = String(heightPct) + "%";
      }
      if (tooltip) {
        tooltip.textContent = String(occupied);
      }
      if (label) {
        label.textContent = labelText;
      }
      el.dataset.date = String((day && day.date) || "");
      el.dataset.barValue = String(occupied);
      el.dataset.barLabel = labelText;

      chart.appendChild(el);
      if (heightSamples.length < 3) {
        heightSamples.push(heightPct);
      }
      rendered += 1;
    });

    if (debugMode) {
      console.log("occupancy maxOccupied", maxOccupiedRaw);
      console.log("occupancy heightPct sample", heightSamples);
    }

    return rendered;
  }

  function renderReservations(rows) {
    var tbody = byId("reservations-tbody");
    var loading = byId("reservations-loading");
    if (!tbody) {
      return;
    }
    tbody.innerHTML = "";
    if (!rows.length) {
      var empty = document.createElement("tr");
      empty.innerHTML =
        '<td class="px-6 py-6 text-center text-slate-500 dark:text-slate-400" colspan="6">No reservations in range.</td>';
      tbody.appendChild(empty);
      return;
    }
    rows.slice(0, 10).forEach(function (r) {
      var tr = document.createElement("tr");
      [
        r.reservation_id,
        r.guest_name,
        r.check_in,
        r.check_out,
        r.room_type,
        r.source_channel,
      ].forEach(function (value) {
        var td = document.createElement("td");
        td.className = "px-6 py-4 text-sm";
        td.textContent = value == null ? "" : String(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    if (loading) {
      loading.style.display = "none";
    }
  }

  function setText(id, value) {
    var el = byId(id);
    if (el) {
      el.textContent = String(value);
    }
  }

  function setAskStatus(message) {
    var status = byId("ask-status");
    if (status) {
      status.textContent = String(message || "");
    }
  }

  function renderAskOutput(output, format, contentType) {
    var askOutputText = byId("ask-output-text");
    var askOutputHtml = byId("ask-html-preview");
    var outputText = String(output || "");
    var isHtml = String(format || "") === "html" || String(contentType || "") === "text/html";

    if (askOutputText) {
      askOutputText.classList.toggle("hidden", isHtml);
    }
    if (askOutputHtml) {
      askOutputHtml.classList.toggle("hidden", !isHtml);
    }

    if (isHtml && askOutputHtml) {
      askOutputHtml.srcdoc = outputText;
    } else if (askOutputText) {
      // Markdown is rendered as plain text when no markdown renderer is available.
      askOutputText.textContent = outputText;
    }
  }

  function setAskBusy(isBusy) {
    var askSubmit = byId("ask-submit");
    var askSave = byId("ask-save");
    var askDownload = byId("ask-download");
    var askDownloadJson = byId("ask-download-json");
    if (askSubmit) {
      askSubmit.disabled = Boolean(isBusy);
      askSubmit.textContent = isBusy ? "Running... ⏳" : "Ask";
    }
    if (askSave) {
      var req = currentAskRequest();
      askSave.disabled = Boolean(isBusy) || !req.question;
    }
    if (askDownload) {
      askDownload.disabled = Boolean(isBusy) || !lastAskOutput;
    }
    if (askDownloadJson) {
      askDownloadJson.disabled = Boolean(isBusy) || !lastAskResponse;
    }
  }

  function downloadAskOutput() {
    if (!lastAskOutput) {
      return;
    }
    var ext = lastAskFormat === "html" ? "html" : "md";
    var filename = buildAskFilename(lastAskQuestion, ext);
    var blob = new Blob([lastAskOutput], { type: lastAskContentType || "text/plain" });
    var downloadUrl = window.URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(downloadUrl);
  }

  function hashText(text) {
    var h = 5381;
    var s = String(text || "");
    for (var i = 0; i < s.length; i += 1) {
      h = ((h << 5) + h) ^ s.charCodeAt(i);
      h = h >>> 0;
    }
    return h.toString(16);
  }

  function slugifyText(text) {
    var s = String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    if (!s) {
      return "ask";
    }
    return s.slice(0, 40);
  }

  function buildAskRunShortSlug(question) {
    return slugifyText(question).slice(0, 32);
  }

  function buildAskRunHash8(payload) {
    var normalized = {
      question: String((payload && payload.question) || "").trim(),
      format: String((payload && payload.format) || "md") === "html" ? "html" : "md",
      redact_pii: Boolean(payload && payload.redact_pii),
      debug: Boolean(payload && payload.debug),
    };
    var encoded = JSON.stringify(normalized);
    var full = hashText(encoded);
    return full.padStart(8, "0").slice(-8);
  }

  function buildAskFilename(question, ext) {
    return "ask_" + slugifyText(question) + "_" + hashText(question) + "." + ext;
  }

  function buildAskJsonTimestamp() {
    var now = new Date();
    var year = String(now.getFullYear());
    var month = String(now.getMonth() + 1).padStart(2, "0");
    var day = String(now.getDate()).padStart(2, "0");
    var hours = String(now.getHours()).padStart(2, "0");
    var minutes = String(now.getMinutes()).padStart(2, "0");
    var seconds = String(now.getSeconds()).padStart(2, "0");
    return year + month + day + "_" + hours + minutes + seconds;
  }

  function toFiniteNumber(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function formatMoney(value) {
    var n = toFiniteNumber(value);
    return n == null ? "n/a" : n.toFixed(2);
  }

  function formatPercent(value) {
    var n = toFiniteNumber(value);
    return n == null ? "n/a" : n.toFixed(2) + "%";
  }

  function renderAskDelta(spec, meta) {
    var card = byId("ask-delta-card");
    var deltaTotalEl = byId("ask-delta-total");
    var deltaPctEl = byId("ask-delta-pct");
    var maxSpanEl = byId("ask-max-span");
    var minSpanEl = byId("ask-min-span");
    if (!card || !deltaTotalEl || !deltaPctEl || !maxSpanEl || !minSpanEl) {
      return;
    }

    var deltas = meta && meta.deltas && typeof meta.deltas === "object" ? meta.deltas : {};
    var spans = spec && Array.isArray(spec.spans) ? spec.spans : [];
    var totals = meta && Array.isArray(meta.totals) ? meta.totals : [];
    var hasDeltas = Object.keys(deltas).length > 0;
    var isMultiSpan = spans.length >= 2;
    if (!hasDeltas && !isMultiSpan) {
      card.classList.add("hidden");
      deltaTotalEl.textContent = "delta_total_sales: -";
      deltaPctEl.textContent = "pct_change_total_sales: -";
      maxSpanEl.textContent = "max_span: -";
      minSpanEl.textContent = "min_span: -";
      return;
    }

    var deltaTotalSales = deltas.delta_total_sales;
    var pctChangeTotalSales = deltas.pct_change_total_sales;
    var maxSpanLabel = deltas.max_span_label;
    var maxSpanTotalSales = deltas.max_span_total_sales;
    var minSpanLabel = deltas.min_span_label;
    var minSpanTotalSales = deltas.min_span_total_sales;

    if (totals.length >= 2) {
      var first = totals[0] || {};
      var last = totals[totals.length - 1] || {};
      var firstSales = toFiniteNumber(first.total_sales);
      var lastSales = toFiniteNumber(last.total_sales);
      if (deltaTotalSales == null && firstSales != null && lastSales != null) {
        deltaTotalSales = Number((lastSales - firstSales).toFixed(2));
      }
      if (pctChangeTotalSales == null && firstSales != null && lastSales != null && firstSales !== 0) {
        pctChangeTotalSales = Number((((lastSales - firstSales) / firstSales) * 100).toFixed(2));
      }
      if (maxSpanLabel == null || maxSpanTotalSales == null || minSpanLabel == null || minSpanTotalSales == null) {
        var validTotals = totals
          .map(function (row) {
            var sales = toFiniteNumber(row && row.total_sales);
            return sales == null ? null : { label: String((row && row.label) || ""), total_sales: sales };
          })
          .filter(function (row) { return row != null; });
        if (validTotals.length) {
          validTotals.sort(function (a, b) {
            if (a.total_sales === b.total_sales) {
              return a.label < b.label ? -1 : (a.label > b.label ? 1 : 0);
            }
            return a.total_sales - b.total_sales;
          });
          var minRow = validTotals[0];
          var maxRow = validTotals[validTotals.length - 1];
          if (maxSpanLabel == null) {
            maxSpanLabel = maxRow.label;
          }
          if (maxSpanTotalSales == null) {
            maxSpanTotalSales = maxRow.total_sales;
          }
          if (minSpanLabel == null) {
            minSpanLabel = minRow.label;
          }
          if (minSpanTotalSales == null) {
            minSpanTotalSales = minRow.total_sales;
          }
        }
      }
    }

    var pctSuffix = "";
    if (pctChangeTotalSales == null && deltas.pct_change_note) {
      pctSuffix = " (" + String(deltas.pct_change_note) + ")";
    }
    deltaTotalEl.textContent = "delta_total_sales: " + formatMoney(deltaTotalSales);
    deltaPctEl.textContent = "pct_change_total_sales: " + formatPercent(pctChangeTotalSales) + pctSuffix;
    maxSpanEl.textContent = "max_span: " + String(maxSpanLabel || "n/a") + " (" + formatMoney(maxSpanTotalSales) + ")";
    minSpanEl.textContent = "min_span: " + String(minSpanLabel || "n/a") + " (" + formatMoney(minSpanTotalSales) + ")";
    card.classList.remove("hidden");
  }

  function downloadAskJson() {
    if (!lastAskResponse) {
      return;
    }
    var filename = "ask_alice_" + buildAskJsonTimestamp() + ".json";
    var payload = JSON.stringify(lastAskResponse, null, 2);
    var blob = new Blob([payload], { type: "application/json" });
    var downloadUrl = window.URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(downloadUrl);
  }

  function renderAskMeta(spec, meta) {
    var askMeta = byId("ask-meta");
    var askSpansCount = byId("ask-spans-count");
    if (!askMeta) {
      return;
    }
    var reportType = spec && spec.report_type ? String(spec.report_type) : (meta && meta.report_type ? String(meta.report_type) : "");
    var start = meta && meta.start ? String(meta.start) : "";
    var end = meta && meta.end ? String(meta.end) : "";
    var range = start && end ? start + ".." + end : "";
    var totalSales = meta && meta.total_sales != null ? String(Number(meta.total_sales).toFixed(2)) : "";
    var intentMode = meta && meta.intent_mode ? String(meta.intent_mode) : "";
    var executedCount = meta && meta.executed_count != null ? String(meta.executed_count) : "";
    var spansCount = meta && meta.spans_count != null ? Number(meta.spans_count) : null;
    askMeta.textContent = "report_type=" + reportType + "  range=" + range + (totalSales ? "  total_sales=" + totalSales : "") + (executedCount ? "  executed_count=" + executedCount : "") + (intentMode ? "  intent_mode=" + intentMode : "");
    if (askSpansCount) {
      if (spansCount != null) {
        askSpansCount.classList.remove("hidden");
        askSpansCount.textContent = "Detected spans: " + String(spansCount);
      } else {
        askSpansCount.classList.add("hidden");
        askSpansCount.textContent = "";
      }
    }
  }

  function renderAskWarnings(warnings) {
    var askWarnings = byId("ask-warnings");
    if (!askWarnings) {
      return;
    }
    var list = Array.isArray(warnings) ? warnings.filter(function (w) { return !!w; }) : [];
    if (!list.length) {
      askWarnings.classList.add("hidden");
      askWarnings.textContent = "";
      return;
    }
    askWarnings.classList.remove("hidden");
    askWarnings.textContent = "Warnings:\\n- " + list.join("\\n- ");
  }

  function setAskTraceExpanded(expanded) {
    var askTrace = byId("ask-trace");
    var askTraceToggle = byId("ask-trace-toggle");
    askTraceExpanded = Boolean(expanded);
    if (askTrace) {
      askTrace.classList.toggle("hidden", !askTraceExpanded);
    }
    if (askTraceToggle) {
      askTraceToggle.textContent = askTraceExpanded ? "Hide Trace" : "Show Trace";
    }
  }

  function renderAskTrace(trace) {
    var askTrace = byId("ask-trace");
    if (!askTrace) {
      return;
    }
    if (!trace || typeof trace !== "object") {
      askTrace.textContent = "Trace not available (enable debug=1)";
      return;
    }
    askTrace.textContent = JSON.stringify(trace, null, 2);
  }

  function initAskTracePanel() {
    var askTracePanel = byId("ask-trace-panel");
    var askTraceToggle = byId("ask-trace-toggle");
    if (!askTracePanel || !askTraceToggle) {
      return;
    }
    if (!debugMode) {
      askTracePanel.classList.add("hidden");
      askTracePanel.style.display = "none";
      return;
    }
    askTracePanel.classList.remove("hidden");
    askTracePanel.style.display = "block";
    setAskTraceExpanded(false);
    renderAskTrace(null);
    askTraceToggle.addEventListener("click", function () {
      setAskTraceExpanded(!askTraceExpanded);
    });
  }

  function hideAskSaveBanner() {
    var banner = byId("ask-save-banner");
    if (!banner) {
      return;
    }
    banner.classList.add("hidden");
  }

  function showAskSaveBanner(runId, indexUrl) {
    var banner = byId("ask-save-banner");
    var runIdEl = byId("ask-save-run-id");
    var link = byId("ask-save-link");
    if (!banner || !runIdEl || !link) {
      return;
    }
    runIdEl.textContent = "Saved run: " + String(runId || "");
    link.href = indexUrl || "#";
    banner.classList.remove("hidden");
  }

  function currentAskRequest() {
    var askInput = byId("ask-input");
    var askFormat = byId("ask-format");
    var askRedact = byId("ask-redact");
    return {
      question: String((askInput && askInput.value) || "").trim(),
      format: askFormat ? String(askFormat.value || "md") : "md",
      redact_pii: Boolean(askRedact && askRedact.checked),
    };
  }

  function renderRecentAskRuns(rows) {
    var list = byId("ask-runs-list");
    var empty = byId("ask-runs-empty");
    if (!list || !empty) {
      return;
    }
    list.innerHTML = "";
    var runs = Array.isArray(rows) ? rows : [];
    if (!runs.length) {
      empty.classList.remove("hidden");
      empty.textContent = "No saved runs yet.";
      return;
    }
    empty.classList.add("hidden");
    runs.forEach(function (run, idx) {
      var row = document.createElement("div");
      row.className = "rounded border border-slate-200 dark:border-slate-700 px-3 py-2 space-y-1";

      var top = document.createElement("div");
      top.className = "flex items-center justify-between gap-2";

      var left = document.createElement("div");
      left.className = "text-[11px] text-slate-700 dark:text-slate-200 font-semibold";
      left.textContent = String((run && run.run_id) || "");
      top.appendChild(left);

      var created = document.createElement("div");
      created.className = "text-[11px] text-slate-500 dark:text-slate-400";
      created.textContent = String((run && run.created_at) || "");
      top.appendChild(created);
      row.appendChild(top);

      var snippet = document.createElement("div");
      snippet.className = "text-[11px] text-slate-600 dark:text-slate-300";
      snippet.textContent = String((run && run.question_snippet) || (run && run.question) || "");
      row.appendChild(snippet);

      var actions = document.createElement("div");
      actions.className = "flex items-center gap-2";
      var openBtn = document.createElement("button");
      openBtn.id = "run-open-" + String(idx);
      openBtn.type = "button";
      openBtn.className = "px-2.5 py-1 rounded bg-slate-200 dark:bg-slate-700 text-slate-800 dark:text-slate-100 text-[11px] font-semibold hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors";
      openBtn.textContent = "Open";
      openBtn.addEventListener("click", function () {
        var url = String((run && run.index_url) || ("/ask-run/" + String((run && run.run_id) || "") + "/index.md"));
        window.open(url, "_blank", "noopener");
      });
      actions.appendChild(openBtn);

      var compareBtn = document.createElement("button");
      compareBtn.id = "run-compare-" + String(idx);
      compareBtn.type = "button";
      compareBtn.className = "px-2.5 py-1 rounded bg-sky-700 text-white text-[11px] font-semibold hover:bg-sky-800 transition-colors";
      compareBtn.textContent = "Compare";
      compareBtn.addEventListener("click", function () {
        compareSavedRunWithCurrent(String((run && run.run_id) || "")).catch(function () {
          setAskStatus("Compare failed.");
        });
      });
      actions.appendChild(compareBtn);
      row.appendChild(actions);

      list.appendChild(row);
    });
  }

  async function refreshRecentAskRuns() {
    var payload = await fetchJson("/api/ask/runs?limit=20");
    renderRecentAskRuns(payload.runs || []);
  }

  async function saveAskRun(options) {
    var opts = options || {};
    var quiet = Boolean(opts.quiet);
    var req = currentAskRequest();
    if (!req.question) {
      setAskStatus("Question is required.");
      throw new Error("question is required");
    }
    if (!quiet) {
      setAskBusy(true);
      setAskStatus("Saving run...");
    }
    try {
      var saveUrl = debugMode ? "/api/ask/save?debug=1" : "/api/ask/save";
      var saved = await fetchJson(saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      var response = saved.response || {};
      var output = String(response.output || "");
      var contentType = String(response.content_type || (req.format === "html" ? "text/html" : "text/markdown"));
      lastAskQuestion = req.question;
      lastAskOutput = output;
      lastAskFormat = req.format;
      lastAskContentType = contentType;
      lastAskResponse = response;
      lastAskRunId = String(saved.run_id || "");
      renderAskOutput(output, req.format, contentType);
      renderAskMeta(response.spec || {}, response.meta || {});
      renderAskDelta(response.spec || {}, response.meta || {});
      renderAskWarnings((response.meta || {}).warnings || []);
      renderAskTrace(response.trace || null);
      showAskSaveBanner(lastAskRunId, ((saved.files || {}).index_url) || ("/ask-run/" + lastAskRunId + "/index.md"));
      await refreshRecentAskRuns();
      if (!quiet) {
        setAskStatus("Saved run: " + lastAskRunId);
      }
      return saved;
    } finally {
      if (!quiet) {
        setAskBusy(false);
      }
    }
  }

  async function compareSavedRunWithCurrent(runId) {
    if (!runId) {
      setAskStatus("Invalid run ID.");
      return;
    }
    var req = currentAskRequest();
    if (!req.question && !lastAskQuestion) {
      setAskStatus("Run Ask first, then compare.");
      return;
    }
    setAskBusy(true);
    setAskStatus("Saving current output for compare...");
    try {
      var currentSaved = await saveAskRun({ quiet: true });
      var runB = String((currentSaved && currentSaved.run_id) || lastAskRunId || "");
      var compareFormat = req.format === "html" ? "html" : "md";
      var url =
        "/api/ask/compare?run_a=" +
        encodeURIComponent(runId) +
        "&run_b=" +
        encodeURIComponent(runB) +
        "&format=" +
        encodeURIComponent(compareFormat);
      var compared = await fetchJson(url);
      var diff = String(compared.diff || "");
      if (!diff) {
        diff = "(no diff)";
      }
      lastAskOutput = diff;
      lastAskFormat = "md";
      lastAskContentType = "text/plain";
      renderAskOutput(diff, "md", "text/markdown");
      renderAskMeta({}, {});
      renderAskDelta({}, {});
      renderAskWarnings([]);
      renderAskTrace(null);
      setAskStatus("Compared " + String(compared.run_a || runId) + " vs " + String(compared.run_b || runB) + ".");
    } finally {
      setAskBusy(false);
    }
  }

  async function refreshDashboard() {
    var startInput = byId("start-date");
    var endInput = byId("end-date");
    if (!startInput || !endInput) {
      return;
    }
    var start = startInput.value;
    var end = endInput.value;
    var query = "start=" + encodeURIComponent(start) + "&end=" + encodeURIComponent(end);

    var occupancy = await fetchJson("/api/occupancy?" + query);
    var reservations = await fetchJson("/api/reservations?" + query + "&limit=500");

    var renderedBars = renderChart(occupancy);
    if (debugMode) {
      console.log("occupancy payload", occupancy);
      console.log("occupancy bars rendered", renderedBars);
    }
    renderReservations(reservations);

    var occupancyPct = Number(occupancy.occupancy_pct || 0);
    setText("occupancy-value", occupancyPct.toFixed(2) + "%");

    // Defined as arrivals/departures on the selected end date.
    var arrivals = reservations.filter(function (r) { return r.check_in === end; }).length;
    var departures = reservations.filter(function (r) { return r.check_out === end; }).length;
    setText("arrivals-value", arrivals);
    setText("departures-value", departures);
  }

  async function submitAsk() {
    var askInput = byId("ask-input");
    var askFormat = byId("ask-format");
    var askRedact = byId("ask-redact");
    if (!askInput) {
      return;
    }

    var question = String(askInput.value || "").trim();
    if (!question) {
      setAskStatus("Question is required.");
      return;
    }

    var format = askFormat ? String(askFormat.value || "md") : "md";
    var redactValue = Boolean(askRedact && askRedact.checked);
    lastAskQuestion = question;
    hideAskSaveBanner();
    setAskBusy(true);
    setAskStatus("Running...");
    try {
      var askUrl = debugMode ? "/api/ask?debug=1" : "/api/ask";
      var response = await fetchJson(askUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, format: format, redact_pii: redactValue }),
      });
      var output = String(response.output || "");
      var contentType = String(response.content_type || (format === "html" ? "text/html" : "text/markdown"));
      lastAskOutput = output;
      lastAskFormat = format;
      lastAskContentType = contentType;
      lastAskResponse = response;
      renderAskOutput(output, format, contentType);
      renderAskMeta(response.spec || {}, response.meta || {});
      renderAskDelta(response.spec || {}, response.meta || {});
      renderAskWarnings((response.meta || {}).warnings || []);
      renderAskTrace(response.trace || null);
      setAskStatus("Done.");
    } catch (err) {
      lastAskOutput = "";
      lastAskResponse = null;
      renderAskMeta({}, {});
      renderAskDelta({}, {});
      renderAskWarnings([]);
      renderAskTrace(null);
      renderAskOutput("Ask failed: " + err.message, "md", "text/markdown");
      setAskStatus("Error.");
      throw err;
    } finally {
      setAskBusy(false);
    }
  }

  function initDashboard() {
    var refreshBtn = byId("refresh-btn");
    var exportBtn = byId("export-btn");
    var askBtn = byId("ask-submit");
    var askSave = byId("ask-save");
    var askDownload = byId("ask-download");
    var askDownloadJson = byId("ask-download-json");
    var askRunsRefresh = byId("ask-runs-refresh");
    var askInput = byId("ask-input");
    var askOutput = byId("ask-output");
    if (!refreshBtn || !exportBtn || !byId("occupancy-chart")) {
      return;
    }

    setDefaultRange();
    refreshBtn.addEventListener("click", function () {
      refreshDashboard().catch(function (err) {
        alert("Dashboard refresh failed: " + err.message);
      });
    });

    exportBtn.addEventListener("click", function () {
      var start = byId("start-date").value;
      var end = byId("end-date").value;
      downloadExport(start, end).catch(function (err) {
        alert("Export failed: " + err.message);
      });
    });

    if (askBtn && askInput && askOutput) {
      askBtn.addEventListener("click", function () {
        submitAsk().catch(function (err) {
          setAskStatus("Ask failed.");
        });
      });
      askInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submitAsk().catch(function (err) {
            setAskStatus("Ask failed.");
          });
        }
      });
      askInput.addEventListener("input", function () {
        setAskBusy(false);
      });
    }
    if (askSave) {
      askSave.addEventListener("click", function () {
        saveAskRun({ quiet: false }).catch(function (err) {
          setAskStatus("Save run failed.");
        });
      });
    }
    if (askDownload) {
      askDownload.addEventListener("click", function () {
        downloadAskOutput();
      });
    }
    if (askDownloadJson) {
      askDownloadJson.addEventListener("click", function () {
        downloadAskJson();
      });
    }
    if (askRunsRefresh) {
      askRunsRefresh.addEventListener("click", function () {
        refreshRecentAskRuns().catch(function (err) {
          setAskStatus("Recent runs refresh failed.");
        });
      });
    }
    initAskTracePanel();
    hideAskSaveBanner();
    setAskBusy(false);
    refreshRecentAskRuns().catch(function () {
      setAskStatus("Recent runs unavailable.");
    });

    // Smoke check: Open http://127.0.0.1:8011/?debug=1 and verify bars render.
    refreshDashboard().catch(function (err) {
      alert("Dashboard load failed: " + err.message);
    });
  }

  function hideElement(el) {
    if (!el) {
      return;
    }
    el.classList.add("hidden");
    el.style.display = "none";
  }

  function showElement(el) {
    if (!el) {
      return;
    }
    el.classList.remove("hidden");
    el.style.display = "flex";
  }

  async function submitCheckin(event) {
    event.preventDefault();
    var form = byId("checkin-form");
    var success = byId("checkin-success");
    var error = byId("checkin-error");
    if (!form) {
      return;
    }

    hideElement(success);
    if (error) {
      hideElement(error);
      error.textContent = "";
    }

    var formData = new FormData(form);
    var payload = {};
    formData.forEach(function (value, key) {
      payload[key] = value;
    });

    try {
      var result = await fetchJson("/api/checkin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (success) {
        var message = success.querySelector("p");
        if (message) {
          message.textContent = "Check-in saved: " + result.reservation_id;
        } else {
          success.textContent = "Check-in saved: " + result.reservation_id;
        }
        showElement(success);
      }
      form.reset();
    } catch (err) {
      if (error) {
        error.textContent = "Check-in failed: " + err.message;
        showElement(error);
      } else {
        alert("Check-in failed: " + err.message);
      }
    }
  }

  function initCheckin() {
    var form = byId("checkin-form");
    if (!form) {
      return;
    }
    form.addEventListener("submit", submitCheckin);
  }

  var askHelpers = {
    hashText: hashText,
    slugifyText: slugifyText,
    buildAskRunShortSlug: buildAskRunShortSlug,
    buildAskRunHash8: buildAskRunHash8,
  };
  if (typeof globalThis !== "undefined") {
    globalThis.__ASK_HELPERS__ = askHelpers;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = askHelpers;
  }
  if (!hasDom) {
    return;
  }

  wireNav();
  initDashboard();
  initCheckin();
})();
