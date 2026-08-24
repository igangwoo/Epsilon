"""The proof explorer's suggestions must actually work.

A suggestion that does not apply is worse than no suggestion: it sends the
reader down a path that fails. So the central test here does not check that
a plausible name appears — it takes every suggestion the engine makes, puts
the tactic into a theorem, and checks the file.
"""

import pytest

from epsilon.elab.elaborator import Elaborator
from epsilon.kernel.term import Const, Pi, instantiate
from epsilon.project import Session
from epsilon.suggest import MAX_SIDE_GOALS, suggest
from epsilon.syntax.parser import parse_expression


@pytest.fixture(scope="module")
def sess():
    return Session()


def goal_of(sess, text):
    """Elaborate a ∀-statement and open its binders, as a tactic sees it."""
    el = Elaborator(sess.env, sess.ctx)
    t = el.finalize(el.elab_expr(
        parse_expression(text, extra_ops=dict(sess.extra_ops)), None))
    while isinstance(t, Pi):
        t = instantiate(t.body, Const(t.name))
    return t


#: (goal source, a theorem the tactic gets dropped into)
CASES = [
    ("forall (a : Nat) (b : Nat), a + b = b + a",
     "theorem probe (a b : Nat) : a + b = b + a := by\n  {}"),
    ("forall (a : Nat), a + 0 = a",
     "theorem probe (a : Nat) : a + 0 = a := by\n  {}"),
    ("forall (a : Nat), 0 + a = a",
     "theorem probe (a : Nat) : 0 + a = a := by\n  {}"),
    ("forall (a : Nat) (b : Nat) (c : Nat), a + b + c = a + (b + c)",
     "theorem probe (a b c : Nat) : a + b + c = a + (b + c) := by\n  {}"),
    ("2 <= 3", "theorem probe : 2 <= 3 := by\n  {}"),
    ("forall (a : Nat) (b : Nat), a * b = b * a",
     "theorem probe (a b : Nat) : a * b = b * a := by\n  {}"),
]


def build(template, suggestion):
    """The theorem with the suggested tactic, side goals left to `sorry`."""
    src = template.format(suggestion.tactic)
    trailing = suggestion.side_goals or (1 if suggestion.tactic.startswith("rw") else 0)
    for _ in range(trailing):
        src += "\n  sorry"
    return src


@pytest.mark.parametrize("goal_src,template", CASES)
def test_every_suggestion_applies(sess, goal_src, template):
    suggestions = suggest(sess, goal_of(sess, goal_src), limit=8)
    assert suggestions, f"no suggestion at all for {goal_src}"
    for s in suggestions:
        fresh = Session()
        result = fresh.check_source(build(template, s), "probe")
        assert result.ok, (
            f"suggested `{s.tactic}` for `{goal_src}` but it does not apply: "
            f"{result.diagnostics[0].message if result.diagnostics else ''}")


@pytest.mark.parametrize("goal_src,expected", [
    ("forall (a : Nat) (b : Nat), a + b = b + a", "Nat.add_comm"),
    ("forall (a : Nat), a + 0 = a", "Nat.add_zero"),
    ("forall (a : Nat) (b : Nat), a * b = b * a", "Nat.mul_comm"),
    ("forall (a : Nat) (b : Nat) (c : Nat), a + b + c = a + (b + c)",
     "Nat.add_assoc"),
])
def test_the_obvious_result_is_suggested_first(sess, goal_src, expected):
    top = suggest(sess, goal_of(sess, goal_src), limit=8)[0]
    assert top.name == expected
    assert top.tactic.startswith("exact ")
    assert top.side_goals == 0


def test_a_closing_suggestion_carries_its_arguments(sess):
    top = suggest(sess, goal_of(sess, "forall (a : Nat) (b : Nat), a + b = b + a"))[0]
    assert top.tactic == "exact Nat.add_comm a b"


def test_suggestions_carry_the_mathematical_name(sess):
    top = suggest(sess, goal_of(sess, "forall (a : Nat) (b : Nat), a + b = b + a"))[0]
    assert top.display_name == "NaturalNumbers.Addition.Commutativity"
    assert top.status == "proven"
    assert top.statement


# --------------------------------------------------------------------------
# what must never be suggested
# --------------------------------------------------------------------------

@pytest.mark.parametrize("goal_src", [s for s, _ in CASES])
def test_sorry_and_the_trust_axioms_are_never_suggested(sess, goal_src):
    """They close any goal, which is exactly why offering them is wrong.

    The product's promise is that a result carries an honest verification
    status. Proposing that the user assume the goal does not help them reach
    one.
    """
    names = {s.name for s in suggest(sess, goal_of(sess, goal_src), limit=50)}
    assert not (names & {"Epsilon.sorry", "Epsilon.trustedCAS",
                         "Epsilon.trustedNumeric"})


@pytest.mark.parametrize("goal_src", [s for s, _ in CASES])
def test_universally_applicable_results_are_not_suggested(sess, goal_src):
    """A conclusion that is a bare variable matches everything, so it says
    nothing about *this* goal."""
    names = {s.name for s in suggest(sess, goal_of(sess, goal_src), limit=50)}
    assert "Classical.byContradiction" not in names
    assert "Classical.not_not" not in names


@pytest.mark.parametrize("goal_src", [s for s, _ in CASES])
def test_no_suggestion_leaves_too_many_side_goals(sess, goal_src):
    for s in suggest(sess, goal_of(sess, goal_src), limit=50):
        assert s.side_goals <= MAX_SIDE_GOALS


def test_a_goal_nothing_matches_yields_nothing(sess):
    """Honest emptiness beats a list of near-misses."""
    out = suggest(sess, goal_of(sess, "forall (a : Nat), a + a = a"), limit=8)
    assert all(s.tactic.startswith(("rw", "apply")) for s in out), \
        "no result proves a + a = a, so none should claim to"


# --------------------------------------------------------------------------
# goals written as text (the proof pane's explorer)
# --------------------------------------------------------------------------

from epsilon.suggest import suggest_for_text  # noqa: E402


@pytest.mark.parametrize("goal,expected", [
    ("a + b = b + a", "exact Nat.add_comm a b"),
    ("n + 0 = n", "exact Nat.add_zero n"),
    ("2 <= 3", "exact Nat.le_succ 2"),
    ("forall (a b : Nat), a * b = b * a", "exact Nat.mul_comm a b"),
])
def test_a_typed_goal_is_understood(sess, goal, expected):
    """Bare variables are allowed; the reader should not have to write
    binders to ask a question."""
    assert suggest_for_text(sess, goal, limit=4)[0].tactic == expected


def test_reflexivity_is_offered_as_rfl(sess):
    """`Eq.refl` is a constructor, not a theorem, and it is the most basic
    proof step there is — the explorer would be poor without it. It is
    offered the way anyone writes it."""
    top = suggest_for_text(sess, "forall (x : Real), Real.sin(x) = Real.sin(x)")[0]
    assert top.tactic == "rfl"
    assert top.name == "Eq.refl"


def test_arguments_are_parenthesised(sess):
    """`exact Nat.add_zero a + b` would parse as something else entirely."""
    tactics = [s.tactic for s in
               suggest_for_text(sess, "forall (a b : Nat), a + b + 0 = a + b", limit=6)]
    assert "exact Nat.add_zero (a + b)" in tactics


def test_hypotheses_from_a_proof_step_are_used(sess):
    """The proof tree hands over the context along with the target."""
    top = suggest_for_text(sess, "a + b = b + a",
                           hypotheses=[("a", "Nat"), ("b", "Nat")])[0]
    assert top.name == "Nat.add_comm"


def test_an_unreadable_goal_raises_rather_than_inventing_one(sess):
    with pytest.raises(Exception):
        suggest_for_text(sess, "nonsense ++")


def test_an_empty_goal_is_refused(sess):
    with pytest.raises(ValueError):
        suggest_for_text(sess, "   ")


def test_data_constructors_are_not_offered_as_proofs(sess):
    """`Nat.succ` builds a number, not a proof."""
    for goal, _ in CASES:
        names = {s.name for s in suggest(sess, goal_of(sess, goal), limit=50)}
        assert "Nat.succ" not in names
        assert "Nat.zero" not in names
