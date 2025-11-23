(() => {
  const socket = window._socSocket || (window.io && window.io());
  const tbody = document.getElementById("dashboard-logs-body");
  if (!socket || !tbody) return;

  socket.on("log:new", (logs) => {
    if (!Array.isArray(logs)) return;

    logs
      .slice()
      .reverse() // newest last in loop so it ends at top
      .forEach((l) => {
        const tr = document.createElement("tr");
        tr.className = "hover:bg-slate-800/70 transition-colors";
        tr.innerHTML = `
          <td class="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">
            ${new Date(l.timestamp).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}
          </td>
          <td class="px-3 py-2 text-xs uppercase tracking-wide text-slate-400 whitespace-nowrap">${l.source_type}</td>
          <td class="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">${l.host || ""}</td>
          <td class="px-3 py-2 text-xs whitespace-nowrap">${l.severity}</td>
          <td class="px-3 py-2 text-xs text-slate-200">
            <span title="${l.message}">${(l.message || "").slice(0, 120)}</span>
          </td>
        `;
        tbody.insertBefore(tr, tbody.firstChild);
        if (tbody.rows.length > 500) {
          tbody.deleteRow(tbody.rows.length - 1);
        }
      });
  });
})();

