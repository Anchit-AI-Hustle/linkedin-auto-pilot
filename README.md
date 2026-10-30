# linkedin-auto-pilot

A small robot that publishes one approved LinkedIn post every morning at 9:00 AM IST, for the **#20BuildsIn20Days** series.

It is publish-only. It posts to my own profile through LinkedIn's official Posts API and never likes, comments on other people's posts, messages or connects. I reply to every comment myself.

## How it works

- `posts.json` holds the approved queue: 23 posts, one per date (2 to 24 November 2026).
- `.github/workflows/daily-post.yml` runs `post.py` every day at 03:30 UTC (09:00 IST).
- `post.py` picks the post for today's date, checks it, and publishes it.
- `posted.json` records what went out, so a post can never be published twice.

## Safety

- **Guard:** a post is blocked if it is empty, over 3,000 characters, still has a placeholder like `[ADD ...]`, or contains an em or en dash.
- **Pause:** add an empty file called `PAUSE` to the repo and nothing is posted until you delete it.
- **Dry run:** run the workflow by hand (Actions, Daily LinkedIn post, Run workflow) and it only prints what it would post.
- **Failures:** a failed run shows red in Actions and GitHub emails you. The next day runs as normal.
- **Formatting:** text is converted to LinkedIn's "little text" format, so brackets and underscores publish as written and hashtags stay clickable.

## Setup (once)

1. Create an app at linkedin.com/developers (it must be linked to a LinkedIn Page).
2. Add the products **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
3. Generate an access token with the scopes `openid profile w_member_social`.
4. In this repo: Settings, Secrets and variables, Actions, add `LINKEDIN_ACCESS_TOKEN`.
5. Run the workflow once with dry run on to check, then leave it to the schedule.

Tokens last 60 days, which covers the whole series. If a run fails with 401, generate a new token and update the secret.

## Tests

```
python -W ignore test_post.py
```

14 tests cover escaping, hashtags, the guard, scheduling, pause, dry run, and the live posting path against a fake LinkedIn.
