# Documentation

All file paths are inside the `PolygonMigration/` folder.

## 2.1 User Flows

The tool is a single page (`/`). Every button on it sends a form to the same view, `index` in
`problems/views.py`. The view checks which hidden field came with the form to decide what to do.

### Flow 1: User login

**Endpoint:** `/users/login/` → `login_view` (`users/views.py:8-23`)

#### 1. What the user clicks or submits

The user opens `/`. If they aren't logged in, they're sent to `/users/login/`. They type their
email and password and click **Login**.

#### 2. What data the frontend sends to the backend

A POST with `email`, `password` and `csrfmiddlewaretoken` (a hidden token that stops fake form
posts from other sites).

#### 3. What the backend does, in order

1. Django checks the CSRF token (`settings.py:49`). A bad token gets a 403 error.
2. If someone is already logged in, they're logged out first. This happens even when the page is
   only opened, not submitted (`users/views.py:9-10`).
3. It checks the email and password with `authenticate()` (`users/views.py:14`). Two checkers run
   one after the other (`settings.py:189-192`): the project's own `EmailBackend` and Django's
   `ModelBackend`. Both do the same check, so a wrong password gets checked twice.
4. No match: the login page is shown again with an error (`users/views.py:21-22`).
5. Match, but not staff: the login page again, with a different error (`users/views.py:19-20`).
6. Staff: `login()` starts a session and sends the user to `/` (`users/views.py:16-18`).

#### 4. Which external APIs are called

None. Login only uses the local database.

#### 5. What is read or written in the database or storage

- **Reads** `users_user`: `email`, `password`, `is_active`, `is_staff`.
- **Writes** `users_user.last_login` and a new session row in `django_session`.
- **Cookie:** the browser gets a `sessionid` cookie that lasts 1 day (`settings.py:123`).

#### 6. What the user sees when the action completes

- **Success:** the main page, with "Welcome, *first name last name*" at the top.
- **Wrong email or password:** "Invalid email or password."
- **Not staff:** "You do not have staff access."

### Flow 2: Fetching a problem from Polygon

**Endpoint:** `POST /` → `index` (`problems/views.py:88-573`)

#### 1. What the user clicks or submits

Types a Polygon problem ID on the main page and clicks **Fetch Problem**.

#### 2. What data the frontend sends to the backend

A POST with `problem_id` and the CSRF token. The page first shows a loading screen that says it
"may take 3-4 minutes".

#### 3. What the backend does, in order

1. Checks the user is logged-in staff (`views.py:88`) and loads all tags for the tag picker
   (`views.py:110-122`).
2. If the problem is already in the database, it loads its tags and difficulty and gets the main
   solution from Polygon (`views.py:146-184`). If no solution is marked as main, it just takes the
   first one in the list (`views.py:171-173`). That could be a wrong solution, but the page still
   calls it "Main Correct Solution".
3. Gets the time and memory limits (`views.py:235`).
4. Downloads the newest built package (a ZIP file), reads `problem.html` from it, and pulls out the
   title, statement, input/output format and notes (`polygon_api.py:129-241`, `views.py:19-86`).
   The ZIP is deleted afterwards. This is the last *built* package, so if someone edits the
   statement on Polygon and doesn't build a new package, the tool shows the old statement.
5. Downloads every test, input and answer, one by one (`polygon_api.py:351-407`), and keeps them
   in Redis for 30 minutes (`views.py:259`). If a test fails to download, it's saved as empty and
   only a warning goes to the log (`polygon_api.py:399-402`).
6. Makes the slug (the short name used in the problem's URL) from the title (`views.py:284`).
   Non-English letters are dropped, so a Russian or Chinese title gives an empty slug.
7. Gets the checker type (`views.py:292-306`) and counts the tests (`views.py:308`).
8. Shows the page (`views.py:573`).

If anything fails, the error is shown and the problem's Redis cache is cleared
(`views.py:553-564`).

#### 4. Which external APIs are called

The Polygon API, one call after another:

| # | Polygon method | Where | Returns |
|---|---|---|---|
| 1 | `problem.updateWorkingCopy` | `views.py:160` | JSON (empty) |
| 2 | `problem.solutions` | `views.py:162` | JSON list |
| 3 | `problem.viewSolution` | `views.py:177` | plain text (code) |
| 4 | `problem.info` | `views.py:235` | JSON |
| 5 | `problem.info` (repeat of 4) | `polygon_api.py:150` | JSON |
| 6 | `problem.packages` | `polygon_api.py:155` | JSON list |
| 7 | `problem.package` | `polygon_api.py:187` | ZIP file |
| 8 | `problem.tests` | `polygon_api.py:364` | JSON list |
| – | `problem.testInput` and `problem.testAnswer`, for each test | `polygon_api.py:383`, `:390` | plain text |
| 9 | `problem.checker` | `views.py:292` | JSON |
| 10 | `problem.checker` (repeat of 9) | `polygon_api.py:421` | JSON |
| 11 | `problem.tests` (repeat of 8, only to count) | `polygon_api.py:304` | JSON list |

Calls 1 to 3 only run if the problem is already in the database. So the total is 11 calls plus 2
per test, or 8 plus 2 per test for a new problem. Calls 5, 10 and 11 ask for data the code
already has.

#### 5. What is read or written in the database or storage

- **Database:** nothing is written. It reads all tags, and the problem and its tags if it exists.
- **Redis:** each test is saved under `polygon_migration_test_cases_<id>_...` for 30 minutes
  (`polygon_api.py:799-844`).

#### 6. What the user sees when the action completes

The page reloads and shows:

- the title, slug, limits, checker and number of tests;
- the statement, input/output format and notes. These show up as raw HTML code (with the `<p>`
  tags visible), because the page escapes them (`index.html:207`);
- a table of all tests, showing the first 50 characters of each;
- the main solution, only if the problem is already in the database.

The two test buttons stay disabled until the problem is saved to the database.

### Flow 3: Migrating a problem to the database

**Endpoint:** `POST /` → `index` (`problems/views.py`), the same view as the fetch

#### 1. What the user clicks or submits

After a fetch, picks a difficulty and tags, and clicks **Create/Update problem in Database**.

#### 2. What data the frontend sends to the backend

A POST (`index.html:237-248`) with `problem_id`, `migrate_to_db=1`, `difficulty`, one `tags`
field per tag, and the CSRF token. If no difficulty is picked, the browser shows an alert and
sends nothing (`index.html:404-414`).

The server also reads a `new_tag` field (`views.py:131`), but the page never sends one.

#### 3. What the backend does, in order

1. **Runs the whole fetch again** (Flow 2), except the tests come from Redis
   (`views.py:146-329`, `:247-254`). That's 9 to 12 Polygon calls for things the user has
   already seen.
2. Checks a difficulty was sent (`views.py:334`). This only happens after all those calls.
3. Creates the problem, or updates it if the Polygon ID is already in the database
   (`views.py:340-388`). On an update, the slug is rebuilt from the title (`views.py:345`).
   `constraints` and `editorial` are always saved as empty, because the tool never fills them
   (`views.py:288-289`). The only way to fill them is from the admin page,
   <http://127.0.0.1:8000/admin/> → **Problems** → open a problem → **Content** section
   (`problems/admin.py:31`). If they were filled in there, a re-migration empties them again
   (`views.py:350-351`). If they were never filled in, nothing is lost.
4. Removes the problem's old tags and adds the selected ones, creating any new tags
   (`views.py:396-408`).
5. Saves the sample tests from Redis (`views.py:426-463`). Old samples are never deleted, so if a
   problem goes from 3 samples to 2, the 3rd one stays.
6. Gets the main solution from Polygon again (`views.py:470-495`).
7. Shows the page.

All database changes happen in one transaction (`views.py:187`), so if anything fails, none of
them are kept. The error always says "Migration failed and all changes have been rolled back",
even for something simple like a missing difficulty (`views.py:555`).

#### 4. Which external APIs are called

The same calls as the fetch, minus the test downloads, plus the solution calls again:

| # | Polygon method | Where | Returns |
|---|---|---|---|
| 1–3 | `updateWorkingCopy`, `solutions`, `viewSolution` | `views.py:160-177` | JSON, JSON list, text |
| 4–5 | `problem.info` twice | `views.py:235`, `polygon_api.py:150` | JSON |
| 6–7 | `problem.packages`, `problem.package` | `polygon_api.py:155`, `:187` | JSON list, ZIP |
| 8–9 | `problem.checker` twice | `views.py:292`, `polygon_api.py:421` | JSON |
| 10 | `problem.tests` (only to count) | `polygon_api.py:304` | JSON list |
| 11–12 | `solutions`, `viewSolution` again | `views.py:473`, `:488` | JSON list, text |

That's 12 calls, or 9 for a new problem. If the Redis cache has expired, add 1 plus 2 per test.

#### 5. What is read or written in the database or storage

- **Writes:**
  - `problems_problem`: title, slug, difficulty, statement, input/output format, notes, limits,
    checker type, test count, and empty constraints and editorial (`views.py:340-388`)
  - `problems_problemtag`: any new tag (`views.py:403`)
  - `problems_problem_extra_tags`: old tag links removed, new ones added (`views.py:396-404`)
  - `problems_sampletestcase`: input, output and order of each sample (`views.py:449-462`)
- **Reads:** the same as Flow 2, plus the problem's existing samples (`views.py:441`).
- **Redis:** the tests are read twice (`views.py:248`, `:426`).

#### 6. What the user sees when the action completes

- **No difficulty picked:** a browser alert, and nothing is sent.
- **Success:** a blue box, "Problem '*title*' created in database successfully." (or "updated").
  The page also shows the database ID, the Algopath link (built from the slug) and the main
  solution. The two test buttons are now enabled.
- **Failure:** a red box, "Migration failed and all changes have been rolled back. Reason: ..."

### Flow 4: Migrating test cases to the database

**Endpoint:** `POST /` → `index` (`problems/views.py`), the same view as the fetch

#### 1. What the user clicks or submits

Clicks **Migrate Test Description to Database** under the test table. The button is disabled
until the problem is in the database.

#### 2. What data the frontend sends to the backend

A POST with `problem_id`, `migrate_test_cases_to_db=1` and the CSRF token
(`index.html:310-315`).

#### 3. What the backend does, in order

1. Runs the whole fetch again, with the tests from Redis (`views.py:146-329`). That's 10 Polygon
   calls this button doesn't need.
2. Checks the problem is in the database (`views.py:498`), again only after those calls.
3. Reads the tests from Redis (`views.py:505`), or downloads them again if the cache expired.
4. Saves each test, keeping only the first 260 characters of the input and the answer
   (`views.py:516-549`). Empty tests are skipped. Existing rows are updated by position, and
   extra old rows are never deleted.
5. Shows the page.

#### 4. Which external APIs are called

10 Polygon calls, all repeats of the fetch (`views.py:160-308`). If the cache has expired, add 1
plus 2 per test.

#### 5. What is read or written in the database or storage

- **Writes** `problems_problemtestcase`: input, output, `is_sample`, description and order of each
  test (`views.py:530-548`).
- **Reads** the same as Flow 2, plus the problem's existing tests (`views.py:516`).
- **Redis:** reads the tests (`views.py:505`).

#### 6. What the user sees when the action completes

A green box: "Test cases description migrated to database Successfully."

### Flow 5: Uploading test cases to cloud storage

**Endpoint:** `POST /` → `index` (`problems/views.py`), the same view as the fetch

We store tests in AWS S3, so `.env` has `STORAGE_PROVIDER=s3`. The code and the page still use
the word "Azure" in a few places (the button, the form field, the messages) because the tool was
first written for Azure. Those are just old names. With `STORAGE_PROVIDER=s3`, every file goes to
S3.

#### 1. What the user clicks or submits

Clicks the button labelled **Migrate Test Cases to Azure**. It's disabled until the problem is in
the database.

#### 2. What data the frontend sends to the backend

A POST with `problem_id`, `migrate_to_azure=1` and the CSRF token (`index.html:250-255`). The page
shows a "Migrating to Azure..." loading screen.

#### 3. What the backend does, in order

1. Gets the main solution from Polygon (`views.py:149-184`).
2. Checks the problem is in the database (`views.py:193-197`). If not, it shows an error and
   stops.
3. Deletes the Redis keys `oj_dev_with_redis_storage_test_cases_<db id>*` (`views.py:208` →
   `polygon_api.py:771-797`). Nothing in this project writes these keys. They belong to the
   judge.
4. Uploads the tests to S3 (`views.py:218` → `migrate_to_storage`, `polygon_api.py:708-769`):
   - reads the tests from Redis, or from Polygon if the cache expired (`polygon_api.py:731-737`);
   - `get_storage()` sees `STORAGE_PROVIDER=s3` and creates an `S3BlobManager` with the AWS keys
     from `.env` (`storage.py:8-14`, `S3Testcase.py:11-20`);
   - deletes every file under `test_cases/<db id>/` in the bucket (`polygon_api.py:750` →
     `empty_blob`, `S3Testcase.py:37-46`). It lists the files and deletes them in batches;
   - uploads each test as two files, `01` (input) and `01.a` (answer), one `put_object` call each
     (`S3Testcase.py:28-35`). Empty tests are skipped. If an upload fails, the error stops the
     whole upload (`S3Testcase.py:33-35`).
5. If the problem has a custom checker, tries to compile it with `g++` on this server and upload
   it to the same folder (`polygon_api.py:767` → `:570-706`). If compiling fails, it uploads the
   `.cpp` source instead. Checker errors only go to the log.
6. Runs the whole fetch again (`views.py:234-329`) and shows the page.

What happens when something fails:

- **An upload to S3 fails:** the error is shown. The old files are already deleted and the files
  uploaded before the error stay, so the problem is left with only some tests in S3.
- **Something fails after the upload** (for example the fetch in step 6): the tool deletes all of
  the problem's files in S3 (`views.py:557-562`). The old files were already deleted in step 4, so
  the problem is left with no tests at all.

#### 4. Which external APIs are called

- **Polygon:** 12 calls. The 3 solution calls, `problem.checker` twice before the upload
  (`views.py:211`, `polygon_api.py:588`), then the 7 fetch calls again. So `problem.checker` runs
  4 times in one click. A custom checker adds 1 to 3 `problem.viewFile` calls, and an expired
  cache adds 1 plus 2 per test.
- **AWS S3** (through `boto3`):
  - `ListObjectsV2` to find the old files, and `DeleteObjects` to delete them
    (`S3Testcase.py:40-44`);
  - `PutObject` twice per test (input and answer), plus once for the checker
    (`S3Testcase.py:25`).

#### 5. What is read or written in the database or storage

- **Database:** nothing written. Reads the problem's `id`, which names the S3 folder
  (`views.py:193`).
- **Redis:** deletes the judge's `oj_dev_...` keys and reads the cached tests
  (`polygon_api.py:792-794`, `:731`).
- **S3:** replaces everything under `test_cases/<db id>/` in the bucket.

#### 6. What the user sees when the action completes

A green box: "Test cases migrated to Azure Blob Storage successfully." It says Azure, but the
files are in S3. With a custom checker it adds "was also compiled and uploaded", even if only the
source was uploaded. If anything fails, a red box: "Migration failed and all changes have been
rolled back. Reason: ..."

## 2.2 Polygon API and cloud storage

### Polygon endpoints used

Every call is a POST to `https://polygon.codeforces.com/api/<method>` (`polygon_api.py:26`).

| Endpoint | Used for | Where |
|---|---|---|
| `problem.info` | time and memory limits | `polygon_api.py:254` |
| `problem.packages` | list of built packages, to find the newest | `polygon_api.py:155` |
| `problem.package` | download the package ZIP, to read `problem.html` | `polygon_api.py:172-187` |
| `problem.tests` | list of tests (number, sample or not, description) | `polygon_api.py:304`, `:364` |
| `problem.testInput` | one test's input | `polygon_api.py:383` |
| `problem.testAnswer` | one test's answer | `polygon_api.py:390` |
| `problem.checker` | checker name, standard (`std::...`) or custom | `views.py:292`, `polygon_api.py:421` |
| `problem.viewFile` | source code of a custom checker | `polygon_api.py:452-479` |
| `problem.solutions` | list of solutions, to find the main one | `views.py:162`, `:473` |
| `problem.viewSolution` | code of the main solution | `views.py:177`, `:488` |
| `problem.updateWorkingCopy` | called before reading solutions | `views.py:160` |

There are also helpers for `problem.statements`, `problem.script`, `problem.files` and
`problem.viewFile` (`polygon_api.py:258-349`), but nothing calls them.

### How requests are signed

Polygon needs an API key and secret, read from `.env` (`POLYGON_API_KEY`, `POLYGON_API_SECRET`).
The app won't start without them (`settings.py:125-129`). Every request is signed in
`_generate_api_sig` (`polygon_api.py:35-68`):

1. Add `apiKey` and `time` (the current Unix time) to the parameters.
2. Sort the parameters by name and join them as `name=value&...`.
3. Build the text `<6 random chars>/<method>?<params>#<secret>`.
4. Hash it with SHA-512. `apiSig` is the 6 random chars followed by the hash.

The request then sends `apiKey`, `time`, `apiSig` and the normal parameters as form fields
(`polygon_api.py:88-96`). The secret itself is never sent.

Polygon replies with JSON `{status, result, comment}`. If `status` is `FAILED`, the code raises an
error with the comment (`polygon_api.py:105-106`). Tests, solutions and files come back as plain
text, and the package as ZIP bytes. No timeout is set on these requests (`polygon_api.py:96`,
`:187`), so if Polygon hangs, the page hangs too.

### S3 storage

We use AWS S3. The code can also talk to Azure, and `STORAGE_PROVIDER` in `.env` picks which
one (`storage.py:4-25`). We set it to `s3`. This matters: if it's missing, the code falls back to
Azure (`storage.py:6`).

With `s3`, `get_storage()` creates an `S3BlobManager` (`S3Testcase.py`). It needs these in
`.env`:

| Variable | What it is |
|---|---|
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | the bucket's region |
| `AWS_S3_BUCKET_NAME` | the bucket, `polygon-testcases-puzzled` in our setup |

If any of the first three is missing, the upload fails straight away with an error
(`S3Testcase.py:12-13`).

Each problem gets one folder, named after its database ID, not its Polygon ID:

```text
s3://polygon-testcases-puzzled/
└── test_cases/
    └── <db problem id>/        e.g. test_cases/1/
        ├── 01                  input of test 1
        ├── 01.a                answer of test 1
        ├── 02
        ├── 02.a
        ├── ...
        └── custom_checker.cpp  only if the problem has a custom checker
```

- **Test files** are numbered by their position in the list, with 2 digits
  (`S3Testcase.py:29`). The input has no extension and the answer ends in `.a`. A skipped empty
  test leaves a gap, like `01`, `03`.
- **Custom checker:** if it compiles, the binary is uploaded as `custom_checker` (or
  `custom_checker.exe` on Windows). If it doesn't compile, the source is uploaded as
  `custom_checker.cpp` instead (`polygon_api.py:668`).
- **Contents:** each file is plain text, uploaded with `put_object` (`S3Testcase.py:22-26`).
- **Updating:** everything in the folder is deleted first (`S3Testcase.py:37-46`), then the new
  files are uploaded.
- **Errors:** an upload error stops the upload and shows on the page, but files uploaded before
  it stay (`S3Testcase.py:33-35`). When deleting, S3 can fail on single files without raising an
  error, and the code doesn't check for that (`S3Testcase.py:43-44`), so an old file could stay
  behind.
- **Old folders:** if a problem is deleted from the database and migrated again, it gets a new ID
  and a new folder. The old folder is never deleted.