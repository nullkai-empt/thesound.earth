let grid = [];
let gridMap = new Map();
const NUM_STREAMS = 2400;
const TRAIL_LEN = 10;
const EARTH_R = 1.004;
let streams = [];

function latLngToXYZ(lat, lng, r) {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lng + 180) * (Math.PI / 180);
  return [
    -r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta),
  ];
}

function lookupUV(lat, lng) {
  return gridMap.get(`${Math.round(lat)},${Math.round(lng)}`) || null;
}

function spawnStream() {
  const seed = grid[Math.floor(Math.random() * grid.length)];
  const trail = Array.from({ length: TRAIL_LEN }, () => ({ lat: seed.lat, lng: seed.lng }));
  return { trail, speed: seed.speed, life: 30 + Math.random() * 70 };
}

self.onmessage = (e) => {
  if (e.data.type === 'init') {
    grid = e.data.points;
    if (!grid.length) return;
    gridMap.clear();
    for (const p of grid) {
      gridMap.set(`${Math.round(p.lat)},${Math.round(p.lng)}`, p);
    }
    streams = Array.from({ length: NUM_STREAMS }, spawnStream);
    setInterval(step, 50);
  }
};

function step() {
  const vertsPerStream = (TRAIL_LEN - 1) * 2;
  const out = new Float32Array(NUM_STREAMS * vertsPerStream * 5);
  let ptr = 0;

  for (let i = 0; i < NUM_STREAMS; i++) {
    let st = streams[i];
    const head = st.trail[st.trail.length - 1];
    const local = lookupUV(head.lat, head.lng);
    st.life -= 1;

    if (!local || st.life <= 0 || head.lat > 85 || head.lat < -85) {
      st = spawnStream();
      streams[i] = st;
    } else {
      const nextLat = head.lat + local.v * 0.35;
      const nextLng = ((head.lng + local.u * 0.35 + 540) % 360) - 180;
      st.trail.shift();
      st.trail.push({ lat: nextLat, lng: nextLng });
      st.speed = local.speed;
    }

    for (let j = 0; j < TRAIL_LEN - 1; j++) {
      const a = st.trail[j];
      const b = st.trail[j + 1];
      const [ax, ay, az] = latLngToXYZ(a.lat, a.lng, EARTH_R);
      const [bx, by, bz] = latLngToXYZ(b.lat, b.lng, EARTH_R);
      const fadeA = j / (TRAIL_LEN - 1);
      const fadeB = (j + 1) / (TRAIL_LEN - 1);

      out[ptr++] = ax; out[ptr++] = ay; out[ptr++] = az; out[ptr++] = fadeA; out[ptr++] = st.speed;
      out[ptr++] = bx; out[ptr++] = by; out[ptr++] = bz; out[ptr++] = fadeB; out[ptr++] = st.speed;
    }
  }
  self.postMessage(out, [out.buffer]);
}