async function refreshDevicesAll() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    const fleetOverview = await fetchFleetOverview();
    const { servers, clients } = paintDevicesSummary(fleetOverview);
    paintDeviceCards("serverCards", servers.slice(0, 6), "No servers reporting yet.");
    paintDeviceCards("clientCards", clients.slice(0, 6), "No clients reporting yet.");
    errorLabel.textContent = "";
    return Number(fleetOverview.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `Device fetch failed: ${err.message}`;
    return 30;
  }
}

startDevicesPage(refreshDevicesAll, "all");
