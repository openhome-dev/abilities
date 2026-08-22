# Music Template

For Abilities that play a track and decide what happens next.

**Resolve a link → `stream_music_from_url()` → branch on `outcome`**

## When to Use This

- Streaming music, radio or a podcast from an API
- Anything that plays for minutes and can be interrupted by voice
- Any "play it, then react to how it ended" pattern

## The one call

```python
result = await self.capability_worker.stream_music_from_url(
    url,
    duration_seconds=210.0,             # FULL track length
    announce="Playing Blinding Lights.",
)
result["outcome"]   # "finished" | "paused" | "stopped" | "unplayable" | "error"
result["position"]  # seconds heard — pass back as start_seconds to resume
```

It blocks until playback genuinely ends and tells you why. The audio pipeline,
the device buffer, music mode and the recovery afterwards are all inside the
call — `speak()` and `run_io_loop()` work on the very next line no matter how
it ended, including the error path.

While the stream is live the Ability is in **music mode**: it receives no
transcriptions, and must not call `speak()` or `run_io_loop()`. "pause" and
"stop" from the user come back as `outcome` values instead of events you handle.

## How to Customize

1. Copy this folder to `community/your-ability-name/`
2. Replace `MUSIC_API` with your service's base URL
3. Update `search_track()` to parse your search response — `duration` must be
   the **FULL** track length in seconds
4. Update `stream_url()` to return a **progressive mp3** link (not HLS/DASH)
5. Upload to OpenHome and set your trigger words in the dashboard
6. Replace any API keys with `YOUR_API_KEY_HERE` placeholders before submitting

## Notes

- **Resume is just calling again.** There is no separate resume function: pass
  `result["position"]` as `start_seconds` and `result["byte_offset"]` as
  `byte_offset`.
- **Re-resolve the URL on every pass.** Signed CDN links expire while the user
  sits paused.
- **Only `"paused"` loops.** `finished`, `stopped`, `error` and `unplayable` all
  leave; a loop that retries on `error` spins.
- **An unclear pause reply should stop, not resume.** A user who asked for
  silence must not get the track back because a reply didn't parse.
- **`announce` on the first pass only**, or every resume re-announces the title.
- `duration_seconds` is the **FULL** track length — the call subtracts
  `start_seconds` itself. Wrong values don't crash anything, they just make
  `position` drift, so a later resume starts in the wrong place. Pass `0` to
  take a three-minute estimate.
- Always call `resume_normal_flow()` before exiting
- Always log errors with `self.worker.editor_logging_handler`
- Never hardcode production API keys — use placeholders

## Reference

Full guide: [Playing Music from an Ability](https://docs.openhome.com/building-abilities/music-playback)
