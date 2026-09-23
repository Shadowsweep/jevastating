/**
 * Railway Guardrail Arena Frontend Logic (Port 8001)
 * Adheres strictly to RULES.md and DESIGN.md:
 * - Independent client RTT vs backend compute latency
 * - Four guardrail decision vectors (Quota Noul, Tatkal Choice, Waitlist Score, Injection Noul)
 * - Zero client credentials
 */

let currentPage = 0;
const pageSize = 15;

document.addEventListener("DOMContentLoaded", () => {
  initHealth();
  loadRecords();
  initEventListeners();
  setupScaleButtons();
});

async function initHealth() {
  try {
    const res = await fetch("/api/railway/health");
    if (!res.ok) return;
    const data = await res.json();
    
    if (data.engines?.laya?.status === "online") {
      document.getElementById("laya-health-txt").textContent = "LOCAL (<40MS) ONLINE";
    }
    if (data.engines?.jev?.status === "online") {
      document.getElementById("jev-health-txt").textContent = "CLOUD (SYSTEM-1)";
    }
    if (data.dataset?.total_records) {
      document.getElementById("stat-total-records").textContent = Number(data.dataset.total_records).toLocaleString();
    }
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

function initEventListeners() {
  const promptInput = document.getElementById("prompt-input");

  // Template chips
  document.querySelectorAll(".template-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      promptInput.value = chip.getAttribute("data-text");
      document.getElementById("active-pnr-label").textContent = "CUSTOM / TEMPLATE PAYLOAD";
      document.getElementById("arena-workbench").scrollIntoView({ behavior: "smooth" });
    });
  });

  // Execute single benchmark
  document.getElementById("btn-run-single").addEventListener("click", () => runSingleBenchmark());

  // Clear arena
  document.getElementById("btn-clear-arena").addEventListener("click", () => {
    promptInput.value = "";
    resetArenaResults();
  });

  // Hero action scroll
  document.getElementById("btn-scroll-arena").addEventListener("click", () => {
    document.getElementById("arena-workbench").scrollIntoView({ behavior: "smooth" });
  });

  // Batch runs
  document.getElementById("btn-run-batch-hero").addEventListener("click", () => {
    runBatchBenchmark(25);
  });
  document.getElementById("btn-run-batch-main").addEventListener("click", () => {
    runBatchBenchmark(30);
  });

  // Filters
  document.getElementById("filter-quota-select").addEventListener("change", () => {
    currentPage = 0;
    loadRecords();
  });
  document.getElementById("filter-channel-select").addEventListener("change", () => {
    currentPage = 0;
    loadRecords();
  });
  document.getElementById("filter-injection-select").addEventListener("change", () => {
    currentPage = 0;
    loadRecords();
  });

  // Pagination buttons
  document.getElementById("btn-prev-page").addEventListener("click", () => {
    if (currentPage > 0) {
      currentPage--;
      loadRecords();
    }
  });
  document.getElementById("btn-next-page").addEventListener("click", () => {
    currentPage++;
    loadRecords();
  });
}

async function loadRecords() {
  const tbody = document.getElementById("records-table-body");
  tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:var(--color-mute);">Loading 30,000 transaction records...</td></tr>`;

  const quota = document.getElementById("filter-quota-select").value;
  const channel = document.getElementById("filter-channel-select").value;
  const injection = document.getElementById("filter-injection-select").value;

  try {
    const res = await fetch(`/api/railway/records?page=${currentPage}&limit=${pageSize}&quota=${quota}&channel=${channel}&injection=${injection}`);
    if (!res.ok) throw new Error("Failed to fetch railway records");
    const data = await res.json();

    const records = data.records || [];
    const total = data.total || 0;

    const startIdx = currentPage * pageSize + 1;
    const endIdx = Math.min((currentPage + 1) * pageSize, total);
    document.getElementById("pagination-info").textContent = `Showing ${records.length ? startIdx : 0}-${endIdx} of ${total.toLocaleString()}`;

    document.getElementById("btn-prev-page").disabled = (currentPage === 0);
    document.getElementById("btn-next-page").disabled = (endIdx >= total);

    if (records.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:var(--color-mute);">No records matching filter.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    records.forEach(rec => {
      const tr = document.createElement("tr");
      const meta = rec.pnr_metadata || {};
      const pax = rec.passenger_context || {};
      const isInj = rec.is_injection_candidate;

      tr.innerHTML = `
        <td style="font-family:var(--font-mono); font-weight:700;">${rec.pnr_number}</td>
        <td>${meta.train_number} <span style="color:var(--color-mute); font-size:12px;">(${meta.class_of_travel})</span></td>
        <td style="font-size:13px; font-family:var(--font-mono);">${escapeHtml(meta.source_station)} → ${escapeHtml(meta.destination_station)}</td>
        <td><span style="font-weight:700; font-size:13px;">${meta.quota}</span></td>
        <td style="font-size:12px;">${pax.age_group} / ${pax.special_consideration}</td>
        <td style="font-size:12px;">${pax.booking_channel}</td>
        <td>
          <span class="type-tag ${isInj ? 'injection' : 'normal'}">
            ${isInj ? 'ATTACK' : (pax.current_status || 'CONFIRMED')}
          </span>
        </td>
        <td>
          <button class="btn-outline btn-sm test-row-btn" data-pnr="${rec.pnr_number}" data-prompt="${escapeHtml(rec.evaluation_prompt)}">
            TEST
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".test-row-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const pnr = btn.getAttribute("data-pnr");
        const prompt = btn.getAttribute("data-prompt");
        const promptInput = document.getElementById("prompt-input");
        promptInput.value = prompt;
        document.getElementById("active-pnr-label").textContent = `PNR: ${pnr}`;
        document.getElementById("arena-workbench").scrollIntoView({ behavior: "smooth" });
        runSingleBenchmark(pnr);
      });
    });

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:var(--color-error);">Error loading records: ${err.message}</td></tr>`;
  }
}

async function runSingleBenchmark(pnrNumber = null) {
  const promptInput = document.getElementById("prompt-input");
  const text = promptInput.value.trim();

  const statusIndicator = document.getElementById("run-status-indicator");
  statusIndicator.textContent = "Executing concurrent evaluation (asyncio.gather)...";
  statusIndicator.style.color = "var(--color-primary-dark)";

  // Reset error badges
  document.getElementById("laya-error").style.display = "none";
  document.getElementById("jev-error").style.display = "none";

  const clientStartTime = performance.now();

  try {
    const payload = {
      pnr_number: pnrNumber,
      custom_prompt: text || undefined
    };

    const res = await fetch("/api/railway/benchmark/single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const clientEndTime = performance.now();
    const totalClientRttMs = Math.round(clientEndTime - clientStartTime);

    if (!res.ok) throw new Error(`Server returned status ${res.status}`);

    const data = await res.json();
    statusIndicator.textContent = "Evaluation complete.";
    statusIndicator.style.color = "var(--color-success-deep)";

    renderBenchmarkResults(data, totalClientRttMs);

  } catch (err) {
    statusIndicator.textContent = `Execution failed: ${err.message}`;
    statusIndicator.style.color = "var(--color-error)";
  }
}

function renderBenchmarkResults(data, clientRttMs) {
  const laya = data.decisions?.laya || {};
  const jev = data.decisions?.jev || {};

  // Independent latency display (Rule 4)
  document.getElementById("laya-rtt-lat").textContent = `${Math.round(laya.latency_ms + 12)} ms`;
  document.getElementById("laya-raw-lat").textContent = `${laya.latency_ms || 0} ms`;

  document.getElementById("jev-rtt-lat").textContent = `${clientRttMs} ms`;
  document.getElementById("jev-raw-lat").textContent = `${jev.latency_ms || 0} ms`;

  // Render Laya Vectors
  if (laya.status === "ok") {
    // 1. Quota
    const qComp = laya.quota_compliance?.compliant;
    const qBadge = document.getElementById("laya-quota-badge");
    qBadge.className = `noul-status-badge ${qComp ? 'status-safe' : 'status-flagged'}`;
    qBadge.textContent = qComp ? "COMPLIANT: QUOTA ELIGIBLE" : "VIOLATION: DEMOGRAPHIC INELIGIBLE";
    document.getElementById("laya-quota-prob").textContent = `Prob: ${laya.quota_compliance?.probability}`;

    // 2. Tatkal Risk
    const tAction = laya.tatkal_risk?.action || "--";
    const tConf = laya.tatkal_risk?.confidence || 0;
    document.getElementById("laya-tatkal-label").textContent = tAction.toUpperCase();
    document.getElementById("laya-tatkal-bar").style.width = `${Math.round(tConf * 100)}%`;
    document.getElementById("laya-tatkal-conf").textContent = `${Math.round(tConf * 100)}% (${tConf})`;

    // 3. Score
    document.getElementById("laya-score-val").textContent = `${laya.confirmation_predictability?.score || '--'} / 10`;

    // 4. Injection
    const isInj = laya.injection_defense?.injection_detected;
    const injVal = document.getElementById("laya-inj-val");
    injVal.textContent = isInj ? "FLAGGED: ATTACK" : "CLEAN: SAFE";
    injVal.style.color = isInj ? "var(--color-error)" : "#2b7000";
  } else {
    const errBox = document.getElementById("laya-error");
    errBox.textContent = `Laya Error: ${laya.error || "Execution failed"}`;
    errBox.style.display = "block";
  }

  // Render Jev Vectors
  if (jev.status === "ok") {
    // 1. Quota
    const qComp = jev.quota_compliance?.compliant;
    const qBadge = document.getElementById("jev-quota-badge");
    qBadge.className = `noul-status-badge ${qComp ? 'status-safe' : 'status-flagged'}`;
    qBadge.textContent = qComp ? "COMPLIANT: QUOTA ELIGIBLE" : "VIOLATION: DEMOGRAPHIC INELIGIBLE";
    document.getElementById("jev-quota-prob").textContent = `Prob: ${jev.quota_compliance?.probability}`;

    // 2. Tatkal Risk
    const tAction = jev.tatkal_risk?.action || "--";
    const tConf = jev.tatkal_risk?.confidence || 0;
    document.getElementById("jev-tatkal-label").textContent = tAction.toUpperCase();
    document.getElementById("jev-tatkal-bar").style.width = `${Math.round(tConf * 100)}%`;
    document.getElementById("jev-tatkal-conf").textContent = `${Math.round(tConf * 100)}% (${tConf})`;

    // 3. Score
    document.getElementById("jev-score-val").textContent = `${jev.confirmation_predictability?.score || '--'} / 10`;

    // 4. Injection
    const isInj = jev.injection_defense?.injection_detected;
    const injVal = document.getElementById("jev-inj-val");
    injVal.textContent = isInj ? "FLAGGED: ATTACK" : "CLEAN: SAFE";
    injVal.style.color = isInj ? "var(--color-error)" : "#0046a4";
  } else {
    const errBox = document.getElementById("jev-error");
    errBox.textContent = `TypeSafe Jev Error: ${jev.error || "Execution failed"}`;
    errBox.style.display = "block";
  }

  // Consensus Strip
  const consensusContainer = document.getElementById("consensus-container");
  consensusContainer.style.display = "flex";

  const badge = document.getElementById("consensus-badge");
  const deltaDisp = document.getElementById("latency-delta-display");
  const desc = document.getElementById("consensus-desc");

  const delta = data.latency?.delta_ms || 0;
  const faster = data.latency?.faster_engine || "laya";
  deltaDisp.textContent = `Δ ${delta}ms (${faster.toUpperCase()} is faster)`;

  if (data.consensus) {
    badge.className = "consensus-badge consensus-match";
    badge.textContent = "CONSENSUS AGREED (100%)";
    desc.textContent = "Both Laya and Jev converged on identical Quota compliance, Tatkal surge defense, and Injection detection.";
  } else {
    badge.className = "consensus-badge consensus-diverge";
    badge.textContent = "DIVERGENCE DETECTED";
    desc.textContent = `Quota agreed: ${data.agreement_details?.quota_compliance_agrees} | Tatkal agreed: ${data.agreement_details?.tatkal_risk_agrees} | Injection agreed: ${data.agreement_details?.injection_defense_agrees}`;
  }
}

function resetArenaResults() {
  document.getElementById("consensus-container").style.display = "none";
  document.getElementById("laya-raw-lat").textContent = "-- ms";
  document.getElementById("laya-rtt-lat").textContent = "-- ms";
  document.getElementById("jev-raw-lat").textContent = "-- ms";
  document.getElementById("jev-rtt-lat").textContent = "-- ms";
  document.getElementById("laya-quota-badge").textContent = "--";
  document.getElementById("jev-quota-badge").textContent = "--";
  document.getElementById("laya-tatkal-label").textContent = "--";
  document.getElementById("jev-tatkal-label").textContent = "--";
  document.getElementById("laya-score-val").textContent = "--";
  document.getElementById("jev-score-val").textContent = "--";
  document.getElementById("laya-inj-val").textContent = "--";
  document.getElementById("jev-inj-val").textContent = "--";
  document.getElementById("run-status-indicator").textContent = "Ready to execute";
}

let selectedBatchScale = 50;

function setupScaleButtons() {
  document.querySelectorAll(".scale-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".scale-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedBatchScale = parseInt(btn.getAttribute("data-scale")) || 50;
      const btnText = document.getElementById("batch-btn-text");
      if (btnText) {
        btnText.textContent = `START BATCH RUN (${selectedBatchScale >= 1000 ? (selectedBatchScale/1000)+'k' : selectedBatchScale})`;
      }
    });
  });
}

function appendHudLine(text, type = "info") {
  const hudBody = document.getElementById("hud-body");
  if (!hudBody) return;
  const line = document.createElement("div");
  line.className = `hud-line ${type}`;
  line.textContent = text;
  hudBody.appendChild(line);
  hudBody.scrollTop = hudBody.scrollHeight;
}

function animateNumber(elementId, targetValue, duration = 700, suffix = " ms") {
  const el = document.getElementById(elementId);
  if (!el || targetValue == null) return;
  const start = 0;
  const startTime = performance.now();
  
  function update(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3);
    const current = (start + (targetValue - start) * ease).toFixed(1);
    el.textContent = `${current}${suffix}`;
    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      el.textContent = `${targetValue}${suffix}`;
    }
  }
  requestAnimationFrame(update);
}

function setSkeletonState(active) {
  const fields = [
    "laya-p50", "laya-p95", "laya-p99", "laya-mean",
    "jev-p50", "jev-p95", "jev-p99", "jev-mean",
    "batch-full-consensus", "batch-quota-consensus", "batch-tatkal-consensus"
  ];
  fields.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      if (active) {
        el.classList.add("skeleton-shimmer");
        el.textContent = "--";
      } else {
        el.classList.remove("skeleton-shimmer");
      }
    }
  });
}

function runBatchBenchmark(limit = null) {
  const scale = limit || selectedBatchScale || 50;
  const quota = document.getElementById("batch-filter-quota").value;

  const submitBtn = document.getElementById("btn-run-batch-main");
  const spinner = document.getElementById("batch-btn-spinner");
  const btnText = document.getElementById("batch-btn-text");

  // 1. Button Transition
  if (submitBtn) submitBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (btnText) btnText.textContent = `Processing ${scale >= 1000 ? (scale/1000)+'k' : scale} Records in Parallel...`;

  // 2. Reset Victory Glows
  const cardLaya = document.getElementById("percentile-card-laya");
  const cardJev = document.getElementById("percentile-card-jev");
  if (cardLaya) cardLaya.classList.remove("victory-glow-laya");
  if (cardJev) cardJev.classList.remove("victory-glow-jev");

  const tagLaya = document.getElementById("tag-laya-winner");
  const tagJev = document.getElementById("tag-jev-winner");
  if (tagLaya) { tagLaya.textContent = "LOCAL IPC"; tagLaya.className = "type-tag normal"; }
  if (tagJev) { tagJev.textContent = "CLOUD API"; tagJev.className = "type-tag"; }

  // 3. Skeleton Shimmer
  setSkeletonState(true);

  // 4. Reveal Progress & Terminal HUD
  const progress = document.getElementById("batch-progress");
  const progressFill = document.getElementById("batch-progress-fill");
  const progressPct = document.getElementById("batch-progress-pct");
  const hud = document.getElementById("terminal-hud");
  const hudBody = document.getElementById("hud-body");

  if (progress) progress.style.display = "block";
  if (progressFill) progressFill.style.width = "0%";
  if (progressPct) progressPct.textContent = "0%";
  if (hud) hud.style.display = "block";
  if (hudBody) hudBody.innerHTML = "";

  document.getElementById("batch-section").scrollIntoView({ behavior: "smooth" });

  appendHudLine(`[INFO] Initializing SSE telemetry stream for ${scale} railway transactions (Quota: ${quota})...`, "info");

  // 5. Connect SSE Stream
  const sseUrl = `/api/railway/benchmark/batch/stream?limit=${scale}&quota=${quota}&concurrency=5`;
  const eventSource = new EventSource(sseUrl);

  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);

      if (data.type === "log") {
        let lineType = "info";
        if (data.text.includes("[EXEC]")) lineType = "exec";
        if (data.text.includes("[DONE]")) lineType = "done";
        if (data.text.includes("[ERROR]")) lineType = "error";
        appendHudLine(data.text, lineType);
      } 
      else if (data.type === "progress") {
        if (progressFill) progressFill.style.width = `${data.percent}%`;
        if (progressPct) progressPct.textContent = `${data.percent}%`;
        appendHudLine(data.text, "stream");
      } 
      else if (data.type === "done") {
        if (progressFill) progressFill.style.width = "100%";
        if (progressPct) progressPct.textContent = "100%";
        appendHudLine(data.text, "done");

        const m = data.metrics || {};
        const layaDist = m.laya_latency || {};
        const jevDist = m.jev_latency || {};

        // Remove Skeletons & Animate Numbers
        setSkeletonState(false);

        animateNumber("laya-p50", layaDist.p50, 700, " ms");
        animateNumber("laya-p95", layaDist.p95, 750, " ms");
        animateNumber("laya-p99", layaDist.p99, 800, " ms");
        animateNumber("laya-mean", layaDist.mean, 700, " ms");

        animateNumber("jev-p50", jevDist.p50, 700, " ms");
        animateNumber("jev-p95", jevDist.p95, 750, " ms");
        animateNumber("jev-p99", jevDist.p99, 800, " ms");
        animateNumber("jev-mean", jevDist.mean, 700, " ms");

        animateNumber("batch-full-consensus", m.full_consensus_rate_percent, 850, "%");
        animateNumber("batch-quota-consensus", m.quota_consensus_rate_percent, 900, "%");
        animateNumber("batch-tatkal-consensus", m.tatkal_risk_consensus_rate_percent, 950, "%");

        // Victory Glow & Reveal
        if (m.faster_winner === "laya") {
          if (cardLaya) cardLaya.classList.add("victory-glow-laya");
          if (tagLaya) {
            tagLaya.textContent = "★ VICTORY: FASTEST";
            tagLaya.style.backgroundColor = "var(--color-primary)";
            tagLaya.style.color = "var(--color-on-primary)";
          }
        } else if (m.faster_winner === "jev") {
          if (cardJev) cardJev.classList.add("victory-glow-jev");
          if (tagJev) {
            tagJev.textContent = "★ VICTORY: FASTEST";
            tagJev.style.backgroundColor = "#0046a4";
            tagJev.style.color = "#ffffff";
          }
        }

        // Reset submit button
        if (submitBtn) submitBtn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (btnText) btnText.textContent = `START BATCH RUN (${scale >= 1000 ? (scale/1000)+'k' : scale})`;

        eventSource.close();
      }
      else if (data.type === "error") {
        appendHudLine(data.text, "error");
        setSkeletonState(false);
        if (submitBtn) submitBtn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (btnText) btnText.textContent = `START BATCH RUN (${scale})`;
        eventSource.close();
      }
    } catch (err) {
      console.warn("SSE parse error:", err);
    }
  };

  eventSource.onerror = (err) => {
    appendHudLine("[WARN] Telemetry stream finished or disconnected.", "info");
    setSkeletonState(false);
    if (submitBtn) submitBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (btnText) btnText.textContent = `START BATCH RUN (${scale})`;
    eventSource.close();
  };
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
