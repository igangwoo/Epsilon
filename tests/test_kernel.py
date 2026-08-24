"""Kernel tests — soundness first.

The most important property of the whole system is that the kernel accepts
correct proofs and rejects incorrect ones. These tests exercise that
directly, plus reduction, inductives, and axiom tracking.
"""

from fractions import Fraction

import pytest

from epsilon.kernel.bootstrap import bootstrap
from epsilon.kernel.env import (Declaration, DeclKind, KernelError,
                                SORRY_AXIOM, TRUSTED_CAS_AXIOM,
                                TRUSTED_NUMERIC_AXIOM)
from epsilon.kernel.typecheck import add_decl, infer_type, check_type
from epsilon.kernel.reduce import whnf, def_eq, normalize
from epsilon.kernel.inductive import (InductiveSpec, ConstructorSpec,
                                      declare_inductive)
from epsilon.kernel.term import (Const, App, Pi, Lam, Var, Sort, Lit, MVar,
                                 mk_app, nat_lit, int_lit, rat_lit, PROP, TYPE)


@pytest.fixture()
def env():
    return bootstrap()


# ---------------------------------------------------------------------------
# SOUNDNESS
# ---------------------------------------------------------------------------

def test_accepts_correct_proof(env):
    # refl proves 2 + 2 = 4
    proof = mk_app(Const("Eq.refl"), Const("Nat"), nat_lit(4))
    goal = mk_app(Const("Eq"), Const("Nat"),
                  mk_app(Const("Nat.add"), nat_lit(2), nat_lit(2)), nat_lit(4))
    check_type(env, proof, goal)  # must not raise


def test_rejects_false_proof(env):
    proof = mk_app(Const("Eq.refl"), Const("Nat"), nat_lit(4))
    bad = mk_app(Const("Eq"), Const("Nat"),
                 mk_app(Const("Nat.add"), nat_lit(2), nat_lit(2)), nat_lit(5))
    with pytest.raises(KernelError):
        check_type(env, proof, bad)


def test_rejects_ill_typed_application(env):
    with pytest.raises(KernelError):
        infer_type(env, App(nat_lit(1), nat_lit(2)))


def test_rejects_metavariables(env):
    with pytest.raises(KernelError):
        add_decl(env, Declaration("m", DeclKind.DEFINITION, Const("Nat"),
                                  value=MVar(1)))


def test_rejects_duplicate(env):
    with pytest.raises(KernelError):
        add_decl(env, Declaration("Nat.add", DeclKind.OPAQUE, Const("Nat")))


def test_rejects_unbound_variable(env):
    with pytest.raises(KernelError):
        infer_type(env, Var(7))


def test_rejects_non_positive_inductive(env):
    # Bad : (Bad -> Nat) -> Bad would allow encoding False
    with pytest.raises(KernelError):
        declare_inductive(env, InductiveSpec("Bad", TYPE, 0, [
            ConstructorSpec("Bad.mk",
                            Pi("f", Pi("_", Const("Bad"), Const("Nat")),
                               Const("Bad")))]))


def test_axiom_cannot_have_body(env):
    with pytest.raises(KernelError):
        add_decl(env, Declaration("ax", DeclKind.AXIOM, Const("Nat"),
                                  value=nat_lit(1)))


def test_prop_singleton_rule(env):
    # multi-constructor Prop (Or) gets no large eliminator
    assert env.contains("Or.ind")
    assert not env.contains("Or.rec")
    # Exists must not have .rec (would leak data out of Prop)
    assert not env.contains("Exists.rec")
    # subsingleton Prop (And) may have .rec
    assert env.contains("And.rec")


def test_no_type_in_type(env):
    # Sort n : Sort (n+1); a proof that Type : Type must fail
    assert infer_type(env, TYPE) == Sort(2)
    with pytest.raises(KernelError):
        check_type(env, TYPE, TYPE)


def test_prop_impredicative(env):
    # Pi (A : Prop), A  lives in Prop (impredicativity)
    assert infer_type(env, Pi("A", PROP, Var(0))) == PROP
    # Pi (A : Type), A  lives in Type 1 (predicative)
    assert infer_type(env, Pi("A", TYPE, Var(0))) == Sort(2)


# ---------------------------------------------------------------------------
# reduction / literal arithmetic
# ---------------------------------------------------------------------------

def test_nat_literal_arithmetic(env):
    def ev(op, a, b):
        return whnf(env, mk_app(Const(f"Nat.{op}"), nat_lit(a), nat_lit(b)))
    assert ev("add", 3, 4) == nat_lit(7)
    assert ev("mul", 6, 7) == nat_lit(42)
    assert ev("sub", 5, 3) == nat_lit(2)
    assert ev("sub", 3, 5) == nat_lit(0)   # truncated (monus)
    assert ev("pow", 2, 10) == nat_lit(1024)


def test_nat_div_by_zero_total(env):
    # kernel convention: division by zero yields 0 (field axioms carry x≠0)
    assert whnf(env, mk_app(Const("Nat.div"), nat_lit(5), nat_lit(0))) == nat_lit(0)


def test_rat_arithmetic(env):
    r = whnf(env, mk_app(Const("Rat.add"), rat_lit(Fraction(1, 2)),
                         rat_lit(Fraction(1, 3))))
    assert r == Lit(Fraction(5, 6), "Rat")


def test_bool_comparisons(env):
    assert whnf(env, mk_app(Const("Nat.ble"), nat_lit(2), nat_lit(3))) == \
        Const("Bool.true")
    assert whnf(env, mk_app(Const("Nat.blt"), nat_lit(3), nat_lit(3))) == \
        Const("Bool.false")


def test_def_eq_succ_literal_bridge(env):
    # Nat.succ (Nat.succ Nat.zero) is def-eq to the literal 2
    succ = Const("Nat.succ")
    two = App(succ, App(succ, Const("Nat.zero")))
    assert def_eq(env, two, nat_lit(2))
    assert not def_eq(env, two, nat_lit(3))


def test_iota_reduction_on_recursor(env):
    # Nat.rec with a literal major computes
    motive = Lam("_", Const("Nat"), Const("Nat"))
    zero_case = nat_lit(100)
    succ_case = Lam("n", Const("Nat"), Lam("ih", Const("Nat"),
                                           App(Const("Nat.succ"), Var(0))))
    # rec on 0 gives the zero case
    t0 = mk_app(Const("Nat.rec"), motive, zero_case, succ_case, nat_lit(0))
    assert whnf(env, t0) == nat_lit(100)
    # rec on 3 gives succ(succ(succ(100)))-ish; normalize to a literal
    t3 = mk_app(Const("Nat.rec"), motive, nat_lit(0), succ_case, nat_lit(3))
    assert normalize(env, t3) == nat_lit(3)


# ---------------------------------------------------------------------------
# axiom tracking / verification status
# ---------------------------------------------------------------------------

def test_axioms_transitive(env):
    add_decl(env, Declaration("myax", DeclKind.AXIOM,
                              mk_app(Const("Eq"), Const("Nat"), nat_lit(0),
                                     nat_lit(0))))
    add_decl(env, Declaration("uses_ax", DeclKind.THEOREM,
                              mk_app(Const("Eq"), Const("Nat"), nat_lit(0),
                                     nat_lit(0)),
                              value=Const("myax")))
    assert "myax" in env.axioms_of("uses_ax")


def test_verification_status_from_trust_axioms(env):
    for ax, expect in ((SORRY_AXIOM, "heuristic"),
                       (TRUSTED_NUMERIC_AXIOM, "numeric"),
                       (TRUSTED_CAS_AXIOM, "symbolic")):
        goal = mk_app(Const("Eq"), Const("Nat"), nat_lit(1), nat_lit(2))
        name = f"t_{expect}"
        add_decl(env, Declaration(name, DeclKind.THEOREM, goal,
                                  value=App(Const(ax), goal)))
        assert env.verification_status(name) == expect


def test_rollback(env):
    n = env.snapshot_len()
    add_decl(env, Declaration("tmp", DeclKind.OPAQUE, Const("Nat")))
    assert env.contains("tmp")
    env.rollback_to(n)
    assert not env.contains("tmp")


def test_worst_status_wins(env):
    goal = mk_app(Const("Eq"), Const("Nat"), nat_lit(1), nat_lit(2))
    add_decl(env, Declaration("num_lemma", DeclKind.THEOREM, goal,
                              value=App(Const(TRUSTED_NUMERIC_AXIOM), goal)))
    add_decl(env, Declaration("sorry_lemma", DeclKind.THEOREM, goal,
                              value=App(Const(SORRY_AXIOM), goal)))
    # a theorem depending on both is heuristic (the worst)
    both = mk_app(Const("And"), goal, goal)
    add_decl(env, Declaration("both", DeclKind.THEOREM, both,
                              value=mk_app(Const("And.intro"), goal, goal,
                                           Const("num_lemma"),
                                           Const("sorry_lemma"))))
    assert env.verification_status("both") == "heuristic"
