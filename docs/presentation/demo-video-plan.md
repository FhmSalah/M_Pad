# Demo video plan — "Macro Pad in use"

For the **Project Journey** presentation (`Macro Pad_Project Journey.pdf`, 14 slides).
Slide 14 already says: *"I've also made a short video of the journey and the pad in use:
[video link]"*. This video fills that link. Later it can also go in the GitHub README.

## The idea in one line

The deck **tells** the story (it didn't work → I opened it, rewired it, wrote firmware and
an app → V1). The video **proves** it: the same pad, plugged in, working instantly in real
creative work.

So every shot should answer "does it really work?" for one claim in the deck. Don't retell
the journey; the slides already do that.

## Format

| | |
|---|---|
| Length | **60–90 seconds.** Short enough to watch to the end. |
| Shape | 16:9 landscape, 1080p, to match the slides. |
| Sound | Real click and knob sounds plus quiet music. Captions instead of a voice-over, so it works muted. |
| Look | Dark desk or background, matching the deck's dark slides and green accent. Captions in white with a green highlight, same font feel as the slides (Inter / a clean sans). |
| Two cameras | **A:** phone above the desk, filming hands and pad. **B:** screen recording. Show them side by side or switch between them. |

## Shot list

Each row links back to the slide it proves.

| # | Time | Camera | What to do | Caption idea | Proves |
|---|---|---|---|---|---|
| 1 | 0:00–0:05 | A + B | **Hook.** Close-up of the pad, press one key, and something visibly happens on screen (e.g. a Krita lasso appears). No title yet. | — | the whole deck |
| 2 | 0:05–0:12 | A, then B | Plug in the USB cable. Cut to the screen: hover the tray icon, which says **Connected**. | "Plugged in. Detected in a second." | Slide 3 (on day one Windows saw nothing) |
| 3 | 0:12–0:22 | A + B side by side | Open the app window. Press keys quickly, then turn both knobs. Each control **lights up live** on the drawing as you press. | "All 18 inputs, every press, no lag." | Slides 6 and 10 (18 inputs, live feedback) |
| 4 | 0:22–0:37 | B (A inset) | **Assign in ten seconds:** click a key on the drawing → Hotkey → Record shortcut → press the combination → give it a label → Save. Press the physical key and it works at once. | "Click a key. Assign it. Done." | Slide 10 (select / assign / feedback) |
| 5 | 0:37–0:55 | A + B | **Real work in Krita:** turn the left knob to rotate the canvas, click it to reset, press keys for lasso, deselect, brush, eraser, undo. Keep it short, like you're actually drawing. | "Made for creative work." | Slide 11 (creative apps) |
| 6 | 0:55–1:05 | B | **Automatic profiles:** click from Krita over to Brave. The profile switches to **Browser** by itself, and the **same knob** now scrolls the page and the same keys handle tabs. Switch back and it returns to Krita. | "The pad follows the app you're in." | Slide 11 (automatic profiles) |
| 7 | 1:05–1:15 | B | **Lives in the background:** close the window, keep using the pad, then right-click the tray icon to show **Open / Start at login / Quit**. | "Close the window. It keeps working." | New since V1 (slide 13, next steps) |
| 8 | 1:15–1:22 | Mac screen *(optional)* | The same pad on the MacBook doing one or two of the above. | "Same pad, same app, on macOS." | Slides 8 and 12 (two platforms) |
| 9 | 1:22–1:30 | A | **End card:** the pad on the desk, still. Fade to text: "Macro Pad — a small project that grew into a complete V1." Then the GitHub link once it's public. | as written | Slide 14 |

**If you only have time for four shots:** 1, 3, 5 and 6.

## Before you record

**Tidy the profiles** so labels look good on screen. Back up `%APPDATA%\Macro Pad\config.json` first:
- [ ] General: replace test labels "1" and "test" with real names (e.g. "Find").
- [ ] Browser: fix "Scrool" → "Scroll". The right knob's label says "Volume" but it
      scrolls, so rename it. The left knob's directions look reversed (CW = volume down);
      check this is intended.
- [ ] Krita: fill a few more keys so shot 5 has something to press, e.g. brush `b`,
      eraser `e`, undo `ctrl+z`, redo `ctrl+shift+z`, smaller/bigger brush `[` / `]`.
      Label the left knob "Rotate".
- [ ] Ae is empty: fill it, or leave After Effects out of the video.

**Prepare the screen:**
- [ ] Turn on Do Not Disturb (Windows: Focus / Notifications off; Mac: Focus).
- [ ] Hide anything personal: browser tabs, bookmarks bar, email, other people's names,
      file paths with your user name. The video will be public once the repo is.
- [ ] Use a clean demo canvas in Krita and one neutral web page in Brave.
- [ ] Set display scaling so the Macro Pad window is readable when recorded (125–150%).

**Recording tools:**
- Windows screen: **OBS Studio** (free), or Xbox Game Bar (`Win + Alt + R`) for quick takes.
- Mac screen: `Cmd + Shift + 5`.
- Phone: landscape on a stand above the desk, exposure locked, soft light from the side
  so the keycaps don't glare.
- **Syncing camera A and B:** start each take by pressing one key hard. The click sound
  and the on-screen highlight line up the two recordings.

## Editing

- Cut fast: each shot shows one thing, then moves on. Trim the waiting.
- Show the pad and screen together whenever a press causes something on screen (shots 3–6);
  that's the whole point.
- Captions: 3–6 words each, bottom left, same place every time.
- Free editors: DaVinci Resolve, CapCut, or Clipchamp (built into Windows).
- Export: 1080p MP4 (H.264). Keep it under ~100 MB so it's easy to share.

## Putting it in the presentation

1. **Slide 14:** upload the video (YouTube *unlisted*, Google Drive, or later the GitHub
   repo) and replace `[video link]` with a short link.
2. **Optional new slide between 11 and 12, "See it in use":** a still frame from shot 5 or 6
   with a play icon. In PowerPoint, Keynote or Google Slides you can embed the video there to
   play it live; in the PDF it's a clickable link.
3. A QR code next to the link helps if the deck is shown on a screen or printed.

## Later: reuse for GitHub

- Cut a **10–15 second loop** of shots 3 and 6 (live highlight plus profile switch) as a
  GIF or MP4 for the top of the public README.
- Use the full video as the link in the README's "See it in action" line.
