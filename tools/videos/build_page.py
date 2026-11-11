"""Builds the public page served at anchit-tandon.com/linkedin-auto-pilot from posts.json, posted.json and the rendered videos."""
import datetime, glob, json, os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
SITE = os.path.join(ROOT, "linkedin-auto-pilot"); VIDEOS = os.path.join(SITE, "videos")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30)); SLOTS = (2, 8, 14, 20)
def next_slots(after, n):
    out = []; t = after.replace(minute=0, second=0, microsecond=0)
    while len(out) < n:
        t += datetime.timedelta(hours=1)
        if t.hour in SLOTS: out.append(t)
    return out
def main():
    posts = json.load(open(os.path.join(ROOT, "posts.json"), encoding="utf-8"))
    posted = json.load(open(os.path.join(ROOT, "posted.json"), encoding="utf-8"))
    last = max([datetime.datetime.fromisoformat(v["at"]) for v in posted.values() if v.get("at")] or [datetime.datetime.now(IST)])
    pending = [p for p in posts if str(p["day"]) not in posted]
    when = dict(zip([p["day"] for p in pending], next_slots(max(last, datetime.datetime.now(IST)), len(pending))))
    data = []
    for p in posts:
        x = {k: p[k] for k in ("day", "date", "title", "post", "first_comment")}
        v = posted.get(str(p["day"]))
        if v and v.get("skipped"):
            continue                                   # held back from the series on purpose
        if v:
            x["status"] = "Live"
            if v.get("urn"): x["live"] = "https://www.linkedin.com/feed/update/" + v["urn"] + "/"
            if v.get("at"): x["when"] = datetime.datetime.fromisoformat(v["at"]).astimezone(IST).strftime("%a %-d %b, %-I:%M %p IST")
        else:
            x["status"] = "Scheduled"; x["when"] = when[p["day"]].strftime("%a %-d %b, %-I:%M %p IST")
        vids = sorted(glob.glob(os.path.join(VIDEOS, f"demo-{p['day']:02d}-*.mp4")))
        if vids:
            name = os.path.basename(vids[0]); x["ad"] = "/linkedin-auto-pilot/videos/" + name; x["adname"] = name
            poster = name[:-4] + ".jpg"
            if os.path.exists(os.path.join(VIDEOS, poster)): x["poster"] = "/linkedin-auto-pilot/videos/" + poster
        data.append(x)
    tpl = open(os.path.join(HERE, "page_template.html"), encoding="utf-8").read()
    html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")).replace("__N__", str(len(data)))
    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(html)
    print(f"Wrote {SITE}/index.html: {len(data)} posts, {sum(1 for d in data if d.get('ad'))} videos, {sum(1 for d in data if d['status']=='Live')} live")
if __name__ == "__main__":
    main()
