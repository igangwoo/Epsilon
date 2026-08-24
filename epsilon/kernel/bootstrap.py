"""Bootstrap the core environment: the mathematical objects every Epsilon
session starts from.

Everything here goes through the checked `add_decl` / `declare_inductive`
entry points - the bootstrap is itself kernel-verified on every startup.

Declared here (Python level, because they need recursors or literal support):
    Bool, Nat, And, Or, Iff, True, False, Exists, Prod, Sum, List, Unit, Eq
    Not, Ne, ite, Nat.add/mul/pred/sub/pow (defined via Nat.rec), Nat.le/lt
    opaque numeric types Int, Rat, Real, Complex, String with their operators
    analysis constants (sin, cos, exp, limit, deriv, integral, Continuous, ...)
    trust-tracking axioms (Epsilon.trustedCAS / trustedNumeric / sorry)

Mathematical axioms (field axioms for Real, classical logic, set theory, ...)
live in the standard library (`epsilon/lib/*.epsl`) so their use is visible
and tracked per-theorem.
"""

from __future__ import annotations

from fractions import Fraction

from .env import (Environment, Declaration, DeclKind,
                  TRUSTED_CAS_AXIOM, TRUSTED_NUMERIC_AXIOM, SORRY_AXIOM)
from .inductive import (InductiveSpec, ConstructorSpec, declare_inductive,
                        declare_eq, close_pi, close_lam, ph)
from .term import (Term, Const, Sort, App, Lam, Pi, Lit, mk_app,
                   PROP, TYPE)
from .typecheck import add_decl


def _opaque(env: Environment, name: str, ty: Term, doc: str | None = None) -> None:
    add_decl(env, Declaration(name, DeclKind.OPAQUE, ty, doc=doc, module="core"))


def _def(env: Environment, name: str, ty: Term, value: Term,
         doc: str | None = None, reducible: bool = True) -> None:
    add_decl(env, Declaration(name, DeclKind.DEFINITION, ty, value=value,
                              doc=doc, module="core", reducible=reducible))


def _axiom(env: Environment, name: str, ty: Term, doc: str | None = None) -> None:
    add_decl(env, Declaration(name, DeclKind.AXIOM, ty, doc=doc, module="core"))


def _arrow(*tys: Term) -> Term:
    """Non-dependent arrow t1 → t2 → ... → tn."""
    result = tys[-1]
    for ty in reversed(tys[:-1]):
        result = Pi("_", ty, result)
    return result


def bootstrap() -> Environment:
    env = Environment()
    B = Const("Bool")
    N = Const("Nat")

    # ---- basic sorts-level types ------------------------------------------
    declare_inductive(env, InductiveSpec(
        "Bool", TYPE, 0,
        [ConstructorSpec("Bool.false", B), ConstructorSpec("Bool.true", B)]))

    declare_inductive(env, InductiveSpec(
        "Nat", TYPE, 0,
        [ConstructorSpec("Nat.zero", N),
         ConstructorSpec("Nat.succ", _arrow(N, N))]))

    declare_inductive(env, InductiveSpec("Unit", TYPE, 0,
                                         [ConstructorSpec("Unit.star", Const("Unit"))]))

    # ---- logic -------------------------------------------------------------
    declare_inductive(env, InductiveSpec("True", PROP, 0,
                                         [ConstructorSpec("True.intro", Const("True"))]))
    declare_inductive(env, InductiveSpec("False", PROP, 0, []))

    declare_inductive(env, InductiveSpec(
        "And", _arrow(PROP, PROP, PROP), 2,
        [ConstructorSpec("And.intro", close_pi(
            [("a", PROP), ("b", PROP), ("ha", ph("a")), ("hb", ph("b"))],
            mk_app(Const("And"), ph("a"), ph("b"))))]))

    declare_inductive(env, InductiveSpec(
        "Or", _arrow(PROP, PROP, PROP), 2,
        [ConstructorSpec("Or.inl", close_pi(
            [("a", PROP), ("b", PROP), ("h", ph("a"))],
            mk_app(Const("Or"), ph("a"), ph("b")))),
         ConstructorSpec("Or.inr", close_pi(
             [("a", PROP), ("b", PROP), ("h", ph("b"))],
             mk_app(Const("Or"), ph("a"), ph("b"))))]))

    declare_inductive(env, InductiveSpec(
        "Iff", _arrow(PROP, PROP, PROP), 2,
        [ConstructorSpec("Iff.intro", close_pi(
            [("a", PROP), ("b", PROP),
             ("mp", _arrow(ph("a"), ph("b"))), ("mpr", _arrow(ph("b"), ph("a")))],
            mk_app(Const("Iff"), ph("a"), ph("b"))))]))

    declare_inductive(env, InductiveSpec(
        "Exists", close_pi([("A", TYPE)], _arrow(_arrow(ph("A"), PROP), PROP)), 2,
        [ConstructorSpec("Exists.intro", close_pi(
            [("A", TYPE), ("p", _arrow(ph("A"), PROP)),
             ("w", ph("A")), ("h", App(ph("p"), ph("w")))],
            mk_app(Const("Exists"), ph("A"), ph("p"))))]))

    declare_eq(env)

    _def(env, "Not", _arrow(PROP, PROP),
         close_lam([("a", PROP)], _arrow(ph("a"), Const("False"))),
         doc="Not a := a → False")

    _def(env, "Ne", close_pi([("A", TYPE)], _arrow(ph("A"), ph("A"), PROP)),
         close_lam([("A", TYPE), ("a", ph("A")), ("b", ph("A"))],
                   App(Const("Not"), mk_app(Const("Eq"), ph("A"), ph("a"), ph("b")))),
         doc="a ≠ b := ¬(a = b)")

    # ---- data --------------------------------------------------------------
    declare_inductive(env, InductiveSpec(
        "Prod", _arrow(TYPE, TYPE, TYPE), 2,
        [ConstructorSpec("Prod.mk", close_pi(
            [("A", TYPE), ("B", TYPE), ("fst", ph("A")), ("snd", ph("B"))],
            mk_app(Const("Prod"), ph("A"), ph("B"))))]))

    declare_inductive(env, InductiveSpec(
        "Sum", _arrow(TYPE, TYPE, TYPE), 2,
        [ConstructorSpec("Sum.inl", close_pi(
            [("A", TYPE), ("B", TYPE), ("a", ph("A"))],
            mk_app(Const("Sum"), ph("A"), ph("B")))),
         ConstructorSpec("Sum.inr", close_pi(
             [("A", TYPE), ("B", TYPE), ("b", ph("B"))],
             mk_app(Const("Sum"), ph("A"), ph("B"))))]))

    declare_inductive(env, InductiveSpec(
        "List", _arrow(TYPE, TYPE), 1,
        [ConstructorSpec("List.nil", close_pi(
            [("A", TYPE)], App(Const("List"), ph("A")))),
         ConstructorSpec("List.cons", close_pi(
             [("A", TYPE), ("head", ph("A")),
              ("tail", App(Const("List"), ph("A")))],
             App(Const("List"), ph("A"))))]))

    # ---- ite ---------------------------------------------------------------
    _def(env, "ite",
         close_pi([("A", TYPE)], _arrow(B, ph("A"), ph("A"), ph("A"))),
         close_lam([("A", TYPE), ("c", B), ("t", ph("A")), ("e", ph("A"))],
                   mk_app(Const("Bool.rec"),
                          Lam("_", B, ph("A")), ph("e"), ph("t"), ph("c"))),
         doc="if c then t else e (on Bool)")

    # ---- Nat arithmetic (genuinely defined via Nat.rec) --------------------
    nat_motive = Lam("_", N, N)

    _def(env, "Nat.add", _arrow(N, N, N),
         close_lam([("a", N), ("b", N)],
                   mk_app(Const("Nat.rec"), nat_motive, ph("a"),
                          close_lam([("n", N), ("ih", N)],
                                    App(Const("Nat.succ"), ph("ih"))),
                          ph("b"))),
         doc="a + succ b = succ (a + b), a + 0 = a")

    _def(env, "Nat.mul", _arrow(N, N, N),
         close_lam([("a", N), ("b", N)],
                   mk_app(Const("Nat.rec"), nat_motive, Lit(Fraction(0), "Nat"),
                          close_lam([("n", N), ("ih", N)],
                                    mk_app(Const("Nat.add"), ph("ih"), ph("a"))),
                          ph("b"))),
         doc="a * succ b = a * b + a, a * 0 = 0")

    _def(env, "Nat.pred", _arrow(N, N),
         close_lam([("n", N)],
                   mk_app(Const("Nat.rec"), nat_motive, Lit(Fraction(0), "Nat"),
                          close_lam([("k", N), ("ih", N)], ph("k")),
                          ph("n"))))

    _def(env, "Nat.sub", _arrow(N, N, N),
         close_lam([("a", N), ("b", N)],
                   mk_app(Const("Nat.rec"), nat_motive, ph("a"),
                          close_lam([("n", N), ("ih", N)],
                                    App(Const("Nat.pred"), ph("ih"))),
                          ph("b"))),
         doc="truncated subtraction (monus)")

    _def(env, "Nat.pow", _arrow(N, N, N),
         close_lam([("a", N), ("b", N)],
                   mk_app(Const("Nat.rec"), nat_motive, Lit(Fraction(1), "Nat"),
                          close_lam([("n", N), ("ih", N)],
                                    mk_app(Const("Nat.mul"), ph("ih"), ph("a"))),
                          ph("b"))))

    _def(env, "Nat.le", _arrow(N, N, PROP),
         close_lam([("a", N), ("b", N)],
                   mk_app(Const("Exists"), N,
                          close_lam([("c", N)],
                                    mk_app(Const("Eq"), N,
                                           mk_app(Const("Nat.add"), ph("a"), ph("c")),
                                           ph("b"))))),
         doc="a ≤ b := ∃ c, a + c = b")

    _def(env, "Nat.lt", _arrow(N, N, PROP),
         close_lam([("a", N), ("b", N)],
                   mk_app(Const("Nat.le"), App(Const("Nat.succ"), ph("a")), ph("b"))),
         doc="a < b := succ a ≤ b")

    for op in ("div", "mod"):
        _opaque(env, f"Nat.{op}", _arrow(N, N, N))
    for op in ("beq", "ble", "blt"):
        _opaque(env, f"Nat.{op}", _arrow(N, N, B))
    _opaque(env, "Nat.gcd", _arrow(N, N, N))

    # ---- opaque numeric towers ---------------------------------------------
    for tyname in ("Int", "Rat", "Real", "Complex"):
        _opaque(env, tyname, TYPE)
    _opaque(env, "String", TYPE)
    _opaque(env, "String.append", _arrow(Const("String"), Const("String"), Const("String")))

    def numeric_ops(T: str, with_inv: bool) -> None:
        C = Const(T)
        for op in ("add", "sub", "mul"):
            _opaque(env, f"{T}.{op}", _arrow(C, C, C))
        _opaque(env, f"{T}.neg", _arrow(C, C))
        if with_inv:
            _opaque(env, f"{T}.inv", _arrow(C, C))
            _opaque(env, f"{T}.div", _arrow(C, C, C))
        _opaque(env, f"{T}.pow", _arrow(C, C, C))
        if T != "Complex":
            for op in ("le", "lt"):
                _opaque(env, f"{T}.{op}", _arrow(C, C, PROP))
            for op in ("beq", "ble", "blt"):
                _opaque(env, f"{T}.{op}", _arrow(C, C, B))

    numeric_ops("Int", with_inv=False)
    _opaque(env, "Int.div", _arrow(Const("Int"), Const("Int"), Const("Int")))
    _opaque(env, "Int.mod", _arrow(Const("Int"), Const("Int"), Const("Int")))
    _opaque(env, "Int.natAbs", _arrow(Const("Int"), N))
    numeric_ops("Rat", with_inv=True)
    numeric_ops("Real", with_inv=True)
    numeric_ops("Complex", with_inv=True)

    # coercions (literal-aware in the kernel)
    R, Z, Q, Cx = Const("Real"), Const("Int"), Const("Rat"), Const("Complex")
    _opaque(env, "Int.ofNat", _arrow(N, Z))
    _opaque(env, "Rat.ofNat", _arrow(N, Q))
    _opaque(env, "Rat.ofInt", _arrow(Z, Q))
    _opaque(env, "Real.ofNat", _arrow(N, R))
    _opaque(env, "Real.ofInt", _arrow(Z, R))
    _opaque(env, "Real.ofRat", _arrow(Q, R))
    _opaque(env, "Complex.ofReal", _arrow(R, Cx))

    # ---- real analysis constants ------------------------------------------
    for f in ("sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
              "tanh", "exp", "log", "sqrt", "abs"):
        _opaque(env, f"Real.{f}", _arrow(R, R))
    _opaque(env, "Real.pi", R)
    _opaque(env, "Real.euler", R)
    _opaque(env, "Real.floor", _arrow(R, Z))
    _opaque(env, "Real.ceil", _arrow(R, Z))

    RR = _arrow(R, R)
    _opaque(env, "limit", _arrow(RR, R, R),
            doc="limit f a : the limit of f at a (value form; see HasLimitAt)")
    _opaque(env, "HasLimitAt", _arrow(RR, R, R, PROP),
            doc="HasLimitAt f a L : f tends to L at a (ε-δ; axiomatized in lib)")
    _opaque(env, "deriv", _arrow(RR, RR))
    _opaque(env, "HasDerivAt", _arrow(RR, R, R, PROP))
    _opaque(env, "integral", _arrow(RR, R, R, R),
            doc="integral f a b : definite integral of f from a to b")
    _opaque(env, "Continuous", _arrow(RR, PROP))
    _opaque(env, "ContinuousAt", _arrow(RR, R, PROP))

    # ---- Complex structure -------------------------------------------------
    _opaque(env, "Complex.mk", _arrow(R, R, Cx))
    _opaque(env, "Complex.re", _arrow(Cx, R))
    _opaque(env, "Complex.im", _arrow(Cx, R))
    _opaque(env, "Complex.I", Cx)
    _opaque(env, "Complex.conj", _arrow(Cx, Cx))
    _opaque(env, "Complex.abs", _arrow(Cx, R))

    # ---- sets, functions, linear algebra scaffolding -----------------------
    _opaque(env, "Set", _arrow(TYPE, TYPE))
    _opaque(env, "Set.mem", close_pi([("A", TYPE)],
                                     _arrow(ph("A"), App(Const("Set"), ph("A")), PROP)))
    _opaque(env, "setOf", close_pi([("A", TYPE)],
                                   _arrow(_arrow(ph("A"), PROP), App(Const("Set"), ph("A")))))
    _def(env, "Set.subset",
         close_pi([("A", TYPE)],
                  _arrow(App(Const("Set"), ph("A")), App(Const("Set"), ph("A")), PROP)),
         close_lam([("A", TYPE), ("s", App(Const("Set"), ph("A"))),
                    ("t", App(Const("Set"), ph("A")))],
                   close_pi([("x", ph("A"))],
                            _arrow(mk_app(Const("Set.mem"), ph("A"), ph("x"), ph("s")),
                                   mk_app(Const("Set.mem"), ph("A"), ph("x"), ph("t"))))),
         doc="s ⊆ t := ∀ x, x ∈ s → x ∈ t")

    _opaque(env, "Vector", _arrow(TYPE, N, TYPE))
    _opaque(env, "Matrix", _arrow(TYPE, N, N, TYPE))
    _opaque(env, "Sequence", _arrow(TYPE, TYPE), doc="Sequence A := Nat-indexed values")

    # ---- function combinators ---------------------------------------------
    def _mark_implicit(t: Term, n: int) -> Term:
        if n == 0 or not isinstance(t, Pi):
            return t
        return Pi(t.name, t.ty, _mark_implicit(t.body, n - 1), implicit=True)

    comp_ty = _mark_implicit(
        close_pi([("A", TYPE), ("B", TYPE), ("C", TYPE)],
                 _arrow(_arrow(ph("B"), ph("C")), _arrow(ph("A"), ph("B")),
                        _arrow(ph("A"), ph("C")))), 3)
    comp_val = close_lam(
        [("A", TYPE), ("B", TYPE), ("C", TYPE),
         ("g", _arrow(ph("B"), ph("C"))), ("f", _arrow(ph("A"), ph("B"))),
         ("x", ph("A"))],
        App(ph("g"), App(ph("f"), ph("x"))))
    _def(env, "Function.comp", comp_ty, comp_val, doc="(g ∘ f)(x) = g(f(x))")

    id_ty = _mark_implicit(close_pi([("A", TYPE)], _arrow(ph("A"), ph("A"))), 1)
    id_val = close_lam([("A", TYPE), ("a", ph("A"))], ph("a"))
    _def(env, "Function.id", id_ty, id_val)

    # ---- trust-tracking axioms (section 27: honest statuses) ---------------
    _axiom(env, TRUSTED_CAS_AXIOM, close_pi([("p", PROP)], ph("p")),
           doc="Trusted CAS oracle. Any theorem depending on this is at most "
               "'Symbolically Verified', never 'Formally Proven'.")
    _axiom(env, TRUSTED_NUMERIC_AXIOM, close_pi([("p", PROP)], ph("p")),
           doc="Trusted numeric oracle. Any theorem depending on this is at "
               "most 'Numerically Verified'.")
    _axiom(env, SORRY_AXIOM, close_pi([("p", PROP)], ph("p")),
           doc="Unfinished proof placeholder; marks results as Heuristic.")

    return env
