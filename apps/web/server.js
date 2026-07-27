const nodeId = queryParam("nodeId");

function setStatusBadge(stale) {
  setStatusPill("statusBadge", stale ? "STALE" : "ONLINE", stale ? "warn" : "ok");
}

function paintTableBody(tableId, rows, emptyText, columns) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!rows.length) {
    const cells = columns > 1 ? [emptyText, ...Array(columns - 1).fill("")] : [emptyText];
    tbody.appendChild(row(cells));
    return;
  }
  rows.forEach((r) => tbody.appendChild(r));
}

function paintZfsPools(pools) {
  const panel = document.getElementById("zfsPoolsPanel");
  if (!panel) return;
  if (!pools.length) {
    panel.classList.add("hidden-panel");
    return;
  }
  panel.classList.remove("hidden-panel");
  const rows = pools.map((pool) => {
    const health = document.createElement("span");
    health.className = zfsHealthClass(pool.health);
    health.textContent = pool.health || "unknown";
    return row([
      pool.name,
      health,
      pct(pool.percent),
      `${formatBytes(pool.usedBytes)} / ${formatBytes(pool.totalBytes)}`,
    ]);
  });
  paintTableBody("zfsPoolsTable", rows, "No ZFS pools", 4);
}

function paintFilesystems(filesystems) {
  const panel = document.getElementById("filesystemsPanel");
  if (!panel) return;
  if (!filesystems.length) {
    panel.classList.add("hidden-panel");
    return;
  }
  panel.classList.remove("hidden-panel");
  const rows = filesystems.map((fs) => {
    return row([
      fs.path,
      fs.fstype || "-",
      pct(fs.percent),
      `${formatBytes(fs.usedBytes)} / ${formatBytes(fs.totalBytes)}`,
    ]);
  });
  paintTableBody("filesystemsTable", rows, "No mounted filesystems", 4);
}

function paintBlockDevices(devices) {
  const panel = document.getElementById("blockDevicesPanel");
  if (!panel) return;
  if (!devices.length) {
    panel.classList.add("hidden-panel");
    return;
  }
  panel.classList.remove("hidden-panel");
  const rows = devices.map((dev) => {
    return row([
      dev.name || dev.path,
      dev.kind || "-",
      dev.fstype || "-",
      formatBytes(dev.totalBytes),
      dev.mountpoint || "-",
    ]);
  });
  paintTableBody("blockDevicesTable", rows, "No block devices", 5);
}

function paintHostSections(snapshot) {
  const sections = hostSections(snapshot);
  const servicesPanel = document.getElementById("servicesPanel");
  const containersPanel = document.getElementById("containersPanel");
  if (servicesPanel) {
    servicesPanel.classList.toggle("hidden-panel", !sections.services);
  }
  if (containersPanel) {
    containersPanel.classList.toggle("hidden-panel", !sections.containers);
  }
  return sections;
}

function paintPills(containerId, items, emptyText) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<div class="noc-empty">${emptyText}</div>`;
    return;
  }
  items.forEach((item) => {
    const pill = document.createElement("div");
    pill.className = `noc-pill ${item.status || "stopped"}`;
    pill.innerHTML = `<span class="dot"></span><span>${item.name}</span><span>${item.statusText || item.status}</span>`;
    container.appendChild(pill);
  });
}

function paintContainers(containers, capabilities) {
  const container = document.getElementById("containersGrid");
  if (!container) return;
  container.innerHTML = "";
  const items = containers || [];
  const containerActions = ((capabilities && capabilities.actions) || []).filter(
    (action) => action.scope === "container",
  );
  if (!items.length) {
    container.innerHTML = `<div class="noc-empty">No Docker containers reported on this host</div>`;
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = `service-card ${item.status || "stopped"}`;
    const memText =
      item.memoryUsedBytes || item.memoryLimitBytes
        ? `${formatBytes(item.memoryUsedBytes || 0)}${item.memoryLimitBytes ? ` / ${formatBytes(item.memoryLimitBytes)}` : ""}`
        : item.statusText || item.status || "unknown";
    const metaParts = [
      item.image || "unknown image",
      item.cpuPercent != null ? `CPU ${pct(item.cpuPercent)}` : null,
      memText,
    ].filter(Boolean);
    card.innerHTML = `
      <div class="service-title">${item.name}</div>
      <div class="service-meta">${metaParts.join(" | ")}</div>
      <div class="service-actions"></div>
    `;
    const actionsRow = card.querySelector(".service-actions");
    const allowedActions = containerActions.filter((action) => containerActionAllowed(action.id, item.status));
    if (!allowedActions.length) {
      actionsRow.innerHTML = `<div class="noc-empty">No actions for ${item.status || "unknown"}</div>`;
    } else {
      allowedActions.forEach((action) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `action-button${action.dangerous ? " danger" : ""}`;
        btn.textContent = action.label || action.id;
        btn.addEventListener("click", () => runAction(action.id, item.name, {}, Boolean(action.dangerous)));
        actionsRow.appendChild(btn);
      });
    }
    container.appendChild(card);
  });
}

function serviceIsManaged(item) {
  if (Object.prototype.hasOwnProperty.call(item, "managed")) {
    return item.managed === true;
  }
  return true;
}

function paintServices(services, capabilities) {
  const tbody = document.querySelector("#servicesTable tbody");
  const filterInput = document.getElementById("servicesFilter");
  const countEl = document.getElementById("servicesCount");
  if (!tbody) return;

  const items = services || [];
  const serviceActions = ((capabilities && capabilities.actions) || []).filter((action) => action.scope === "service");

  const render = () => {
    const query = (filterInput && filterInput.value ? filterInput.value : "").trim().toLowerCase();
    const filtered = items.filter((item) => !query || String(item.name || "").toLowerCase().includes(query));
    tbody.innerHTML = "";

    if (!filtered.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 3;
      td.innerHTML = `<div class="noc-empty">${items.length ? "No services match the filter" : "No services reported on this host"}</div>`;
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      filtered.forEach((item) => {
        const tr = document.createElement("tr");
        const nameCell = document.createElement("td");
        nameCell.innerHTML = `<strong>${item.name}</strong>`;
        tr.appendChild(nameCell);

        const statusCell = document.createElement("td");
        statusCell.innerHTML = statusPillHtml(item.statusText || item.status || "unknown", statusPillTone(item.status));
        tr.appendChild(statusCell);

        const actionsCell = document.createElement("td");
        if (!serviceIsManaged(item)) {
          actionsCell.innerHTML = `<span class="cell-sub">View only</span>`;
        } else {
          const allowedActions = serviceActions.filter((action) => serviceActionAllowed(action.id, item.status));
          if (!allowedActions.length) {
            actionsCell.innerHTML = `<span class="cell-sub">No actions</span>`;
          } else {
            const row = document.createElement("div");
            row.className = "action-row";
            allowedActions.forEach((action) => {
              const btn = document.createElement("button");
              btn.type = "button";
              btn.className = `action-button${action.dangerous ? " danger" : ""}`;
              btn.textContent = action.label || action.id;
              btn.addEventListener("click", () => runAction(action.id, item.name, {}, Boolean(action.dangerous)));
              row.appendChild(btn);
            });
            actionsCell.appendChild(row);
          }
        }
        tr.appendChild(actionsCell);
        tbody.appendChild(tr);
      });
    }

    if (countEl) {
      const running = filtered.filter((item) => String(item.status || "").toLowerCase() === "running").length;
      countEl.textContent = query
        ? `${filtered.length} shown (${running} running) of ${items.length}`
        : `${items.length} services (${running} running)`;
    }
  };

  if (filterInput && !filterInput.dataset.bound) {
    filterInput.dataset.bound = "1";
    filterInput.addEventListener("input", render);
  }
  render();
}

function setActionStatus(message, isError = false) {
  const el = document.getElementById("actionStatus");
  if (!el) return;
  el.textContent = message || "";
  el.style.color = isError ? "var(--bad)" : "var(--muted)";
}

async function runAction(actionId, target = null, params = {}, dangerous = false) {
  try {
    setActionStatus(`Queueing ${actionId}${target ? ` (${target})` : ""}...`);
    await submitAction(nodeId, actionId, target, params, dangerous);
    setActionStatus(`Action queued: ${actionId}${target ? ` (${target})` : ""}. Agent will execute on next heartbeat.`);
  } catch (err) {
    setActionStatus(err.message, true);
  }
}

function paintHostActions(capabilities) {
  const section = document.getElementById("hostActionsSection");
  const container = document.getElementById("hostActions");
  if (!section || !container) return;
  const actions = (capabilities && capabilities.actions) || [];
  const hostActions = actions.filter((action) => action.scope === "host");
  if (!hostActions.length) {
    section.classList.add("hidden-panel");
    return;
  }
  section.classList.remove("hidden-panel");
  container.innerHTML = "";
  hostActions.forEach((action) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `action-button${action.dangerous ? " danger" : ""}`;
    btn.textContent = action.label || action.id;
    btn.addEventListener("click", () => runAction(action.id, null, {}, Boolean(action.dangerous)));
    container.appendChild(btn);
  });
}

function getPrimaryHostIp(node, summary) {
  const ips = (node && node.ips) || (summary && summary.ips) || [];
  return ips.find((ip) => ip && !String(ip).startsWith("127.") && !String(ip).includes(":")) || ips[0] || null;
}

function buildProxmoxShellUrl(hostname, ip) {
  const host = ip || hostname;
  const nodeName = String(hostname || "").toLowerCase();
  return `https://${host}:8006/#v1:0:=node/${encodeURIComponent(nodeName)}:4:=shell::::::`;
}

function paintRemoteAccess(snapshot, summary, hostname) {
  const panel = document.getElementById("remoteAccessPanel");
  const body = document.getElementById("remoteAccessBody");
  const toolbar = document.getElementById("remoteAccessToolbar");
  const titleEl = document.getElementById("remoteAccessTitle");
  if (!panel || !body || !toolbar) return;

  const node = snapshot.node || {};
  const caps = snapshot.capabilities || {};
  const hostRole = node.hostRole || snapshot.hostRole || caps.hostRole || "unknown";
  const platform = node.platform || summary.platform || "";
  const ip = getPrimaryHostIp(node, summary);
  const workloads = snapshot.workloads || {};

  let mode = "placeholder";
  let title = "Remote access";
  let url = null;
  let message = "Remote console and terminal access for this host will appear here.";

  if (hostRole === "proxmox" || workloads.kind === "proxmox") {
    mode = "proxmox";
    title = "Hypervisor shell";
    url = buildProxmoxShellUrl(hostname, ip);
    message = "Proxmox node shell";
  } else if (platform === "windows" || hostRole === "windows-server" || hostRole === "windows-client") {
    mode = "windows";
    title = "Remote desktop";
    message = "RDP and PowerShell sessions will load here — one gateway, no extra VPN rules.";
  } else if (platform === "linux") {
    mode = "linux";
    title = "Terminal";
    message = "SSH terminal access will load here through the HCC gateway.";
  }

  if (titleEl) titleEl.textContent = title;
  toolbar.innerHTML = "";

  if (url) {
    const openBtn = document.createElement("a");
    openBtn.className = "button-link";
    openBtn.href = url;
    openBtn.target = "_blank";
    openBtn.rel = "noopener noreferrer";
    openBtn.textContent = "Open in new tab";
    toolbar.appendChild(openBtn);

    const reloadBtn = document.createElement("button");
    reloadBtn.type = "button";
    reloadBtn.className = "button-link";
    reloadBtn.textContent = "Reload";
    reloadBtn.addEventListener("click", () => {
      const frame = body.querySelector(".remote-access-frame");
      if (frame) frame.src = url;
    });
    toolbar.appendChild(reloadBtn);
  }

  body.innerHTML = "";
  body.className = "remote-access-body";

  if (mode === "proxmox" && url) {
    const note = document.createElement("p");
    note.className = "cell-sub remote-access-note";
    note.textContent =
      "Proxmox shell for this node. Sign in with your Proxmox credentials if prompted. If the embed is blank, use Open in new tab (some browsers block Proxmox in iframes).";

    const frameWrap = document.createElement("div");
    frameWrap.className = "remote-access-frame-wrap";
    const frame = document.createElement("iframe");
    frame.className = "remote-access-frame";
    frame.src = url;
    frame.title = `${hostname} Proxmox shell`;
    frame.loading = "lazy";
    frame.referrerPolicy = "no-referrer";
    frameWrap.appendChild(frame);

    body.appendChild(note);
    body.appendChild(frameWrap);
    return;
  }

  const placeholder = document.createElement("div");
  placeholder.className = "remote-access-placeholder";
  const icon = mode === "windows" ? "🖥" : mode === "linux" ? "⌘" : "◈";
  placeholder.innerHTML = `
    <div class="remote-access-placeholder-icon" aria-hidden="true">${icon}</div>
    <strong>${title}</strong>
    <p>${message}</p>
    ${ip ? `<p class="cell-sub">${hostname} · ${ip}</p>` : `<p class="cell-sub">${hostname}</p>`}
  `;
  body.appendChild(placeholder);
}

function paintVMs(workloads, capabilities) {
  const panel = document.getElementById("vmsPanel");
  const container = document.getElementById("vmCards");
  if (!panel || !container) return;

  const vms = (workloads && workloads.vms) || [];
  if (!vms.length || workloads.kind !== "proxmox") {
    panel.classList.add("hidden-panel");
    return;
  }

  const vmActions = ((capabilities && capabilities.actions) || []).filter((action) => action.scope === "vm");
  const running = vms.filter((vm) => vm.status === "running").length;
  setText("vmTotals", `${vms.length} VM(s) | ${running} running`);
  panel.classList.remove("hidden-panel");
  container.innerHTML = "";

  vms.forEach((vm) => {
    const card = document.createElement("div");
    card.className = `vm-card ${vm.status || "unknown"}`;
    card.innerHTML = `
      <div class="vm-title">${vm.name || `VM ${vm.id}`}</div>
      <div class="vm-meta">ID ${vm.id} | ${String(vm.type || "qemu").toUpperCase()} | ${vm.osType || "-"} | ${vm.status || "unknown"}</div>
      <div class="vm-stats">
        <div>Memory: ${vm.memoryMb ? `${vm.memoryMb} MB` : "-"}</div>
        <div>Disk: ${vm.diskGb ? `${vm.diskGb} GB` : "-"}</div>
        <div>PID: ${vm.pid ? vm.pid : "-"}</div>
      </div>
      <div class="vm-actions"></div>
    `;
    const actionsRow = card.querySelector(".vm-actions");
    const allowedActions = vmActions.filter((action) => vmActionAllowed(action.id, vm.status));
    if (!allowedActions.length) {
      actionsRow.innerHTML = `<div class="noc-empty">No actions for ${vm.status || "unknown"} state</div>`;
    }
    allowedActions.forEach((action) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `action-button${action.dangerous ? " danger" : ""}`;
      btn.textContent = action.label || action.id;
      btn.addEventListener("click", () => {
        runAction(action.id, vm.id, { vmType: vm.type || "qemu" }, Boolean(action.dangerous));
      });
      actionsRow.appendChild(btn);
    });
    container.appendChild(card);
  });
}

function paintHistory(items) {
  const points = (items || []).slice(-24).reverse();
  const rows = points.map((point) => {
    return row([
      new Date(point.at).toLocaleString(),
      pct(point.cpuPercent),
      pct(point.memoryPercent),
      pct(point.storagePercent),
      `${formatBytes(point.networkRxBytesPerSec)}/s`,
      `${formatBytes(point.networkTxBytesPerSec)}/s`,
    ]);
  });
  paintTableBody("historyTable", rows, "No history yet", 6);
}

function paintStoragePanel(storageDetail, fallbackStorage) {
  const detail = storageDetail || {};
  const totals = detail.totals || {};
  const hasDetail = Boolean(
    Number(totals.totalBytes || 0) > 0 ||
    (detail.zfsPools && detail.zfsPools.length) ||
    (detail.filesystems && detail.filesystems.length) ||
    (detail.blockDevices && detail.blockDevices.length),
  );

  if (hasDetail) {
    setText(
      "storageTotals",
      `Total attached: ${formatBytes(totals.usedBytes || 0)} used / ${formatBytes(totals.totalBytes || 0)} (${pct(totals.percent || 0)})`,
    );
    paintZfsPools(detail.zfsPools || []);
    paintFilesystems(detail.filesystems || []);
    paintBlockDevices(detail.blockDevices || []);
    return totals;
  }

  const fallback = fallbackStorage || [];
  setText("storageTotals", "Using configured mount paths");
  document.getElementById("zfsPoolsPanel").classList.add("hidden-panel");
  document.getElementById("blockDevicesPanel").classList.add("hidden-panel");
  document.getElementById("filesystemsPanel").classList.remove("hidden-panel");
  const rows = fallback.map((item) => {
    return row([item.path, item.fstype || "configured", pct(item.percent), `${formatBytes(item.usedBytes)} / ${formatBytes(item.totalBytes)}`]);
  });
  paintTableBody("filesystemsTable", rows, "No storage data", 4);

  const used = fallback.reduce((sum, item) => sum + Number(item.usedBytes || 0), 0);
  const total = fallback.reduce((sum, item) => sum + Number(item.totalBytes || 0), 0);
  return {
    usedBytes: used,
    totalBytes: total,
    percent: total > 0 ? (used * 100) / total : 0,
  };
}

async function refreshServerDetail() {
  const errorLabel = document.getElementById("errorLabel");
  if (!nodeId) {
    errorLabel.textContent = "Missing nodeId in URL. Example: server.html?nodeId=proxmox-01";
    setStatusBadge(true);
    return 30;
  }

  try {
    const [detail, history] = await Promise.all([
      apiFetch(`/api/v1/fleet/node?nodeId=${encodeURIComponent(nodeId)}`),
      apiFetch(`/api/v1/fleet/node/history?nodeId=${encodeURIComponent(nodeId)}&limit=180`),
    ]);
    const snapshot = detail.snapshot || {};
    const node = snapshot.node || {};
    const summary = detail.summary || {};
    const system = snapshot.system || {};
    const memory = system.memory || {};
    const network = system.network || {};
    const hardware = node.hardware || summary.hardware || {};
    const hostname = node.hostname || summary.hostname || nodeId;

    document.title = `${hostname} | HCC NOC`;
    setText("pageTitle", hostname);
    setText("nodeIdLabel", `Node: ${nodeId}`);
    setText("nodeTypeLabel", `Type: ${nodeTypeLabel(hardware)}`);
    setText("hostRoleValue", node.hostRole || snapshot.hostRole || "unknown");
    setText("cpuModelValue", (node.cpu && node.cpu.model) || "-");
    setText("cpuCoresValue", formatCpuTopology(node.cpu, summary.resources));
    setText("loadAvgValue", formatLoadLabel(system.cpu || summary.resources, node.platform || summary.platform));
    setText(
      "memoryDetailValue",
      `${formatBytes(memory.usedBytes || summary.resources?.memoryUsedBytes || 0)} / ${formatBytes(memory.totalBytes || summary.resources?.memoryTotalBytes || 0)} (${pct(memory.percent || summary.resources?.memoryPercent || 0)})`,
    );
    setText(
      "swapDetailValue",
      memory.swapTotalBytes || summary.resources?.swapTotalBytes
        ? `${formatBytes(memory.swapUsedBytes || summary.resources?.swapUsedBytes || 0)} / ${formatBytes(memory.swapTotalBytes || summary.resources?.swapTotalBytes || 0)} (${pct(memory.swapPercent || summary.resources?.swapPercent || 0)})`
        : "none configured",
    );
    setText("osLabel", `OS: ${osText(node)}`);
    setText("timeLabel", `Updated: ${new Date(detail.generatedAt).toLocaleString()}`);
    setStatusBadge(Boolean(summary.stale));

    setText("hostnameValue", hostname);
    setText("uptimeValue", formatUptime(node.uptimeSec || summary.uptimeSec || 0));
    setText("kernelValue", (node.os && node.os.kernel) || "-");
    setText("archValue", (node.os && node.os.arch) || "-");
    setText("ipsValue", (node.ips || summary.ips || []).join(" ") || "no address");
    setText("virtValue", hardware.virtualizationType || "unknown");

    const cpu = Number(system.cpuPercent || summary.resources?.cpuPercent || 0);
    const memPct = Number(memory.percent || summary.resources?.memoryPercent || 0);
    const cpuTopology = formatCpuTopology(node.cpu, summary.resources);
    const loadText = formatLoadLabel(system.cpu || summary.resources, node.platform || summary.platform);
    setGauge("kpiCpu", cpu, pct(cpu), `${cpuTopology} | ${loadText}`);
    setGauge(
      "kpiMem",
      memPct,
      pct(memPct),
      `${formatBytes(memory.usedBytes || summary.resources?.memoryUsedBytes || 0)} / ${formatBytes(memory.totalBytes || summary.resources?.memoryTotalBytes || 0)}`,
    );

    const storageTotals = paintStoragePanel(snapshot.storageDetail, snapshot.storage || []);
    const storagePct = Number(storageTotals.percent || summary.resources?.storagePercent || 0);
    setGauge("kpiStorage", storagePct, pct(storagePct));

    const netDown = Number(network.rxBytesPerSec || summary.resources?.networkRxBytesPerSec || 0);
    const netUp = Number(network.txBytesPerSec || summary.resources?.networkTxBytesPerSec || 0);
    const netRoot = document.getElementById("kpiNet");
    if (netRoot) {
      netRoot.querySelector(".noc-kpi-value").textContent = `${formatBytes(netDown)}/s`;
      netRoot.querySelector(".noc-kpi-sub").textContent = `up ${formatBytes(netUp)}/s`;
    }

    const sections = paintHostSections(snapshot);
    if (sections.services) {
      paintServices(snapshot.services || [], snapshot.capabilities || {});
    }
    if (sections.containers) {
      paintContainers(snapshot.containers || [], snapshot.capabilities || {});
    }
    paintHostActions(snapshot.capabilities || {});
    paintRemoteAccess(snapshot, summary, hostname);
    paintVMs(snapshot.workloads || {}, snapshot.capabilities || {});
    paintHistory(history.items || []);

    errorLabel.textContent = "";
    return Number(detail.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `Server detail fetch failed: ${err.message}`;
    setStatusBadge(true);
    return 30;
  }
}

async function loop() {
  await ensureAuth();
  initAppPage("devices");
  while (true) {
    const waitSec = await refreshServerDetail();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
