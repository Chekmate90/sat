let availableOrbitPaths = [];
let currentSort = {
  key: "time_until_seconds",
  direction: "asc",
};

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

    /*Load newly generated results*/

    await loadConjunctions();
    await loadOrbits();

    status.textContent = `Analysis complete — ${result.events_found} conjunctions found.`;
  } catch (error) {
    console.error(error);

    status.textContent = "Analysis failed. Showing previous results.";

    /*Load cached results*/

    await loadConjunctions();
  } finally {
    button.disabled = false;

    button.textContent = "Refresh Analysis";
  }
}

/* ==================================================
        LOAD ORBITS
    ================================================== */

async function loadOrbits() {
  const chart = document.getElementById("orbit-chart");

  try {
    const response = await fetch("/orbits");

    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }

    const result = await response.json();
    availableOrbitPaths = result.orbit_paths;
    renderOrbitChart(availableOrbitPaths);
  } catch (error) {
    console.error("Failed to load orbit paths:", error);

    chart.innerHTML = `
      <div class="empty">
        Failed to load orbit visualization.
      </div>
    `;
  }
}

/* ==================================================
        RENDER ORBITS
    ================================================== */

function renderOrbitChart(orbitPaths) {
  const chart = document.getElementById("orbit-chart");

  if (!Array.isArray(orbitPaths) || orbitPaths.length === 0) {
    Plotly.purge(chart);

    chart.innerHTML = `
      <div class="empty">
        Run an analysis to load orbit paths.
      </div>
    `;

    return;
  }

  const traces = orbitPaths.map((orbit) => {
    return {
      type: "scatter",
      mode: "lines+markers",
      name: orbit.name,

      x: orbit.points.map((point) => point.x),
      y: orbit.points.map((point) => point.y),

      text: orbit.points.map((point) => {
        const time = new Date(point.time).toLocaleString();

        return `${orbit.name}<br>NORAD: ${orbit.norad_id}<br>${time}`;
      }),

      hovertemplate:
        "%{text}<br>X: %{x:.0f} km<br>Y: %{y:.0f} km<extra></extra>",

      line: {
        width: 2,
      },

      marker: {
        size: 4,
      },
    };
  });

  const earthRadius = 6378;

  const layout = {
    paper_bgcolor: "#120624",
    plot_bgcolor: "#120624",

    font: {
      color: "#d9f7f3",
    },

    margin: {
      left: 70,
      right: 30,
      top: 30,
      bottom: 70,
    },

    xaxis: {
      title: "X position (km)",
      gridcolor: "#3e4455",
      zerolinecolor: "#71b6ff",
      scaleanchor: "y",
      scaleratio: 1,
    },

    yaxis: {
      title: "Y position (km)",
      gridcolor: "#3e4455",
      zerolinecolor: "#71b6ff",
    },

    legend: {
      orientation: "h",
      y: -0.2,
    },

    shapes: [
      {
        type: "circle",
        xref: "x",
        yref: "y",
        x0: -earthRadius,
        y0: -earthRadius,
        x1: earthRadius,
        y1: earthRadius,
        fillcolor: "#235b8c",
        line: {
          color: "#71b6ff",
          width: 2,
        },
        layer: "below",
      },
    ],
  };

  const config = {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
  };

  Plotly.newPlot(chart, traces, layout, config);
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
    conjunctionData = result.conjunctions;
    const data = getSortedConjunctions();

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
        ARRANGES CONJUCTIONS
    ================================================== */

function sortConjunctions(key) {
  if (currentSort.key === key) {
    currentSort.direction = currentSort.direction === "asc" ? "desc" : "asc";
  } else {
    currentSort.key = key;
    currentSort.direction = "asc";
  }

  updateDashboard(getSortedConjunctions());
}

function getSortedConjunctions() {
  const direction = currentSort.direction === "asc" ? 1 : -1;
  const key = currentSort.key;

  return [...conjunctionData].sort((a, b) => {
    const valueA = a[key];
    const valueB = b[key];

    if (typeof valueA === "string") {
      return valueA.localeCompare(valueB) * direction;
    }

    return (valueA - valueB) * direction;
  });
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

    row.classList.add("conjunction-row");

    row.addEventListener("click", () => {
      selectConjunction(event, row);
    });

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
        SELECTION OF ROWS
    ================================================== */
function selectConjunction(event, selectedRow) {
  const selectedOrbits = availableOrbitPaths.filter((orbit) => {
    const noradId = String(orbit.norad_id);

    return (
      noradId === String(event.norad_a) || noradId === String(event.norad_b)
    );
  });

  document.querySelectorAll(".conjunction-row").forEach((row) => {
    row.classList.remove("selected");
  });

  selectedRow.classList.add("selected");

  renderOrbitChart(selectedOrbits);

  document.getElementById("status").textContent =
    `Showing ${event.object_a} and ${event.object_b} — closest distance: ${event.distance_km} km`;
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
loadOrbits();
