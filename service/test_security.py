"""Security + hardening tests for public beta (offline, GitHub stubbed).

Covers: missing/invalid auth, invalid repo/branch, path traversal, oversized
payloads, duplicate semantics, cross-user isolation, GitHub failure mapping,
rate limiting, and token hygiene (no token in logs/responses).

    python test_security.py
"""

import copy

from fastapi.testclient import TestClient

import file_builder
import main
from schema import Submission

PAYLOAD = {
    "problem_id": 1,
    "title": "Two Sum",
    "slug": "two-sum",
    "difficulty": "Easy",
    "tags": ["Array", "Hash Table"],
    "runtime_ms": 52,
    "memory_mb": 14.3,
    "runtime_percentile": 87.5,
    "memory_percentile": 72.1,
    "code": "class Solution:\n    def twoSum(self, nums, target):\n        return []",
    "language": "python3",
    "repo_owner": "testuser",
    "repo_name": "leetcode-solutions",
    "branch": "main",
}

committed = {}


def fake_commit(token, repo_full_name, branch, submission):
    assert token and repo_full_name == "testuser/leetcode-solutions" or repo_full_name, "unexpected repo"
    path = file_builder.resolve_path(submission)
    committed[path] = file_builder.build_content(submission)
    return f"https://github.com/x/y/blob/{branch}/{path}"


def fake_upsert(token, repo_full_name, branch, submission):
    return None


main.github_client.commit_solution = fake_commit
main.readme_updater.upsert_row = fake_upsert
main.github_client.verify_write_access = lambda *a, **k: None
# Distinct stable user ids per token (same scheme as test_smoke.py).
_USER_IDS = {"tok_A": 201, "tok_B": 202, "fake_token": 1, "token_A": 101, "token_B": 102}
main.get_caller_identity = lambda token: _USER_IDS.get(token, 999)

client = TestClient(main.app)
passed = failed = 0


def check(label, condition):
    global passed, failed
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if condition:
        passed += 1
    else:
        failed += 1


def fresh():
    main._recent.clear()
    main._rate_hits.clear()
    committed.clear()


def post(payload=None, token="Bearer tok_A"):
    headers = {"Authorization": token} if token else {}
    return client.post("/submit", json=payload or PAYLOAD, headers=headers)


print("\n1. authentication")
fresh()
r = post(token=None)
check(f"missing header -> 401 (got {r.status_code})", r.status_code == 401)
r = client.post("/submit", json=PAYLOAD, headers={"Authorization": "Token abc"})
check("wrong scheme -> 401", r.status_code == 401)
r = client.post("/submit", json=PAYLOAD, headers={"Authorization": "Bearer "})
check("empty bearer -> 401", r.status_code == 401)

print("\n2. invalid repo/branch rejected at validation boundary")
fresh()
for field, value in [("repo_owner", "evil/owner"), ("repo_name", "a/b"),
                     ("repo_owner", ".."), ("branch", "main; rm -rf"),
                     ("branch", "../../etc"), ("slug", "../../x"),
                     ("slug", "UPPER CASE!"), ("title", ""),
                     ("problem_id", -5), ("code", ""),
                     ("runtime_percentile", 150.0)]:
    bad = dict(PAYLOAD, **{field: value})
    rr = post(bad)
    check(f"{field}={value!r} -> 400 (got {rr.status_code})", rr.status_code == 400)

print("\n3. path traversal impossible via title")
fresh()
evil = dict(PAYLOAD, title="../../pwned", problem_id=99)
sub = Submission(**evil)  # validation must accept; path must stay safe
path = file_builder.resolve_path(sub)
check(f"path contained ({path})", path.startswith("topics/") and ".." not in path)

print("\n4. oversized payload rejected")
fresh()
big = dict(PAYLOAD, code="x" * 100_001)
rr = post(big)
check(f"100k+ code -> 422/400 (got {rr.status_code})", rr.status_code in (400, 422))
check("no file committed for oversized", not committed)

print("\n5. duplicate semantics")
fresh()
r1 = post()
r2 = post()
check("same code twice -> duplicate", r2.json()["status"] == "duplicate")
fresh()
post()
r3 = post(dict(PAYLOAD, code="class Solution:\n    pass\n"))
check("different code -> ok (update)", r3.json()["status"] == "ok")

print("\n6. cross-user isolation (user-scoped identity)")
fresh()
post(PAYLOAD, token="Bearer tok_A")
rb = post(dict(PAYLOAD, repo_owner="userB", repo_name="other"), token="Bearer tok_B")
check("user B other repo unaffected", rb.json()["status"] == "ok")

print("\n6b. identical submission, same repo, different users -> both allowed")
fresh()
ra = post(PAYLOAD, token="Bearer tok_A")
rb2 = post(PAYLOAD, token="Bearer tok_B")
check("user A synced", ra.json()["status"] == "ok")
check("user B same repo+problem+code also synced (no false duplicate)", rb2.json()["status"] == "ok")
ra2 = post(PAYLOAD, token="Bearer tok_A")
check("same user same submission -> duplicate", ra2.json()["status"] == "duplicate")

print("\n7. GitHub failure mapping (no raw exceptions to users)")
fresh()


class FakeGithubExc(Exception):
    def __init__(self, status, data=""):
        super().__init__(data)
        self.status = status
        self.data = data


main.github_client.commit_solution = lambda *a, **k: (_ for _ in ()).throw(
    FakeGithubExc(401, "Bad credentials"))
rr = post()
check("401 -> reconnect message", rr.status_code == 401 and "Reconnect" in rr.json()["message"])
main.github_client.commit_solution = lambda *a, **k: (_ for _ in ()).throw(
    FakeGithubExc(403, "Resource not accessible"))
main._recent.clear()
main._rate_hits.clear()
rr = post()
check("403 -> permission message, no internals", rr.status_code == 403 and "Bad credentials" not in rr.json()["message"])
main.github_client.commit_solution = lambda *a, **k: (_ for _ in ()).throw(
    FakeGithubExc(404, "Not Found"))
main._recent.clear()
main._rate_hits.clear()
rr = post()
check("404 -> not-found message", rr.status_code == 404)
main.github_client.commit_solution = fake_commit

print("\n8. rate limiting (best-effort per instance)")
fresh()
codes = set()
for _ in range(35):
    main._recent.clear()  # bypass dedup to isolate the rate limiter
    rr = post()
    codes.add(rr.status_code)
check(f"flooding submits -> 429 seen ({sorted(codes)})", 429 in codes)

print("\n9. token hygiene")
fresh()
import pathlib
log_path = pathlib.Path(__file__).parent / "error.log"
before = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
main.github_client.commit_solution = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
post(dict(PAYLOAD), token="Bearer SUPER_SECRET_TOKEN_XYZ")
after = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
check("token never written to error.log", "SUPER_SECRET_TOKEN_XYZ" not in after[len(before):])
main.github_client.commit_solution = fake_commit

print("\n10. branch validation on proxy endpoint")
fresh()
rr = client.get("/github/repos/evil!owner/repo/branches", headers={"Authorization": "Bearer tok"})
check("bad owner -> 400", rr.status_code == 400)

print("\n11. markdown-special-character input stays in one table row")
import readme_updater as _ru
evil_sub = Submission(**dict(PAYLOAD, title="Weird [Title] | (x)",
                             tags=["A|B", "C[D]"], problem_id=7, slug="weird-title"))
row = _ru.build_row(evil_sub)
check("row is single-line", "\n" not in row)
cells = [c for c in row.split("|")]
# Unescaped pipes would add extra cells: 7 fields + leading/trailing empties.
check(f"pipe chars escaped ({row.count(chr(92)+'|')} escaped)", "\\|" in row and row.count("|") - row.count("\\|") == 8)
check("brackets escaped in link text", "\\[Title\\]" in row)
check("row still parses to problem 7", _ru._row_id(row) == 7)

print(f"\n{passed} passed, {failed} failed.")
raise SystemExit(1 if failed else 0)
