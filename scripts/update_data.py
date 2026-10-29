#!/usr/bin/env python3
"""
อัปเดตไฟล์ข้อมูลของ NAPA-1 Re-entry Monitor (data/*.json) — รันโดย GitHub Actions ทุก 2 ชม.

แหล่งข้อมูล
  - TLE ล่าสุด : CelesTrak GP  (สำรอง: SatNOGS DB ซึ่งมาจาก Space-Track)
  - TLE ย้อนหลัง: Space-Track gp_history 10 วัน (ถ้าตั้ง secrets ST_USER / ST_PASS ไว้)
  - F10.7, Kp   : NOAA SWPC
  - วันตกทางการ : CelesTrak SATCAT (DECAY_DATE)
ใช้แค่ Python standard library
"""
import json, os, sys, time, urllib.parse, urllib.request, http.cookiejar
from datetime import datetime, timedelta, timezone

NORAD = int(os.environ.get("NORAD", "46320"))
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
UA = {"User-Agent": "napa-reentry-monitor/1.0 (GitHub Actions)"}
notes = []


def get(url, timeout=40, opener=None):
    req = urllib.request.Request(url, headers=UA)
    with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
        return r.read().decode("utf-8", "replace")


def load(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(name, obj, **kw):
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)


def epoch_ms(l1):
    yy, doy = int(l1[18:20]), float(l1[20:32])
    ep = datetime(2000 + yy if yy < 57 else 1900 + yy, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)
    return int(ep.timestamp() * 1000)


def parse_tle(txt):
    lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
    out = []
    for i, l in enumerate(lines):
        if l.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 ") and len(l) >= 69:
            if int(l[2:7]) == NORAD:
                out.append((l[:69], lines[i + 1][:69]))
    return out


# ---------- 1) TLE ----------
tle = load("tle.json", [])
have = {t["l1"][18:32] for t in tle if t.get("l1")}
new_sets = []

def add(pairs, source):
    for l1, l2 in pairs:
        key = l1[18:32]
        if key in have:
            continue
        have.add(key)
        tle.append({"norad": NORAD, "epoch": epoch_ms(l1), "l1": l1, "l2": l2, "source": source})
        new_sets.append(key)

try:
    txt = get(f"https://celestrak.org/NORAD/elements/gp.php?CATNR={NORAD}&FORMAT=TLE")
    pairs = parse_tle(txt)
    if pairs:
        add(pairs, "CelesTrak GP")
    elif "No GP data" in txt:
        notes.append("CelesTrak: No GP data (อาจตกแล้ว)")
except Exception as e:
    notes.append(f"CelesTrak error: {e}")
    try:
        j = json.loads(get(f"https://db.satnogs.org/api/tle/?norad_cat_id={NORAD}&format=json"))
        if j:
            add(parse_tle("\n".join([j[0]["tle1"], j[0]["tle2"]])), "SatNOGS DB (Space-Track)")
    except Exception as e2:
        notes.append(f"SatNOGS error: {e2}")

st_user, st_pass = os.environ.get("ST_USER"), os.environ.get("ST_PASS")
if st_user and st_pass:
    try:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request("https://www.space-track.org/ajaxauth/login",
                data=urllib.parse.urlencode({"identity": st_user, "password": st_pass}).encode(), headers=UA), timeout=40).read()
        q = (f"https://www.space-track.org/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{NORAD}"
             "/EPOCH/%3Enow-10/orderby/EPOCH%20asc/format/tle/emptyresult/show")
        add(parse_tle(get(q, 90, op)), "Space-Track gp_history")
    except Exception as e:
        notes.append(f"Space-Track error: {e}")

tle.sort(key=lambda t: t["epoch"])
save("tle.json", tle, indent=1)

# ---------- 2) Space weather ----------
wx = load("wx.json", {"series": {}})
try:
    flux = json.loads(get("https://services.swpc.noaa.gov/json/f107_cm_flux.json"))
    flux.sort(key=lambda x: x["time_tag"])
    series = wx.get("series") or {}
    for x in flux:
        if x["time_tag"].endswith("T20:00:00") and x.get("flux") is not None:
            m = x.get("ninety_day_mean")
            series[x["time_tag"][:10]] = [round(float(x["flux"]), 1), round(float(m), 1) if m is not None else None]
    newest = [x for x in flux if x.get("flux") is not None][-1]
    mean = [x for x in flux if x.get("ninety_day_mean") is not None][-1]
    kp = wx.get("kp", 2)
    try:
        k = json.loads(get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"))
        vals = [float(r[1]) for r in k[1:]] if isinstance(k[0], list) else [float(r.get("Kp", r.get("kp_index"))) for r in k]
        kp = round(sum(vals[-8:]) / len(vals[-8:]), 1)
    except Exception as e:
        notes.append(f"Kp error: {e}")
    wx = {"f107": round(float(newest["flux"]), 1), "f81": round(float(mean["ninety_day_mean"]), 1), "kp": kp,
          "src": "NOAA SWPC " + newest["time_tag"][:10], "t": int(time.time() * 1000), "series": dict(sorted(series.items()))}
    save("wx.json", wx)
except Exception as e:
    notes.append(f"NOAA error: {e}")

# ---------- 3) Official decay date ----------
status = load("status.json", {})
try:
    rec = json.loads(get(f"https://celestrak.org/satcat/records.php?CATNR={NORAD}&FORMAT=JSON"))
    if rec and rec[0].get("DECAY_DATE"):
        status["decay_date"] = rec[0]["DECAY_DATE"]
except Exception as e:
    notes.append(f"SATCAT error: {e}")

status.update({"lastRun": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "note": (f"new TLE: {', '.join(new_sets)}" if new_sets else "no new TLE") + ("; " + "; ".join(notes) if notes else "")})
save("status.json", status, indent=1)
print(status["note"])
