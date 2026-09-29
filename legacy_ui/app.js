/* GridPulse frontend: one script drives both the driver app and the operator dashboard. */
(() => {
  "use strict";

  // ---------- helpers ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

  async function api(path, { method = "GET", body } = {}) {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON body */ }
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      if (data && typeof data.detail === "string") msg = data.detail;
      else if (data && Array.isArray(data.detail))
        msg = data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
      throw new Error(msg);
    }
    return data;
  }

  const fmtTime = (iso) =>
    iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "–";
  const fmtMin = (m) => {
    if (m === null || m === undefined) return "–";
    const r = Math.round(m);
    return r < 60 ? `${r} min` : `${Math.floor(r / 60)} h ${String(r % 60).padStart(2, "0")} min`;
  };
  const badge = (cls, text) => `<span class="badge ${esc(cls)}">${esc(text ?? cls)}</span>`;

  // =====================================================================================
  // DRIVER APP
  // =====================================================================================
  function initDriver() {
    const state = {
      lat: null, lon: null, accuracy: null, source: null, watchId: null, request: null, rec: null, pollTimer: null,
      lastSent: null, sending: false, updatesSent: 0, autoTimer: null, reserved: false,
    };
    const SEND_MIN_MOVE_M = 20;     // push a new position when the driver moved this far...
    const SEND_HEARTBEAT_MS = 15000; // ...or at least this often while the view is active

    if (!window.isSecureContext) $("#secureBanner").classList.remove("hidden");

    api("/health").then((h) => {
      if (h.center) {
        $("#manLat").value = h.center.lat;
        $("#manLon").value = h.center.lon;
      }
    }).catch(() => {});

    function setLocation(lat, lon, accuracy, source) {
      state.lat = lat; state.lon = lon; state.accuracy = accuracy; state.source = source;
      $("#locReadout").classList.remove("hidden");
      $("#latOut").textContent = lat.toFixed(6);
      $("#lonOut").textContent = lon.toFixed(6);
      $("#accOut").textContent = accuracy != null ? `±${Math.round(accuracy)} m` : "n/a";
      $("#srcOut").textContent = source === "gps" ? "Live GPS" : "Manual entry";
      $("#locStatus").textContent = source === "gps" ? "Live location active" : "Using manual location";
      maybeSendLocation(false);
    }

    // ---------- live location -> backend ----------
    function distMeters(aLat, aLon, bLat, bLon) {
      const R = 6371008.8, rad = Math.PI / 180;
      const dLat = (bLat - aLat) * rad, dLon = (bLon - aLon) * rad;
      const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLon / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(h));
    }

    function setLive(text, kind) {
      const box = $("#liveBox");
      box.classList.remove("hidden", "ok", "warn", "err");
      if (kind) box.classList.add(kind);
      $("#liveLine").textContent = text;
    }

    function renderLiveEtas(etas, fallback) {
      const line = etas.map((e) => `${esc(e.station_code)}: ${fmtMin(e.travel_min)} (${e.distance_km.toFixed(1)} km)`).join("  ·  ");
      $("#liveEtas").textContent = "";
      $("#liveEtas").insertAdjacentHTML("beforeend",
        `Route ETA now: ${line}${fallback ? ' <span class="badge warn">estimated</span>' : ""}`);
    }

    async function maybeSendLocation(force) {
      if (!state.request || state.lat === null || state.sending) return;
      if (document.hidden && !force) return;
      const now = Date.now();
      const last = state.lastSent;
      const moved = last ? distMeters(last.lat, last.lon, state.lat, state.lon) : Infinity;
      if (!force && last && moved < SEND_MIN_MOVE_M && now - last.ts < SEND_HEARTBEAT_MS) return;
      state.sending = true;
      try {
        const out = await api("/driver/location/update", {
          method: "POST",
          body: { request_id: state.request.id, lat: state.lat, lon: state.lon,
                  accuracy_m: state.accuracy, source: state.source },
        });
        state.lastSent = { lat: state.lat, lon: state.lon, ts: Date.now() };
        state.updatesSent += 1;
        const how = state.source === "gps" ? "GPS" : "manual position";
        setLive(`sent ${how} to operator (update #${state.updatesSent}, ${new Date().toLocaleTimeString()})`, "ok");
        renderLiveEtas(out.etas, out.routing_fallback_used);
      } catch (e) {
        setLive(`could not reach the server (${e.message}); will retry`, "warn");
      } finally {
        state.sending = false;
      }
    }

    document.addEventListener("visibilitychange", () => {
      if (!state.request) return;
      if (document.hidden) setLive("paused while this tab is in the background", "warn");
      else maybeSendLocation(true);
    });
    setInterval(() => maybeSendLocation(false), 5000); // heartbeat check; sends only if moved or 15 s elapsed

    function geoError(err) {
      const msgs = {
        1: "Location permission denied. Allow it in your browser settings, or enter coordinates manually.",
        2: "Location unavailable right now. Enter coordinates manually.",
        3: "Location request timed out. Try again or enter coordinates manually.",
      };
      $("#locStatus").textContent = msgs[err.code] || `Location error: ${err.message}`;
      $("#manualBox").open = true;
      $("#btnLocate").disabled = false;
    }

    $("#btnLocate").addEventListener("click", () => {
      if (!("geolocation" in navigator)) {
        $("#locStatus").textContent = "This browser has no geolocation support. Enter coordinates manually.";
        $("#manualBox").open = true;
        return;
      }
      if (!window.isSecureContext) {
        $("#locStatus").textContent = "Geolocation is blocked on insecure (non-HTTPS, non-localhost) pages. Enter coordinates manually.";
        $("#manualBox").open = true;
        return;
      }
      if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
      $("#locStatus").innerHTML = '<span class="spinner"></span> Waiting for location…';
      $("#btnLocate").disabled = true;
      state.watchId = navigator.geolocation.watchPosition(
        (pos) => {
          $("#btnLocate").disabled = false;
          $("#btnLocate").textContent = "Refresh location";
          setLocation(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, "gps");
        },
        geoError,
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 }
      );
    });

    $("#btnManual").addEventListener("click", () => {
      const lat = parseFloat($("#manLat").value), lon = parseFloat($("#manLon").value);
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
        $("#locStatus").textContent = "Enter a valid latitude (-90..90) and longitude (-180..180).";
        return;
      }
      if (state.watchId !== null) { navigator.geolocation.clearWatch(state.watchId); state.watchId = null; }
      setLocation(lat, lon, null, "manual");
      maybeSendLocation(true);
    });

    document.querySelectorAll("[data-deadline]").forEach((b) =>
      b.addEventListener("click", () => { $("#deadline").value = b.dataset.deadline; })
    );

    function showFormError(msg) {
      const el = $("#formError");
      el.textContent = msg;
      el.classList.toggle("hidden", !msg);
    }

    $("#needForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      showFormError("");
      if (state.lat === null) { showFormError("Share your location or enter it manually first (step 1)."); return; }
      const socNow = parseFloat($("#socNow").value), socTarget = parseFloat($("#socTarget").value);
      const deadline = parseFloat($("#deadline").value);
      if (![socNow, socTarget, deadline].every(Number.isFinite)) { showFormError("Fill in battery levels and deadline."); return; }
      if (socTarget <= socNow) { showFormError("Target battery must be higher than current battery."); return; }

      const btn = $("#btnSubmit");
      btn.disabled = true; btn.textContent = "Comparing stations…";
      stopPolling();
      $("#reservationBox").classList.add("hidden");
      try {
        const req = await api("/drivers/request", {
          method: "POST",
          body: {
            driver_name: $("#name").value.trim() || "Driver",
            lat: state.lat, lon: state.lon,
            location_source: state.source, location_accuracy_m: state.accuracy,
            soc_current: socNow, soc_target: socTarget, deadline_minutes: deadline,
            battery_kwh: parseFloat($("#battery").value) || 40,
            max_charge_kw: parseFloat($("#maxKw").value) || 50,
          },
        });
        const rec = await api("/recommendation", { method: "POST", body: { request_id: req.id } });
        state.request = req; state.rec = rec; state.reserved = false; state.lastSent = null; state.updatesSent = 0;
        renderResult(rec);
        maybeSendLocation(true);
        upgradeExplanation(req.id);
      } catch (e) {
        showFormError(e.message);
      } finally {
        btn.disabled = false; btn.textContent = "Find best charger";
      }
    });

    async function upgradeExplanation(requestId) {
      try {
        const out = await api("/explanation", { method: "POST", body: { request_id: requestId } });
        if (!state.request || state.request.id !== requestId) return;
        const t = $("#reasonText"), s = $("#reasonSrc");
        if (!t || !s) return;
        t.textContent = out.text;
        s.textContent = out.source === "llm"
          ? `Phrased by AI (${out.model}). Numbers come from the deterministic engine.`
          : "Rule-based explanation from the deterministic engine.";
      } catch (_) { /* keep the rule-based text already shown */ }
    }

    function renderResult(rec, { scroll = true } = {}) {
      const box = $("#result");
      box.classList.remove("hidden");
      const drv = rec.driver;
      const warnings = (rec.warnings || []).map((w) => `<div class="notice warn">${esc(w)}</div>`).join("");

      if (!rec.chosen) {
        box.innerHTML = `<div class="card">
          <h2>No usable station</h2>${warnings}
          <p>${esc(rec.explanation.text)}</p>${candidatesTable(rec, false)}</div>`;
        return;
      }
      const c = rec.chosen;
      const cmp = rec.comparison_with_nearest;
      const vsNearest = cmp && cmp.minutes_saved != null
        ? `<div class="small muted" style="margin-bottom:8px">Not the nearest — saves ${fmtMin(cmp.minutes_saved)} vs ${esc(cmp.nearest_station_name)}.</div>` : "";
      box.innerHTML = `
        <div class="card hero">
          <div class="row" style="justify-content:space-between">
            <div><div class="muted small">Recommended station</div><h2 style="margin:0">${esc(c.name)}</h2></div>
            <div>${badge(drv.priority_class)} ${badge(c.kind)}</div>
          </div>
          ${vsNearest}
          <div class="metrics">
            <div class="metric"><div class="v">${c.distance_km.toFixed(1)} km</div><div class="k">Route distance · ${routeLabel(c)}</div></div>
            <div class="metric"><div class="v">${fmtMin(c.travel_min)}</div><div class="k">Route travel time</div></div>
            <div class="metric"><div class="v">${fmtMin(c.wait_min)}</div><div class="k">Predicted wait${c.queue_ahead ? ` (${c.queue_ahead} ahead)` : ""}</div></div>
            <div class="metric"><div class="v">${fmtMin(c.charge_min)}</div><div class="k">Charge duration @ ${c.charge_kw.toFixed(0)} kW</div></div>
            <div class="metric"><div class="v">${fmtTime(c.completion_at)}</div><div class="k">Ready at (total ${fmtMin(c.total_min)})</div></div>
            <div class="metric"><div class="v">${c.deadline_ok ? badge("ok", "On time") : badge("warn", "Late " + fmtMin(c.deadline_miss_min))}</div><div class="k">Deadline ${fmtMin(drv.deadline_minutes)}</div></div>
          </div>
          ${warnings}
          <div class="reason">
            <div id="reasonText">${esc(rec.explanation.text)}</div>
            <div id="reasonSrc" class="src">Rule-based explanation from the deterministic engine. <span class="spinner"></span> asking AI to rephrase…</div>
          </div>
          <div class="row" style="margin-top:14px">
            <button id="btnReserve" class="primary" style="flex:1" type="button">Reserve at ${esc(c.name)}</button>
            <button id="btnRefreshRec" type="button">Refresh recommendation</button>
          </div>
          <label class="row small" style="margin:10px 0 0;font-weight:500">
            <input id="autoRec" type="checkbox" ${state.autoTimer ? "checked" : ""}> Auto-refresh every 30 s while I drive
          </label>
          <div id="refreshInfo" class="small muted" style="margin-top:4px"></div>
          <div id="reserveError" class="notice err hidden" style="margin-top:10px" role="alert"></div>
        </div>
        <div class="card"><h2>All stations compared</h2>${candidatesTable(rec, true)}
          <p class="small muted" style="margin-bottom:0">final score = travel time + predicted wait + charging time + load penalty − urgency bonus. Lower is better. Each station's own breakdown is shown under its name.</p></div>`;
      $("#btnReserve").addEventListener("click", () => reserve(c.station_id));
      $("#btnRefreshRec").addEventListener("click", () => refreshRecommendation(true));
      $("#autoRec").addEventListener("change", (ev) => setAutoRefresh(ev.target.checked));
      box.querySelectorAll("[data-reserve]").forEach((b) =>
        b.addEventListener("click", () => reserve(parseInt(b.dataset.reserve, 10)))
      );
      if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function breakdownText(b) {
      if (!b) return "";
      return `${b.travel_time} travel + ${b.predicted_wait} wait + ${b.charging_time} charge + ${b.load_penalty} load − ${b.urgency_bonus} urgency = <b>${b.final_score}</b>`;
    }

    function routeLabel(c) {
      if (c.route_fallback) return '<span class="badge warn">estimated (routing down)</span>';
      if (c.route_estimated) return '<span class="badge warn">estimated</span>';
      return "road route";
    }

    // ---------- refresh the recommendation with the latest live position ----------
    async function refreshRecommendation(manual) {
      if (!state.request || state.reserved) return;
      const btn = $("#btnRefreshRec");
      if (btn) { btn.disabled = true; btn.textContent = "Refreshing…"; }
      try {
        await maybeSendLocation(true); // make sure the backend has our newest position first
        const rec = await api("/recommendation", { method: "POST", body: { request_id: state.request.id } });
        const prev = state.rec && state.rec.chosen ? state.rec.chosen.station_name || state.rec.chosen.name : null;
        state.rec = rec;
        renderResult(rec, { scroll: false });
        const info = $("#refreshInfo");
        if (info) {
          const changed = prev && rec.chosen && prev !== rec.chosen.name ? ` Recommendation changed from ${esc(prev)}.` : "";
          info.innerHTML = `Updated ${new Date().toLocaleTimeString()} from your current position.${changed}`;
        }
        upgradeExplanation(state.request.id);
      } catch (e) {
        const info = $("#refreshInfo");
        if (info) info.textContent = `Refresh failed: ${e.message}`;
        if (btn) { btn.disabled = false; btn.textContent = "Refresh recommendation"; }
      }
    }

    function setAutoRefresh(on) {
      if (state.autoTimer) { clearInterval(state.autoTimer); state.autoTimer = null; }
      if (on) state.autoTimer = setInterval(() => { if (!document.hidden) refreshRecommendation(false); }, 30000);
    }

    function candidatesTable(rec, withButtons) {
      const bestId = rec.chosen ? rec.chosen.station_id : null;
      const rows = rec.candidates.map((c) => {
        if (!c.feasible) {
          return `<tr><td>${esc(c.name)}</td><td colspan="5" class="muted">Not usable: ${esc(c.rejection_reason)}</td><td></td></tr>`;
        }
        const btn = withButtons && c.station_id !== bestId
          ? `<button class="small" data-reserve="${c.station_id}" type="button">Reserve here</button>` : (c.station_id === bestId ? badge("ok", "Best") : "");
        return `<tr class="${c.station_id === bestId ? "best" : ""}">
          <td>${esc(c.name)}<div class="muted small">${breakdownText(c.score_breakdown)}</div></td><td class="num">${fmtMin(c.travel_min)}<div class="muted small">${c.distance_km.toFixed(1)} km${c.route_estimated ? " est." : ""}</div></td><td class="num">${fmtMin(c.wait_min)}</td>
          <td class="num">${fmtMin(c.charge_min)}</td><td class="num"><b>${fmtMin(c.total_min)}</b></td>
          <td class="num">${c.score.toFixed(0)}</td><td>${btn}</td></tr>`;
      }).join("");
      return `<div class="tablewrap"><table><thead><tr><th>Station</th><th class="num">Travel</th><th class="num">Wait</th>
        <th class="num">Charge</th><th class="num">Total</th><th class="num">Score</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
    }

    async function reserve(stationId) {
      if (!state.request) return;
      const btn = $("#btnReserve");
      const err = $("#reserveError");
      err.classList.add("hidden");
      if (btn) { btn.disabled = true; btn.textContent = "Reserving…"; }
      try {
        const res = await api("/reservations", { method: "POST", body: { request_id: state.request.id, station_id: stationId } });
        state.reserved = true;
        setAutoRefresh(false);
        renderReservation(res);
        startPolling(res.id);
      } catch (e) {
        err.textContent = e.message;
        err.classList.remove("hidden");
        if (btn) { btn.disabled = false; btn.textContent = "Try reserving again"; }
      }
    }

    function renderReservation(r) {
      const box = $("#reservationBox");
      box.classList.remove("hidden");
      const st = {
        queued: r.queue_position ? `In queue — position ${r.queue_position}` : "Booked",
        active: "Charging now",
        done: "Charging complete",
        cancelled: "Cancelled",
      }[r.status] || r.status;
      const cls = r.status === "cancelled" ? "warn" : "ok";
      const cancel = r.status === "queued" || r.status === "active"
        ? `<button id="btnCancel" class="danger small" type="button">Cancel reservation</button>` : "";
      box.innerHTML = `<div class="card">
        <div class="row" style="justify-content:space-between"><h2 style="margin:0">Reservation #${r.id}</h2>${badge(cls, st)}</div>
        <div class="metrics">
          <div class="metric"><div class="v">${esc(r.station_code)}</div><div class="k">${esc(r.station_name)}</div></div>
          <div class="metric"><div class="v">${fmtTime(r.arrival_at)}</div><div class="k">You arrive</div></div>
          <div class="metric"><div class="v">${fmtTime(r.planned_start_at)}</div><div class="k">Charging starts</div></div>
          <div class="metric"><div class="v">${fmtTime(r.planned_end_at)}</div><div class="k">Charging ends</div></div>
          <div class="metric"><div class="v">${r.allocated_kw.toFixed(0)} kW</div><div class="k">Allocated power</div></div>
          <div class="metric"><div class="v">${badge(r.priority_class)}</div><div class="k">Priority</div></div>
        </div>
        <div class="small muted">Status updates automatically. The operator dashboard already shows this booking.</div>
        <div style="margin-top:10px">${cancel}</div></div>`;
      const c = $("#btnCancel");
      if (c) c.addEventListener("click", async () => {
        try { renderReservation(await api(`/reservations/${r.id}/cancel`, { method: "POST" })); stopPolling(); }
        catch (e) { alert(e.message); }
      });
    }

    function stopPolling() { if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; } }
    function startPolling(id) {
      stopPolling();
      state.pollTimer = setInterval(async () => {
        try {
          const r = await api(`/reservations/${id}`);
          renderReservation(r);
          if (r.status === "done" || r.status === "cancelled") stopPolling();
        } catch (_) { /* transient */ }
      }, 5000);
    }
  }

  // =====================================================================================
  // OPERATOR DASHBOARD
  // =====================================================================================
  function initDashboard() {
    let timer = null;
    let busy = false;

    const showError = (msg) => {
      const el = $("#dashError");
      el.textContent = msg || "";
      el.classList.toggle("hidden", !msg);
    };

    function renderTiles(s) {
      const t = s.totals;
      const tile = (v, k) => `<div class="tile"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`;
      $("#tiles").innerHTML =
        tile(`${t.stations_online}/${t.stations}`, "Stations online") +
        tile(t.active_sessions, "Active sessions") +
        tile(t.queued, "Drivers queued") +
        tile(`${t.ev_load_kw} kW`, "EV charging load") +
        tile({ real: "REAL LIVE", simulated: "SIMULATED", software: "SOFTWARE" }[s.hardware_summary.mode],
          s.hardware_summary.stale + s.hardware_summary.offline + s.hardware_summary.placeholder > 0 && s.hardware_summary.mode === "software"
            ? "Hardware mode (device stale/absent)" : "Hardware mode");
    }

    const CMD_STYLE = {
      NORMAL: ["ok", ""], REDUCE_LOAD: ["warn", "warn"], PRIORITIZE_URGENT: ["urgent", "urgent"], PAUSE_FLEX: ["offline", "pause"],
    };
    // How is this station's command being confirmed? Distinguishes real hardware, a simulator, and stale hardware.
    function confState(c) {
      if (!c) return ["flexible", "UNKNOWN"];
      if (c.confirmation === "hardware-confirmed") return ["ok", "HARDWARE CONFIRMED" + (c.dry_run ? " · DRY-RUN" : "")];
      if (c.confirmation === "hardware-pending") return ["warn", "HARDWARE PENDING"];
      if (c.device_mode === "real" && c.telemetry_age_s == null) return ["flexible", "AWAITING HARDWARE → SIMULATED"];
      if (c.device_mode === "real") return ["offline", c.freshness === "stale" ? "HARDWARE STALE → SIMULATED" : "HARDWARE OFFLINE → SIMULATED"];
      if (c.device_mode === "simulated" && c.freshness === "live") return ["normal", "SIMULATED DEVICE"];
      if (c.device_mode === "simulated") return ["flexible", `SIMULATED DEVICE (${c.freshness})`];
      return ["flexible", "SOFTWARE-SIMULATED"];
    }

    const ACK_STYLE = {
      applied: ["ok", "ACKED"], pending: ["warn", "PENDING"], rejected: ["offline", "REJECTED"],
      local_override: ["warn", "LOCAL OVERRIDE"], failsafe: ["offline", "FAILSAFE"], none: ["flexible", "NO ACK YET"],
    };
    const ackBadge = (status) => { const [c, t] = ACK_STYLE[status] || ["flexible", String(status).toUpperCase()]; return badge(c, t); };
    const freshBadge = (f, age) =>
      f === "live" ? badge("ok", "LIVE") : f === "stale" ? badge("warn", "STALE" + (age != null ? " " + Math.round(age) + " s" : ""))
        : badge("offline", "OFFLINE" + (age != null ? " " + Math.round(age) + " s" : ""));
    const modeBadge = (m) => (m === "real" ? badge("physical", "REAL") : m === "simulated" ? badge("normal", "SIMULATED") : badge("flexible", "NONE"));

    function controlBlock(st) {
      const c = st.control;
      if (!c) return "";
      const d = st.device;
      const [badgeCls, boxCls] = CMD_STYLE[c.command] || ["normal", ""];
      const [confCls, confText] = confState(c);
      const simBox = c.source === "simulated" && !boxCls ? "sim" : boxCls;
      const sent = d && d.last_command_sent
        ? `${esc(d.last_command_sent.command)} #${d.last_command_sent.seq} at ${fmtTime(d.last_command_sent.at)}` : "not delivered to a device yet";
      const ack = d && d.last_ack ? ` · last ack: ${esc(d.last_ack.status)} #${d.last_ack.seq} at ${fmtTime(d.last_ack.at)}` : "";
      return `<div class="ctl ${simBox}">
        <div class="row" style="justify-content:space-between">
          <span><b>Control command</b> ${badge(badgeCls, c.command)}</span>${badge(confCls, confText)}
        </div>
        <div class="small" style="margin-top:4px">${esc(c.reason)}</div>
        <div class="small muted" style="margin-top:2px">Output ${c.duty_pct}% · command #${c.seq} generated ${fmtTime(c.command_generated_at)}${
          c.hardware_mode ? ` · device reports ${esc(c.hardware_mode)}` : ""}</div>
        <div class="small muted" style="margin-top:2px">Latest sent: ${sent}${ack}${d ? "" : ""}</div>
        <div class="small" style="margin-top:2px">Acknowledgment: ${ackBadge(c.ack_status)}</div>
        ${c.fallback_reason ? `<div class="small fallback"><b>Fallback:</b> ${esc(c.fallback_reason)}</div>` : ""}
      </div>`;
    }

    function deviceBlock(st) {
      const d = st.device;
      if (!d) return `<div class="small muted" style="margin-top:10px">Software-only station — no device assigned; control is simulated by the backend.</div>`;
      const kv = (k, v) => `<div class="k">${k}</div><div>${v}</div>`;
      return `<div style="margin-top:10px"><b class="small">Device</b> ${modeBadge(d.device_mode)} ${freshBadge(d.freshness, d.telemetry_age_s)}
          ${d.placeholder ? badge("flexible", "NOT REGISTERED · placeholder") : ""}
          ${d.dry_run ? badge("warn", "DRY-RUN") : ""}
          ${d.sensor_status && d.sensor_status !== "ok" && d.sensor_status !== "unknown" ? badge(d.sensor_status === "simulated" ? "normal" : "offline", "SENSOR " + d.sensor_status.toUpperCase()) : ""}
          ${d.local_override ? badge("urgent", "LOCAL OVERRIDE") : ""}</div>
        <div class="kv">
          ${kv("Device", `<span class="coords">${esc(d.device_id)}</span>${d.firmware_version ? " · " + esc(d.firmware_version) : ""}`)}
          ${kv("Last telemetry", d.last_telemetry_at ? `${fmtTime(d.last_telemetry_at)} (${Math.round(d.telemetry_age_s)} s ago) · source ${esc(d.telemetry_source || "?")}` : "never")}
          ${kv("Last seen", d.last_seen_at ? fmtTime(d.last_seen_at) : "never")}
          ${kv("Button", `${d.button_count} press(es)${d.last_button_at ? ", last " + fmtTime(d.last_button_at) : ""}`)}
        </div>
        ${d.caveats.length ? `<ul class="caveats">${d.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}`;
    }

    function telemetryBlock(st) {
      const t = st.telemetry, d = st.device;
      if (!t) {
        if (!st.device_id) return "";  // software-only station: the control/device blocks already say so
        return `<div class="small muted" style="margin-top:10px">No telemetry from <span class="coords">${esc(st.device_id)}</span> yet — hardware not connected; control is simulated.</div>`;
      }
      const placeholder = t.sensor_status === "missing" || t.sensor_status === "error";
      const cell = (v, k, ph) => `<div class="cell ${ph ? "ph" : ""}"><div class="v">${v}</div><div class="k">${k}${ph ? " · placeholder" : ""}</div></div>`;
      const fresh = d ? freshBadge(d.freshness, d.telemetry_age_s) : (t.is_stale ? badge("warn", "STALE") : badge("ok", "LIVE"));
      const src = t.source === "simulated" ? badge("normal", "SIMULATED PACKETS") : badge("physical", "REAL PACKETS");
      return `<div style="margin-top:10px"><b class="small">Telemetry</b> ${fresh} ${src}
        <span class="muted small">${t.note ? esc(t.note) : ""}</span></div>
        <div class="tel">${cell(placeholder ? "–" : t.voltage.toFixed(2) + " V", "Voltage", placeholder)}${
          cell(placeholder ? "–" : t.current.toFixed(3) + " A", "Current", placeholder)}${
          cell(placeholder ? "–" : t.power.toFixed(2) + " W", "Power", placeholder)}${
          cell(t.temperature == null ? "–" : t.temperature.toFixed(1) + " °C", "Temperature", false)}</div>
        <div class="small muted" style="margin-top:4px">Mode reported: ${esc(t.mode || "–")} · packet ${Math.round(t.age_s)} s ago${
          d && d.freshness !== "live" ? " · values are the LAST known, not current" : ""}</div>`;
    }

    function stationCard(st) {
      const cls = st.over_limit ? "over" : st.utilization_pct >= 80 ? "hot" : "";
      const active = st.active.length
        ? st.active.map((a) => `<li><span>${badge(a.priority_class)} ${esc(a.driver_name)} <span class="muted">port ${(a.port_index ?? 0) + 1}</span></span>
            <span>${a.kw.toFixed(0)} kW · ${fmtMin(a.remaining_min)} left</span></li>`).join("")
        : `<li class="muted">No active sessions</li>`;
      const queue = st.queue.length
        ? st.queue.map((q) => `<li><span>#${q.position} ${badge(q.priority_class)} ${esc(q.driver_name)}</span>
            <span>starts ${fmtTime(q.planned_start_at)} (${fmtMin(q.starts_in_min)})</span></li>`).join("")
        : `<li class="muted">Queue is empty</li>`;
      return `<article class="card ${st.is_chosen_for_latest ? "chosen" : ""}" data-station="${st.id}">
        <div class="row" style="justify-content:space-between">
          <h2 style="margin:0"><span class="dot ${st.is_online ? "" : "off"}"></span>${esc(st.name)}</h2>
          <div>${st.is_chosen_for_latest ? badge("ok", "CHOSEN FOR LATEST REQUEST") : ""} ${badge(st.kind)} ${st.is_online ? "" : badge("offline", "OFFLINE")}</div>
        </div>
        <div class="muted small">${st.ports} port(s) × ${st.max_kw_per_port} kW · ${st.lat.toFixed(4)}, ${st.lng.toFixed(4)}</div>
        <div class="small" style="margin-top:6px">Ports free <b>${st.available_ports}/${st.ports}</b> · Queue <b>${st.queue_count}</b> ·
          Load <b>${(st.current_load_w / 1000).toFixed(1)}</b> of <b>${(st.site_power_limit_w / 1000).toFixed(1)} kW</b> limit (${st.utilization_pct}%)</div>

        <div style="margin-top:12px"><b>Site load</b> <span class="coords">${st.current_load_kw} / ${st.site_limit_kw} kW</span>
          ${st.over_limit ? badge("offline", "OVER LIMIT") : ""}</div>
        <div class="bar" role="img" aria-label="Site load ${st.utilization_pct}% of limit"><i class="${cls}" style="width:${st.utilization_pct}%"></i></div>
        <div class="legend"><span>Base ${st.base_load_kw} kW + EV ${st.ev_load_kw} kW</span><span>Headroom ${st.headroom_kw} kW</span></div>

        ${controlBlock(st)}
        ${deviceBlock(st)}
        ${telemetryBlock(st)}

        <h3 style="margin-top:14px">Charging now (${st.ports_busy}/${st.ports} ports)</h3><ul class="plain">${active}</ul>
        <h3 style="margin-top:14px">Queue (${st.queue_length})</h3><ul class="plain">${queue}</ul>

        <div class="controls">
          <div class="small muted" style="margin-bottom:6px">Grid controls (re-plans the queue immediately)</div>
          <div class="row">
            <label class="small" style="margin:0">Site limit kW <input type="number" min="1" step="1" data-f="site_limit_kw" value="${st.site_limit_kw}"></label>
            <label class="small" style="margin:0">Base load kW <input type="number" min="0" step="1" data-f="base_load_kw" value="${st.base_load_kw}"></label>
            <button class="small" type="button" data-act="apply">Apply</button>
            <button class="small ${st.is_online ? "danger" : ""}" type="button" data-act="toggle">${st.is_online ? "Take offline" : "Bring online"}</button>
          </div>
        </div>
      </article>`;
    }

    function renderStations(s) {
      // Don't clobber a control the operator is typing into.
      const active = document.activeElement;
      if (active && active.closest && active.closest("#stations") && active.tagName === "INPUT") return;
      $("#stations").innerHTML = s.stations.map(stationCard).join("");
    }

    function renderRequests(s) {
      const rows = s.recent_requests.map((r) => `<tr>
        <td>${fmtTime(r.created_at)}</td>
        <td>${esc(r.driver_name)}<div class="muted small">${r.location_source === "gps" ? "GPS" : "manual"} ${r.lat.toFixed(3)}, ${r.lon.toFixed(3)}</div></td>
        <td class="num">${r.soc_current}% → ${r.soc_target}%</td>
        <td class="num">${fmtMin(r.deadline_minutes)}</td>
        <td>${badge(r.priority_class)} <span class="muted small">${r.urgency.toFixed(2)}</span></td>
        <td>${r.recommended_station ? `<b>${esc(r.recommended_station)}</b>${r.was_nearest ? "" : ` <span class="badge ok">not nearest</span>`}
             <div class="muted small">wait ${fmtMin(r.wait_min)} · total ${fmtMin(r.total_min)} · ${r.charge_kw} kW</div>` : '<span class="muted">none / pending</span>'}</td>
        <td>${r.reserved ? `#${r.reserved}` : "–"}</td>
        <td class="small">${esc(r.explanation || "")}</td></tr>`).join("");
      $("#requestsTable").innerHTML = `<thead><tr><th>Time</th><th>Driver</th><th class="num">SOC</th><th class="num">Deadline</th>
        <th>Urgency</th><th>Recommendation</th><th>Res.</th><th>Why</th></tr></thead><tbody>${rows || '<tr><td colspan="8" class="muted">No driver requests yet — submit one from the driver app.</td></tr>'}</tbody>`;
    }

    function resRow(r) {
      return `<tr><td>#${r.id}</td><td>${esc(r.driver_name)}</td><td>${esc(r.station_code)}</td><td>${badge(r.priority_class)}</td>
        <td>${badge(r.status === "active" ? "ok" : r.status === "queued" ? "normal" : "flexible", r.status + (r.queue_position ? ` #${r.queue_position}` : ""))}</td>
        <td class="num">${fmtTime(r.arrival_at)}</td><td class="num">${fmtTime(r.planned_start_at)}</td><td class="num">${fmtTime(r.planned_end_at)}</td>
        <td class="num">${r.allocated_kw.toFixed(0)} kW</td></tr>`;
    }
    const resHead = `<thead><tr><th>ID</th><th>Driver</th><th>Stn</th><th>Priority</th><th>Status</th><th class="num">Arrives</th><th class="num">Starts</th><th class="num">Ends</th><th class="num">Power</th></tr></thead>`;

    function renderReservations(s) {
      $("#reservationsTable").innerHTML = resHead + `<tbody>${s.reservations.map(resRow).join("") || '<tr><td colspan="9" class="muted">No open reservations.</td></tr>'}</tbody>`;
      $("#finishedTable").innerHTML = resHead + `<tbody>${s.recent_finished.map(resRow).join("") || '<tr><td colspan="9" class="muted">Nothing finished yet.</td></tr>'}</tbody>`;
    }

    function renderSystem(s) {
      const y = s.system, r = y.routing;
      const routingText = r.mode !== "osrm" ? "straight-line estimates (haversine mode)"
        : r.osrm_available ? `OSRM road routing (${r.osrm_ok} ok, ${r.fallbacks} fallback)`
        : `OSRM unavailable → estimates for ${r.cooldown_s} s${r.last_error ? " (" + r.last_error + ")" : ""}`;
      $("#sysLine").textContent =
        `Updated ${fmtTime(s.now)} · hardware: ${{ real: "REAL device live", simulated: "SIMULATED device live", software: "software-simulated (no live device)" }[s.hardware_summary.mode]} · routing: ${routingText} · explanations: ` +
        (y.openrouter_configured ? `OpenRouter (${y.openrouter_model})` : "rule-based (no OPENROUTER_API_KEY)") +
        (y.last_explanation_source ? ` · last used: ${y.last_explanation_source}` : "");
    }

    const HORIZON_FALLBACK = 120;

    function renderLatestRec(s) {
      const lr = s.latest_recommendation;
      if (!lr) {
        $("#lrWho").textContent = "";
        $("#latestRec").innerHTML = '<div class="muted small">No recommendation yet — submit a request from the driver app (or POST /recommend).</div>';
        return;
      }
      const d = lr.driver;
      $("#lrWho").textContent = `· ${d.name} · request #${lr.request_id} · ${fmtTime(lr.generated_at)}`;
      const ch = lr.chosen_station;
      const stateBy = new Map(s.stations.map((x) => [x.id, x]));
      const rows = lr.ranking.map((r) => {
        const st = stateBy.get(r.station_id);
        const b = r.score_breakdown;
        const load = st ? `<span class="util"><i class="${st.over_limit ? "over" : st.utilization_pct >= 80 ? "hot" : ""}" style="width:${st.utilization_pct}%"></i></span>${(st.current_load_w / 1000).toFixed(1)}/${(st.site_power_limit_w / 1000).toFixed(0)} kW` : "–";
        if (!r.feasible) {
          return `<tr><td>${r.rank}</td><td><b>${esc(r.name)}</b></td><td colspan="8" class="muted">Not usable: ${esc(r.rejection_reason)}</td></tr>`;
        }
        return `<tr class="${ch && ch.id === r.station_id ? "best" : ""}">
          <td>${r.rank}</td><td><b>${esc(r.name)}</b>${ch && ch.id === r.station_id ? " " + badge("ok", "CHOSEN") : ""}</td>
          <td class="num">${st ? st.available_ports + "/" + st.ports : "–"}</td><td class="num">${st ? st.queue_count : "–"}</td><td>${load}</td>
          <td class="num">${b.travel_time}</td><td class="num">${b.predicted_wait}</td><td class="num">${b.charging_time}</td>
          <td class="num pos">+${b.load_penalty}</td><td class="num neg">−${b.urgency_bonus}</td><td class="num"><b>${b.final_score}</b></td></tr>`;
      }).join("");
      const ex = lr.explanation;
      const src = ex.source === "llm" ? `Reworded by OpenRouter (${esc(ex.model || "")}) — the ranking above is computed by the deterministic engine.`
        : "Rule-based explanation from the deterministic engine (OpenRouter is optional and only rewrites this text).";
      $("#latestRec").innerHTML = `
        <div class="lr-head">
          <div><div class="muted small">Chosen station</div>
            <div class="lr-choice">${ch ? esc(ch.name) : "No usable station"}</div></div>
          <div class="small">Driver: <b>${d.soc_current}% → ${d.soc_target}%</b> · deadline <b>${fmtMin(d.deadline_minutes)}</b> ·
            ${badge(d.priority_class)} urgency ${d.urgency.toFixed(2)}</div>
        </div>
        <div class="tablewrap" style="margin-top:10px"><table>
          <thead><tr><th>#</th><th>Station</th><th class="num">Ports free</th><th class="num">Queue</th><th>Site load / limit</th>
            <th class="num">Travel</th><th class="num">Wait</th><th class="num">Charge</th><th class="num">Load pen.</th><th class="num">Urgency bonus</th><th class="num">Final score</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <div class="small muted" style="margin:6px 0 10px">${esc(lr.formula)} · minutes, lower is better</div>
        ${(lr.warnings || []).map((w) => `<div class="notice warn">${esc(w)}</div>`).join("")}
        <div class="reason"><div><b>Why:</b> ${esc(ex.text)}</div><div class="src">${src}</div></div>`;
    }

    function renderDevices(s) {
      const rows = s.devices.map((d) => {
        const [cc, ct] = confState({ confirmation: d.confirmation, device_mode: d.device_mode, freshness: d.freshness,
                                     telemetry_age_s: d.telemetry_age_s, dry_run: d.dry_run });
        return `<tr>
          <td><span class="coords">${esc(d.device_id)}</span><div class="muted small">${d.station_code ? "Station " + esc(d.station_code) : "unbound"}${d.firmware_version ? " · " + esc(d.firmware_version) : ""}</div></td>
          <td>${modeBadge(d.device_mode)}${d.placeholder ? `<div>${badge("flexible", "placeholder")}</div>` : ""}</td>
          <td>${freshBadge(d.freshness, d.telemetry_age_s)}<div class="muted small">${d.last_telemetry_at ? "telemetry " + fmtTime(d.last_telemetry_at) : "no telemetry yet"}</div></td>
          <td>${badge(cc, ct)}${d.dry_run ? `<div>${badge("warn", "dry-run")}</div>` : ""}</td>
          <td class="small">${d.last_command_sent ? `${esc(d.last_command_sent.command)} #${d.last_command_sent.seq}<div class="muted">${fmtTime(d.last_command_sent.at)}</div>` : '<span class="muted">none</span>'}</td>
          <td class="small">${ackBadge(d.ack_status)}${d.last_ack ? `<div class="muted">${esc(d.last_ack.status)} #${d.last_ack.seq} ${fmtTime(d.last_ack.at)}${d.last_ack.detail ? " · " + esc(d.last_ack.detail) : ""}</div>` : ""}</td>
          <td class="small">${d.fallback_reason ? esc(d.fallback_reason) : '<span class="muted">— (live real hardware)</span>'}</td></tr>`;
      }).join("");
      $("#devicesTable").innerHTML = `<thead><tr><th>Device</th><th>Mode</th><th>Telemetry</th><th>Control confirmation</th><th>Latest command sent</th><th>Latest acknowledgment</th><th>Fallback reason</th></tr></thead><tbody>${
        rows || '<tr><td colspan="7" class="muted">No devices known.</td></tr>'}</tbody>`;
    }

    function renderTimeline(s) {
      const H = s.timeline.horizon_min || HORIZON_FALLBACK;
      const LANE = 30;
      const rows = s.stations.map((st) => {
        // overlapping sessions (different ports) get their own lane so nothing is hidden
        const items = s.timeline.items.filter((i) => i.station_id === st.id).sort((a, b) => a.start_min - b.start_min);
        const laneEnds = [];
        items.forEach((i) => {
          let lane = laneEnds.findIndex((end) => end <= i.start_min + 0.01);
          if (lane < 0) lane = laneEnds.length;
          laneEnds[lane] = i.end_min;
          i.lane = lane;
        });
        const blocks = items.map((i) => {
          const left = (i.start_min / H) * 100, width = Math.max(1.5, ((i.end_min - i.start_min) / H) * 100);
          const tip = `${i.driver_name} · ${i.status} · ${i.priority_class} · ${i.allocated_kw.toFixed(0)} kW · ` +
            `${fmtMin(i.start_min)} → ${fmtMin(i.end_min)}${i.truncated ? " (continues)" : ""}`;
          return `<div class="tl-block ${esc(i.priority_class)} ${i.status === "queued" ? "queued" : ""}" style="left:${left}%;width:${width}%;top:${4 + i.lane * LANE}px;bottom:auto;height:${LANE - 4}px" title="${esc(tip)}">${esc(i.driver_name)}</div>`;
        }).join("");
        const height = Math.max(1, laneEnds.length) * LANE + 4;
        return `<div class="tl-row"><div><b>${esc(st.code)}</b> <span class="muted small">${esc(st.kind)}${st.is_online ? "" : " · offline"}</span></div>
          <div class="tl-track" style="height:${height}px" role="img" aria-label="Schedule for ${esc(st.name)}">${blocks}</div></div>`;
      }).join("");
      const ticks = [0, 30, 60, 90, 120].map((m) => `<span>${m === 0 ? "now" : "+" + m + " min"}</span>`).join("");
      $("#timeline").innerHTML = rows + `<div class="tl-axis"><div></div><div>${ticks}</div></div>
        <div class="small muted" style="margin-top:6px">Solid = charging now · hatched = queued · red urgent / blue normal / grey flexible</div>`;
    }

    function renderLiveDrivers(s) {
      const d = s.live_drivers;
      if (!d.length) {
        $("#liveDrivers").innerHTML = '<div class="muted small">No driver has shared a live location recently. Open the driver app, share your location and submit a request.</div>';
        return;
      }
      $("#liveDrivers").innerHTML = `<ul class="plain">${d.map((x) => `<li>
        <span><span class="live-dot ${x.is_live ? "" : "old"}"></span><b>${esc(x.driver_name)}</b> ${x.priority_class ? badge(x.priority_class) : ""}
          <div class="coords muted small">${x.lat.toFixed(5)}, ${x.lon.toFixed(5)}${x.accuracy_m != null ? ` ±${Math.round(x.accuracy_m)} m` : ""} · ${x.source === "gps" ? "GPS" : "manual"}</div></span>
        <span class="small" style="text-align:right">${x.is_live ? "LIVE" : "last seen"} ${Math.round(x.age_s)} s ago<div class="muted">${x.updates} update(s)</div></span></li>`).join("")}</ul>`;
    }

    function renderRouteEtas(s) {
      const e = s.latest_route_etas;
      if (!e) { $("#etaWho").textContent = ""; $("#routeEtas").innerHTML = '<div class="muted small">No requests yet.</div>'; return; }
      $("#etaWho").textContent = `· ${e.driver_name} (request #${e.request_id})`;
      const live = new Map((e.live_etas || []).map((x) => [x.station_id, x]));
      const rows = e.items.map((i) => {
        const l = live.get(i.station_id);
        const src = i.route_fallback ? badge("warn", "fallback est.") : i.route_source === "osrm" ? badge("ok", "OSRM") : badge("warn", "estimate");
        return `<tr><td>${esc(i.name)}</td><td class="num">${i.distance_km.toFixed(1)} km</td><td class="num"><b>${fmtMin(i.travel_min)}</b></td>
          <td class="num">${i.feasible ? fmtMin(i.wait_min) : "–"}</td><td class="num">${i.feasible ? fmtMin(i.total_min) : "–"}</td>
          <td>${src}${l ? `<div class="muted small">live: ${fmtMin(l.travel_min)}</div>` : ""}${i.feasible ? "" : `<div class="muted small">${esc(i.rejection_reason)}</div>`}</td></tr>`;
      }).join("");
      $("#routeEtas").innerHTML = `<div class="tablewrap"><table><thead><tr><th>Station</th><th class="num">Route</th><th class="num">Travel</th><th class="num">Wait</th><th class="num">Total</th><th>Source</th></tr></thead><tbody>${
        rows || '<tr><td colspan="6" class="muted">Request has no recommendation yet.</td></tr>'}</tbody></table></div>`;
    }

    function renderControlLog(s) {
      const rows = s.control_events.map((ev) => {
        const [cls] = CMD_STYLE[ev.command] || ["normal"];
        return `<tr><td>${fmtTime(ev.ts)}</td><td>${esc(ev.station_code)}</td><td>${ev.previous ? esc(ev.previous) + " → " : ""}${badge(cls, ev.command)}</td>
          <td class="num">${Math.round(ev.power_fraction * 100)}%</td><td class="small">${esc(ev.reason)}</td></tr>`;
      }).join("");
      $("#controlLog").innerHTML = `<thead><tr><th>Time</th><th>Stn</th><th>Command</th><th class="num">Output</th><th>Reason</th></tr></thead><tbody>${
        rows || '<tr><td colspan="5" class="muted">No control decisions yet.</td></tr>'}</tbody>`;
    }

    async function refresh() {
      if (busy) return;
      busy = true;
      try {
        const s = await api("/dashboard/state");
        showError("");
        renderTiles(s); renderStations(s); renderLatestRec(s); renderDevices(s); renderTimeline(s); renderLiveDrivers(s); renderRouteEtas(s);
        renderControlLog(s); renderRequests(s); renderReservations(s); renderSystem(s);
      } catch (e) {
        showError(`Cannot reach backend: ${e.message}`);
      } finally {
        busy = false;
      }
    }

    function schedule() {
      if (timer) { clearInterval(timer); timer = null; }
      if ($("#autoRefresh").checked) timer = setInterval(refresh, 3000);
    }

    $("#btnRefresh").addEventListener("click", refresh);
    $("#autoRefresh").addEventListener("change", schedule);
    $("#btnReseed").addEventListener("click", async () => {
      if (!confirm("Reset all data and restore the demo scenario?")) return;
      try { await api("/seed?reset=true", { method: "POST" }); await refresh(); } catch (e) { showError(e.message); }
    });

    $("#stations").addEventListener("click", async (ev) => {
      const btn = ev.target.closest("button[data-act]");
      if (!btn) return;
      const card = btn.closest("[data-station]");
      const id = card.dataset.station;
      try {
        if (btn.dataset.act === "apply") {
          const body = {};
          card.querySelectorAll("input[data-f]").forEach((i) => { body[i.dataset.f] = parseFloat(i.value); });
          await api(`/stations/${id}`, { method: "PATCH", body });
        } else {
          const st = (await api(`/stations/${id}`));
          await api(`/stations/${id}`, { method: "PATCH", body: { is_online: !st.is_online } });
        }
        if (document.activeElement) document.activeElement.blur();
        await refresh();
      } catch (e) { showError(e.message); }
    });

    refresh();
    schedule();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    if (page === "driver") initDriver();
    else if (page === "dashboard") initDashboard();
  });
})();
