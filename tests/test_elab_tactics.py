"""Elaboration and tactic-engine tests, driven through Session.check_source."""

import pytest

from epsilon.project import Session


def check(src, module="t"):
    s = Session()
    return s, s.check_source(src, module)


def statuses(s, module="t"):
    return {t["name"]: t["status"] for t in s.theorem_list(module)}


# ---------------------------------------------------------------------------
# elaboration: coercions, implicits
# ---------------------------------------------------------------------------

def test_numeric_coercion_join():
    _, r = check("def x : Real := 2 + 2.5")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_nat_literal_in_real_position():
    _, r = check("def x : Real := 3")
    assert r.ok


def test_decimal_defaults_to_rat():
    _, r = check("#eval 1 / 2")
    assert r.ok
    # 1/2 lives in ℚ, so evaluates to a fraction, not 0
    msg = [x.message for x in r.results if x.kind == "eval"][0]
    assert "/" in msg


def test_implicit_argument_insertion():
    _, r = check(
        "theorem t (a b : Nat) (h : a = b) : b = a := by\n"
        "  exact Eq.symm(h)")
    assert r.ok, [d.format() for d in r.diagnostics]
    assert statuses(_ if False else _, "t")  # placeholder


# ---------------------------------------------------------------------------
# tactics — each exercised at least once
# ---------------------------------------------------------------------------

TACTIC_CASES = {
    "intro_exact": "theorem t (p : Prop) : p → p := by intro h; exact h",
    "assumption": "theorem t (p : Prop) (h : p) : p := by assumption",
    "rfl": "theorem t (a : Nat) : a + 0 = a := by rfl",
    "apply": "theorem t (p q : Prop) (h : p → q) (hp : p) : q := by apply h; exact hp",
    "symm": "theorem t (a b : Nat) (h : a = b) : b = a := by symm; exact h",
    "constructor": "theorem t (p q : Prop) (hp : p) (hq : q) : p ∧ q := by "
                   "constructor; exact hp; exact hq",
    "left": "theorem t (p q : Prop) (hp : p) : p ∨ q := by left; exact hp",
    "right": "theorem t (p q : Prop) (hq : q) : p ∨ q := by right; exact hq",
    "exists": "theorem t : ∃ (n : Nat), n = 5 := by exists 5",
    "exfalso": "theorem t (p : Prop) (h : False) : p := by exfalso; exact h",
    "contradiction": "theorem t (p q : Prop) (hp : p) (hnp : ¬p) : q := by "
                     "contradiction",
    "decide_nat": "theorem t : 3 ≤ 8 := by decide",
    "trivial": "theorem t : True := by trivial",
    "have": "theorem t (a : Nat) : a + 1 + 1 = a + 2 := by "
            "have h : a + 1 + 1 = a + 2 := by rfl\n  exact h",
    "show": "theorem t (a : Nat) : a + 0 = a := by show a = a; rfl",
    "cases_and": "theorem t (p q : Prop) : p ∧ q → p := by "
                 "intro h; cases h with | intro hp hq => exact hp",
}


@pytest.mark.parametrize("name,src", list(TACTIC_CASES.items()))
def test_tactic(name, src):
    _, r = check(src)
    assert r.ok, f"{name}: " + "; ".join(d.format() for d in r.diagnostics)


def test_induction_and_rw():
    _, r = check(
        "theorem t (a : Nat) : 0 + a = a := by\n"
        "  induction a with\n"
        "  | zero => rfl\n"
        "  | succ n ih => rw [Nat.add_succ, ih]")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_rw_reverse():
    _, r = check(
        "theorem t (a b : Nat) (h : a = b) : b = a := by\n"
        "  rw [← h]")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_simp_closes_zero_add():
    s, r = check("theorem t (a : Nat) : 0 + a = a := by simp")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_calc():
    _, r = check(
        "theorem t (a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c := by\n"
        "  calc a = b := by exact h1\n"
        "       _ = c := by exact h2")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_auto_search():
    _, r = check("theorem t (p q : Prop) : p ∧ q → q ∧ p := by auto")
    assert r.ok, [d.format() for d in r.diagnostics]


# ---------------------------------------------------------------------------
# honesty and error recovery
# ---------------------------------------------------------------------------

def test_wrong_exact_produces_error_and_recovers():
    s, r = check(
        "theorem bad (a : Nat) : a = a := by exact Nat.zero\n"
        "theorem after (a : Nat) : a = a := by rfl")
    assert not r.ok
    assert any(d.severity == "error" for d in r.diagnostics)
    # recovery: `bad` still exists (as heuristic) and later commands run
    st = statuses(s)
    assert st.get("after") == "proven"
    assert st.get("bad") == "heuristic"


def test_sorry_is_heuristic():
    s, r = check("theorem t : 1 = 2 := by sorry")
    assert r.ok  # sorry is accepted, but labeled honestly
    assert statuses(s)["t"] == "heuristic"


def test_unsolved_goals_error_mentions_goal():
    _, r = check("theorem t (p q : Prop) (hp : p) : p ∧ q := by exact hp")
    assert not r.ok
    # the mismatch is reported
    assert any("mismatch" in d.message.lower() or "unsolved" in d.message.lower()
               or "type" in d.message.lower() for d in r.diagnostics)
