async function refreshAnalysis() {
    const status = document.getElementById("status");

    const button = document.getElementById("refresh-button");

    status.textContent = "Running orbital conjunction analysis...";

    button.disabled = true;

    button.textContent = "Analyzing...";

    try {
        const response = await fetch("/refresh", {
        method: "POST",
        });

        if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();

        console.log("Refresh result:", result);

        /*
        * Load newly generated results
        */

        await loadConjunctions();

        status.textContent = `Analysis complete — ${result.events_found} conjunctions found.`;
    } catch (error) {
        console.error(error);

        status.textContent = "Analysis failed. Showing previous results.";

        /*
        * Load cached results
        */

        await loadConjunctions();
    } finally {
        button.disabled = false;

        button.textContent = "Refresh Analysis";
    }
    }

    /* ==================================================
        LOAD CONJUNCTIONS
        ONLY READS CACHED RESULTS
    ================================================== */

    async function loadConjunctions() {
    try {
        const response = await fetch("/conjunctions");

        if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();

        // Get the actual conjunction array
        const data = result.conjunctions;

        // Update objects tracked
        document.getElementById("objects-count").textContent =
        result.objects_tracked;

        // Update dashboard
        updateDashboard(data);

        document.getElementById("status").textContent =
        `${data.length} conjunctions found`;
    } catch (error) {
        console.error(error);

        document.getElementById("status").textContent =
        "Failed to load conjunction data.";
    }
    }

    /* ==================================================
        UPDATE DASHBOARD
    ================================================== */

    function updateDashboard(data) {
    const table = document.getElementById("conjunctions");

    table.innerHTML = "";

    /*
        * Conjunction count
        */

    document.getElementById("conjunction-count").textContent = data.length;

    /*
        * Risk counters
        */

    let critical = 0;

    let high = 0;

    let medium = 0;

    let low = 0;

    for (const event of data) {
        if (event.risk === "CRITICAL") {
        critical++;
        } else if (event.risk === "HIGH") {
        high++;
        } else if (event.risk === "MEDIUM") {
        medium++;
        } else if (event.risk === "LOW") {
        low++;
        }
    }

    /*
        * Update risk cards
        */

    document.getElementById("critical-count").textContent = critical;

    document.getElementById("high-count").textContent = high;

    document.getElementById("medium-count").textContent = medium;

    document.getElementById("low-count").textContent = low;

    /*
        * Empty state
        */

    if (data.length === 0) {
        table.innerHTML = `

                <tr>

                    <td
                        colspan="6"
                        class="empty"
                    >
                        No conjunctions found.
                    </td>

                </tr>

            `;

        return;
    }

    /*
        * Create table rows
        */

    for (const event of data) {
        const row = document.createElement("tr");

        const riskClass = getRiskClass(event.risk);

        row.innerHTML = `
                <td>
                    ${event.id}
                </td>
                <td>
                    ${event.object_a}
                </td>
                <td>
                    ${event.object_b}
                </td>
                <td>
                    ${event.distance_km} km
                </td>
                <td>
                    ${formatTime(event.time_until_seconds)}
                </td>
                <td class="risk ${riskClass}">
                    ${event.risk}
                </td>
            `;
        table.appendChild(row);
    }
    }

    /* ==================================================
        FORMAT TIME
    ================================================== */

    function formatTime(seconds) {
    if (seconds < 0) {
        return "Passed";
    }

    const minutes = Math.floor(seconds / 60);

    const hours = Math.floor(minutes / 60);

    const days = Math.floor(hours / 24);

    const years = Math.floor(days / 365);

    const remainingDays = days % 365;

    const remainingHours = hours % 24;

    const remainingMinutes = minutes % 60;

    /*Years*/
    if (years > 0) {
        return `${years}y ${remainingDays}d`;
    }

    /*Days*/
    if (days > 0) {
        return `${days}d ${remainingHours}h`;
    }

    /*Hours*/
    if (hours > 0) {
        return `${hours}h ${remainingMinutes}m`;
    }

    /* Minutes*/
    return `${minutes}m`;
    }

    /* ==================================================
        RISK CSS CLASS
    ================================================== */

    function getRiskClass(risk) {
    switch (risk) {
        case "CRITICAL":
        return "risk-critical";

        case "HIGH":
        return "risk-high";

        case "MEDIUM":
        return "risk-medium";

        case "LOW":
        return "risk-low";

        case "SAFE":
        return "risk-safe";

        default:
        return "";
    }
    }

    /* ==================================================
        LOAD CACHED RESULTS ON PAGE OPEN
    ================================================== */

    loadConjunctions();