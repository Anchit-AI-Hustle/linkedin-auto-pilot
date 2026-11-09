"""HD demo videos for the LinkedIn series: desktop browser + phone, frame-perfect smooth scrolling,
captions from each product, original music. Every frame is captured individually, so motion never lags.

Usage: python tools/videos/video.py 1 2 3   ->  tools/videos/build/out/demo-NN-<slug>.mp4
"""
import json, math, os, re, shutil, subprocess, sys, textwrap, asyncio, urllib.request, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from playwright.async_api import async_playwright
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
os.makedirs(ASSET_DIR, exist_ok=True)
FONTS = {"Poppins-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf",
         "Poppins-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf",
         "Poppins-Medium.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Medium.ttf"}
def fonts():
    for n, u in FONTS.items():
        p = os.path.join(ASSET_DIR, n)
        if not os.path.exists(p):
            local = "/usr/share/fonts/truetype/google-fonts/" + n
            try:
                urllib.request.urlretrieve(u, p)
            except Exception:
                if os.path.exists(local):
                    import shutil; shutil.copy(local, p)
                else: raise
def png(name, img): img.save(os.path.join(ASSET_DIR, name))
def visuals():
    W, H = 1300, 1620
    y, x = np.mgrid[0:H, 0:W]
    r = 8 + 46 * (1 - y / H) * x / W; g = 10 + 14 * (1 - y / H) * (1 - x / W); b = 22 + 80 * (1 - y / H) * (1 - x / W) + 20 * (y / H)
    png("bg_big.png", Image.fromarray(np.dstack([r, g, b]).clip(0, 255).astype("uint8")))
    glow = Image.new("RGBA", (900, 900), (0, 0, 0, 0)); ImageDraw.Draw(glow).ellipse([150, 150, 750, 750], fill=(139, 92, 246, 110))
    png("glow.png", glow.filter(ImageFilter.GaussianBlur(120)))
    # desktop browser window: 980x613 content area under a 44px title bar
    DW, DH, TB = 980, 613, 44
    win = Image.new("RGBA", (DW + 4, DH + TB + 4), (0, 0, 0, 0)); d = ImageDraw.Draw(win)
    d.rounded_rectangle([0, 0, DW + 3, DH + TB + 3], 18, fill=(30, 33, 44, 255), outline=(78, 82, 100, 255), width=2)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([18 + i * 22, 15, 32 + i * 22, 29], fill=c + (255,))
    d.rounded_rectangle([110, 10, DW - 60, 34], 10, fill=(18, 20, 28, 255))
    png("browser.png", win)
    m = Image.new("L", (DW, DH), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, DW - 1, DH - 1 + 20], 14, fill=255); png("mask_desk.png", m)
    sh = Image.new("RGBA", (DW + 120, DH + TB + 120), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([60, 70, DW + 60, DH + TB + 60], 24, fill=(0, 0, 0, 160))
    png("shadow_desk.png", sh.filter(ImageFilter.GaussianBlur(26)))
    # phone: 300x649 screen (390x844 ratio), bezel 12px
    PW, PH, B, R = 300, 649, 12, 34
    m = Image.new("L", (PW, PH), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, PW - 1, PH - 1], R, fill=255); png("mask_phone.png", m)
    bz = Image.new("RGBA", (PW + 2 * B, PH + 2 * B), (0, 0, 0, 0)); d = ImageDraw.Draw(bz)
    d.rounded_rectangle([0, 0, PW + 2 * B - 1, PH + 2 * B - 1], R + B, fill=(20, 22, 30, 255), outline=(84, 88, 108, 255), width=3)
    d.rounded_rectangle([B, B, B + PW - 1, B + PH - 1], R, fill=(0, 0, 0, 0))
    d.rounded_rectangle([(PW + 2 * B) // 2 - 44, B + 8, (PW + 2 * B) // 2 + 44, B + 26], 9, fill=(8, 8, 12, 255))
    png("phone.png", bz)
    sh = Image.new("RGBA", (PW + 140, PH + 140), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([60, 70, PW + 80, PH + 80], 50, fill=(0, 0, 0, 180))
    png("shadow_phone.png", sh.filter(ImageFilter.GaussianBlur(24)))
def wav(name, sig, sr=44100):
    st = np.stack([sig, np.roll(sig, int(0.01 * sr))], 1)
    w = wave.open(os.path.join(ASSET_DIR, name), "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(st, -1, 1) * 32767).astype("<i2").tobytes()); w.close()
def audio():
    sr = 44100; bpm = 96; beat = 60 / bpm; dur = 60
    t = np.arange(int(sr * dur)) / sr; out = np.zeros_like(t)
    note = lambda m: 440 * 2 ** ((m - 69) / 12)
    prog = [[57, 60, 64, 69], [53, 57, 60, 65], [48, 52, 55, 60], [55, 59, 62, 67]]
    bar = 4 * beat
    for i in range(int(dur / bar) + 1):
        s = int(i * bar * sr); e = min(len(t), int((i + 1) * bar * sr) + int(0.5 * sr))
        if s >= len(t): break
        tt = t[s:e] - t[s]; env = np.minimum(1, tt / 0.8) * np.exp(-np.maximum(0, tt - bar) / 0.4)
        for m in prog[i % 4]:
            f = note(m); out[s:e] += 0.05 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt + 0.3) + 0.15 * np.sin(2 * np.pi * f * 1.003 * tt))
        out[s:e] += 0.09 * env * np.sin(2 * np.pi * note(prog[i % 4][0] - 12) * tt)
        for k in range(8):
            a = int(s + k * beat / 2 * sr); b2 = min(len(t), a + int(0.35 * sr))
            if a >= len(t): break
            ta = t[a:b2] - t[a]; out[a:b2] += 0.035 * np.exp(-ta / 0.12) * np.sin(2 * np.pi * note(prog[i % 4][k % 4] + 12) * ta)
    for k in range(8, int(dur / beat)):
        a = int(k * beat * sr); b2 = min(len(t), a + int(0.25 * sr)); ta = t[a:b2] - t[a]
        out[a:b2] += 0.18 * np.exp(-ta / 0.07) * np.sin(2 * np.pi * (50 + 60 * np.exp(-ta / 0.03)) * ta)
    out *= np.minimum(1, np.minimum(t / 2.0, (dur - t) / 3.0)); out /= np.max(np.abs(out)) * 1.6
    wav("music.wav", out)
    tw = np.arange(int(sr * 0.9)) / sr; n = np.random.default_rng(1).standard_normal(len(tw)); f = np.cumsum(n); f -= np.convolve(f, np.ones(200) / 200, "same")
    f *= np.sin(np.pi * np.clip(tw / 0.9, 0, 1)) ** 2; wav("whoosh.wav", f / np.max(np.abs(f)) * 0.5)
    tk = np.arange(int(sr * 0.12)) / sr; wav("tick.wav", 0.5 * np.sin(2 * np.pi * 1800 * tk) * np.exp(-tk / 0.02))

HERE = os.path.dirname(os.path.abspath(__file__)); B = OUT_ASSETS = os.path.join(HERE, "build"); OUT = os.path.join(B, "out")
FPS, W, H = 30, 1080, 1350
DESK = dict(w=1440, h=900, dpr=1, mobile=False); PHONE = dict(w=390, h=844, dpr=2, mobile=True)
ACC = "0x8B5CF6"; BOLD = f"{B}/Poppins-Bold.ttf"; REG = f"{B}/Poppins-Regular.ttf"; MED = f"{B}/Poppins-Medium.ttf"
BAD = {"SIGN IN", "PROFILE", "LIFEENGINE", "RELEASES", "RELEASED", "CHAPTERS", "MORE PAGES", "PERFORMANCE", "EQUITY & DRAWDOWN", "START HERE", "ANCHITTANDON", "PLAY MUSIC"}
CAP_JS = """()=>{const vh=innerHeight;const hs=[...document.querySelectorAll('h1,h2,h3')].filter(e=>{const r=e.getBoundingClientRect();const t=(e.innerText||'').trim();return r.top>=30&&r.top<vh*0.7&&r.height>0&&t.length>5&&getComputedStyle(e).visibility!=='hidden';});return hs.length?hs[0].innerText.replace(/\\s+/g,' ').trim():'';}"""
def ease(x): return 0.5 - 0.5 * math.cos(math.pi * max(0, min(1, x)))
def default_actions(total):
    return [{"hold": 1.2}, {"scroll": total - 2.4}, {"hold": 1.2}]
async def capture(browser, url, spec, actions, frames_dir, want_caps):
    shutil.rmtree(frames_dir, ignore_errors=True); os.makedirs(frames_dir)
    ctx = await browser.new_context(viewport={"width": spec["w"], "height": spec["h"]}, device_scale_factor=spec["dpr"],
                                    is_mobile=spec["mobile"], has_touch=spec["mobile"], color_scheme="dark",
                                    permissions=["camera", "microphone"])
    pg = await ctx.new_page()
    try: await pg.goto(url, wait_until="networkidle", timeout=45000)
    except Exception: pass
    await pg.wait_for_timeout(2500)
    for label in ["No thanks", "Decline", "Reject", "Got it", "Accept", "OK"]:
        try:
            btn = pg.get_by_role("button", name=label, exact=True)
            if await btn.count(): await btn.first.click(timeout=800); break
        except Exception: pass
    await pg.add_style_tag(content="*{scroll-behavior:auto!important} ::-webkit-scrollbar{display:none}")
    await pg.wait_for_timeout(500)
    n = 0; caps = []; t = 0.0
    async def shot():
        nonlocal n
        await pg.screenshot(path=f"{frames_dir}/{n:05d}.jpg", type="jpeg", quality=92); n += 1
    async def hold(sec):
        nonlocal n, t
        k = round(sec * FPS)
        if k <= 0: return
        await shot(); src = f"{frames_dir}/{n-1:05d}.jpg"
        for _ in range(k - 1):
            shutil.copyfile(src, f"{frames_dir}/{n:05d}.jpg"); n += 1
        t += k / FPS
    for a in actions:
        if want_caps:
            try: caps.append((t, await pg.evaluate(CAP_JS)))
            except Exception: pass
        if "click" in a:
            try: await pg.get_by_text(a["click"], exact=True).first.click(timeout=3000)
            except Exception: pass
            k = round(a.get("hold", 3) * FPS); live = min(k, round(0.8 * FPS))
            for _ in range(live): await shot()                      # capture the transition frame by frame
            t += live / FPS; await hold((k - live) / FPS)
        elif "scroll" in a:
            sec = a["scroll"]; k = round(sec * FPS)
            start = await pg.evaluate("scrollY"); maxy = await pg.evaluate("document.documentElement.scrollHeight-innerHeight")
            end = min(maxy, start + spec["h"] * 3.2)
            for i in range(k):
                y = start + (end - start) * ease((i + 1) / k)
                await pg.evaluate(f"window.scrollTo(0,{y:.1f})")
                if want_caps and i % (FPS * 2) == FPS:
                    try: caps.append((t + i / FPS, await pg.evaluate(CAP_JS)))
                    except Exception: pass
                await shot()
            t += k / FPS
        else:
            await hold(a.get("hold", 1))
    await ctx.close()
    return n, caps
def wrap(s, width=34):
    s = re.sub(r"\s+", " ", s).strip(); lines = textwrap.wrap(s, width)
    if len(lines) > 2: lines = lines[:2]; lines[1] = lines[1].rstrip(" ,.;:") + "\u2026"
    return "\n".join(lines)
def tf(work, name, s):
    p = os.path.join(work, name + ".txt"); open(p, "w").write(s); return p
def compose(day, cfg, work, nframes, caps, out):
    INTRO, OUTRO, X = 3.0, 4.2, 0.6
    D = nframes / FPS if nframes else 6.0
    total = INTRO + D + OUTRO - 2 * X; t_demo = INTRO - X; t_out = INTRO + D - 2 * X
    f = {k: tf(work, k, v) for k, v in dict(label=cfg["label"], name=cfg["name"], hook="\n".join(textwrap.wrap(cfg["hook"], 34)[:2]),
                                             url=cfg["url_text"], cta="Try it free", sub="Desktop and mobile · live product").items()}
    # caption track (deduplicated, meaningful, wrapped), times relative to the demo segment
    track = []; last = None
    for tm, txt in caps:
        if not txt or txt.strip().upper() in BAD or len(txt.strip()) < 6: continue
        w = wrap(txt)
        if w != last: track.append((tm, w)); last = w
    if not track or track[0][0] > 0.5: track.insert(0, (0.0, wrap(cfg["caption"])))
    capf, ticks = [], []
    for i, (a, txt) in enumerate(track):
        b = track[i + 1][0] if i + 1 < len(track) else D
        if b - a < 1.0: continue
        p = tf(work, f"cap{i}", txt)
        capf.append(f"drawtext=fontfile={BOLD}:textfile={p}:fontcolor=white:fontsize=42:line_spacing=8:shadowcolor=black@0.45:shadowy=3:"
                    f"x=60:y='962+16*(1-min(1,(t-{a:.2f})/0.4))':enable='between(t,{a:.2f},{b:.2f})':alpha='min(1,(t-{a:.2f})/0.4)*min(1,({b:.2f}-t)/0.3)'")
        if i: ticks.append(t_demo + a)
    nsize = 104 if len(cfg["name"]) <= 12 else (80 if len(cfg["name"]) <= 18 else 62)
    move = "crop=1080:1350:x='110+100*sin(t/5)':y='135+120*cos(t/6.5)'"
    has = nframes > 0
    inp = ["-loop", "1", "-framerate", str(FPS), "-t", f"{INTRO}", "-i", f"{B}/bg_big.png",          # 0 intro bg
           "-loop", "1", "-framerate", str(FPS), "-t", f"{D:.3f}", "-i", f"{B}/bg_big.png",         # 1 demo bg
           "-loop", "1", "-framerate", str(FPS), "-t", f"{OUTRO}", "-i", f"{B}/bg_big.png",         # 2 outro bg
           "-loop", "1", "-framerate", str(FPS), "-t", f"{max(INTRO, D, OUTRO):.3f}", "-i", f"{B}/glow.png",  # 3
           "-i", f"{B}/music.wav", "-i", f"{B}/whoosh.wav", "-i", f"{B}/tick.wav"]                   # 4 5 6
    if has:
        inp += ["-framerate", str(FPS), "-i", f"{work}/desk/%05d.jpg", "-framerate", str(FPS), "-i", f"{work}/phone/%05d.jpg",  # 7 8
                "-i", f"{B}/browser.png", "-i", f"{B}/mask_desk.png", "-i", f"{B}/phone.png", "-i", f"{B}/mask_phone.png",       # 9 10 11 12
                "-i", f"{B}/shadow_desk.png", "-i", f"{B}/shadow_phone.png"]                                                      # 13 14
    fc = (f"[3:v]split=3[g1][g2][g3];"
          f"[0:v]{move}[bi];[bi][g1]overlay=x=-120:y=180:shortest=1,"
          f"drawtext=fontfile={BOLD}:textfile={f['label']}:fontcolor={ACC}:fontsize=36:x='90-50*(1-min(1,t/0.6))':y=470:alpha='min(1,t/0.5)',"
          f"drawbox=x=90:y=524:w='max(1,min(170,170*(t-0.2)/0.7))':h=8:color={ACC}:t=fill,"
          f"drawtext=fontfile={BOLD}:textfile={f['name']}:fontcolor=white:fontsize={nsize}:shadowcolor=black@0.4:shadowy=4:x=90:y='566+36*(1-min(1,max(0,(t-0.25)/0.6)))':alpha='min(1,max(0,(t-0.25)/0.6))',"
          f"drawtext=fontfile={REG}:textfile={f['hook']}:fontcolor=0xD1D5DB:fontsize=42:line_spacing=10:x=90:y={566+nsize+44}:alpha='min(1,max(0,(t-0.8)/0.6))'[intro];")
    if has:
        fc += (f"[7:v]scale=980:613:flags=lanczos,format=rgba[ds];[10:v]format=gray[dm];[ds][dm]alphamerge[dsr];"
               f"[8:v]scale=300:649:flags=lanczos,format=rgba[ps];[12:v]format=gray[pm];[ps][pm]alphamerge[psr];"
               f"[1:v]{move}[bd];[bd][g2]overlay=x=60:y=260:shortest=1[b1];"
               f"[b1][13:v]overlay=x=-12:y=190[b2];[b2][9:v]overlay=x=48:y=248[b3];[b3][dsr]overlay=x=50:y=294[b4];"
               f"[b4][14:v]overlay=x=650:y=575[b5];[b5][11:v]overlay=x=724:y=636[b6];[b6][psr]overlay=x=736:y=648,"
               f"drawtext=fontfile={BOLD}:textfile={f['label']}:fontcolor={ACC}:fontsize=26:x=60:y=60,"
               f"drawtext=fontfile={BOLD}:textfile={f['name']}:fontcolor=white:fontsize=58:x=60:y=104,"
               f"drawtext=fontfile={MED}:textfile={f['url']}:fontcolor=0x94A3B8:fontsize=26:x=60:y=184,"
               + ",".join(capf) + ("," if capf else "") +
               f"drawtext=fontfile={REG}:textfile={f['sub']}:fontcolor=0x94A3B8:fontsize=22:x=60:y=1262,"
               f"drawbox=x=60:y=1318:w=960:h=4:color=white@0.12:t=fill,drawbox=x=60:y=1318:w='max(1,960*t/{D:.3f})':h=4:color={ACC}:t=fill,trim=duration={D:.3f}[demo];")
    else:
        p = tf(work, "mid", wrap(cfg["caption"], 26))
        fc += (f"[1:v]{move}[bd];[bd][g2]overlay=x=90:y=200:shortest=1,"
               f"drawtext=fontfile={BOLD}:textfile={p}:fontcolor=white:fontsize=58:line_spacing=14:x=(w-tw)/2:y=(h-th)/2:alpha='min(1,t/0.6)'[demo];")
    fc += (f"[2:v]{move}[bo];[bo][g3]overlay=x=90:y=120:shortest=1,"
           f"drawtext=fontfile={BOLD}:textfile={f['cta']}:fontcolor={ACC}:fontsize=50:x=(w-tw)/2:y='520+20*(1-min(1,t/0.5))':alpha='min(1,t/0.5)',"
           f"drawtext=fontfile={BOLD}:textfile={f['url']}:fontcolor=white:fontsize={48 if len(cfg['url_text']) <= 30 else 36}:x=(w-tw)/2:y=610:alpha='min(1,max(0,(t-0.2)/0.5))',"
           f"drawtext=fontfile={BOLD}:text='Anchit Tandon':fontcolor=0x64748B:fontsize=32:x=(w-tw)/2:y=1180[outro];"
           f"[intro][demo]xfade=transition=smoothup:duration={X}:offset={t_demo:.3f}[a];[a][outro]xfade=transition=fade:duration={X}:offset={t_out:.3f},"
           f"vignette=angle=PI/6,format=yuv420p[v];"
           f"[4:a]atrim=0:{total:.3f},afade=t=in:d=1.2,afade=t=out:st={total-2.5:.3f}:d=2.5,volume=0.55[mus];"
           f"[5:a]asplit=2[w1][w2];[w1]adelay={int((t_demo-0.3)*1000)}|{int((t_demo-0.3)*1000)},volume=0.35[wa];[w2]adelay={int((t_out-0.3)*1000)}|{int((t_out-0.3)*1000)},volume=0.35[wb];")
    mix = ["[mus]", "[wa]", "[wb]"]
    if ticks:
        fc += f"[6:a]asplit={len(ticks)}" + "".join(f"[k{i}]" for i in range(len(ticks))) + ";"
        for i, tk in enumerate(ticks):
            fc += f"[k{i}]adelay={int(tk*1000)}|{int(tk*1000)},volume=0.16[kk{i}];"; mix.append(f"[kk{i}]")
    fc += "".join(mix) + f"amix=inputs={len(mix)}:normalize=0:duration=first,alimiter=limit=0.9[aout]"
    cmd = ["ffmpeg", "-y", "-v", "error", *inp, "-filter_complex", fc, "-map", "[v]", "-map", "[aout]", "-r", str(FPS),
           "-c:v", "libx264", "-preset", os.environ.get("X264_PRESET", "slow"), "-crf", os.environ.get("X264_CRF", "21"),
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise SystemExit(f"ffmpeg failed for {day}: {r.stderr[-1500:]}")
    return total
async def render(days):
    cfgs = json.load(open(os.path.join(HERE, "sites.json"))); os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--hide-scrollbars"])
        for day in days:
            cfg = cfgs[str(day)]; work = os.path.join(B, f"work{day}"); os.makedirs(work, exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "-", cfg["name"].lower()).strip("-"); out = os.path.join(OUT, f"demo-{day:02d}-{slug}.mp4")
            n, caps = 0, []
            if cfg.get("site"):
                actions = cfg.get("actions") or default_actions(float(os.environ.get("DEMO_SECONDS", "16")))
                n, caps = await capture(br, cfg["site"], DESK, actions, f"{work}/desk", True)
                n2, _ = await capture(br, cfg["site"], PHONE, actions, f"{work}/phone", False)
                n = min(n, n2)
                if cfg.get("captions"):
                    marks = [0.0]; tt = 0.0
                    for a in actions:
                        tt += a.get("hold", a.get("scroll", 0)) if "click" not in a else a.get("hold", 3)
                        marks.append(tt)
                    caps = list(zip(marks, cfg["captions"]))
            total = compose(day, cfg, work, n, caps, out)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "4.5", "-i", out, "-frames:v", "1", "-vf", "scale=540:675", "-q:v", "3", out[:-4] + ".jpg"], check=False)
            shutil.rmtree(work, ignore_errors=True)
            print(f"{out} {os.path.getsize(out)/1e6:.1f} MB {total:.1f}s", flush=True)
        await br.close()
if __name__ == "__main__":
    fonts(); visuals(); audio()
    asyncio.run(render([int(a) for a in sys.argv[1:]]))
