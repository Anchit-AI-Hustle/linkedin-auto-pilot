# linkedin-auto-pilot

A small robot that publishes the **#20BuildsIn20Days** LinkedIn series: 22 approved posts, one a day at 9:00 AM IST.

It is publish-only. It posts to my own profile through LinkedIn's official Posts API and never likes, comments on other people's posts, messages or connects. I reply to every comment myself.

## Start and stop

- **Start:** Actions, **Start posting**, Run workflow. It checks the LinkedIn token, publishes Day 0 straight away, and then posts the next day every morning at 9:00 AM IST until all 22 are out.
- **Stop:** Actions, **Stop posting**, Run workflow. Nothing more goes out until you start again, and it picks up from the next unposted day.
- **Preview:** Actions, **Daily LinkedIn post**, Run workflow with dry run on. It prints the next post and changes nothing.

The repo ships paused (the `PAUSE` file), so nothing posts until you press Start.

## How it works

- `posts.json` holds the approved queue, Day 0 to Day 21.
- `.github/workflows/daily-post.yml` runs `post.py` every day at 03:30 UTC (09:00 IST).
- `post.py` publishes the next unposted day, never more than one a day.
- `posted.json` records what went out, so nothing is published twice.

## Safety

- **Guard:** a post is blocked if it is empty, over 3,000 characters, still has a placeholder like `[ADD ...]`, or contains an em or en dash.
- **Token check:** Start refuses to begin if the token is missing or rejected.
- **Failures:** a failed run shows red in Actions and GitHub emails you. The next day runs as normal.
- **Formatting:** text is converted to LinkedIn's "little text" format, so brackets and underscores publish as written and hashtags stay clickable.

## One-time setup

1. Create an app at linkedin.com/developers (LinkedIn requires it to be linked to a LinkedIn Page).
2. Add the products **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
3. Generate an access token with the scopes `openid profile w_member_social`.
4. In this repo: Settings, Secrets and variables, Actions, New repository secret, name `LINKEDIN_ACCESS_TOKEN`.

Tokens last 60 days, which covers the whole series. If a run fails with 401, generate a new token and update the secret.

## Tests

```
python -W ignore test_post.py
```

17 tests cover escaping, hashtags, the guard, ordering, one post a day, pause, the token check, dry run, and the live posting path against a fake LinkedIn.
