# Secrets Setup (one-time, per machine)

This repo is committed to GitHub. Never put credentials in files that git tracks.

## IB paper account password

On the **Windows PC**, create the file:

```
C:\Users\13174\Trading-and-Analysis-Platform\.ib_secret
```

with a single line:

```
set IB_PASSWORD=your_real_password_here
```

`.ib_secret` is covered by `.gitignore` (via the `*.secret` pattern) and will never be committed.
`StartTradeCommand.bat` loads it automatically at startup via `call .ib_secret`.

## If your password was previously committed to git history

The password `Socr1025!@!?` was in `StartTradeCommand.bat` commits before 2026-04-20. Even though
it's a **paper** account, you should:

1. Log into IB Account Management → Users & Access Rights
2. Change the paper account password
3. Put the new password in the local `.ib_secret` file only

## Rotation

Any time you rotate the password, update `.ib_secret` on the Windows PC. No git commit needed.
