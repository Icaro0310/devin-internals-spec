"""Static contract test for the ``dist`` artifact handoff in pypi-publish.yml.

The publish job consumes the ``dist`` artifact produced by the verify job
(the devin-powerups ``verify-wheel-version.yml`` reusable, which uploads via
``actions/upload-artifact`` v4). These tests assert the handoff contract
instead of running the workflow: job ordering, artifact name/path, a
v4+-compatible hash-pinned download, the merged-origin guard, and the OIDC
upload shape. The PyPI upload itself is never exercised here.
"""

import re
from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "pypi-publish.yml"
)


def _workflow():
    raw = WORKFLOW.read_text(encoding="utf-8")
    return yaml.safe_load(raw), raw


def _step(job, name_fragment=None, uses_prefix=None):
    for step in job["steps"]:
        if name_fragment and name_fragment in (step.get("name") or ""):
            return step
        if uses_prefix and step.get("uses", "").startswith(uses_prefix):
            return step
    return None


def test_publish_needs_verify():
    wf, _ = _workflow()
    assert "verify" in wf["jobs"]["publish"]["needs"]


def test_dist_download_contract_and_pin():
    wf, raw = _workflow()
    publish = wf["jobs"]["publish"]
    step = _step(publish, uses_prefix="actions/download-artifact@")
    assert step is not None
    assert step["with"]["name"] == "dist"
    assert step["with"]["path"] == "dist/"
    m = re.search(r"actions/download-artifact@([0-9a-f]{40})\s*#\s*v(\d+)", raw)
    assert m, "download-artifact must be hash-pinned with a version comment"
    # Producer uploads with upload-artifact v4; v8 consumers cannot read
    # pre-v4 artifacts, so the pin must stay on a v4+ major.
    assert int(m.group(2)) >= 4


def test_publish_origin_guard_and_oidc_upload():
    wf, _ = _workflow()
    publish = wf["jobs"]["publish"]
    guard = _step(publish, name_fragment="merged into main")
    assert guard is not None
    upload = _step(publish, uses_prefix="pypa/gh-action-pypi-publish@")
    assert upload is not None
    assert upload["with"].get("skip-existing") is True
    assert "password" not in upload["with"]
    assert publish["environment"] == "pypi"
    assert publish["permissions"]["id-token"] == "write"
