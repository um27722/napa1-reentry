#!/usr/bin/env python3
"""
Re-entry Watch (หลายเป้าหมาย) — อัปเดตไฟล์ข้อมูลใน multi/data/  แยกจากระบบ NAPA-1 โดยสิ้นเชิง
  - รายชื่อเป้าหมาย : multi/data/targets.json
  - TLE ย้อนหลัง     : Space-Track gp_history (ST_USER / ST_PASS) + สำรอง CelesTrak GP
  - TIP / Decay      : Space-Track
  - SATCAT           : Space-Track (ชื่อ ขนาด RCS วันตก)
  - F10.7 / Kp       : NOAA SWPC
ใช้ Python standard library เท่านั้น
"""
import json, os, urllib.parse, urllib.request, http.cookiejar
from datetime import datetime, timedelta, timezone

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "multi", "data")
UA = {"User-Agent": "reentry-watch/1.0 (GitHub Actions)"}
notes = []
now = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")


def get(url, timeout=60, opener=None):
    req = urllib.request.Request(url, headers=UA)
    with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
        return r.read().decode("utf-8", "replace")


def load(name, default):
    try:
        with open(os.path.join(D, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(name, obj):
    with open(os.path.join(D, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def epoch_ms(l1):
    yy, doy = int(l1[18:20]), float(l1[20:32])
    ep = datetime(2000 + yy if yy < 57 else 1900 + yy, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)
    return int(ep.timestamp() * 1000)


def parse_tle(txt):
    lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
    out = []
    for i, l in enumerate(lines):
        if l.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 ") and len(l) >= 69:
            out.append((int(l[2:7]), l[:69], lines[i + 1][:69]))
    return out


targets = load("targets.json", {"targets": []}).get("targets", [])
ids = [int(t["norad"]) for t in targets if str(t.get("norad", "")).isdigit() or isinstance(t.get("norad"), int)]
sats = {n: load(f"sat_{n}.json", {"norad": n, "tle": [], "tip": [], "decay": [], "satcat": {}}) for n in ids}
for t in targets:
    if int(t["norad"]) in sats:
        sats[int(t["norad"])]["name"] = t.get("name")
        sats[int(t["norad"])]["note"] = t.get("note", "")
new_count = {n: 0 for n in ids}


def add(n, l1, l2, src):
    s = sats.get(n)
    if not s:
        return
    if any(x["l1"][18:32] == l1[18:32] for x in s["tle"]):
        return
    s["tle"].append({"l1": l1, "l2": l2, "epoch": epoch_ms(l1), "src": src})
    new_count[n] += 1


# ---------- Space-Track ----------
st_user, st_pass = os.environ.get("ST_USER"), os.environ.get("ST_PASS")
op = None
if st_user and st_pass and ids:
    try:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request("https://www.space-track.org/ajaxauth/login",
                data=urllib.parse.urlencode({"identity": st_user, "password": st_pass}).encode(), headers=UA), timeout=40).read()
    except Exception as e:
        op = None
        notes.append(f"Space-Track login error: {e}")
idlist = ",".join(str(n) for n in ids)
if op:
    try:
        days = 10 if any(len(s["tle"]) < 3 for s in sats.values()) else 3
        q = (f"https://www.space-track.org/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{idlist}"
             f"/EPOCH/%3Enow-{days}/orderby/EPOCH%20asc/format/tle/emptyresult/show")
        raw = get(q, 120, op)
        for n, l1, l2 in parse_tle(raw):
            add(n, l1, l2, "Space-Track gp_history")
        with open(os.path.join(D, "spacetrack_gp_history.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"# Space-Track gp_history {idlist}, fetched {iso(now)}\n# query: {q}\n" + raw)
    except Exception as e:
        notes.append(f"Space-Track gp_history error: {e}")
    for cls in ("tip", "decay", "satcat"):
        try:
            if cls == "satcat":
                q = f"https://www.space-track.org/basicspacedata/query/class/satcat/NORAD_CAT_ID/{idlist}/format/json/emptyresult/show"
            else:
                q = (f"https://www.space-track.org/basicspacedata/query/class/{cls}/NORAD_CAT_ID/{idlist}"
                     "/orderby/MSG_EPOCH%20desc/limit/100/format/json/emptyresult/show")
            rows = json.loads(get(q, 60, op) or "[]")
            for n in ids:
                mine = [r for r in rows if str(r.get("NORAD_CAT_ID") or r.get("OBJECT_NUMBER") or "") == str(n)]
                if cls == "satcat":
                    if mine:
                        r = mine[0]
                        sats[n]["satcat"] = {k: r.get(k) for k in ("SATNAME", "OBJECT_NAME", "INTLDES", "OBJECT_ID", "COUNTRY", "LAUNCH", "DECAY", "PERIOD", "INCLINATION", "APOGEE", "PERIGEE", "RCS_SIZE", "RCSVALUE", "OBJECT_TYPE") if k in r}
                else:
                    sats[n][cls] = mine[:15]
        except Exception as e:
            notes.append(f"Space-Track {cls} error: {e}")

# ---------- CelesTrak GP (backup / latest) ----------
for n in ids:
    try:
        txt = get(f"https://celestrak.org/NORAD/elements/gp.php?CATNR={n}&FORMAT=TLE", 40)
        for m, l1, l2 in parse_tle(txt):
            if m == n:
                add(n, l1, l2, "CelesTrak GP")
    except Exception as e:
        notes.append(f"CelesTrak {n} error: {str(e)[:60]}")

# ---------- NOAA space weather ----------
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
    cut = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    wx = {"f107": round(float(newest["flux"]), 1), "f81": round(float(mean["ninety_day_mean"]), 1), "kp": kp,
          "src": "NOAA SWPC " + newest["time_tag"][:10], "t": int(now.timestamp() * 1000),
          "series": {k: v for k, v in sorted(series.items()) if k >= cut}}
except Exception as e:
    notes.append(f"NOAA error: {e}")
save("wx.json", wx)

# ---------- save ----------
keep = int((now - timedelta(days=21)).timestamp() * 1000)
for n, s in sats.items():
    s["tle"] = sorted([x for x in s["tle"] if x["epoch"] >= keep] or s["tle"][-5:], key=lambda x: x["epoch"])
    s["checked"] = iso(now)
    save(f"sat_{n}.json", s)
status = load("status.json", {})
status.update({"lastRun": iso(now), "notes": notes, "new": {str(k): v for k, v in new_count.items()}, "ids": ids})
save("status.json", status)
print("new TLE:", new_count, "|", "; ".join(notes) or "ok")
