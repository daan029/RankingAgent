You are running the daily automated production of one DailyWreck YouTube
Shorts video. Work from the RankingAgent repo root (this file's parent
directory's parent). Do the judgment-heavy steps yourself; delegate the
mechanical steps to the `rankingagent` CLI (`python -m rankingagent.cli ...`,
run inside the project's `.venv`).

Follow these steps in order. If any step fails, stop and report what
happened rather than guessing around it — don't retry destructive steps
blindly.

## 1. Pick today's theme

The available themes are defined in `config/themes.yaml` (currently: `fails`,
`karen_moments`, `worst_tackles`). Do a quick (2-3 searches, a few minutes
max — this isn't a research report) web search for what's currently
resonating in this space on TikTok/Instagram/YouTube Shorts, to get a feel
for which of these three categories seems hottest right now. Also run
`python -m rankingagent.cli history --theme <name>` for each theme to see
when it was last used — avoid a theme published in the last 2 days if a
reasonable alternative exists. Pick one theme for today.

## 2. Discover and download clips

Reddit's official API application for this project was denied (see the
`reddit-api-blocker` memory entry), so the primary discovery path is RSS,
not the API:

```
python -m rankingagent.cli discover-rss --theme <theme>
```

This is **slow on purpose** (paced ~25s between requests to avoid Reddit's
anonymous rate limit) — a run touching 3 subreddits can take 10+ minutes.
Let it run; don't interrupt or parallelize it. If it fails outright (not
just slow), fall back to:

```
python -m rankingagent.cli discover-manual --theme <theme> --urls-file <path>
```

— but only if you or the user already have a curated URL list ready; don't
invent one. If neither path yields any clips, stop and report rather than
guessing.

## 3. Review candidates for tone AND narrative fit BEFORE selecting — do not skip this

RSS "top" posts are **not** pre-filtered for tone or appropriateness. This
is a confirmed real issue, not a theoretical one: on 2026-08-14,
r/PublicFreakout's actual top-of-week posts were mostly serious political/
war-related confrontations (not comedic), and one r/Whatcouldgowrong
candidate involved a real firearm mishap. Both would be inappropriate for
this brand (chaos/comedy — NOT tragedy, real injury, war, or political
conflict).

```
python -m rankingagent.cli candidates --theme <theme>
```

Read every candidate's `caption` (and creator/source_url if the caption is
ambiguous). Reject anything that is: political or war-related, about a real
injury/death/tragedy, sexual, or otherwise not lighthearted comedic chaos.

**Also reject anything that doesn't actually match what the theme's title
promises the viewer — a subreddit source is not itself proof of fit.**
Confirmed real issue (2026-08-18): `karen_moments` clips were selected on
chaos/score alone, but a Karen moment is specifically a filmed
*confrontation/argument* — a caption with no dialogue or conflict doesn't
qualify no matter how chaotic. Same day, `instant_karma` (sourced partly
from r/IdiotsInCars) got titled "Instant Karma" but several selected clips
were just generic bad-driving/dashcam footage with no actual comeuppance
beat (wrongdoer doing something reckless and immediately paying for it) —
"came from a related subreddit" is not the same as "matches the theme".
Before selecting, ask for each candidate: does this specific clip deliver
the thing the on-screen title will claim it delivers? If the honest answer
for a candidate is "it's chaotic/relevant but not really that", reject it
rather than filling the quota with adjacent-but-off content.

```
python -m rankingagent.cli reject --theme <theme> --clip-ids <comma,separated,ids>
```

Only proceed to step 4 once the remaining candidates are all genuinely
on-brand AND genuinely match the theme's specific narrative, not just its
general subject area.

## 4. Select and rank

```
python -m rankingagent.cli select --theme <theme>
```

This prints a JSON array of the 5 chosen clips, each with `id`, `caption`,
`creator`, `source_url`, `rank` (1 = highest score = the climax, shown last),
and `reveal_index` (the order clips appear in the video). Keep this JSON —
you'll need the `id`s and `caption`s for the next steps.

## 5. Clip trim points are automatic — nothing to do here

`render` (step 8) automatically asks Gemini where the fail/highlight moment
is in each clip and trims from there — the fail/punchline is often NOT at
the very start of the raw clip (confirmed 2026-08-14: a car-vs-gate clip's
action didn't start until ~16s into a 66s clip), so this is no longer a
manual step. Only intervene if you have a specific reason to override a
clip's start time: pass `--clip-starts '{"reddit_abc123": 14.0}'` to
`render`, which takes precedence over Gemini's pick for that clip. Requires
`GEMINI_API_KEY` in `.env`; if it's missing, `render` logs a warning and
every clip defaults to start=0 instead of failing outright.

## 6. Write a reaction for each clip

For each of the 5 clips, based on its `caption` (and `source_url` if you can
usefully check it), write a short reaction — 1 to 3 words plus one emoji,
matching the tone of examples like "Aaaah💀", "No way😱", "Unbelievable🔥".
Keep it punchy, not a description of what happens. Build a JSON object
mapping clip `id` -> reaction text, e.g.:
`{"reddit_abc123": "Ouch😬", "reddit_def456": "No way😱"}`

## 7. Write the on-screen title, YouTube title, and description

Check `python -m rankingagent.cli history --theme <theme>` for previously
used titles so you don't repeat one. Based on the actual 5 selected clips
(not a generic template), come up with 3-5 candidate titles, then pick the
best one yourself.

You're writing **two** related but distinct pieces of text:

- **On-screen title** (burned into the video, after "Ranking Best "): a few
  words with real context about tonight's specific clips — not just the bare
  theme name ("Fails"). E.g. "Craziest Fails Of The Week" or "Fails You Won't
  Believe". Keep it short enough to fit one line at the top of a vertical
  video (roughly 3-6 words after "Ranking Best "). Wrap only the single most
  important word (or two) in asterisks — that part renders in brand red, the
  rest in white, e.g. `"*Craziest* Fails Of The Week"`. Don't wrap the whole
  phrase; pick just the word that matters most.
- **YouTube title** (video metadata): favor a clear hook, no misleading
  claims, under 100 characters, include `#Shorts`. Can be longer/more
  specific than the on-screen title.

The description MUST credit each of the 5 clips' original creators by their
Reddit username (from the `creator` field in step 4's output) — this is a
non-negotiable project requirement, not optional flavor text. Use a template
like:

```
Today's top 5 <theme>! All clips are credited to their original creators:
u/<creator1>, u/<creator2>, u/<creator3>, u/<creator4>, u/<creator5>

If you're the creator of a clip and want it removed, contact us at [email].

#Shorts #<theme-related-tags>
```

## 8. Render the video

```
python -m rankingagent.cli render --theme <theme> --reactions '<json from step 6>' --title-text "<on-screen title from step 7>"
```

This calls Gemini once per clip to find its highlight moment (see step 5) —
expect it to take a bit longer than a plain render, that's normal. Prints
the path to the rendered mp4. If ffmpeg isn't on PATH or fails, report the
error rather than retrying blindly.

## 9. Upload

```
python -m rankingagent.cli upload --theme <theme> --video <path from step 8> --title "<YouTube title from step 7>" --description "<description from step 7>" --tags "<comma,separated,tags>"
```

Don't pass `--privacy` unless the user has explicitly told you to go public —
it defaults to `YOUTUBE_PRIVACY_STATUS` from `.env` (currently `unlisted`),
which is intentional until the pipeline has a track record.

The first time this runs, `upload` will open a one-time browser window for
Google OAuth consent — this requires a human at the keyboard once. After
that, the cached token is reused automatically (see
`youtube-upload-lessons` — while the OAuth app is in "Testing" mode, that
token expires every 7 days and needs re-consent; get the app verified to
avoid that).

## 10. Report

State the resulting YouTube URL, the theme and title chosen, and note the
privacy status. If any step was skipped or failed, say so clearly instead of
reporting success.
