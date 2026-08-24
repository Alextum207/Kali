/**
 * Renders the PDF report page. Reads the findings snapshot that
 * popup.js's ReportButton stored in chrome.storage.local right before
 * opening this tab, builds a simple table from it, and wires the "Als PDF
 * speichern" button to the browser's native print dialog — no PDF library,
 * no backend call, matches Kali's server-side report.html field set
 * (pattern_type / norm / impact / quote / screenshot) for consistency.
 */

/**
 * Escapes a string for safe insertion as HTML text content.
 * @param {string|null|undefined} str
 * @returns {string}
 */
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
}

(async () => {
    const { reportData } = await chrome.storage.local.get("reportData");
    const meta = document.getElementById("meta");
    const content = document.getElementById("content");

    if (!reportData || !reportData.items || reportData.items.length === 0) {
        meta.textContent = reportData ? reportData.url : "";
        content.innerHTML = "<p class=\"empty\">Keine Dark Patterns auf dieser Seite erkannt.</p>";
        return;
    }

    meta.textContent = `${reportData.url} — erstellt am ${new Date(reportData.generatedAt).toLocaleString("de-DE")}`;

    // Same full-tab screenshot (not cropped to the element) for every row —
    // shows the whole page context a finding was detected on, not just the
    // matched element in isolation.
    const thumbCell = reportData.screenshot
        ? `<img src="${reportData.screenshot}" alt="Screenshot der Seite" style="max-width:320px;border:1px solid #D8D5CA;border-radius:4px;">`
        : "–";

    // Full URL (with path/query string), not just the domain — every row
    // repeats it since one report covers one page, but the value itself
    // must be the complete address, not a shortened/truncated form.
    const urlCell = `<a href="${escapeHtml(reportData.url)}" target="_blank" rel="noopener">Link</a>`;

    const table = document.createElement("table");
    table.innerHTML = "<tr><th>Pattern-Typ</th><th>Norm</th><th>Auswirkung</th><th>Beispiel</th><th>Anzahl</th><th>URL</th><th>Screenshot</th></tr>";
    for (const item of reportData.items) {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${escapeHtml(item.pattern_type)}</td>
            <td>Möglicherweise rechtlich relevant — juristische Prüfung erforderlich</td>
            <td>${escapeHtml(item.impact)}</td>
            <td>${escapeHtml(item.quote)}</td>
            <td>${item.count}</td>
            <td>${urlCell}</td>
            <td>${thumbCell}</td>
        `;
        table.appendChild(row);
    }
    content.appendChild(table);
})();

document.getElementById("print-btn").addEventListener("click", () => window.print());
