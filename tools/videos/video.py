"""HD demo videos for the LinkedIn series: desktop browser + phone, frame-perfect smooth scrolling,
captions from each product, original music. Every frame is captured individually, so motion never lags.

Usage: python tools/videos/video.py 1 2 3   ->  tools/videos/build/out/demo-NN-<slug>.mp4
"""
import json, math, os, re, shutil, subprocess, sys, textwrap, asyncio, urllib.request, wave
from urllib.parse import urljoin, urlparse
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from playwright.async_api import async_playwright
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
os.makedirs(ASSET_DIR, exist_ok=True)
FONT_NAMES = ("Poppins-Bold.ttf", "Poppins-Regular.ttf", "Poppins-Medium.ttf")
FONT_SOURCES = ("https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/poppins/{}",          # CDN first: GitHub raw rate-limits CI runners
                "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/{}",
                "https://github.com/google/fonts/raw/main/ofl/poppins/{}")
FALLBACK = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
def fonts():
    """Poppins from the first source that answers (with retries); never fail a render over a font."""
    import time as _t
    for n in FONT_NAMES:
        p = os.path.join(ASSET_DIR, n)
        if os.path.exists(p) and os.path.getsize(p) > 10000: continue
        got = False
        for attempt in range(3):
            for src in FONT_SOURCES:
                try:
                    req = urllib.request.Request(src.format(n), headers={"User-Agent": "linkedin-auto-pilot-video"})
                    data = urllib.request.urlopen(req, timeout=30).read()
                    if len(data) > 10000 and data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                        open(p, "wb").write(data); got = True; break
                except Exception as err:
                    print(f"  font {n} from {src.split('/')[2]}: {err}", flush=True)
            if got: break
            _t.sleep(5 * (attempt + 1))
        if not got:
            local = "/usr/share/fonts/truetype/google-fonts/" + n
            fb = local if os.path.exists(local) else next((f for f in FALLBACK if os.path.exists(f) and ("Bold" in f) == ("Bold" in n)), None)
            if not fb: raise SystemExit(f"No font available for {n}")
            shutil.copy(fb, p); print(f"  font {n}: using {os.path.basename(fb)} instead", flush=True)
def png(name, img): img.save(os.path.join(ASSET_DIR, name))
def visuals():
    BW, BH = q(1300), q(1620)
    y, x = np.mgrid[0:BH, 0:BW]
    r = 8 + 46 * (1 - y / BH) * x / BW; g = 10 + 14 * (1 - y / BH) * (1 - x / BW); b = 22 + 80 * (1 - y / BH) * (1 - x / BW) + 20 * (y / BH)
    png("bg_big.png", Image.fromarray(np.dstack([r, g, b]).clip(0, 255).astype("uint8")))
    glow = Image.new("RGBA", (q(900), q(900)), (0, 0, 0, 0)); ImageDraw.Draw(glow).ellipse([q(150), q(150), q(750), q(750)], fill=(139, 92, 246, 110))
    png("glow.png", glow.filter(ImageFilter.GaussianBlur(q(120))))
    DW, DH, TB = q(980), q(613), q(44)
    win = Image.new("RGBA", (DW + q(4), DH + TB + q(4)), (0, 0, 0, 0)); d = ImageDraw.Draw(win)
    d.rounded_rectangle([0, 0, DW + q(3), DH + TB + q(3)], q(18), fill=(30, 33, 44, 255), outline=(78, 82, 100, 255), width=max(2, q(2)))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([q(18 + i * 22), q(15), q(32 + i * 22), q(29)], fill=c + (255,))
    d.rounded_rectangle([q(110), q(10), DW - q(60), q(34)], q(10), fill=(18, 20, 28, 255))
    png("browser.png", win)
    m = Image.new("L", (DW, DH), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, DW - 1, DH - 1 + q(20)], q(14), fill=255); png("mask_desk.png", m)
    sh = Image.new("RGBA", (DW + q(120), DH + TB + q(120)), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([q(60), q(70), DW + q(60), DH + TB + q(60)], q(24), fill=(0, 0, 0, 160))
    png("shadow_desk.png", sh.filter(ImageFilter.GaussianBlur(q(26))))
    PW, PH, Bz, R = q(300), q(649), q(12), q(34)
    m = Image.new("L", (PW, PH), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, PW - 1, PH - 1], R, fill=255); png("mask_phone.png", m)
    bz = Image.new("RGBA", (PW + 2 * Bz, PH + 2 * Bz), (0, 0, 0, 0)); d = ImageDraw.Draw(bz)
    d.rounded_rectangle([0, 0, PW + 2 * Bz - 1, PH + 2 * Bz - 1], R + Bz, fill=(20, 22, 30, 255), outline=(84, 88, 108, 255), width=max(3, q(3)))
    d.rounded_rectangle([Bz, Bz, Bz + PW - 1, Bz + PH - 1], R, fill=(0, 0, 0, 0))
    d.rounded_rectangle([(PW + 2 * Bz) // 2 - q(44), Bz + q(8), (PW + 2 * Bz) // 2 + q(44), Bz + q(26)], q(9), fill=(8, 8, 12, 255))
    png("phone.png", bz)
    sh = Image.new("RGBA", (PW + q(140), PH + q(140)), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([q(60), q(70), PW + q(80), PH + q(80)], q(50), fill=(0, 0, 0, 180))
    png("shadow_phone.png", sh.filter(ImageFilter.GaussianBlur(q(24))))
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
FPS = 30
S = float(os.environ.get("VIDEO_SCALE", "1.6"))          # 1.6 -> 1728x2160 master (2160p), downscaled copy for the web
W, H = round(1080 * S), round(1350 * S)
def q(n): return int(round(n * S))
DESK = dict(w=1440, h=900, dpr=2, mobile=False); PHONE = dict(w=390, h=844, dpr=2, mobile=True)
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
            clicked = False
            for loc in (pg.get_by_role("button", name=a["click"]), pg.get_by_role("link", name=a["click"]), pg.get_by_text(a["click"], exact=False)):
                try:
                    if await loc.count():
                        await loc.first.click(timeout=3000); clicked = True; break
                except Exception: pass
            if not clicked: print(f"  click not found: {a['click']} ({spec['w']}px)", flush=True)
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
def wrap(s, width=22):   # fits left of the phone frame at every caption size
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
        if not txt or txt.strip().upper() in BAD or len(txt.strip()) < 3: continue
        w = wrap(txt)
        if w != last: track.append((tm, w)); last = w
    if not track or track[0][0] > 0.5: track.insert(0, (0.0, wrap(cfg["caption"])))
    capf, ticks = [], []
    for i, (a, txt) in enumerate(track):
        b = track[i + 1][0] if i + 1 < len(track) else D
        if b - a < 1.0: continue
        for j, line in enumerate(txt.split("\n")):
            p = tf(work, f"cap{i}_{j}", line)
            capf.append(f"drawtext=fontfile={BOLD}:textfile={p}:fontcolor=white:fontsize={q(42)}:shadowcolor=black@0.45:shadowy={q(3)}:"
                        f"x={q(60)}:y='{q(962 + j * 56)}+{q(16)}*(1-min(1,(t-{a:.2f})/0.4))':enable='between(t,{a:.2f},{b:.2f})':alpha='min(1,(t-{a:.2f})/0.4)*min(1,({b:.2f}-t)/0.3)'")
        if i: ticks.append(t_demo + a)
    nsize = q(104 if len(cfg["name"]) <= 12 else (80 if len(cfg["name"]) <= 18 else 62))
    move = f"crop={W}:{H}:x='{q(110)}+{q(100)}*sin(t/5)':y='{q(135)}+{q(120)}*cos(t/6.5)'"
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
          f"[0:v]{move}[bi];[bi][g1]overlay=x={-q(120)}:y={q(180)}:shortest=1,"
          f"drawtext=fontfile={BOLD}:textfile={f['label']}:fontcolor={ACC}:fontsize={q(36)}:x='{q(90)}-{q(50)}*(1-min(1,t/0.6))':y={q(470)}:alpha='min(1,t/0.5)',"
          f"drawbox=x={q(90)}:y={q(524)}:w='max(1,min({q(170)},{q(170)}*(t-0.2)/0.7))':h={q(8)}:color={ACC}:t=fill,"
          f"drawtext=fontfile={BOLD}:textfile={f['name']}:fontcolor=white:fontsize={nsize}:shadowcolor=black@0.4:shadowy={q(4)}:x={q(90)}:y='{q(566)}+{q(36)}*(1-min(1,max(0,(t-0.25)/0.6)))':alpha='min(1,max(0,(t-0.25)/0.6))',"
          + "".join(f"drawtext=fontfile={REG}:textfile={tf(work, f'hook{j}', ln)}:fontcolor=0xD1D5DB:fontsize={q(42)}:x={q(90)}:y={q(566)+nsize+q(44+j*58)}:alpha='min(1,max(0,(t-0.8-0.15*{j})/0.6))'," for j, ln in enumerate(textwrap.wrap(cfg["hook"], 34)[:2])).rstrip(",") + "[intro];")
    if has:
        fc += (f"[7:v]scale={q(980)}:{q(613)}:flags=lanczos,format=rgba[ds];[10:v]format=gray[dm];[ds][dm]alphamerge[dsr];"
               f"[8:v]scale={q(300)}:{q(649)}:flags=lanczos,format=rgba[ps];[12:v]format=gray[pm];[ps][pm]alphamerge[psr];"
               f"[1:v]{move}[bd];[bd][g2]overlay=x={q(60)}:y={q(260)}:shortest=1[b1];"
               f"[b1][13:v]overlay=x={-q(12)}:y={q(190)}[b2];[b2][9:v]overlay=x={q(48)}:y={q(248)}[b3];[b3][dsr]overlay=x={q(50)}:y={q(294)}[b4];"
               f"[b4][14:v]overlay=x={q(650)}:y={q(575)}[b5];[b5][11:v]overlay=x={q(724)}:y={q(636)}[b6];[b6][psr]overlay=x={q(736)}:y={q(648)},"
               f"drawtext=fontfile={BOLD}:textfile={f['label']}:fontcolor={ACC}:fontsize={q(26)}:x={q(60)}:y={q(60)},"
               f"drawtext=fontfile={BOLD}:textfile={f['name']}:fontcolor=white:fontsize={q(58)}:x={q(60)}:y={q(104)},"
               f"drawtext=fontfile={MED}:textfile={f['url']}:fontcolor=0x94A3B8:fontsize={q(26)}:x={q(60)}:y={q(184)},"
               + ",".join(capf) + ("," if capf else "") +
               f"drawtext=fontfile={REG}:textfile={f['sub']}:fontcolor=0x94A3B8:fontsize={q(22)}:x={q(60)}:y={q(1262)},"
               f"drawbox=x={q(60)}:y={q(1318)}:w={q(960)}:h={q(4)}:color=white@0.12:t=fill,drawbox=x={q(60)}:y={q(1318)}:w='max(1,{q(960)}*t/{D:.3f})':h={q(4)}:color={ACC}:t=fill,trim=duration={D:.3f}[demo];")
    else:
        mids = wrap(cfg["caption"], 22).split("\n")
        fc += (f"[1:v]{move}[bd];[bd][g2]overlay=x={q(90)}:y={q(200)}:shortest=1," + ",".join(
               f"drawtext=fontfile={BOLD}:textfile={tf(work, f'mid{j}', ln)}:fontcolor=white:fontsize={q(58)}:x=(w-tw)/2:y={q(640 + (j - (len(mids) - 1) / 2) * 76)}:alpha='min(1,t/0.6)'"
               for j, ln in enumerate(mids)) + "[demo];")
    fc += (f"[2:v]{move}[bo];[bo][g3]overlay=x={q(90)}:y={q(120)}:shortest=1,"
           f"drawtext=fontfile={BOLD}:textfile={f['cta']}:fontcolor={ACC}:fontsize={q(50)}:x=(w-tw)/2:y='{q(520)}+{q(20)}*(1-min(1,t/0.5))':alpha='min(1,t/0.5)',"
           f"drawtext=fontfile={BOLD}:textfile={f['url']}:fontcolor=white:fontsize={q(48 if len(cfg['url_text']) <= 30 else 36)}:x=(w-tw)/2:y={q(610)}:alpha='min(1,max(0,(t-0.2)/0.5))',"
           f"drawtext=fontfile={BOLD}:text='Anchit Tandon':fontcolor=0x64748B:fontsize={q(32)}:x=(w-tw)/2:y={q(1180)}[outro];"
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
           "-c:v", "libx264", "-preset", os.environ.get("X264_PRESET", "medium"), "-crf", os.environ.get("X264_CRF", "17"),
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise SystemExit(f"ffmpeg failed for {day}: {r.stderr[-1500:]}")
    return total

# ---------- Full tour: every page and every feature view of a product ----------
SKIP_URL = re.compile(r"privacy|terms|cookie|legal|refund|login|signin|sign-in|signup|sign-up|logout|/auth|account|careers|"
                      r"\.(pdf|zip|apk|png|jpe?g|svg|mp4|mobileconfig|xml|json|txt)$|mailto:|tel:|wa\.me|/api/", re.I)
SKIP_TEXT = re.compile(r"^(sign ?in|log ?in|sign ?up|log ?out|menu|close|open menu|toggle|theme|dark|light|language|english|hindi|skip|"
                       r"cancel|ok|got it|accept|decline|share|copy|download|install|×|✕|☰|…|\.\.\.)$", re.I)
LINKS_JS = """()=>[...document.querySelectorAll('a[href]')].filter(a=>{const r=a.getBoundingClientRect();return r.width>0&&r.height>0}).map(a=>({h:a.href,t:(a.innerText||a.getAttribute('aria-label')||a.title||'').replace(/\\s+/g,' ').trim()}))"""
TABS_JS = """()=>{const out=[];const seen=new Set();
 for(const el of document.querySelectorAll('nav button,header button,aside button,[role=tablist] [role=tab],[role=tab],nav [role=button],.tabs button,.tab-bar button,.bottom-nav button,footer nav button')){
  const r=el.getBoundingClientRect(); if(!r.width||!r.height) continue;
  const t=(el.innerText||el.getAttribute('aria-label')||'').replace(/\\s+/g,' ').trim();
  if(t.length<2||t.length>28||seen.has(t)) continue; seen.add(t); out.push(t);} return out;}"""
TITLE_JS = """()=>{const h=document.querySelector('main h1,h1,main h2,h2');const t=(h&&h.innerText||document.title||'').replace(/\\s+/g,' ').trim();return t.slice(0,60);}"""
def nice(label, fallback):
    t = re.sub(r"\s+", " ", (label or "")).strip(" -|·→>")
    if len(t) < 3 or len(t) > 40 or SKIP_TEXT.match(t): t = fallback
    return t[:40]
async def settle(pg, ms=1200):
    try: await pg.wait_for_load_state("networkidle", timeout=8000)
    except Exception: pass
    await pg.wait_for_timeout(ms)
    try: await pg.add_style_tag(content="*{scroll-behavior:auto!important} ::-webkit-scrollbar{display:none}")
    except Exception: pass
async def dismiss(pg):
    for label in ["No thanks", "Decline", "Reject", "Got it", "Accept", "OK", "Close"]:
        try:
            btn = pg.get_by_role("button", name=label, exact=True)
            if await btn.count(): await btn.first.click(timeout=800); return
        except Exception: pass
async def plan_tour(browser, cfg):
    """Desktop pass: list every reachable page (same site) and every tab/feature view, keeping only ones that really open."""
    site = cfg["site"]; base = urlparse(site); root = base.path.rstrip("/")
    ctx = await browser.new_context(viewport={"width": DESK["w"], "height": DESK["h"]}, color_scheme="dark",
                                    permissions=["camera", "microphone"])
    pg = await ctx.new_page()
    try: await pg.goto(site, wait_until="networkidle", timeout=45000)
    except Exception: pass
    await settle(pg, 1500); await dismiss(pg)
    scenes = [{"kind": "home", "label": cfg.get("caption") or cfg["name"]}]
    for a in (cfg.get("actions") or []) + (cfg.get("scenes") or []):   # walkthrough first, then pages/features
        if "click" in a:
            scenes.append({"kind": "click", "target": a["click"], "label": a.get("label", a["click"]), "sec": a.get("sec", a.get("hold", 3)),
                           "fill": a.get("fill"), "scroll": a.get("scroll", True), "phone_target": a.get("phone"), "reset": a.get("reset")})
        elif "url" in a:
            scenes.append({"kind": "url", "target": urljoin(site, a["url"]), "label": a.get("label", a["url"]), "sec": a.get("sec")})
        elif "show" in a:
            scenes.append({"kind": "show", "target": a["show"], "label": a.get("label", a["show"]), "sec": a.get("sec", 3.5)})
    seen = {root or "/"} | {urlparse(x["target"]).path.rstrip("/") or "/" for x in scenes if x["kind"] == "url"}; pages = []
    for l in await pg.evaluate(LINKS_JS):
        u = urlparse(l["h"])
        if u.netloc != base.netloc or SKIP_URL.search(l["h"]) or SKIP_TEXT.match(l["t"] or "x"): continue
        if root and not u.path.startswith(root): continue
        frag = u.fragment if u.fragment.startswith("/") else ""
        key = (u.path.rstrip("/") or "/") + ("#" + frag if frag else "")
        if key in seen: continue
        seen.add(key); pages.append((f"{u.scheme}://{u.netloc}{key}", l["t"]))
    extra = [(urljoin(site, x), "") for x in cfg.get("pages", [])]
    for url, label in (extra + pages)[: int(os.environ.get("MAX_PAGES", "40"))]:
        try:
            r = await pg.goto(url, wait_until="domcontentloaded", timeout=25000); await settle(pg, 600)
            final = urlparse(pg.url)
            if (r and r.status >= 400) or SKIP_URL.search(pg.url) or final.netloc != base.netloc: continue
            title = await pg.evaluate(TITLE_JS)
            scenes.append({"kind": "url", "target": url, "label": nice(label, title or url.rsplit("/", 1)[-1])})
        except Exception: continue
    if not any(s["kind"] in ("url", "click") for s in scenes):          # app-style products: walk every tab / view
        try: await pg.goto(site, wait_until="networkidle", timeout=30000)
        except Exception: pass
        await settle(pg, 1200); await dismiss(pg)
        for t in (await pg.evaluate(TABS_JS))[:14]:
            if SKIP_TEXT.match(t): continue
            try:
                loc = pg.get_by_role("tab", name=t)
                if not await loc.count(): loc = pg.get_by_role("button", name=t, exact=True)
                if not await loc.count(): continue
                before = await pg.evaluate("document.body.innerText.length+'|'+location.href")
                await loc.first.click(timeout=2500); await pg.wait_for_timeout(700)
                after = await pg.evaluate("document.body.innerText.length+'|'+location.href")
                if after != before: scenes.append({"kind": "click", "target": t, "label": t})
            except Exception: continue
    await ctx.close()
    return scenes
async def run_tour(browser, cfg, spec, scenes, frames_dir):
    """Capture the tour frame by frame. Same timings on desktop and phone, so both stay in step."""
    shutil.rmtree(frames_dir, ignore_errors=True); os.makedirs(frames_dir)
    ctx = await browser.new_context(viewport={"width": spec["w"], "height": spec["h"]}, device_scale_factor=spec["dpr"],
                                    is_mobile=spec["mobile"], has_touch=spec["mobile"], color_scheme="dark",
                                    permissions=["camera", "microphone"])
    pg = await ctx.new_page()
    n = 0; marks = []; t = 0.0
    budget = float(os.environ.get("TOUR_SECONDS", "100")); per = max(2.4, min(5.0, budget / max(1, len(scenes))))
    XF = 8                                                         # cross-fade frames between scenes
    async def shot():
        nonlocal n
        await pg.screenshot(path=f"{frames_dir}/{n:05d}.jpg", type="jpeg", quality=92); n += 1
    for i, sc in enumerate(scenes):
        sec = sc.get("sec") or (per + 1.5 if sc["kind"] == "home" else per)
        if sc["kind"] == "show":                                    # bring a section of the current page into view
            try:
                await pg.get_by_text(sc["target"], exact=False).first.scroll_into_view_if_needed(timeout=3000)
                await pg.evaluate("window.scrollBy(0,-80)"); await pg.wait_for_timeout(300)
            except Exception: pass
        elif sc["kind"] in ("home", "url"):
            try: await pg.goto(sc.get("target") or cfg["site"], wait_until="domcontentloaded", timeout=30000)
            except Exception: pass
            await settle(pg, 1000)
            if sc["kind"] == "home": await dismiss(pg)
        else:
            if sc.get("reset"):                                          # start this feature from the home screen
                try: await pg.goto(cfg["site"], wait_until="domcontentloaded", timeout=30000)
                except Exception: pass
                await settle(pg, 900)
            for sel, text in (sc.get("fill") or {}).items():          # type into a field before the click
                try:
                    f = pg.locator(sel).first
                    if await f.is_visible(): await f.fill(text)
                except Exception: pass
            clicked = False
            target = sc.get("phone_target") if spec["mobile"] and sc.get("phone_target") else sc["target"]
            sc = dict(sc, target=target)
            for loc in (pg.get_by_role("button", name=sc["target"], exact=True), pg.get_by_role("tab", name=sc["target"]), pg.get_by_role("button", name=sc["target"]),
                        pg.get_by_role("link", name=sc["target"]), pg.get_by_text(sc["target"], exact=False)):
                try:
                    if await loc.count() and await loc.first.is_visible():
                        await loc.first.click(timeout=2500); clicked = True; break
                except Exception: pass
            if not clicked and spec["mobile"]:                        # phone layouts hide navigation behind a menu
                try: await pg.evaluate("""()=>{const b=[...document.querySelectorAll('button,[role=button]')].find(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.x>=0&&r.y<110&&!(e.innerText||'').trim()&&!/close|back/i.test(e.getAttribute('aria-label')||'')});if(b){b.setAttribute('data-tour-menu','1');return true}return false}""")
                except Exception: pass
                for m in (pg.get_by_role("button", name=re.compile("menu|navigation", re.I)), pg.locator("[aria-label*=menu i]"),
                          pg.locator("[data-tour-menu]")):
                    try:
                        if await m.count():
                            await m.first.click(timeout=1500); await pg.wait_for_timeout(400)
                            await pg.get_by_text(sc["target"], exact=False).first.click(timeout=2000); break
                    except Exception: pass
            await pg.wait_for_timeout(700)
        marks.append((t, sc["label"]))
        k = round(sec * FPS); start_n = n
        hold = min(k, round(0.6 * FPS)); scroll = k - hold
        y0 = await pg.evaluate("scrollY"); maxy = await pg.evaluate("document.documentElement.scrollHeight-innerHeight")
        y1 = max(y0, min(maxy - spec["h"] * 0.5, y0 + spec["h"] * 1.1))   # show the page, not its footer
        if sc.get("scroll") is False: y1 = y0                              # live screens (animations) stay put
        if sc["kind"] == "click" and sc.get("scroll") is not False:
            try: await pg.evaluate("window.scrollTo(0,0)"); y0 = 0; y1 = min(y1, spec["h"] * 0.8)
            except Exception: pass
        for _ in range(hold): await shot()
        for j in range(scroll):
            await pg.evaluate(f"window.scrollTo(0,{y0 + (y1 - y0) * ease((j + 1) / scroll):.1f})"); await shot()
        if i and start_n >= XF:                                          # blend the scene change so it never jumps
            prev = Image.open(f"{frames_dir}/{start_n - 1:05d}.jpg").convert("RGB")
            for f in range(min(XF, n - start_n)):
                cur = Image.open(f"{frames_dir}/{start_n + f:05d}.jpg").convert("RGB")
                Image.blend(prev, cur, (f + 1) / (XF + 1)).save(f"{frames_dir}/{start_n + f:05d}.jpg", quality=92)
        t += k / FPS
    await ctx.close()
    return n, marks

async def render(days):
    cfgs = json.load(open(os.path.join(HERE, "sites.json"))); os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--hide-scrollbars"])
        for day in days:
            cfg = cfgs[str(day)]; work = os.path.join(B, f"work{day}"); os.makedirs(work, exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "-", cfg["name"].lower()).strip("-"); out = os.path.join(OUT, f"demo-{day:02d}-{slug}.mp4")
            n, caps = 0, []
            if cfg.get("site"):
                scenes = await plan_tour(br, cfg)
                print(f"  tour: {len(scenes)} scenes: " + " | ".join(x["label"] for x in scenes), flush=True)
                n, caps = await run_tour(br, cfg, DESK, scenes, f"{work}/desk")
                n2, _ = await run_tour(br, cfg, PHONE, scenes, f"{work}/phone")
                n = min(n, n2)
            master = out[:-4] + "-2160p.mp4"                      # 1728x2160 master for LinkedIn
            total = compose(day, cfg, work, n, caps, master)
            shutil.rmtree(work, ignore_errors=True)
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", master, "-vf", "scale=1080:1350:flags=lanczos", "-c:v", "libx264",
                                "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out],
                               capture_output=True, text=True)                 # web copy for the series page
            if r.returncode: raise SystemExit(f"web copy failed for {day}: {r.stderr[-800:]}")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "4.5", "-i", out, "-frames:v", "1", "-vf", "scale=540:675", "-q:v", "3", out[:-4] + ".jpg"], check=False)
            print(f"{master} {os.path.getsize(master)/1e6:.1f} MB | {out} {os.path.getsize(out)/1e6:.1f} MB | {total:.1f}s", flush=True)
        await br.close()
if __name__ == "__main__":
    fonts(); visuals(); audio()
    asyncio.run(render([int(a) for a in sys.argv[1:]]))
