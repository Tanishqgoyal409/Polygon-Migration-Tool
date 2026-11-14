# Issues Analysis

All file paths are inside the `PolygonMigration/` folder.

## Product Issues

### 1. The tool says "success" even when tests or the checker are missing

**Problem:**
To copy a problem, the tool downloads each test from Polygon. If one download fails, the tool
doesn't stop. It saves that test as empty and later skips it (`polygon_api.py:399-402`,
`views.py:524`). At the end it still shows a "successfully" message.

The same happens with custom checkers (the program that decides if an answer is right). The
checker usually fails to build, because a file it needs (`testlib.h`) is never downloaded. Then only
its source file is uploaded, but the page says it was "compiled and uploaded" (`views.py:230-231`).

**Impact:**
A problem can go live with missing tests or a broken checker, and nobody knows. Wrong answers can
get marked as correct.

**Recommended improvement:**
If a download fails, try again. If it still fails, stop and say which test failed. At the end, show
a count like "12 of 12 tests uploaded", and say honestly whether the checker was built.

**Priority rationale:**
This is first because the tool's only job is to copy problems correctly. Here it fails and still
says it worked.

---

### 2. Migrating a problem again overwrites or deletes data

**Problem:**
When a problem changes on Polygon and is copied again:

- **Hand-written content is erased.** The editorial and constraints are always replaced with blanks
  (`views.py:350-351`). Staff write these by hand, so their work is lost.
- **Removed tests stay behind.** If a problem goes from 20 tests to 12, old tests 13 to 20 are never
  deleted from the database (`views.py:530`).
- **All tests can disappear.** Old tests are deleted from S3 before the new ones are uploaded
  (`polygon_api.py:750`). If the upload stops halfway, only some tests are left. If something fails
  after the upload, the tool deletes all the new tests too (`views.py:557-562`).

**Impact:**
After an update, a problem can have old tests, wrong tests or no tests at all, and its editorial
can be gone. The page still says "success".

**Recommended improvement:**
Only update what comes from Polygon, and never touch the editorial. Delete old tests properly.
Upload the new tests to S3 first, and remove the old ones only after that works, so no data is lost.

**Priority rationale:**
Second because it also loses data, but only when a problem is copied again. Issue 1 can happen
every time.

---

### 3. Every button downloads the whole problem again

**Problem:**
All the buttons submit the same form to the same page, and every click also downloads the entire
problem from Polygon again, even when the button only needs to do one small job
(`views.py:234-329`). Pressing F5 afterwards repeats whatever you last clicked.

Times from the log for a problem with 12 tests:

| Button | Time |
|---|---|
| Fetch | about 20 s |
| Save problem | 6 s |
| Save tests | 10 s |
| Upload tests | 24 s |

Each extra test adds about 1 second. Servers like gunicorn stop a request after 30 seconds by
default, so Fetch would fail at around 20 tests, and Upload at around 17.

**Impact:**
Users wait on every click, and big problems can't be copied at all. If time runs out during an
upload, the problem is left with only some of its tests.

**Recommended improvement:**
Download the problem once and reuse it for the other buttons. Run big jobs in the background asynchronously and ensure reliability using retries.

**Priority rationale:**
Third because it mostly wastes time, while issues 1 and 2 break data. It's still in the top three
because it affects every user on every click.

---

## Code Issues

### 1. Passwords set from /admin are saved as plain text, and that user gets locked out

**Problem:**
Passwords should be scrambled (hashed) before they are saved. `createsuperuser` does this. But the
admin page (`/admin`) saves the password exactly as typed, like `MyPass@123`. This is because it
uses a plain admin page (`users/admin.py:4-5`), not Django's safe `UserAdmin`.

So:
- **A user created from `/admin` can never log in.** Login expects a scrambled password and finds
  plain text, so it always says "Invalid email or password".
- **Changing any password from `/admin` locks that person out.** This includes the superuser. There
  is no "forgot password" page, so the only fix is running a command on the server.
- **Passwords can be read.** Any admin can see them in `/admin`, and anyone with the database can
  read them.

Smaller bugs from the same hand-written login code:
- Opening the login page logs you out (`users/views.py:9-10`).
- **The same email can be two different users.** When a user is created, only the part after `@`
  is made lowercase (`users/models.py:9`), and the admin page saves emails exactly as typed. Login
  also needs the exact same capital letters (`users/backends.py:11`). So `a@gmail.com` and
  `A@gmail.com` can be two separate accounts, and typing your email with a different capital letter
  makes login fail.

**Impact:**
Admins can't add or manage users from `/admin` without locking them out. Real passwords are exposed,
and people reuse passwords, so their other accounts can be at risk too.

**Recommended improvement:**
- Use Django's `UserAdmin` for the admin page. It hides the password and gives a proper
  "Change password" form: you type the new password twice, it checks that it's strong enough, and it
  scrambles it before saving.
- Reset every password that was already set from `/admin`.
- Save every email in lowercase, and ignore capital letters when logging in.
- Only log someone out when they click "Log out", not when they open the login page.

**Priority rationale:**
First because it's a big security hole and it locks people out. The fix is small, because Django
already has the safe version.

---

### 2. One class does four different jobs

**Problem:**
`PolygonAPI` (`polygon_api.py`) should only talk to Polygon. But it also manages the cache, uploads
tests to s3 and builds the checker. Some of its code is copied (the cache setup 4 times, the checker
upload twice), and some of it is never used.

**Impact:**
It's hard to know where to look when something breaks. A fix to the checker upload has to be made
in two places. And since every flow uses this class, any change to it is risky.

**Recommended improvement:**
Split it into smaller parts, one per job: Polygon, cache, s3 and checker. Delete the code nobody
uses.

**Priority rationale:**
Second, because every flow depends on this class, so it slows down every future change. It comes
after issue 1 because issue 1 is a security hole and much quicker to fix.

---

### 3. Two login checks do the same job

**Problem:**
The project turns on two login checks: its own `EmailBackend` and Django's built-in `ModelBackend`
(`settings.py:189-191`). Both do the same thing: find the user by email and check the password.
`EmailBackend` (`users/backends.py:4-15`) just repeats what `ModelBackend` already does. 

When a password is wrong, `EmailBackend` says no, so Django tries `ModelBackend`, which checks the
same password again.

**Impact:**
- **Every wrong password is checked twice.** Checking a password is slow on purpose, so this
  doubles the time and server work for every failed login.
- **It shows which emails have an account.** A wrong password on a real email takes about twice
  as long as on an email that doesn't exist. Someone can use that difference to find out who has
  an account.
- It's extra code that does nothing useful, and it confuses anyone reading the login flow.

**Recommended improvement:**
Delete `EmailBackend` and keep only Django's `ModelBackend` in `settings.py`. Login keeps working
the same way, since email is already the login field.

**Priority rationale:**
Third because login still works for real users. But it wastes server work on every failed login and
leaks which emails exist, and the fix is just deleting one file and one line.

---

## Edge Case Analysis

### Q1

> A Polygon problem has 0 sample test cases but 15 regular test cases. What happens when you migrate this problem?

It works with no warning, but students get no examples.

None of the 15 tests is marked as an example (`polygon_api.py:376`), so no examples are saved
(`views.py:439-463`). The page still says "success". Students see no example input or output, even
if the statement says "in the first example...". All 15 tests still reach the judge, so judging
works.

---

### Q2

> A problem is migrated with 20 test cases. Later, the problem setter removes 8 test cases on Polygon (now 12 remain). The problem is re-migrated. What happens?

The judge gets the right 12 tests as it fetches from the s3 and for updating in s3 we need to delete all the tests earlier saved and then new tests are saved so it will just has 12 tests and it will be the source of truth as db tests are truncated also, but the database keeps the 8 removed ones.

The 12 new tests replace the first 12 old ones in order, and old tests 13 to 20 are never deleted
(`views.py:530-538`). So the database shows 20 tests while the problem says 12. The upload deletes
all the old files and uploads the 12 new ones (`polygon_api.py:750`), so the judge is fine. Every
step says "success".

---

### Q3

> Two different Polygon problems have the exact same title: "Two Sum". You migrate the first one successfully. Then you try to migrate the second one. What happens?

The second one fails to save. The first one is fine, because it has a constraint of unique over the slug.

Each problem gets a short web name (slug) made from its title, so both become `two-sum`
(`views.py:284`). Two problems can't share a slug (`models.py:58`), so the second one is rejected
with a red "duplicate key" error. The tool has no way to change the slug, so the only fixes are
renaming the problem on Polygon or editing the database by hand. The first problem is safe because
problems are matched by their Polygon ID, not their title.

---

### Q4

> When test cases are saved to the database via "Migrate Test Cases to DB", some data is intentionally discarded. What data is lost? Why might this cause problems?

**Thrown away on purpose:**
- Everything after the first 260 characters of each input and output (`views.py:526-527`).
- Tests with an empty input or output. They are skipped completely (`views.py:524`).

**Lost by accident:**
- **Changes made by hand in `/admin`.** If someone edits a test's description, the next migration
  writes over it (`views.py:533-537`).
- **Tests that failed to download.** They become empty and get skipped too, with no warning.

**Why it matters:** most real tests are longer than 260 characters, so the saved copy is cut off,
and nothing marks it as cut. The database ends up with fewer tests than the problem's test count
says. And without the test number, you can't tell which Polygon test a row came from.

---

## Notes

- The project as given crashes on Fetch because one database update file (a migration) is missing.
  I didn't rank it because one command (`makemigrations`) fixes it, and I've already done that.
- Everything else I found is in `BUGS_FOUND.md`.
