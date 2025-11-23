(() => {
  const socket = window._socSocket || (window.io && window.io());
  const serverBody = document.getElementById("server-logs-body");
  const clientBody = document.getElementById("client-logs-body");
  if (!socket) return;

  socket.on("log:new", (logs) => {
    if (!Array.isArray(logs)) return;

    logs
      .slice()
      .reverse()
      .forEach((l) => {
        const t = new Date(l.timestamp).toLocaleString("en-IN", {
          timeZone: "Asia/Kolkata",
        });
        const msg = (l.message || "").slice(0, 160);
        const tr = document.createElement("tr");
        tr.setAttribute("data-id", l.id);
        tr.className = "hover:bg-slate-800/70 transition-colors";

        if (l.source_type === "server" && serverBody) {
          tr.innerHTML = `
            <td class="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">${t}</td>
            <td class="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">${l.host || ""}</td>
            <td class="px-3 py-2 text-xs text-slate-400 whitespace-nowrap">${l.file_path || ""}</td>
            <td class="px-3 py-2 text-xs whitespace-nowrap">${l.severity}</td>
            <td class="px-3 py-2 text-xs text-slate-200" title="${l.message}">${msg}</td>
          `;
          serverBody.insertBefore(tr, serverBody.firstChild);
          if (serverBody.rows.length > 300) {
            serverBody.deleteRow(serverBody.rows.length - 1);
          }
        } else if (l.source_type === "client" && clientBody) {
          tr.innerHTML = `
            <td class="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">${t}</td>
            <td class="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">${l.host || ""}</td>
            <td class="px-3 py-2 text-xs whitespace-nowrap">${l.severity}</td>
            <td class="px-3 py-2 text-xs text-slate-200" title="${l.message}">${msg}</td>
          `;
          clientBody.insertBefore(tr, clientBody.firstChild);
          if (clientBody.rows.length > 300) {
            clientBody.deleteRow(clientBody.rows.length - 1);
          }
        }
      });
  });
})();
