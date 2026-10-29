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
st_op = None
if st_user and st_pass:
    try:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request("https://www.space-track.org/ajaxauth/login",
                data=urllib.parse.urlencode({"identity": st_user, "password": st_pass}).encode(), headers=UA), timeout=40).read()
        q = (f"https://www.space-track.org/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{NORAD}"
             "/EPOCH/%3Enow-10/orderby/EPOCH%20asc/format/tle/emptyresult/show")
        add(parse_tle(get(q, 90, op)), "Space-Track gp_history")
        st_op = op
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


# ---------- 4) Official messages (Space-Track TIP / decay) ----------
official = load("official.json", {"tip": [], "decay": []})
if st_op:
    for cls, key in (("tip", "tip"), ("decay", "decay")):
        try:
            q = (f"https://www.space-track.org/basicspacedata/query/class/{cls}/NORAD_CAT_ID/{NORAD}"
                 "/orderby/MSG_EPOCH%20desc/limit/5/format/json/emptyresult/show")
            rows = json.loads(get(q, 60, st_op) or "[]")
            official[key] = [{k: r.get(k) for k in ("MSG_EPOCH", "INSERT_EPOCH", "DECAY_EPOCH", "WINDOW", "REV", "LAT", "LON", "INCL", "MSG_TYPE", "PRECEDENCE") if k in r} for r in rows][:5]
        except Exception as e:
            notes.append(f"Space-Track {cls} error: {e}")
official["checked"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
save("official.json", official, indent=1)

# ---------- 5) News / web mentions (Google News RSS, Reddit) + SatNOGS radio ----------
import re, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
news = load("news.json", {"items": []})
items = {i["url"]: i for i in news.get("items", []) if i.get("url")}
since = datetime.now(timezone.utc) - timedelta(days=14)
KEEP = re.compile(r"(napa[\s-]?1|นภา\s*1|46320)", re.I)
TOPIC = re.compile(r"(satellite|ดาวเทียม|re-?entry|reenter|decay|space|อวกาศ|กองทัพอากาศ|RTAF|ตก)", re.I)

def keep(title):
    return bool(KEEP.search(title or "")) and bool(TOPIC.search(title or ""))

for q, hl in (('"NAPA-1" satellite', "en-US&gl=US&ceid=US:en"), ("ดาวเทียม NAPA-1", "th&gl=TH&ceid=TH:th"), ("ดาวเทียม นภา 1 กองทัพอากาศ", "th&gl=TH&ceid=TH:th")):
    try:
        xml = get("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=" + hl, 40)
        for it in ET.fromstring(xml).iter("item"):
            title, link = it.findtext("title") or "", it.findtext("link") or ""
            try:
                dt = parsedate_to_datetime(it.findtext("pubDate"))
            except Exception:
                continue
            src = it.find("source")
            if dt >= since and keep(title) and link.startswith("https://"):
                items[link] = {"title": title[:200], "url": link, "source": (src.text if src is not None else "Google News")[:60],
                               "date": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": "ข่าว"}
    except Exception as e:
        notes.append(f"Google News error: {str(e)[:60]}")

try:
    j = json.loads(get("https://www.reddit.com/search.json?q=%22NAPA-1%22%20satellite&sort=new&t=month&limit=25", 40))
    for c in j.get("data", {}).get("children", []):
        d = c.get("data", {})
        dt = datetime.fromtimestamp(d.get("created_utc", 0), timezone.utc)
        title = d.get("title", "")
        if dt >= since and keep(title):
            url = "https://www.reddit.com" + d.get("permalink", "")
            items[url] = {"title": title[:200], "url": url, "source": "Reddit r/" + d.get("subreddit", ""),
                          "date": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": "เว็บบอร์ด"}
except Exception as e:
    notes.append(f"Reddit error: {str(e)[:60]}")

satnogs = news.get("satnogs", {})
try:
    obs = json.loads(get(f"https://network.satnogs.org/api/observations/?satellite__norad_cat_id={NORAD}&status=good&format=json", 40))
    if obs:
        satnogs = {"last_good": obs[0].get("end") or obs[0].get("start"), "station": obs[0].get("station_name"),
                   "url": f"https://network.satnogs.org/observations/{obs[0].get('id')}/"}
except Exception as e:
    notes.append(f"SatNOGS network error: {str(e)[:60]}")

fresh = [i for i in items.values() if i.get("date", "") >= since.strftime("%Y-%m-%dT%H:%M:%SZ")]
fresh.sort(key=lambda i: i["date"], reverse=True)
save("news.json", {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": fresh[:30], "satnogs": satnogs}, indent=1)

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
runlog = load("runlog.json", [])
runlog.append({"t": status["lastRun"], "new": new_sets})
save("runlog.json", runlog[-48:], indent=1)
print(status["note"])
