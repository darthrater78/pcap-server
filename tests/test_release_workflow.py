"""Tests for release.yml's gate job -- the checks that stand between a tag
push and a published image.

v1.0.0 was first pushed onto the dev.40 commit, before the release PR merged.
That commit was on the default branch and its Check was green, so the gate let
it through, and :1.0.0 and :latest were published holding code that reported
0.1.0-dev.40. The gate now compares the tag with APP_VERSION in the tagged
commit.

The step's script is lifted out of release.yml as text and run for real, with a
stub `gh` on PATH that serves a chosen backend/main.py. Nothing here parses
YAML: there is no YAML library among the test dependencies, and reading the
script straight from the workflow means the test cannot drift from what runs.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
STEP_NAME = "Require the tag to match APP_VERSION in the tagged commit"
CHECK_STEP_NAME = "Require a passing Check run for this commit"


def _step_script(step_name: str = STEP_NAME) -> str:
    """The `run: |` body of a gate step, dedented."""
    lines = RELEASE_YML.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {step_name}")
    run_at = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    run_indent = len(lines[run_at]) - len(lines[run_at].lstrip())

    body = []
    for line in lines[run_at + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


def _run(tmp_path, *, tag: str, main_py: str | None):
    stub = tmp_path / "bin"
    stub.mkdir()
    served = tmp_path / "main.py"
    if main_py is None:
        gh = '#!/bin/sh\necho "gh: Not Found (HTTP 404)" >&2\nexit 1\n'
    else:
        served.write_text(main_py, encoding="utf-8")
        gh = f'#!/bin/sh\necho "$*" > "{tmp_path}/gh.args"\ncat "{served}"\n'
    (stub / "gh").write_text(gh)
    (stub / "gh").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "unused",
        "REPO": "owner/repo",
        "SHA": "abc123",
        "TAG": tag,
    }
    return subprocess.run(
        ["bash", "-c", _step_script()], env=env, capture_output=True, text=True, timeout=30
    )


def _main_py(version: str) -> str:
    return f'import os\n\nAPP_VERSION = "{version}"\nREPO_URL = "https://example"\n'


def test_step_exists_in_the_gate_job_before_anything_is_built():
    text = RELEASE_YML.read_text(encoding="utf-8")
    step = text.index(f"- name: {STEP_NAME}")
    assert text.index("  gate:") < step < text.index("  release:")


def test_matching_tag_passes(tmp_path):
    result = _run(tmp_path, tag="v1.0.0", main_py=_main_py("1.0.0"))
    assert result.returncode == 0, result.stderr
    assert "v1.0.0 matches APP_VERSION 1.0.0" in result.stdout
    # It reads the file at the tagged commit, not at the branch head.
    assert "contents/backend/main.py?ref=abc123" in (tmp_path / "gh.args").read_text()


def test_tag_on_an_older_commit_is_refused(tmp_path):
    """The dev.40 case: a stable tag on a commit that is still the dev build."""
    result = _run(tmp_path, tag="v1.0.0", main_py=_main_py("0.1.0-dev.40"))
    assert result.returncode == 1
    assert "APP_VERSION is 0.1.0-dev.40" in result.stdout


@pytest.mark.parametrize("tag", ["1.0.0", "v1.0", "v1.0.0-dev.1", "v1.0.00"])
def test_near_misses_are_refused(tmp_path, tag):
    result = _run(tmp_path, tag=tag, main_py=_main_py("1.0.0"))
    assert result.returncode == 1


def test_missing_app_version_is_refused(tmp_path):
    result = _run(tmp_path, tag="v1.0.0", main_py="REPO_URL = 'x'\n")
    assert result.returncode == 1
    assert "No APP_VERSION line" in result.stdout


def test_api_failure_is_refused_not_passed(tmp_path):
    result = _run(tmp_path, tag="v1.0.0", main_py=None)
    assert result.returncode != 0


def test_the_real_main_py_matches_the_shape_the_step_reads():
    """If APP_VERSION's line changes shape, the gate would refuse every release."""
    main_py = (REPO_ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert re.search(r'^APP_VERSION = "[^"]+"$', main_py, re.MULTILINE)


# --- the Check-run step ---------------------------------------------------
#
# v1.1.0-beta.2 was tagged on the merge of its own handoff notes. check.yml
# skips a commit touching only .claude/, so that commit had no Check run and
# the gate refused the release in eight seconds -- correctly by its own rule,
# and wrongly about the code, which had been tested one commit earlier. The
# step now falls back to the nearest ancestor with a passing push run and
# publishes only if everything that changed since lies inside check.yml's own
# paths-ignore list.
#
# Same approach as above: the real script, a stub gh, no YAML parsing. The
# stub serves four endpoints out of files, so a test says what the API would
# have said rather than how the step should behave.

CHECK_STUB = '''#!/usr/bin/env python3
import pathlib, sys

D = pathlib.Path({data!r})
args = " ".join(sys.argv[1:])
(D / "calls").open("a").write(args + "\\n")

if "/actions/workflows/check.yml/runs?head_sha=" in args:
    sha = args.split("head_sha=")[1].split("&")[0]
    kind = "push_runs" if "event=push" in args else "runs"
    f = D / kind / sha
    sys.stdout.write(f.read_text() if f.exists() else "")
elif "/contents/.github/workflows/check.yml?ref=" in args:
    sys.stdout.write((D / "check.yml").read_text())
elif "/commits?sha=" in args:
    sys.stdout.write((D / "commits").read_text())
elif "/compare/" in args:
    f = D / "compare"
    if not f.exists():
        sys.stderr.write("gh: compare unavailable\\n")
        sys.exit(1)
    sys.stdout.write(f.read_text())
else:
    sys.stderr.write("stub: unhandled " + args + "\\n")
    sys.exit(1)
'''

REAL_CHECK_YML = (REPO_ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")


def _run_check_step(
    tmp_path,
    *,
    sha: str = "tagged",
    runs: dict[str, str] | None = None,
    push_runs: dict[str, str] | None = None,
    ancestors: tuple[str, ...] = (),
    changed: tuple[str, ...] | None = (),
    check_yml: str = REAL_CHECK_YML,
):
    """Run the step with the API answering as described.

    `runs`/`push_runs` map a SHA to the "<status> <conclusion> <url>" lines the
    lookup yields; a SHA absent from the mapping has no run. `ancestors` is what
    the commits endpoint returns, `changed` the compare's filenames -- or None to
    make compare fail outright.
    """
    data = tmp_path / "data"
    (data / "runs").mkdir(parents=True)
    (data / "push_runs").mkdir(parents=True)
    for name, mapping in (("runs", runs), ("push_runs", push_runs)):
        for run_sha, lines in (mapping or {}).items():
            (data / name / run_sha).write_text(lines, encoding="utf-8")
    (data / "check.yml").write_text(check_yml, encoding="utf-8")
    (data / "commits").write_text("".join(f"{c}\n" for c in (sha, *ancestors)), encoding="utf-8")
    if changed is not None:
        (data / "compare").write_text("".join(f"{c}\n" for c in changed), encoding="utf-8")

    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "gh").write_text(CHECK_STUB.format(data=str(data)), encoding="utf-8")
    (stub / "gh").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "unused",
        "REPO": "owner/repo",
        "SHA": sha,
    }
    result = subprocess.run(
        ["bash", "-c", _step_script(CHECK_STEP_NAME)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result.calls = (data / "calls").read_text(encoding="utf-8")  # type: ignore[attr-defined]
    return result


PASSED = "completed success https://example/run/1\n"
FAILED = "completed failure https://example/run/1\n"


def test_check_step_exists_in_the_gate_job_before_anything_is_built():
    text = RELEASE_YML.read_text(encoding="utf-8")
    step = text.index(f"- name: {CHECK_STEP_NAME}")
    assert text.index("  gate:") < step < text.index("  release:")


def test_a_passing_run_on_the_tagged_commit_passes(tmp_path):
    result = _run_check_step(tmp_path, runs={"tagged": PASSED})
    assert result.returncode == 0, result.stderr
    assert "Check passed for tagged." in result.stdout
    # The fallback is not consulted when the commit has a run of its own.
    assert "/commits?sha=" not in result.calls


def test_a_failed_run_on_the_tagged_commit_is_refused(tmp_path):
    """A real failure is never explained away by looking at an ancestor."""
    result = _run_check_step(
        tmp_path, runs={"tagged": FAILED}, push_runs={"parent": PASSED}, ancestors=("parent",)
    )
    assert result.returncode == 1
    assert "did not pass" in result.stdout
    assert "/commits?sha=" not in result.calls


def test_a_docs_only_commit_above_a_tested_one_passes(tmp_path):
    """The v1.1.0-beta.2 case, against the real check.yml."""
    result = _run_check_step(
        tmp_path,
        push_runs={"parent": PASSED},
        ancestors=("parent",),
        changed=(".claude/beta2-handoff.md", "CHANGELOG.md", "docs/operating.md"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "but parent passed" in result.stdout


def test_an_identical_tree_above_a_tested_commit_passes(tmp_path):
    result = _run_check_step(
        tmp_path, push_runs={"parent": PASSED}, ancestors=("parent",), changed=()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "identical" in result.stdout


def test_a_code_change_above_the_tested_ancestor_is_refused(tmp_path):
    result = _run_check_step(
        tmp_path,
        push_runs={"parent": PASSED},
        ancestors=("parent",),
        changed=(".claude/notes.md", "backend/main.py"),
    )
    assert result.returncode == 1
    assert "differs from the last tested commit parent in backend/main.py" in result.stdout


def test_the_nearest_tested_ancestor_is_the_one_compared_against(tmp_path):
    result = _run_check_step(
        tmp_path,
        push_runs={"older": PASSED},
        ancestors=("newer", "older"),
        changed=("docs/x.md",),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "but older passed" in result.stdout


def test_an_ancestor_tested_only_by_a_pull_request_run_is_refused(tmp_path):
    """A pull_request run checks out the merge ref, not the commit itself."""
    result = _run_check_step(
        tmp_path, runs={"parent": PASSED}, ancestors=("parent",), changed=("docs/x.md",)
    )
    assert result.returncode == 1
    assert "no commit among the 50 before it has a passing push run" in result.stdout


def test_no_tested_ancestor_at_all_is_refused(tmp_path):
    result = _run_check_step(tmp_path, ancestors=("parent", "grandparent"))
    assert result.returncode == 1
    assert "Nothing establishes that this tree was ever tested" in result.stdout


def test_an_unreadable_paths_ignore_is_refused(tmp_path):
    result = _run_check_step(
        tmp_path,
        push_runs={"parent": PASSED},
        ancestors=("parent",),
        changed=("docs/x.md",),
        check_yml="on:\n  push:\n    branches: ['**']\n",
    )
    assert result.returncode == 1
    assert "paths-ignore list could not be read" in result.stdout


def test_a_pattern_the_gate_cannot_reason_about_is_refused(tmp_path):
    """Rather than guess at a glob and under-report what it covers."""
    result = _run_check_step(
        tmp_path,
        push_runs={"parent": PASSED},
        ancestors=("parent",),
        changed=("docs/x.md",),
        check_yml=REAL_CHECK_YML.replace("- 'README.md'", "- '*.md'"),
    )
    assert result.returncode == 1
    assert "a pattern this gate cannot reason about" in result.stdout


def test_a_compare_that_cannot_be_read_is_refused_not_passed(tmp_path):
    result = _run_check_step(
        tmp_path, push_runs={"parent": PASSED}, ancestors=("parent",), changed=None
    )
    assert result.returncode != 0


def _paths_ignore_blocks() -> list[list[str]]:
    """Every paths-ignore list in check.yml, in file order."""
    return [
        re.findall(r"-\s*['\"]([^'\"]+)['\"]", body)
        for body in re.findall(
            r"^\s*paths-ignore:\s*$\n((?:\s*(?:#.*|-\s*['\"].+['\"])\s*$\n)+)",
            REAL_CHECK_YML,
            re.MULTILINE,
        )
    ]


def test_the_real_check_yml_paths_ignore_matches_the_shape_the_step_reads():
    """The list is parsed out of check.yml at the tagged commit rather than
    restated in release.yml, so a change to its formatting -- not just its
    contents -- would make every skipped-commit release refuse."""
    blocks = _paths_ignore_blocks()
    assert blocks, "check.yml has no paths-ignore block in the shape the step's sed expects"
    entries = blocks[0]
    assert ".claude/**" in entries
    # Every entry is an exact path or a directory glob; the step refuses anything else.
    assert all(e.endswith("/**") or "*" not in e for e in entries), entries


def test_check_yml_ignores_the_same_paths_on_push_and_pull_request():
    """GitHub Actions has no YAML anchors, so check.yml writes the ignore list
    out twice. Nothing but this notices them drifting apart -- and the drift is
    silent and expensive: the pull_request trigger had no filter at all, so a
    .claude/-only commit skipped on push ran the full suite on the PR anyway.
    """
    blocks = _paths_ignore_blocks()
    assert len(blocks) == 2, f"expected a paths-ignore under push and pull_request, got {len(blocks)}"
    assert blocks[0] == blocks[1], f"push ignores {blocks[0]}, pull_request ignores {blocks[1]}"


def test_check_yml_push_trigger_still_covers_the_default_branch():
    """release.yml's gate looks up a push run on the commit a tag points at,
    and the ancestor search below requires one too. Narrowing this trigger past
    main would leave every tag with nothing to find."""
    push = re.search(r"^  push:\n(?:.*\n)*?    branches: \[([^\]]+)\]", REAL_CHECK_YML, re.MULTILINE)
    assert push, "check.yml's push trigger has no branches filter in the expected shape"
    assert "main" in push.group(1), push.group(1)


def test_check_yml_never_cancels_a_run_on_the_default_branch():
    """A cancelled run is not a passing one, so cancelling on main would strand
    a merge commit as untaggable until someone re-ran Check by hand."""
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}" in REAL_CHECK_YML
