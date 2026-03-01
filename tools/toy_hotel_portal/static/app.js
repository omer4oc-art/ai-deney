(function () {
  "use strict";

  var debugMode = window.location.search.indexOf("debug=1") !== -1;
  var warnedEmptyOccupancy = false;

  function byId(id) {
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
    var askOutput = byId("ask-output");
    var askFormat = byId("ask-format");
    var askRedact = byId("ask-redact");
    if (!askInput || !askOutput) {
      return;
    }

    var question = String(askInput.value || "").trim();
    if (!question) {
      askOutput.textContent = "Question is required.";
      return;
    }

    var format = askFormat ? String(askFormat.value || "md") : "md";
    var redactValue = askRedact && askRedact.checked ? 1 : 0;
    askOutput.textContent = "Running...";
    var response = await fetchJson("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, format: format, redact_pii: redactValue }),
    });
    askOutput.textContent = String(response.report || "");
  }

  function initDashboard() {
    var refreshBtn = byId("refresh-btn");
    var exportBtn = byId("export-btn");
    var askBtn = byId("ask-submit");
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
          askOutput.textContent = "Ask failed: " + err.message;
        });
      });
      askInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          submitAsk().catch(function (err) {
            askOutput.textContent = "Ask failed: " + err.message;
          });
        }
      });
    }

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

  wireNav();
  initDashboard();
  initCheckin();
})();
