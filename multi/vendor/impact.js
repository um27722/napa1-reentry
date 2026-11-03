/* Re-entry point geometry: SGP4 gives the orbit plane + phase now; the decay model gives the phase drift to re-entry */
(function (root) {
  const TWO_PI = 2 * Math.PI;
  const wrap = x => ((x % TWO_PI) + TWO_PI) % TWO_PI;
  function planeState(S, satrec, date) {
    const pv = S.propagate(satrec, date); if (!pv || !pv.position) return null;
    const r = pv.position, v = pv.velocity;
    const h = { x: r.y * v.z - r.z * v.y, y: r.z * v.x - r.x * v.z, z: r.x * v.y - r.y * v.x };
    const hm = Math.hypot(h.x, h.y, h.z);
    const inc = Math.acos(h.z / hm), raan = Math.atan2(h.x, -h.y);
    const u = Math.atan2(r.z / Math.sin(inc), r.x * Math.cos(raan) + r.y * Math.sin(raan));
    return { inc, raan, u: wrap(u) };
  }
  // Build a phase model anchored at the TLE epoch
  function buildPhaseModel(S, satrec, epochMs, nRevDay) {
    const t0 = new Date(epochMs), P = 1440 / nRevDay; // minutes
    const s0 = planeState(S, satrec, t0), s1 = planeState(S, satrec, new Date(epochMs + P * 6e4));
    const sD = planeState(S, satrec, new Date(epochMs + 864e5 * 0.5));
    if (!s0 || !s1 || !sD) return null;
    let du = s1.u - s0.u; if (du > Math.PI) du -= TWO_PI; if (du < -Math.PI) du += TWO_PI;
    const uDot = (TWO_PI + du) / P;                 // rad per minute (argument-of-latitude rate)
    let dR = sD.raan - s0.raan; if (dR > Math.PI) dR -= TWO_PI; if (dR < -Math.PI) dR += TWO_PI;
    const raanDot = dR / (0.5 * 1440);              // rad per minute
    return { epochMs, inc: s0.inc, raan0: s0.raan, u0: s0.u, uDot, raanDot };
  }
  // Sub-satellite point at time T (days after epoch) with phase integral uInt (days, Σ n/n0 dt)
  function pointAt(S, pm, Tdays, uIntDays) {
    const u = pm.u0 + pm.uDot * uIntDays * 1440, raan = pm.raan0 + pm.raanDot * Tdays * 1440;
    const ci = Math.cos(pm.inc), si = Math.sin(pm.inc), cu = Math.cos(u), su = Math.sin(u);
    const x = cu * Math.cos(raan) - su * ci * Math.sin(raan), y = cu * Math.sin(raan) + su * ci * Math.cos(raan), z = su * si;
    const date = new Date(pm.epochMs + Tdays * 864e5);
    const lat = Math.asin(z) * 180 / Math.PI;
    let lon = (Math.atan2(y, x) - S.gstime(date)) * 180 / Math.PI;
    lon = ((lon + 540) % 360) - 180;
    return { lat, lon, t: date.getTime(), ascending: cu > 0 };
  }
  // Ground track around a phase point (minutes before/after), assuming constant local rates
  function trackAround(S, pm, Tdays, uIntDays, nRatio, minBefore, minAfter, step) {
    const out = [];
    for (let m = -minBefore; m <= minAfter; m += step) {
      const dt = m / 1440;
      out.push(pointAt(S, pm, Tdays + dt, uIntDays + dt * nRatio));
    }
    return out;
  }
  root.ImpactGeo = { planeState, buildPhaseModel, pointAt, trackAround };
})(typeof window !== 'undefined' ? window : globalThis);
