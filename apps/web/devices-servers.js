async function refreshDevicesServers() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    const fleetOverview = await fetchFleetOverview();
    const { servers } = paintDevicesSummary(fleetOverview);
    paintDeviceCards("serverCards", servers, "No servers reporting yet.");
    errorLabel.textContent = "";
    return Number(fleetOverview.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `Device fetch failed: ${err.message}`;
    return 30;
  }
}

startDevicesPage(refreshDevicesServers, "servers");
