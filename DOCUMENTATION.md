# Documentation

## 2.1 User Flows

All file paths are inside the `PolygonMigration/` folder.

### Flow 1: User login

**Endpoint:** `/users/login/` → `login_view` in `users/views.py`

#### 1. What the user clicks or submits

The user opens `/`. If they are not logged in, they are redirected to `/users/login/`. They enter
their email and password and click **Login**.

#### 2. What data the frontend sends to the backend

A form POST to `/users/login/` with `email`, `password` and `csrfmiddlewaretoken` (a hidden
security token).

#### 3. What the backend does, in order

All of this happens in `login_view` (`users/views.py:8-23`) unless noted.

1. Django checks the security token (CSRF middleware, `settings.py:48`). If it is wrong, it
   returns 403.
2. If the user is already logged in, they are logged out first (`users/views.py:9-10`). This
   also happens when the page is only opened (GET).
3. It calls `authenticate()` with the email and password (`users/views.py:14`). Two backends run
   in order (`AUTHENTICATION_BACKENDS`, `settings.py:189-192`):
   - `EmailBackend` (`users/backends.py:5-16`) finds the user by email and checks the password.
   - If that fails, Django's `ModelBackend` repeats the same lookup and check. **This is an
     issue:** the second backend adds nothing, so every wrong password is checked twice.
4. If no user matches, the login page is shown again with an error (`users/views.py:21-23`).
5. If the user is not staff, the login page is shown again with a different error
   (`users/views.py:19-20`).
6. If the user is staff, `login()` creates a session and redirects the user to `/`
   (`users/views.py:16-18`). On the way out, Django's `SessionMiddleware` (`settings.py:46`)
   saves the session and adds the `sessionid` cookie to the response headers.

#### 4. Which external APIs are called

None. Login only uses the local database.

#### 5. What is read or written

- **Database** (PostgreSQL, `settings.py:73-85`):
  - **WRITE**
    - `users_user`: `last_login`
    - `django_session`: a new session for the user (any old one is deleted)
  - **READ**
    - `users_user`: `email`, `password`, `is_active`, `is_staff` (`users/backends.py:11`)
- **Cookie:** the browser receives `sessionid` in the response headers. It lasts 1 day
  (`SESSION_COOKIE_AGE`, `settings.py:122`), and the browser sends it back on every later
  request.

#### 6. What the user sees

- **Success:** a 302 redirect to the main page, which shows "Welcome, *name*".
- **Wrong email or password:** the login page again, with "Invalid email or password."
- **Not a staff account:** the login page again, with "You do not have staff access."

---

### Flow 2: Fetching a problem from Polygon

**Endpoint:** `POST /` → `index` in `problems/views.py`

#### 1. What the user clicks or submits

The user types a Polygon problem ID on the main page and clicks **Fetch Problem**.

#### 2. What data the frontend sends to the backend

A form POST to `/` with `problem_id` and `csrfmiddlewaretoken`. The page first shows a loading
screen ("may take 3-4 minutes"), then sends the form 50 ms later.

#### 3. What the backend does, in order

All of this happens in `index` (`views.py:89-573`). Polygon calls go through `PolygonAPI`
(`polygon_api.py`).

1. Checks that the user is logged-in staff (`views.py:88`), and loads all tags for the tag picker
   (`views.py:110-122`).
2. If the problem is already in the database, it loads its tags and difficulty and gets the main
   solution from Polygon (`views.py:146-184`).
   - **Issue:** if no solution is tagged as main (`MA`), it takes the first one in the list
     (`views.py:171-173`). That can be a wrong solution, but it is still shown as "Main Correct
     Solution".
3. Gets the problem info: time and memory limits (`views.py:235`).
4. Downloads the package ZIP, reads `problem.html` from it, then deletes the ZIP
   (`polygon_api.py:129-241`). It takes the title, statement, input/output format and notes from
   `problem.html` (`parse_problem_html`, `views.py:19-86`).
5. Downloads every test: first the list of tests, then each test's input and answer
   (`get_all_test_cases`, `polygon_api.py:351-407`). It saves them in Redis for 30 minutes
   (`views.py:259`).
   - **Issue:** a test that fails to download is saved as empty, with only a log warning
     (`polygon_api.py:399-402`). The empty test is cached too, and the migrate actions later read
     this cache and silently skip it (`views.py:447`, `:524`, `polygon_api.py:756`).
6. Builds the details: title, slug and limits (`views.py:283-291`).
   - **Issue:** `slugify(title)` (`views.py:284`) drops non-English letters, so a Russian or
     Chinese title gives an empty slug.
7. Gets the checker type (`views.py:292-306`) and the number of tests (`views.py:308`).
8. Renders `index.html` with the result (`views.py:573`).

If anything fails, it shows the error and clears the Redis cache (`views.py:553-564`).

#### 4. Which external APIs are called

The **Polygon API**. Each call is signed with the API key and secret from `.env`
(`polygon_api.py:35-114`). The calls run one after another, in this order:

| # | Polygon method | Where in the code | Returns |
|---|---|---|---|
| 1 | `problem.updateWorkingCopy` | `views.py:160` | JSON (empty) |
| 2 | `problem.solutions` | `views.py:162` | JSON list |
| 3 | `problem.viewSolution` | `views.py:177` | plain text (solution code) |
| 4 | `problem.info` | `views.py:235` → `get_problem_info` | JSON |
| 5 | `problem.info` ⚠ repeat of 4 | `views.py:239` → `download_and_extract_package` (`polygon_api.py:150`) | JSON |
| 6 | `problem.packages` | same function (`polygon_api.py:155`) | JSON list |
| 7 | `problem.package` | same function (`polygon_api.py:187`) | ZIP file |
| 8 | `problem.tests` | `views.py:256` → `get_all_test_cases` (`polygon_api.py:364`) | JSON list |
| – | `problem.testInput` + `problem.testAnswer`, for each test | same function (`polygon_api.py:383`, `:390`) | plain text |
| 9 | `problem.checker` | `views.py:292` | JSON |
| 10 | `problem.checker` ⚠ repeat of 9 | `views.py:306` → `get_custom_checker_info` (`polygon_api.py:421`) | JSON |
| 11 | `problem.tests` ⚠ repeat of 8 | `views.py:308` → `get_test_cases` (`polygon_api.py:304`), only to count them | JSON list |

Calls 1–3 run only if the problem is already in the database.

**Total:** 11 calls + 2 per test case, or 8 + 2 per test case for a new problem.
- **Issue:** calls 5, 10 and 11 fetch data the code already has.

Removing these repeats saves time and API calls.

#### 5. What is read or written

- **Database:**
  - **WRITE**
    - nothing
  - **READ**
    - `users_user`: `is_staff`, `first_name`, `last_name` of the logged-in user
    - `problems_problemtag`: `tag_name` of all tags, for the tag picker (`views.py:110`)
    - `problems_problem`: `id`, `slug`, `difficulty`, if the problem exists (`views.py:146`)
    - `problems_problem_extra_tags`: the problem's tags (`views.py:152`)
- **Redis:** saves each test under `polygon_migration_test_cases_<id>_...` for 30 minutes
  (`polygon_api.py:799-844`). These keys are deleted in case of transaction rollback.
  (`polygon_api.py:901-934`).

#### 6. What the user sees

The page reloads and shows the problem:

- the title, slug, limits, checker and number of tests;
- the statement, input/output format and notes;
- a table of all tests, showing the first 50 characters of each;
- the main solution, only if the problem is already in the database.

Below that are the buttons for the next steps. The two test-case buttons stay disabled until the
problem is saved to the database.

---

### Flow 3: Migrating a problem to the database

**Endpoint:** `POST /` → `index` in `problems/views.py` (the same view as the fetch)

#### 1. What the user clicks or submits

After a fetch, the user picks a difficulty and tags, and clicks **Create/Update problem in Database**.

#### 2. What data the frontend sends to the backend

A normal form POST to `/` (`index.html:237-248`) with:

- `problem_id`
- `migrate_to_db=1`
- `difficulty`
- one `tags` field per selected tag
- `csrfmiddlewaretoken`

Before sending, the page checks that a difficulty is picked and shows an alert if not. It then
shows the "Migrating to database..." loading screen (`index.html:404-414`). The browser loads a whole new page.

- **Issue:** the backend reads a `new_tag` field that the form never sends (`views.py:131`,
  `:411-418`).

#### 3. What the backend does, in order

1. **Runs the whole fetch again** (Flow 2, steps 1–8, `views.py:146-329`). The only difference is
   that the tests are read from the Redis cache instead of Polygon (`views.py:247-254`).
   - **Issue:** everything the user just reviewed is downloaded again, which adds 9–12 Polygon calls (see point 4).
2. Checks that a difficulty was sent (`views.py:334`).
   - **Issue:** this check only runs after all the Polygon calls.
3. Creates the problem, or updates it if it already exists (`views.py:340-388`).
4. Replaces the problem's tags with the selected ones, creating any new tags
   (`views.py:396-418`).
5. Reads the tests from Redis again (`views.py:426`) and saves the samples (`views.py:439-463`).
   - **Issue (High):** the statement was just downloaded again, but the samples come from the cache made at fetch time. If the problem changed on Polygon in between, the two don't match.
   - **Issue (High):** old samples are never deleted. If a problem goes from 3 samples to 2, the third one stays.
6. Gets the main solution from Polygon again (`views.py:470-495`).
7. Renders the whole `index.html` again (`views.py:573`).

All the database changes run in one transaction (`views.py:187`), so if anything fails, none of
them are kept. The error is shown and the Redis cache is cleared (`views.py:553-564`).

- **Issue:** a missing difficulty is shown as "Migration failed and all changes have been rolled
  back" (`views.py:555`).

#### 4. Which external APIs are called

The **Polygon API**. It makes the same calls as the fetch, except the test downloads, which come
from Redis:

| # | Polygon method | Where in the code | Returns |
|---|---|---|---|
| 1–3 | `problem.updateWorkingCopy`, `problem.solutions`, `problem.viewSolution` ⚠ repeat of fetch | `views.py:160-177` | JSON, JSON list, plain text |
| 4–5 | `problem.info` twice ⚠ | `views.py:235`, `polygon_api.py:150` | JSON |
| 6–7 | `problem.packages`, `problem.package` ⚠ same ZIP as the fetch | `polygon_api.py:155`, `:187` | JSON list, ZIP |
| 8–9 | `problem.checker` twice ⚠ | `views.py:292`, `polygon_api.py:421` | JSON |
| 10 | `problem.tests` ⚠ only to count them | `polygon_api.py:304` | JSON list |
| 11–12 | `problem.solutions`, `problem.viewSolution` ⚠ repeat of 2–3 | `views.py:473`, `:488` | JSON list, plain text |

Calls 1–3 run only if the problem is already in the database.

**Total:** 12 calls, or 9 for a new problem. If the Redis cache has expired, add 1 + 2 per test case.

#### 5. What is read or written

- **Database:**
  - **WRITE**
    - `problems_problem`: `polygon_id`, `title`, `slug`, `difficulty`, `problem_statement`,
      `input_format`, `output_format`, `notes`, `time_limit`, `memory_limit`, `checker_type`,
      `test_case_count` (`views.py:340-388`)
    - `problems_problemtag`: `tag_name` of any new tag (`views.py:403`)
    - `problems_problem_extra_tags`: old tag links removed, selected tags linked
      (`views.py:396-404`)
    - `problems_sampletestcase`: `input`, `output`, `order` of each sample (`views.py:449-462`)
  - **READ**
    - the same as Flow 2
    - `problems_sampletestcase`: the problem's existing samples (`views.py:441`)
- **Redis:** the tests are read twice (`views.py:248`, `:426`). All keys are cleared if the transaction fails. (`views.py:564`).

#### 6. What the user sees

- **No difficulty picked:** a browser alert; nothing is sent.
- **Success:** the page reloads with a blue box, "Problem '*title*' created in database
  successfully." (or "updated"). It also shows the database ID, the Algopath link and the main
  solution, and the two test-case buttons are now enabled.
- **Failure:** a red box, "Migration failed and all changes have been rolled back. Reason: ..."

---

### Flow 4: Migrating test cases to the database

**Endpoint:** `POST /` → `index` in `problems/views.py` (the same view as the fetch)

#### 1. What the user clicks or submits

After the problem is saved to the database, the user clicks **Migrate Test Description to
Database** below the test table. Until then the button is disabled.

#### 2. What data the frontend sends to the backend

A form POST to `/` with `problem_id`, `migrate_test_cases_to_db=1` and `csrfmiddlewaretoken`
(`index.html:310-315`). A loading screen shows, and then the whole page reloads.

#### 3. What the backend does, in order

1. Runs the whole fetch again (Flow 2), but takes the tests from Redis (`views.py:146-329`).
   - **Issue:** this makes 10 Polygon calls that this button doesn't need.
2. Checks that the problem is in the database (`views.py:498`).
   - **Issue:** this check only runs after all the Polygon calls.
3. Reads the tests from Redis again (`views.py:505`). If the cache has expired, it downloads them
   from Polygon again (`polygon_api.py:351`).
4. Saves each test to the database, keeping only the first 260 characters of the input and the
   output (`views.py:516-549`). Empty tests are skipped.
   - **Issue:** this has the same problems as saving the samples in Flow 3:
     - old rows are never deleted;
     - the tests come from a cache that can be 30 minutes old.
   - **Issue:** a test that failed to download in Flow 2 was cached as empty, so it is skipped
     here with no warning.
5. Renders `index.html` again with a success message (`views.py:550`, `:573`).

If anything fails, nothing is saved and the Redis cache is cleared (`views.py:553-564`).

#### 4. Which external APIs are called

The **Polygon API**: the same calls as Flow 3, without the last two solution calls. That makes
**10 calls**, and all of them repeat the fetch (`views.py:160-308`). If the cache has expired, add
1 + 2 per test case.

#### 5. What is read or written

- **Database:**
  - **WRITE**
    - `problems_problemtestcase`: `input`, `output`, `is_sample`, `description`, `order` of each
      test (`views.py:530-548`)
  - **READ**
    - the same as Flow 2
    - `problems_problemtestcase`: the problem's existing tests (`views.py:516`)
- **Redis:** reads the tests (`views.py:505`). The cache is cleared if the migration fails
  (`views.py:564`).

#### 6. What the user sees

The page reloads with a green box: "Test cases description migrated to database Successfully."
---

### Flow 5: Uploading test cases to cloud storage

**Endpoint:** `POST /` → `index` in `problems/views.py` (the same view as the fetch)

#### 1. What the user clicks or submits

After the problem is saved to the database, the user clicks **Migrate Test Cases to Azure**. Until
then the button is disabled.

#### 2. What data the frontend sends to the backend

A form POST to `/` with `problem_id`, `migrate_to_azure=1` and `csrfmiddlewaretoken`
(`index.html:250-255`). A loading screen shows, and then the whole page reloads.

#### 3. What the backend does, in order

1. Gets the main solution from Polygon, as in the fetch (`views.py:149-184`).
2. Checks that the problem is in the database (`views.py:193-197`). If it isn't, it shows an error and stops.
3. Tries to clear the judge's Redis cache for this problem (keys `oj_dev_..._<db id>*`,
   `views.py:208` → `polygon_api.py:771-797`).
   - **Issue:** nothing in this codebase ever writes these keys. They belong to a separate judge
     service, so here nothing is deleted.
4. Uploads the tests (`views.py:218` → `migrate_to_storage`, `polygon_api.py:708-769`):
   - reads the tests from Redis, or from Polygon if the cache has expired;
   - picks S3 or Azure from `STORAGE_PROVIDER` in `.env` (`storage.py:4-26`);
   - deletes all of the problem's old files (`polygon_api.py:750`);
   - uploads each test as `01` (input) and `01.a` (answer) (`S3Testcase.py:28-35` or
     `AzureTestcase.py:60-86`).

   Because the old files are deleted first, an upload that fails halfway leaves only some tests, and it raise an error.

5. If the problem has a custom checker (`views.py:211`), compiles it with `g++` on this server and
   uploads it (`polygon_api.py:767` → `:570-706`).
   - On Windows it is uploaded as `custom_checker.exe`.
   - Checker errors are only logged.
6. Runs the whole fetch again (Flow 2, `views.py:234-329`) and renders `index.html`
   (`views.py:573`).

If anything fails after the upload, all of the problem's files in storage are deleted
(`views.py:557-562`). The old files were already deleted in step 4, so this wipes the problem's
tests from S3 completely.

#### 4. Which external APIs are called

- **Polygon API:** **12 calls**:
  - the 3 solution calls (`views.py:160-177`);
  - `problem.checker` twice before the upload (`views.py:211`, `polygon_api.py:588`);
  - the 7 fetch calls again (`views.py:235-308`).

  That means `problem.checker` runs 4 times in one click. A custom checker adds 1–3
  `problem.viewFile` calls. An expired cache adds 1 call, plus 2 per test.
- **S3 or Azure:** one delete of the old files, then 2 uploads per test, plus one for the checker.

#### 5. What is read or written

- **Database:**
  - **WRITE**
    - nothing
  - **READ**
    - the same as Flow 2
    - `problems_problem`: `id`, used to name the storage folder (`views.py:193`)
- **Redis:** deletes the judge's `oj_dev_...` keys and reads the cached tests
  (`polygon_api.py:792-794`, `:731`).
- **Cloud storage:** replaces everything under `test_cases/<db id>/`.

#### 6. What the user sees

The page reloads with "Test cases migrated to Azure Blob Storage successfully." The message says
Azure even when the files go to S3. If the S3 upload fails, only the red error box is shown. 


---

## 2.2 Polygon API and Cloud Storage

### Polygon API endpoints

All calls go to `https://polygon.codeforces.com/api/<method>` as a POST (`polygon_api.py:26`).

| Endpoint | What it is used for | Where |
|---|---|---|
| `problem.info` | time and memory limits | `polygon_api.py:254` |
| `problem.packages` | list of built packages, to find the newest | `polygon_api.py:155` |
| `problem.package` | download the package ZIP, to read `problem.html` | `polygon_api.py:172-187` |
| `problem.tests` | list of tests (index, sample flag, description) | `polygon_api.py:304`, `:364` |
| `problem.testInput` | one test's input (plain text) | `polygon_api.py:383` |
| `problem.testAnswer` | one test's answer (plain text) | `polygon_api.py:390` |
| `problem.checker` | checker name, standard (`std::...`) or custom | `views.py:292`, `polygon_api.py:421` |
| `problem.viewFile` | source of a custom checker | `polygon_api.py:452-479` |
| `problem.solutions` | list of solutions, to find the main one | `views.py:162`, `:473` |
| `problem.viewSolution` | code of the main solution | `views.py:177`, `:488` |
| `problem.updateWorkingCopy` | called before reading solutions | `views.py:160` |

`problem.statements`, `problem.script` and `problem.files` also have helper functions
(`polygon_api.py:258-349`), but nothing calls them.

### How requests are authenticated

Polygon uses an API key and secret, read from `.env` (`POLYGON_API_KEY`, `POLYGON_API_SECRET`). The
app won't start without them (`settings.py:125-129`). Every request is signed in
`_generate_api_sig` (`polygon_api.py:35-68`):

1. Adds `apiKey` and the current `time` (Unix seconds) to the request parameters.
2. Sorts all parameters by name and joins them as `name=value&...`.
3. Builds the string to hash: `<6 random chars>/<method>?<params>#<secret>` (`to_hash`,
   `polygon_api.py:60`).
4. Hashes `to_hash` with SHA-512. `apiSig` is the 6 random chars followed by the hash
   (`polygon_api.py:63-65`).

The request is then sent with `apiKey`, `time`, `apiSig` and the normal parameters as form fields
(`polygon_api.py:88-96`). The secret itself is never sent.

Polygon replies with JSON `{status, result, comment}`. If `status` is `FAILED`, the code raises an
error with the comment (`polygon_api.py:105-106`). Tests, solutions and files come back as plain
text, and the ZIP as raw bytes.

No timeout is set on the requests, so a slow Polygon response keeps the page waiting.

### Cloud storage: how files are named and organized

The app uses **AWS S3**. With `STORAGE_PROVIDER=s3` in `.env`, `get_storage()` (`storage.py:8-14`)
creates an `S3BlobManager` (`S3Testcase.py`):

- **Login:** a `boto3` S3 client with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_REGION`
  (`S3Testcase.py:14-19`).
- **Bucket:** `AWS_S3_BUCKET_NAME`, here `polygon-testcases-puzzled`.

Each problem gets one folder, named by its **database ID**, not its Polygon ID:

```
s3://polygon-testcases-puzzled/
└── test_cases/
    └── <db problem id>/           e.g. test_cases/1/
        ├── 01                     input of test 1
        ├── 01.a                   answer of test 1
        ├── 02
        ├── 02.a
        ├── ...
        └── custom_checker.cpp     only if the problem has a custom checker
```

- **Test files:** the number is the test's position in the list, padded to 2 digits
  (`S3Testcase.py:29`). The input has no extension, and the answer ends in `.a`. A skipped empty
  test leaves a gap in the numbers. 
- **Custom checker:** the code tries to compile it, but `testlib.h` is never downloaded, so the
  source is uploaded as `custom_checker.cpp` (`polygon_api.py:668`).
- **Contents:** each input and answer is saved as its own plain-text file in the bucket (S3Testcase.py:22-26).
- **Updating:** before each upload, every file under `test_cases/<db problem id>/` is deleted
  (`empty_blob`, `S3Testcase.py:37-46`), then the files are uploaded again.
- **Errors:** an upload error is raised and shown on the page (`S3Testcase.py:33-35`), but the files uploaded before it stay in the bucket.

The folder is named after the database ID. If a problem is deleted from the database and migrated again, it gets a new ID and a new folder, and the old folder is never deleted from the bucket.
