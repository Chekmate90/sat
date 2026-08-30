// Live clock with selectable local and UTC timezones.
const localClockFormatter = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  timeZoneName: 'short',
});

const utcClockFormatter = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  timeZone: 'UTC',
  timeZoneName: 'short',
});

let clockMode = localStorage.getItem('clockMode') === 'utc' ? 'utc' : 'local';

function tickClock() {
  const el = document.getElementById('dashboard-clock');
  if (el) {
    const formatter = clockMode === 'utc' ? utcClockFormatter : localClockFormatter;
    el.textContent = formatter.format(new Date());
  }
}

function setClockMode(mode) {
  clockMode = mode === 'utc' ? 'utc' : 'local';
  localStorage.setItem('clockMode', clockMode);

  document.querySelectorAll('[data-clock-mode]').forEach((button) => {
    const isActive = button.dataset.clockMode === clockMode;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-pressed', String(isActive));
  });

  tickClock();
}

document.querySelectorAll('[data-clock-mode]').forEach((button) => {
  button.addEventListener('click', () => setClockMode(button.dataset.clockMode));
});

setClockMode(clockMode);
tickClock();
setInterval(tickClock, 1000);

// global state
let availableOrbitPaths = [];
let currentConjunctions = [];

// API CALLS (From your original code)

async function refreshAnalysis() {
  const status = document.getElementById("status");
  const button = document.getElementById("refresh-button");
  const objectsScanned = document.getElementById("objects-slider").value;
  const futureHours = document.getElementById("future-slider").value;

  status.className = 'status busy';
  status.textContent =
    `Scanning ${objectsScanned} objects ${futureHours} ${futureHours === "1" ? "hour" : "hours"} into the future...`;
  button.disabled = true;
  button.textContent = "Analyzing...";

  try {
    const params = new URLSearchParams({
      objects_scanned: objectsScanned,
      future_hours: futureHours,
    });
    const response = await fetch(`/refresh?${params}`, { method: "POST" });

    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }

    const result = await response.json();
    console.log("Refresh result:", result);

    await loadConjunctions();
    await loadOrbits();

    status.className = 'status ok';
    status.textContent = `Analysis complete — ${result.events_found} conjunctions found.`;
  } catch (error) {
    console.error(error);
    status.className = 'status';
    status.textContent = "Analysis failed. Showing previous results.";
    await loadConjunctions();
  } finally {
    button.disabled = false;
    button.textContent = "Refresh Analysis";
  }
}

function updateSliderValue(slider, output, formatter) {
  output.textContent = formatter(slider.value);
  const progress =
    ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
  slider.style.setProperty('--slider-progress', `${progress}%`);
}

const objectsSlider = document.getElementById('objects-slider');
const objectsSliderValue = document.getElementById('objects-slider-value');
const futureSlider = document.getElementById('future-slider');
const futureSliderValue = document.getElementById('future-slider-value');

objectsSlider.addEventListener('input', () => {
  updateSliderValue(objectsSlider, objectsSliderValue, (value) => value);
});

futureSlider.addEventListener('input', () => {
  updateSliderValue(
    futureSlider,
    futureSliderValue,
    (value) => `${value} ${value === '1' ? 'hour' : 'hours'}`,
  );
});

updateSliderValue(objectsSlider, objectsSliderValue, (value) => value);
updateSliderValue(
  futureSlider,
  futureSliderValue,
  (value) => `${value} ${value === '1' ? 'hour' : 'hours'}`,
);

async function loadOrbits() {
  const chart = document.getElementById("orbit-chart");
  try {
    const response = await fetch("/orbits");
    if (!response.ok) throw new Error(`HTTP error: ${response.status}`);

    const result = await response.json();
    availableOrbitPaths = result.orbit_paths;
    renderOrbitChart(availableOrbitPaths);
  } catch (error) {
    console.error("Failed to load orbit paths:", error);
    chart.innerHTML = `<div class="empty">Failed to load orbit visualization.</div>`;
  }
}

async function loadConjunctions() {
  try {
    const response = await fetch("/conjunctions");
    if (!response.ok) throw new Error(`HTTP error: ${response.status}`);

    const result = await response.json();
    currentConjunctions = result.conjunctions;

    // Update objects tracked
    document.getElementById("objects-count").textContent = result.objects_tracked;

    updateDashboard(currentConjunctions);
  } catch (error) {
    console.error(error);
    document.getElementById("status").textContent = "Failed to load conjunction data.";
  }
}

 //  UI UPDATES & RENDERING

function updateDashboard(data) {
  const table = document.getElementById("conjunctions");
  table.innerHTML = "";

  // Conjunction count
  document.getElementById("conjunction-count").textContent = data.length;

  // Risk counters
  let critical = 0, high = 0, medium = 0, low = 0;

  for (const event of data) {
    if (event.risk === "CRITICAL") critical++;
    else if (event.risk === "HIGH") high++;
    else if (event.risk === "MEDIUM") medium++;
    else if (event.risk === "LOW") low++;
  }

  // Update risk cards
  document.getElementById("critical-count").textContent = critical;
  document.getElementById("high-count").textContent = high;
  document.getElementById("medium-count").textContent = medium;
  document.getElementById("low-count").textContent = low;

  // Empty state
  if (data.length === 0) {
    table.innerHTML = `<tr><td colspan="6" class="empty">No conjunctions found.</td></tr>`;
    return;
  }

  // Create table rows matching the new UI style
  for (const event of data) {
    const row = document.createElement("tr");

    // Storing data attributes for the search filter
    row.setAttribute('data-a', event.object_a);
    row.setAttribute('data-b', event.object_b);

    row.innerHTML = `
      <td class="dim">${event.id}</td>
      <td>${event.object_a}</td>
      <td>${event.object_b}</td>
      <td>${event.distance_km} km</td>
      <td>${formatTime(event.time_until_seconds)}</td>
      <td><span class="risk-badge risk-${event.risk}">${event.risk}</span></td>
    `;
    table.appendChild(row);
  }
}

function renderOrbitChart(orbitPaths) {
  const chart = document.getElementById("orbit-chart");

  if (!Array.isArray(orbitPaths) || orbitPaths.length === 0) {
    Plotly.purge(chart);
    chart.innerHTML = `<div class="empty">Run an analysis to load orbit paths.</div>`;
    return;
  }

  // Mapping your backend data to the new transparent UI aesthetic
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
      hovertemplate: "%{text}<br>X: %{x:.0f} km<br>Y: %{y:.0f} km<extra></extra>",
      line: { width: 1.2, color: 'rgba(192, 132, 252, 0.6)' },
      marker: { size: 4, color: '#38bdf8' },
    };
  });

  const earthRadius = 6378;

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { family: 'JetBrains Mono, monospace', color: '#94a3b8', size: 11 },
    margin: { l: 50, r: 30, t: 20, b: 40 },
    xaxis: { title: 'X (km)', zeroline: false, gridcolor: 'rgba(139, 92, 246, 0.15)', scaleanchor: 'y' },
    yaxis: { title: 'Y (km)', zeroline: false, gridcolor: 'rgba(139, 92, 246, 0.15)' },
    showlegend: false,
    shapes: [
      {
        type: "circle", xref: "x", yref: "y",
        x0: -earthRadius, y0: -earthRadius, x1: earthRadius, y1: earthRadius,
        fillcolor: "rgba(14, 28, 64, 0.8)",
        line: { color: "#38bdf8", width: 1.5 },
        layer: "below",
      },
    ],
  };

  const config = { responsive: true, displayModeBar: false };
  Plotly.newPlot(chart, traces, layout, config);
}

//        HELPERS & UTILS

function formatTime(seconds) {
  if (seconds < 0) return "Passed";
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const years = Math.floor(days / 365);

  const remainingDays = days % 365;
  const remainingHours = hours % 24;
  const remainingMinutes = minutes % 60;

  if (years > 0) return `${years}y ${remainingDays}d`;
  if (days > 0) return `${days}d ${remainingHours}h`;
  if (hours > 0) return `${hours}h ${remainingMinutes}m`;
  return `${minutes}m`;
}

//        SEARCH FUNCTIONALITY (From new UI)

const searchInput = document.getElementById('object-search');
const clearBtn = document.getElementById('search-clear');

function applyFilter(query) {
  const q = query.trim().toLowerCase();
  const rows = document.querySelectorAll('#conjunctions tr[data-a]');
  let visibleCount = 0;

  if (!q) {
    rows.forEach(r => {
        r.style.display = '';
        r.style.background = '';
    });
    return;
  }

  rows.forEach(r => {
    const a = r.getAttribute('data-a').toLowerCase();
    const b = r.getAttribute('data-b').toLowerCase();
    const isMatch = a.includes(q) || b.includes(q);

    if (isMatch) {
      r.style.display = '';
      r.style.background = 'rgba(56, 189, 248, 0.15)';
      visibleCount++;
    } else {
      r.style.display = 'none';
      r.style.background = '';
    }
  });
}

searchInput.addEventListener('input', (e) => {
  const value = e.target.value;
  clearBtn.classList.toggle('visible', value.length > 0);
  applyFilter(value);
});

clearBtn.addEventListener('click', () => {
  searchInput.value = '';
  clearBtn.classList.remove('visible');
  applyFilter('');
  searchInput.focus();
});

//        INITIALIZE

loadConjunctions();
loadOrbits();
