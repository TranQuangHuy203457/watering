const MAX_POINTS = 40;
let tempChart, humChart, soilChart;
let tempData = [], humData = [], soilData1 = [], soilData2 = [], soilData3 = [], labels = [];

function pushPoint(t, temp, hum, s1, s2, s3) {
  if (labels.length >= MAX_POINTS) {
    labels.shift(); tempData.shift(); humData.shift(); soilData1.shift(); soilData2.shift(); soilData3.shift();
  }
  labels.push(new Date(t).toLocaleTimeString());
  tempData.push(temp); humData.push(hum); soilData1.push(s1); soilData2.push(s2); soilData3.push(s3);
}

function createCharts() {
  if (typeof Chart === 'undefined') {
    console.error('Chart.js not loaded yet');
    return;
  }
  
  try {
    const ctxT = document.getElementById('tempChart').getContext('2d');
    tempChart = new Chart(ctxT, { type: 'line', data: { labels, datasets: [{ label: 'Air °C', data: tempData, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.08)', tension:0.3 }] }, options: { responsive:true, plugins:{legend:{display:false}} } });

    const ctxH = document.getElementById('humChart').getContext('2d');
    humChart = new Chart(ctxH, { type: 'line', data: { labels, datasets: [{ label: 'Humidity %', data: humData, borderColor: '#0ea5a0', backgroundColor: 'rgba(14,165,160,0.08)', tension:0.3 }] }, options: { responsive:true, plugins:{legend:{display:false}} } });

    const ctxS = document.getElementById('soilChart').getContext('2d');
    soilChart = new Chart(ctxS, { type: 'line', data: { labels, datasets: [
      { label: 'S1', data: soilData1, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.06)', tension:0.3 },
      { label: 'S2', data: soilData2, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.06)', tension:0.3 },
      { label: 'S3', data: soilData3, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.06)', tension:0.3 }
    ] }, options: { responsive:true, plugins:{legend:{display:true}} } });
    
    console.log('Charts created successfully');
  } catch (e) {
    console.error('Error creating charts:', e);
  }
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    // top cards
    document.getElementById('air').textContent = j.airTemp.toFixed(1) + 'C / ' + j.airHum.toFixed(0) + '%';
    document.getElementById('f3').textContent = j.forecast3Temp.toFixed(1) + 'C / ' + j.forecast3Hum.toFixed(0) + '%';
    document.getElementById('pump').textContent = j.pumpOn ? '🟢 ON' : '⚫ OFF';
    document.getElementById('light').textContent = j.light ? '💡 ON' : '⚫ OFF';
    // mode
    const modeMap = {0: 'NORMAL', 1: 'DEGRADED', 2: 'SAFE'};
    document.getElementById('mode').textContent = modeMap[j.mode] || (j.mode + '');
    // controls sync
    document.getElementById('pumpChk').checked = j.pumpOn ? true : false;
    document.getElementById('lightChk').checked = j.light ? true : false;

    // push data for charts
    const now = Date.now();
    pushPoint(now, parseFloat(j.airTemp), parseFloat(j.airHum), parseFloat(j.soil[0]), parseFloat(j.soil[1]), parseFloat(j.soil[2]));
    if (tempChart && humChart && soilChart) {
      tempChart.update(); 
      humChart.update(); 
      soilChart.update();
    }
  } catch (e) {
    console.error(e);
  }
}

async function applyControls() {
  const mode = document.querySelector('input[name="ctrlMode"]:checked').value;
  const isManual = (mode === 'manual');
  const pumpDur = parseInt(document.getElementById('pumpDur').value) || 0;
  const lightDur = parseInt(document.getElementById('lightDur').value) || 0;
  
  const body = {
    pump: document.getElementById('pumpChk').checked ? 1 : 0,
    light: document.getElementById('lightChk').checked ? 1 : 0,
    mode: isManual ? 'manual' : 'auto',
    durationPump: isManual ? pumpDur : 0,
    durationLight: isManual ? lightDur : 0
  };
  
  const statusEl = document.getElementById('statusMsg');
  try {
    const resp = await fetch('/api/control', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
    if (resp.ok) {
      statusEl.textContent = `✓ Applied: ${mode.toUpperCase()} mode, Pump ${body.pump ? 'ON' : 'OFF'}, Light ${body.light ? 'ON' : 'OFF'}`;
      statusEl.style.backgroundColor = '#d1fae5';
      statusEl.style.color = '#065f46';
      statusEl.style.display = 'block';
      setTimeout(() => { statusEl.style.display = 'none'; }, 3000);
    } else {
      throw new Error('Server error');
    }
  } catch (e) {
    console.error(e);
    statusEl.textContent = '✗ Error applying changes';
    statusEl.style.backgroundColor = '#fee2e2';
    statusEl.style.color = '#991b1b';
    statusEl.style.display = 'block';
  }
}

function updateControlsState() {
  const mode = document.querySelector('input[name="ctrlMode"]:checked').value;
  const isManual = (mode === 'manual');
  
  // Enable/disable controls based on mode
  document.getElementById('pumpChk').disabled = !isManual;
  document.getElementById('pumpDur').disabled = !isManual;
  document.getElementById('lightChk').disabled = !isManual;
  document.getElementById('lightDur').disabled = !isManual;
  
  // Visual feedback
  const pumpSection = document.getElementById('pumpChk').closest('div').parentElement;
  const lightSection = document.getElementById('lightChk').closest('div').parentElement;
  
  if (isManual) {
    pumpSection.style.opacity = '1';
    lightSection.style.opacity = '1';
  } else {
    pumpSection.style.opacity = '0.5';
    lightSection.style.opacity = '0.5';
  }
}

document.getElementById('applyBtn').addEventListener('click', applyControls);

// Add event listeners for mode radio buttons
document.querySelectorAll('input[name="ctrlMode"]').forEach(radio => {
  radio.addEventListener('change', updateControlsState);
});

// Wait for both DOM and Chart.js to be ready
function initializeApp() {
  if (typeof Chart === 'undefined') {
    console.log('Waiting for Chart.js...');
    setTimeout(initializeApp, 100);
    return;
  }
  
  console.log('Initializing charts...');
  createCharts();
  fetchStatus(); // Initial fetch
  setInterval(fetchStatus, 2000);
  updateControlsState(); // Initialize controls state
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp);
} else {
  initializeApp();
}
