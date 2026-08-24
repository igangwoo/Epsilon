"""Every example file must check cleanly (no error diagnostics)."""

import glob
import os

import pytest

from epsilon.project import Session

EXAMPLES = sorted(glob.glob(
    os.path.join(os.path.dirname(__file__), "..", "examples", "*.epsl")))


@pytest.mark.parametrize("path", EXAMPLES,
                         ids=[os.path.basename(p) for p in EXAMPLES])
def test_example_checks(path):
    s = Session()
    with open(path, encoding="utf-8") as f:
        src = f.read()
    module = os.path.splitext(os.path.basename(path))[0]
    result = s.check_source(src, module)
    errors = [d.format() for d in result.diagnostics if d.severity == "error"]
    assert not errors, f"{path} has errors:\n" + "\n".join(errors)


def test_nat_proofs_are_formally_proven():
    s = Session()
    path = os.path.join(os.path.dirname(__file__), "..", "examples",
                        "nat_proofs.epsl")
    with open(path, encoding="utf-8") as f:
        s.check_source(f.read(), "nat_proofs")
    thms = s.theorem_list("nat_proofs")
    assert thms, "expected theorems in nat_proofs"
    assert all(t["status"] == "proven" for t in thms), \
        "every nat_proofs theorem must be Formally Proven"


def test_showcase_has_honest_cas_status():
    s = Session()
    path = os.path.join(os.path.dirname(__file__), "..", "examples",
                        "showcase.epsl")
    with open(path, encoding="utf-8") as f:
        s.check_source(f.read(), "showcase")
    status = {t["name"]: t["status"] for t in s.theorem_list("showcase")}
    # the CAS-computed limit is Symbolically Verified, never Formally Proven
    assert status.get("sinc_limit") == "symbolic"
    # a kernel-proved theorem is Formally Proven
    assert status.get("add_comm") == "proven"


def test_examples_exist():
    assert EXAMPLES, "no example files found"
