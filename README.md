# linkedin-auto-pilot

Publishes the approved LinkedIn series through LinkedIn's official Posts API, at most once per slot: **2 AM, 8 AM, 2 PM and 8 PM IST**.

It posts to the author's own profile. It never likes, comments on other people's posts, messages or connects.

## Start, stop and preview

- **Start:** Actions, **Start posting**, Run workflow. Checks the token and removes `PAUSE`. The next eligible scheduled run publishes the earliest unposted day if its reviewed video is ready.
- **Stop:** Actions, **Stop posting**, Run workflow. Creates `PAUSE`. Start resumes from the earliest unposted day.
- **Preview:** Actions, **LinkedIn post every 6 hours**, Run workflow with dry run on. Prints the next day and its readiness without downloading media, publishing or changing the record.

The scheduler requests runs at minutes 7, 27 and 47 each hour to tolerate delayed GitHub schedules. There is at most one publication per slot, with a minimum three-hour gap. Manual runs can bypass the catch-up window but cannot bypass ordering or the slot/gap limits.

## Sequential order

- `posts.json` contains 26 entries, Days 0 through 25. The `day` number determines order; the original `date` is informational.
- `posted.json` records published posts and explicit skips. Recorded days are never reposted automatically. Day 17 remains explicitly skipped at the owner's request.
- The earliest unposted day always goes first. Legacy `priority` and `defer` flags cannot reorder it.
- If that day's video is missing, unreviewed or fails to upload, it holds the queue. Later days cannot pass it. A later run retries the same day.
- The series page and WhatsApp review loop use the same numeric order. Review approvals are checked again immediately before publishing to reject stale approvals; review publications record timestamps for the scheduler's slot/gap checks.
- The page labels pending posts **Queued** and future slots as estimates, since a readiness hold can move them.

## Sequence recovery, reviewed 16 November 2026

The saved record contains 17 published days and one explicit skip. Earlier selection rules deferred Days 7, 10, 13 and 22, promoted Day 25, and bypassed days without reviewed videos. Already published posts retain their original history and links; a code correction cannot change their order on LinkedIn.

The remaining recovery order is:

1. Day 7: AI TeleSuite
2. Day 10: TH+ LifeEngine
3. Day 13: Kolab
4. Day 16: JobHunt
5. Day 19: Airpane
6. Day 20: Games
7. Day 22: Prompter Cam
8. Day 24: The workflow behind the series

None of these eight videos is currently listed in `linkedin-auto-pilot/videos/verified.json`. The corrected publisher therefore holds at Day 7. Render or repair its full tour using the **Demo videos and series page** workflow, review the result, then mark the actual reviewed file in `verified.json`. Do the same for subsequent pending days. Existing video files alone do not count as reviewed; do not mark them ready without checking them.

## Guards and failures

- Empty text, over 3,000 characters, placeholders like `[ADD ...]`, em/en dashes and GitHub links block publishing.
- Queue day identifiers must be unique non-negative integers.
- Start refuses a missing or rejected LinkedIn token.
- Failed uploads and API failures leave the current day pending. Failed runs show red in Actions and open one issue per outage.
- Publishing workflows share a concurrency group and the scheduled publisher checks out the latest `main` posting record after acquiring it.
- `posted.json` must be saved after publishing. The workflow retries a failed push and attempts to pause if it cannot save the record. Inspect the live post and saved record before restarting after a failed save.
- LinkedIn text is escaped so brackets and underscores appear as written and hashtags stay clickable. Automatic first comments are off unless `AUTO_COMMENT=true` and the app has the required access.

## One-time setup

1. Create an app at linkedin.com/developers, linked to a LinkedIn Page.
2. Add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
3. Generate a token with scopes `openid profile w_member_social`.
4. Save it in Settings, Secrets and variables, Actions as `LINKEDIN_ACCESS_TOKEN`.

Tokens last 60 days. On a 401, generate a new token and update the secret.

## Tests

```sh
python -W ignore -m unittest discover -v
```

Tests cover numeric ordering, recovery gaps, legacy ordering flags, readiness holds, upload failure/retry, same-slot retries, explicit skips, stale review approvals, page order, API requests, formatting, pause and content guards. CI runs the suite on pull requests and pushes to `main`, and publishing workflows run it before posting.
