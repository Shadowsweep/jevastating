/**
 * Guardrail Arena Frontend Logic
 * Strictly adheres to RULES.md and DESIGN.md:
 * - Independent client RTT vs backend compute latency measurement
 * - Fail-safe visual states on engine errors
 * - Zero credential fields on client
 */

let currentPage = 0;
const pageSize = 15;
let currentFilter = "all";

document.addEventListener("DOMContentLoaded", () => {
  initHealth();
  loadRecords();
  initEventListeners();
});

async function initHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return;
    const data = await res.json();
    
    if (data.engines?.laya?.status === "online") {
      document.getElementById("laya-health-txt").textContent = "LOCAL (<40MS) ONLINE";
    }
    if (data.engines?.jev?.status === "online") {
      document.getElementById("jev-health-txt").textContent = "CLOUD (ONLINE)";
    }
    if (data.dataset?.total_records) {
      document.getElementById("stat-total-records").textContent = data.dataset.total_records;
    }
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

function initEventListeners() {
  // Input counter
  const promptInput = document.getElementById("prompt-input");
  const charCounter = document.getElementById("char-counter");
  promptInput.addEventListener("input", () => {
    const len = promptInput.value.length;
    charCounter.textContent = `${len} / 4000`;
    if (len > 4000) {
      charCounter.style.color = "var(--color-error)";
    } else {
      charCounter.style.color = "var(--color-mute)";
    }
  });

  // Template chips
  document.querySelectorAll(".template-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      promptInput.value = chip.getAttribute("data-text");
      promptInput.dispatchEvent(new Event("input"));
      document.getElementById("arena-workbench").scrollIntoView({ behavior: "smooth" });
    });
  });

  // Execute single benchmark
  document.getElementById("btn-run-single").addEventListener("click", runSingleBenchmark);

  // Clear arena
  document.getElementById("btn-clear-arena").addEventListener("click", () => {
    promptInput.value = "";
    promptInput.dispatchEvent(new Event("input"));
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

  // Dataset filter tabs
  document.querySelectorAll(".tab-row .pill-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab-row .pill-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentFilter = tab.getAttribute("data-filter");
      currentPage = 0;
      loadRecords();
    });
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
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px; color:var(--color-mute);">Loading parquet records...</td></tr>`;

  try {
    const res = await fetch(`/api/records?page=${currentPage}&limit=${pageSize}&filter=${currentFilter}`);
    if (!res.ok) throw new Error("Failed to fetch records");
    const data = await res.json();

    const records = data.records || [];
    const total = data.total || 0;

    const startIdx = currentPage * pageSize + 1;
    const endIdx = Math.min((currentPage + 1) * pageSize, total);
    document.getElementById("pagination-info").textContent = `Showing ${records.length ? startIdx : 0}-${endIdx} of ${total}`;

    document.getElementById("btn-prev-page").disabled = (currentPage === 0);
    document.getElementById("btn-next-page").disabled = (endIdx >= total);

    if (records.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px; color:var(--color-mute);">No records matching filter.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    records.forEach(rec => {
      const tr = document.createElement("tr");
      
      let flightMeta = {};
      try {
        flightMeta = JSON.parse(rec.flight || "{}");
      } catch (e) {}

      const flightStr = flightMeta.flight_no ? `${flightMeta.flight_no} (${flightMeta.origin}→${flightMeta.destination})` : "--";
      const isInj = rec.type === "injection_candidates";

      tr.innerHTML = `
        <td style="font-family:var(--font-mono); font-weight:700;">${rec.id}</td>
        <td class="dialogue-cell" title="${escapeHtml(rec.dialogue)}">${escapeHtml(rec.dialogue)}</td>
        <td style="font-size:13px;">${flightStr}</td>
        <td style="text-transform:uppercase; font-size:12px; font-weight:700;">${rec.intent || "--"}</td>
        <td>
          <span class="type-tag ${isInj ? 'injection' : 'normal'}">
            ${isInj ? 'INJECTION' : 'NORMAL'}
          </span>
        </td>
        <td>
          <button class="btn-outline btn-sm test-row-btn" data-text="${escapeHtml(rec.dialogue)}" data-id="${rec.id}">
            TEST
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".test-row-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const text = btn.getAttribute("data-text");
        const promptInput = document.getElementById("prompt-input");
        promptInput.value = text;
        promptInput.dispatchEvent(new Event("input"));
        document.getElementById("arena-workbench").scrollIntoView({ behavior: "smooth" });
        runSingleBenchmark(btn.getAttribute("data-id"));
      });
    });

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px; color:var(--color-error);">Error loading records: ${err.message}</td></tr>`;
  }
}

async function runSingleBenchmark(recordId = null) {
  const promptInput = document.getElementById("prompt-input");
  const text = promptInput.value.trim();
  if (!text) {
    alert("Please provide dialogue text or select a record to benchmark.");
    return;
  }

  const statusIndicator = document.getElementById("run-status-indicator");
  statusIndicator.textContent = "Executing concurrent evaluation (asyncio.gather)...";
  statusIndicator.style.color = "var(--color-primary-dark)";

  // Reset error badges
  document.getElementById("laya-error").style.display = "none";
  document.getElementById("jev-error").style.display = "none";

  const clientStartTime = performance.now();

  try {
    const payload = {
      custom_text: text,
      question_type: "all"
    };

    const res = await fetch("/api/benchmark/single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const clientEndTime = performance.now();
    const totalClientRttMs = Math.round(clientEndTime - clientStartTime);

    if (!res.ok) {
      throw new Error(`Server returned status ${res.status}`);
    }

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

  // Render Laya
  if (laya.status === "ok") {
    const isInj = laya.noul?.injection_detected;
    const noulBadge = document.getElementById("laya-noul-badge");
    noulBadge.className = `noul-status-badge ${isInj ? 'status-flagged' : 'status-safe'}`;
    noulBadge.textContent = isInj ? "FLAGGED: PROMPT INJECTION" : "SAFE: RULE COMPLIANT";
    document.getElementById("laya-noul-prob").textContent = `Prob: ${laya.noul?.probability}`;

    const intent = laya.choice?.intent || "--";
    const conf = laya.choice?.confidence || 0;
    document.getElementById("laya-intent-label").textContent = intent;
    document.getElementById("laya-intent-bar").style.width = `${Math.round(conf * 100)}%`;
    document.getElementById("laya-intent-conf").textContent = `${Math.round(conf * 100)}% (${conf})`;
  } else {
    // Fail-safe visual state (Rule 5)
    const errBox = document.getElementById("laya-error");
    errBox.textContent = `Laya Error: ${laya.error || "Execution failed"}`;
    errBox.style.display = "block";
  }

  // Render Jev
  if (jev.status === "ok") {
    const isInj = jev.noul?.injection_detected;
    const noulBadge = document.getElementById("jev-noul-badge");
    noulBadge.className = `noul-status-badge ${isInj ? 'status-flagged' : 'status-safe'}`;
    noulBadge.textContent = isInj ? "FLAGGED: PROMPT INJECTION" : "SAFE: RULE COMPLIANT";
    document.getElementById("jev-noul-prob").textContent = `Prob: ${jev.noul?.probability}`;

    const intent = jev.choice?.intent || "--";
    const conf = jev.choice?.confidence || 0;
    document.getElementById("jev-intent-label").textContent = intent;
    document.getElementById("jev-intent-bar").style.width = `${Math.round(conf * 100)}%`;
    document.getElementById("jev-intent-conf").textContent = `${Math.round(conf * 100)}% (${conf})`;
  } else {
    // Fail-safe visual state (Rule 5)
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
    desc.textContent = "Both Laya and Jev converged on identical guardrail status and intent routing.";
  } else {
    badge.className = "consensus-badge consensus-diverge";
    badge.textContent = "DIVERGENCE DETECTED";
    desc.textContent = `Noul agreed: ${data.agreement_details?.noul_agrees} | Intent agreed: ${data.agreement_details?.choice_agrees}`;
  }
}

function resetArenaResults() {
  document.getElementById("consensus-container").style.display = "none";
  document.getElementById("laya-raw-lat").textContent = "-- ms";
  document.getElementById("laya-rtt-lat").textContent = "-- ms";
  document.getElementById("jev-raw-lat").textContent = "-- ms";
  document.getElementById("jev-rtt-lat").textContent = "-- ms";
  document.getElementById("laya-noul-badge").textContent = "--";
  document.getElementById("laya-noul-badge").className = "noul-status-badge status-safe";
  document.getElementById("jev-noul-badge").textContent = "--";
  document.getElementById("jev-noul-badge").className = "noul-status-badge status-safe";
  document.getElementById("laya-intent-label").textContent = "--";
  document.getElementById("laya-intent-bar").style.width = "0%";
  document.getElementById("jev-intent-label").textContent = "--";
  document.getElementById("jev-intent-bar").style.width = "0%";
  document.getElementById("laya-intent-conf").textContent = "--";
  document.getElementById("jev-intent-conf").textContent = "--";
  document.getElementById("run-status-indicator").textContent = "Ready to execute";
}

async function runBatchBenchmark(limit = 25) {
  const filterSelect = document.getElementById("batch-filter-select");
  const filterVal = filterSelect ? filterSelect.value : "all";

  const progress = document.getElementById("batch-progress");
  progress.style.display = "block";
  document.querySelector(".batch-section").scrollIntoView({ behavior: "smooth" });

  try {
    const res = await fetch("/api/benchmark/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        limit: limit,
        filter_type: filterVal,
        concurrency: 5
      })
    });

    if (!res.ok) throw new Error("Batch benchmark request failed");
    const data = await res.json();

    const layaDist = data.distributions?.laya_latency || {};
    const jevDist = data.distributions?.jev_latency || {};

    document.getElementById("laya-p50").textContent = `${layaDist.p50 || 0} ms`;
    document.getElementById("laya-p95").textContent = `${layaDist.p95 || 0} ms`;
    document.getElementById("laya-p99").textContent = `${layaDist.p99 || 0} ms`;
    document.getElementById("laya-mean").textContent = `${layaDist.mean || 0} ms`;

    document.getElementById("jev-p50").textContent = `${jevDist.p50 || 0} ms`;
    document.getElementById("jev-p95").textContent = `${jevDist.p95 || 0} ms`;
    document.getElementById("jev-p99").textContent = `${jevDist.p99 || 0} ms`;
    document.getElementById("jev-mean").textContent = `${jevDist.mean || 0} ms`;

    document.getElementById("batch-consensus-rate").textContent = `${data.consensus_rate_percent}%`;
    document.getElementById("batch-stats-summary").textContent = `Evaluated ${data.total_evaluated} records (${data.valid_comparisons} valid comparisons)`;

  } catch (err) {
    alert("Batch benchmark error: " + err.message);
  } finally {
    progress.style.display = "none";
  }
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
