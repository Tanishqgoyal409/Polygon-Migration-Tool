# Issues

All file paths are inside the `PolygonMigration/` folder.

## Product issues

### 1. It says "success" even when tests or the checker are missing

**Problem:** The tool downloads the tests from Polygon one by one. If one of them fails to
download, it doesn't stop. It just saves that test as empty and skips it later
(`polygon_api.py:399-402`). At the end the page still says everything went through
successfully.

The custom checker has the same problem. The tool tries to compile it, and if that fails it
uploads the source file instead and only writes the error to the log. The page still says the
checker was "compiled and uploaded" (`views.py:230-231`).

**Impact:** A problem can go live with missing tests or a checker that doesn't work, and nobody
finds out. Wrong answers could end up being accepted.

**Recommended improvement:** Retry a download if it fails, and if it still doesn't work, stop and
tell the user which test failed. At the end, show how many tests actually made it, and be honest
about whether the checker compiled.

**Priority rationale:** Copying problems correctly is the whole point of the tool. This is the one
place where it gets that wrong and still says it worked, so it comes first.

### 2. Migrating a problem again leaves things in a bad state

**Problem:** Problems change on Polygon all the time, so they need to be migrated again. When that
happens, a few things go wrong.

Tests that were removed on Polygon stay in the database. If a problem goes from 20 tests to 12,
the extra 8 are never deleted (`views.py:530`). Old sample tests aren't cleaned up either.

S3 can end up with only some of the tests, or none. The tool deletes the old files first and then
uploads the new ones (`polygon_api.py:750`), so if the upload breaks in the middle, the problem is
left half done. And if something fails after the upload, the tool deletes the new files too.

The editorial and constraints also get cleared. The tool never fills these itself, so normally
they're just empty. But staff can fill them in from the admin page
(<http://127.0.0.1:8000/admin/> → Problems → open a problem → Content), and anything typed there is
wiped the next time the problem is migrated (`views.py:350-351`).

**Impact:** After an update, a problem can have old tests, wrong tests or no tests at all, and the
page still says "success".

**Recommended improvement:** Only update what actually comes from Polygon, and leave the editorial
and constraints alone. Delete tests that no longer exist. For S3, upload the new files first and
only remove the old ones once that's done.

**Priority rationale:** This also breaks data, but only when a problem is migrated again. Issue 1
can happen on any migration, so this one is second.

### 3. Every button downloads the whole problem again

**Problem:** Every button on the page downloads the full problem from Polygon again, even when it
only needs to do one small thing (`views.py:234-329`). Refreshing the page after clicking a button
also sends the same request again, so the whole thing runs twice.

From our logs, for a problem with 12 tests:

| Button | Time |
|---|---|
| Fetch | about 20 s |
| Save problem | 6 s |
| Save tests | 10 s |
| Upload tests | 24 s |

Each extra test adds roughly another second. Most servers cut a request off after around 30
seconds, so for bigger problems Fetch and Upload would just time out.

**Impact:** Users wait on every click, and big problems can't be migrated at all. If the time runs
out in the middle of an upload, the problem is left with only some of its tests.

**Recommended improvement:** Give each button its own endpoint, like one for fetching, one for
saving the problem, one for saving tests and one for uploading to S3, so each one only does its
own job. Download the problem once and reuse it for the other buttons instead of fetching it again
every time. The slow parts, like downloading and uploading tests, should run in the background so
the page doesn't time out.

**Priority rationale:** This one mostly wastes time, while the first two break data. It's still in
the top three because everyone runs into it on every click.

## Code issues

### 1. Passwords set from /admin are saved as plain text

**Problem:** Passwords should be hashed before they're saved. `createsuperuser` does that, but the
admin page doesn't. It uses a plain admin page (`users/admin.py`) instead of Django's `UserAdmin`,
so whatever you type as the password, like `MyPass@123`, is saved exactly like that.

This causes a few problems. A user created from the admin page can never log in, because login
expects a hashed password and gets "Invalid email or password". If you change someone's password
from the admin page, even the superuser's, they get locked out, and there's no "forgot password"
page to get back in. And anyone with access to the admin page or the database can read the
passwords.

There are also a couple of smaller login bugs. Just opening the login page logs you out
(`users/views.py:9-10`). And emails are case sensitive, so `a@gmail.com` and `A@gmail.com` can be
two different accounts, and typing your email with a capital letter in a different place won't
work.

**Impact:** Admins can't add or manage users from the admin page without locking them out, and
real passwords are exposed. Since people reuse passwords, their other accounts are at risk too.

**Recommended improvement:** Use Django's `UserAdmin`, which hides the password and has a proper
"change password" form. Reset any passwords that were set from the admin page. Save emails in
lowercase, and only log people out when they click "Logout".

**Priority rationale:** It's a security problem and it locks people out, and the fix is small
because Django already has the safe version built in.

### 2. Everything is crammed into one class

**Problem:** Almost all the work in this tool is done by a single class, `PolygonAPI`
(`polygon_api.py`). Going by its name, it should only talk to Polygon. But it also manages the
Redis cache, uploads files to S3 and compiles the custom checker. These are four separate jobs
that have nothing to do with each other, and they're all mixed together in one big file. Because
of that, some code is repeated inside it and some of it isn't used anywhere.

**Impact:** The code is hard to read and hard to change. If something goes wrong with the S3
upload, you have to dig through Polygon and cache code to find it. A small change in one part can
break another part without you noticing, and since every button uses this class, any change to it
is risky. It's also hard to test one part on its own.

**Recommended improvement:** Give each job its own class: one that only talks to Polygon, one for
the Redis cache, one for uploading to S3, and one for the checker. Each class does one thing, so
it's easy to find, fix and test. While splitting it up, the repeated code can be merged and the
unused code deleted.

**Priority rationale:** Every part of the tool depends on this class, so it slows down every
future change. It's below issue 1 because that one is a security problem and much quicker to fix.

### 3. Two login checks do the same thing

**Problem:** The project turns on two login backends (`settings.py:189-192`): its own
`EmailBackend` and Django's `ModelBackend`. The user model already logs in with email, so
`ModelBackend` can do everything `EmailBackend` does. When the password is wrong, the first one
says no, and Django tries the second one, which checks the same password all over again.

**Impact:** Every wrong password gets checked twice, which wastes time since password checks are
slow on purpose. It can also give away which emails have an account, because a wrong password on
a real account takes longer to fail than one on an email that doesn't exist.

**Recommended improvement:** Remove `EmailBackend` and just keep `ModelBackend`. Login keeps
working the same way.

**Priority rationale:** Login still works for real users, so it's third. But it's wasted work on
every failed login, and the fix is just deleting one file and one line.

## Edge case analysis

### Q1

> A Polygon problem has 0 sample test cases but 15 regular test cases. What happens when you
> migrate this problem?

It goes through fine with no warning, but students don't get any examples.

None of the 15 tests are marked as samples, so no samples are saved and the page still says
"success". Students won't see any example input or output, even if the statement talks about "the
first example". All 15 tests still reach the judge, so judging itself works.

### Q2

> A problem is migrated with 20 test cases. Later, the problem setter removes 8 test cases on
> Polygon (now 12 remain). The problem is re-migrated. What happens?

The judge gets the right 12 tests, but the database still has all 20.

In the database, the 12 new tests just overwrite the first 12 rows, and the other 8 are never
deleted (`views.py:530-538`). So the database says 20 tests for a problem that only has 12. S3 is
fine, because the upload clears out the old files before putting up the new 12. Every step still
says "success".

### Q3

> Two different Polygon problems have the exact same title: "Two Sum". You migrate the first one
> successfully. Then you try to migrate the second one. What happens?

The first one is fine, but the second one fails to save.

Both titles turn into the same slug, `two-sum` (`views.py:284`), and two problems can't share a
slug. So the second one fails with a "duplicate key" error. There's no way to change the slug from
the tool, so the only options are renaming the problem on Polygon or fixing it directly in the
database. The first problem isn't affected, because problems are matched by their Polygon ID, not
their title.

### Q4

> When test cases are saved to the database via "Migrate Test Cases to DB", some data is
> intentionally discarded. What data is lost? Why might this cause problems?

The database only keeps a short preview of each test. The full tests are only in S3.

- **Tests are cut to 260 characters** (`views.py:526-527`). Anything longer is cut off, and
  nothing shows that it was cut, so the saved test looks complete when it isn't.
- **Failed downloads are lost.** A test that failed to download comes through empty and is
  skipped without any warning, so the database ends up with fewer tests than the problem has.
- **Edits from `/admin` are overwritten.** If someone fixes a test in the admin page, the next
  migration replaces it with the Polygon version.

## Other problems found

Smaller issues, not ranked.

### Starting the project

- No migration for the `notes` and `genie_chat` columns, so Fetch crashed. Fixed with
  `makemigrations`.
- The Polygon key check runs when settings load, so `migrate` and `createsuperuser` crash without
  Polygon keys, even though they don't need them.

### Creating a user

- `createsuperuser` accepts a username that's already taken, then crashes at the end and you lose
  everything you typed.
- Graduation year is optional but `createsuperuser` won't let you skip it.

### Fetching a problem

- "Main Correct Solution" can be a wrong-answer solution if none is marked as main.
- Titles that aren't in English give an empty slug.
- The statement preview shows raw HTML tags.

### Saving the problem to the database

- The statement is downloaded fresh but the samples come from the cache, so they can be from
  different versions.