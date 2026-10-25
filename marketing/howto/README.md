# How-to film

The README video (`docs/media/FileMorph-how-to.mp4`). Every frame is a pure function of time,
so it renders identically each run. The orb, pill, liquid fill, check-mark and captions are a
port of `filemorph/ui/node/node.py` painting, with the same springs from `motion.py`.

- `film.html` + `lib.js` + `scenes.js` — the film (open `film.html`, call `seek(t)` in the console)
- `render.py` — renders with headless Chromium (Playwright) and ffmpeg
- `audio.py` — synthesizes the soundtrack and UI sounds (numpy)

```
pip install playwright numpy && playwright install chromium
python render.py stills out/ 14.6 25.5 48          # check a few moments
python render.py frames p1.mp4 0 52 60             # render in halves (parallel)
python render.py frames p2.mp4 52 104 60
python audio.py audio.wav
printf "file p1.mp4\nfile p2.mp4\n" > list.txt
ffmpeg -f concat -safe 0 -i list.txt -i audio.wav -af loudnorm=I=-16:TP=-1.5 \
  -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart master.mp4
# README copy (< 10 MB so GitHub can play it inline): 30 fps, two-pass 640 kbps
```

Copy and timing live in `scenes.js` (one `scene({...})` block per chapter).
