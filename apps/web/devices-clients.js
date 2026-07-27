async function refreshDevicesClients() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    const fleetOverview = await fetchFleetOverview();
    const { clients } = paintDevicesSummary(fleetOverview);
    paintDeviceCards("clientCards", clients, "No clients reporting yet.");
    errorLabel.textContent = "";
    return Number(fleetOverview.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `Device fetch failed: ${err.message}`;
    return 30;
  }
}

startDevicesPage(refreshDevicesClients, "clients");
