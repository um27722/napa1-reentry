/* NAPA re-entry engine — Bates–Walker diffusive-equilibrium thermosphere + calibrated drag integration */
(function (root) {
  const MU = 398600.4418, RE = 6378.137, RP = 6356.77, KB = 1.380649e-23, AMU = 1.66053907e-27;
  const T120 = 380, Z0 = 120;
  // number densities at 120 km [m^-3], molecular mass [amu], thermal diffusion alpha
  const SPECIES = [
    { n: 3.0e17, m: 28.0134, a: 0 },   // N2
    { n: 4.0e16, m: 31.9988, a: 0 },   // O2
    { n: 7.6e16, m: 15.9994, a: 0 },   // O
    { n: 3.4e13, m: 4.0026, a: -0.38 } // He
  ];
  const G120 = 9.80665 * Math.pow(RP / (RP + Z0), 2);

  // Exospheric temperature from solar flux + geomagnetic activity (Jacchia-style, orbit-averaged)
  function exoTemp(f107, f81, kp) {
    const tc = 379 + 3.24 * f81 + 1.3 * (f107 - f81);
    return tc * 1.15 + 28 * kp + 0.03 * Math.exp(kp);
  }
  // Total mass density [kg/m^3] at altitude z [km] for exospheric temperature Tinf
  function density(z, Tinf) {
    if (z < Z0) z = Z0; // model floor; below 120 km the object is already re-entering
    const x = (Tinf - 800) / (750 + 1.722e-4 * (Tinf - 800) * (Tinf - 800));
    const s = 0.0291 * Math.exp(-x * x / 2); // km^-1
    const zeta = (z - Z0) * (RP + Z0) / (RP + z);
    const T = Tinf - (Tinf - T120) * Math.exp(-s * zeta);
    let rho = 0;
    for (const sp of SPECIES) {
      const mass = sp.m * AMU;
      const gamma = mass * G120 / (s * 1e-3 * KB * Tinf);
      const n = sp.n * Math.pow(T120 / T, 1 + sp.a + gamma) * Math.exp(-gamma * s * zeta);
      rho += n * mass;
    }
    return rho;
  }
  // da/dt for near-circular orbit, B = Cd*A/m [m^2/kg]
  // note: da/dt = -rho*B*sqrt(mu*a)  [SI] -> sqrt(mu*a) = v*a(m). result m/s -> km/day
  function dadtSI(a, B, Tinf) {
    const rho = density(a - RE, Tinf);
    const aM = a * 1e3, muSI = MU * 1e9;
    return -rho * B * Math.sqrt(muSI * aM) * 86400 / 1e3; // km/day
  }

  // Parse a TLE pair; returns elements we need
  function parseTLE(l1, l2, name) {
    const yy = parseInt(l1.substr(18, 2), 10), doy = parseFloat(l1.substr(20, 12));
    const year = yy < 57 ? 2000 + yy : 1900 + yy;
    const epoch = Date.UTC(year, 0, 1) + (doy - 1) * 86400000;
    const ndot2 = parseFloat(l1.substr(33, 10));
    const bs = l1.substr(53, 8).trim();
    const bstar = parseFloat((bs[0] === '-' ? '-' : '') + '0.' + bs.replace(/^[-+]/, '').replace(/[-+]\d$/, '')) * Math.pow(10, parseInt(bs.slice(-2), 10));
    const incl = parseFloat(l2.substr(8, 8)), raan = parseFloat(l2.substr(17, 8));
    const ecc = parseFloat('0.' + l2.substr(26, 7).trim());
    const n = parseFloat(l2.substr(52, 11));
    const norad = parseInt(l1.substr(2, 5), 10);
    // un-Kozai to Brouwer mean motion (as SGP4 does) for semi-major axis
    const xke = 60 / Math.sqrt(6378.135 ** 3 / 398600.8), j2 = 0.001082616;
    const no = n * 2 * Math.PI / 1440, cosi = Math.cos(incl * Math.PI / 180);
    const a1 = Math.pow(xke / no, 2 / 3), d1 = 0.75 * j2 * (3 * cosi * cosi - 1) / Math.pow(1 - ecc * ecc, 1.5);
    let del = d1 / (a1 * a1);
    const ao = a1 * (1 - del * (1 / 3 + del * (1 + 134 / 81 * del)));
    del = d1 / (ao * ao);
    const noB = no / (1 + del);
    const a = Math.pow(xke / noB, 2 / 3) * 6378.135;
    return { name: (name || '').replace(/^0\s+/, '').trim(), norad, l1, l2, epoch, ndot2, bstar, incl, raan, ecc, n, a,
      perigee: a * (1 - ecc) - RE, apogee: a * (1 + ecc) - RE, mean: a - RE };
  }
  // observed decay rate from TLE ndot term [km/day]
  function obsRateNdot(el) { return -(2 / 3) * el.a / el.n * (2 * el.ndot2); }

  // integrate a(t) until mean altitude <= stopAlt; spaceWx(tDays)->Tinf
  function integrate(a0, B, TinfFn, opts) {
    opts = opts || {};
    const stop = opts.stopAlt || 120, maxDays = opts.maxDays || 3650, keep = opts.keep;
    let a = a0, t = 0, uInt = 0; const path = keep ? [[0, a0 - RE]] : null;
    const nr = x => Math.pow(a0 / x, 1.5); // mean-motion ratio n(t)/n0 -> along-track phase integral
    while (a - RE > stop && t < maxDays) {
      const r = Math.abs(dadtSI(a, B, TinfFn(t)));
      // step: limit altitude change per step to ~0.5 km, and <= 1 day
      let h = Math.min(1, 0.5 / Math.max(r, 1e-9));
      h = Math.max(Math.min(h, maxDays - t), 1e-9);
      const f = x => dadtSI(x, B, TinfFn(t));
      const k1 = f(a), k2 = f(a + h / 2 * k1), k3 = f(a + h / 2 * k2), k4 = f(a + h * k3);
      const an = a + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4);
      if (an - RE <= stop) { // interpolate crossing
        const frac = (a - RE - stop) / (a - an);
        const aEnd = RE + stop; uInt += h * frac * 0.5 * (nr(a) + nr(aEnd));
        t += h * frac; a = aEnd; if (keep) path.push([t, stop]); break;
      }
      uInt += h * 0.5 * (nr(a) + nr(an));
      a = an; t += h; if (keep) path.push([t, a - RE]);
    }
    return { days: t, uInt, path, reached: a - RE <= stop + 1e-6 };
  }
  // find B so that model decay at a matches observed rate (km/day, negative)
  function calibrateB(a, rateObs, Tinf) { return rateObs / dadtSI(a, 1, Tinf); }

  // fit B to a history of {epoch, a} (ms) by minimizing squared error, log-space golden search
  // fit B to a history of {epoch, a} (ms). Tinf = number or function(epochMs) -> exospheric temperature
  // (time-varying solar flux matters: B fitted with constant T absorbs past flux changes)
  function fitHistory(hist, Tinf) {
    if (hist.length < 2) return null;
    const Tf = typeof Tinf === 'function' ? Tinf : () => Tinf;
    const t0 = hist[0].epoch, a0 = hist[0].a;
    const span = (hist[hist.length - 1].epoch - t0) / 86400000;
    if (span < 0.25) return null;
    const cost = lb => {
      const B = Math.exp(lb); let a = a0, t = 0, err = 0, i = 1;
      while (i < hist.length) {
        const ti = (hist[i].epoch - t0) / 86400000;
        while (t < ti - 1e-9) {
          const h = Math.min(0.05, ti - t), T = Tf(t0 + t * 864e5);
          const f = x => dadtSI(x, B, T);
          const k1 = f(a), k2 = f(a + h / 2 * k1), k3 = f(a + h / 2 * k2), k4 = f(a + h * k3);
          a += h / 6 * (k1 + 2 * k2 + 2 * k3 + k4); t += h;
          if (a - RE < 110) return 1e12;
        }
        const d = a - hist[i].a; err += d * d; i++;
      }
      return err;
    };
    let lo = Math.log(1e-4), hi = Math.log(1);
    const g = (Math.sqrt(5) - 1) / 2;
    let c = hi - g * (hi - lo), d = lo + g * (hi - lo), fc = cost(c), fd = cost(d);
    for (let k = 0; k < 50; k++) {
      if (fc < fd) { hi = d; d = c; fd = fc; c = hi - g * (hi - lo); fc = cost(c); }
      else { lo = c; c = d; fc = fd; d = lo + g * (hi - lo); fd = cost(d); }
    }
    const lb = (lo + hi) / 2, rms = Math.sqrt(cost(lb) / (hist.length - 1));
    return { B: Math.exp(lb), rms, n: hist.length, spanDays: span };
  }

  function randn(rng) { let u = 0, v = 0; while (u === 0) u = rng(); while (v === 0) v = rng(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  function mulberry(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

  /* Full forecast.
     el: latest parsed TLE; cfg: {f107, f81, kp, method:'ndot'|'history'|'bstar', hist:[{epoch,a}], sigmaRate, runs, stopAlt}
     Returns nominal + percentile window (ms timestamps). */
  function forecast(el, cfg) {
    const f107 = cfg.f107, f81 = cfg.f81, kp = cfg.kp;
    const Tnow = exoTemp(f107, f81, kp);
    let B, method = cfg.method, rateObs = obsRateNdot(el), sigB = cfg.sigmaRate || 0.15, fit = null;
    if (method === 'history') {
      fit = fitHistory(cfg.hist || [], cfg.TinfAt || Tnow);
      if (fit) { B = fit.B; sigB = Math.max(0.15, Math.min(0.4, fit.rms / Math.max(1e-3, Math.abs(el.a - cfg.hist[0].a)) + 0.1)); }
      else method = 'ndot';
    }
    if (method === 'bstar') { B = 2 * el.bstar / 0.1570; sigB = 0.3; }
    if (method === 'ndot') { B = calibrateB(el.a, rateObs, Tnow); }
    if (!(B > 0)) return { error: 'ค่าอัตราลดระดับจาก TLE ไม่เป็นบวก — ใช้ข้อมูลย้อนหลังหรือ B* แทน', B, rateObs };
    const stop = cfg.stopAlt || 120;
    const nominal = integrate(el.a, B, () => Tnow, { keep: true, stopAlt: stop });
    const runs = cfg.runs || 300, rng = mulberry(cfg.seed || 12345), out = [];
    // future space weather: F10.7 scatter grows with time; Kp scatter (storms) — sampled as constant per run
    for (let k = 0; k < runs; k++) {
      const bK = B * Math.exp(sigB * randn(rng));
      // persistence forecast: future daily flux scattered around today's value; 81-day mean nearly fixed
      const fD = Math.max(65, f107 * (1 + 0.12 * randn(rng)));
      const fF = Math.max(65, f81 * (1 + 0.04 * randn(rng)));
      // geomagnetic: mild scatter, plus ~7% chance of a storm-level Kp during the remaining life
      let kpS = Math.max(0, kp + 0.8 * randn(rng)); if (rng() < 0.07) kpS += 2 + 2 * rng(); kpS = Math.min(8, kpS);
      const Tf = exoTemp(fD, fF, kpS);
      { const r = integrate(el.a, bK, () => Tf, { stopAlt: stop }); out.push({ days: r.days, uInt: r.uInt }); }
    }
    out.sort((x, y) => x.days - y.days);
    const pct = p => out[Math.min(out.length - 1, Math.max(0, Math.round(p * (out.length - 1))))].days;
    const d = { p05: pct(0.05), p50: pct(0.5), p95: pct(0.95) };
    // band of altitude path for chart: run nominal with min/max B*density extremes
    return {
      method, B, sigB, fit, rateObs, Tinf: Tnow,
      rateModel: dadtSI(el.a, B, Tnow),
      nominalDays: nominal.days, nominalUInt: nominal.uInt, path: nominal.path, reached: nominal.reached,
      days: d,
      eta: el.epoch + nominal.days * 864e5,
      win: [el.epoch + d.p05 * 864e5, el.epoch + d.p50 * 864e5, el.epoch + d.p95 * 864e5],
      samples: out
    };
  }

  root.ReentryEngine = { MU, RE, exoTemp, density, dadtSI, parseTLE, obsRateNdot, integrate, calibrateB, fitHistory, forecast };
})(typeof window !== 'undefined' ? window : globalThis);
