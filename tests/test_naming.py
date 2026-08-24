"""The user-facing mathematical naming layer.

Internal identifiers stay exactly as they were; mathematical names are a
second, presentational layer that the IDE shows and proofs may cite.
"""

import pytest

from epsilon.kernel.env import KernelError
from epsilon.naming import humanize, CORE_NAMES
from epsilon.project import Session
from epsilon.intelligence import search, completions, hover


@pytest.fixture(scope="module")
def sess():
    return Session()


# ---------------------------------------------------------------------------
# humanize
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,label", [
    ("NaturalNumbers.Addition.Commutativity",
     "Natural Numbers · Addition Commutativity"),
    ("Classical.ExcludedMiddle", "Classical · Excluded Middle"),
    ("Equality", "Equality"),
    ("", ""),
])
def test_humanize(name, label):
    assert humanize(name) == label


# ---------------------------------------------------------------------------
# declaring a name
# ---------------------------------------------------------------------------

def test_attribute_declares_a_mathematical_name():
    s = Session()
    r = s.check_source(
        '@[name "Addition.Demo"]\n'
        'theorem demo (a b : Nat) : a + b = b + a := by exact Nat.add_comm(a, b)',
        "m")
    assert r.ok, [d.format() for d in r.diagnostics]
    d = s.env.expect("demo")
    assert d.name == "demo"                       # internal identifier intact
    assert d.display_name == "Addition.Demo"


def test_flags_and_keyed_attributes_are_kept_apart():
    s = Session()
    s.check_source('@[simp, name "Addition.Demo2"]\n'
                   'theorem demo2 (a : Nat) : a + 0 = a := by rfl', "m")
    d = s.env.expect("demo2")
    assert d.attrs == ["simp"]                    # flags only
    assert d.display_name == "Addition.Demo2"


def test_mathematical_name_is_usable_in_a_proof():
    s = Session()
    r = s.check_source(
        "theorem t (x y : Nat) : x + y = y + x := by\n"
        "  exact NaturalNumbers.Addition.Commutativity(x, y)", "m")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_internal_identifier_still_works():
    s = Session()
    r = s.check_source(
        "theorem t (x y : Nat) : x + y = y + x := by\n"
        "  exact Nat.add_comm(x, y)", "m")
    assert r.ok, [d.format() for d in r.diagnostics]


def test_mathematical_name_usable_in_rewrite():
    s = Session()
    r = s.check_source(
        "theorem t (a b c : Nat) : (a + b) + c = a + (b + c) := by\n"
        "  rw [NaturalNumbers.Addition.Associativity]", "m")
    assert r.ok, [d.format() for d in r.diagnostics]


# ---------------------------------------------------------------------------
# collisions are refused, never silently resolved
# ---------------------------------------------------------------------------

def test_duplicate_mathematical_name_is_rejected():
    s = Session()
    r = s.check_source(
        '@[name "Dup.Name"]\ntheorem one (a : Nat) : a = a := by rfl\n'
        '@[name "Dup.Name"]\ntheorem two (a : Nat) : a = a := by rfl', "m")
    assert not r.ok
    assert any("already" in d.message for d in r.diagnostics)


def test_mathematical_name_cannot_shadow_an_internal_identifier():
    s = Session()
    r = s.check_source(
        '@[name "Nat.add_comm"]\ntheorem sneaky (a : Nat) : a = a := by rfl', "m")
    assert not r.ok
    assert any("collides" in d.message for d in r.diagnostics)


def test_real_declaration_wins_over_a_mathematical_name(sess):
    """Resolution order must prefer a genuine declaration."""
    assert sess.ctx.resolve_global("Nat.add_comm") == "Nat.add_comm"


# ---------------------------------------------------------------------------
# the standard library is named
# ---------------------------------------------------------------------------

def test_every_stdlib_theorem_has_a_mathematical_name(sess):
    unnamed = [t["name"] for t in sess.theorem_list() if not t["display_name"]]
    assert not unnamed, f"unnamed stdlib theorems: {unnamed}"


@pytest.mark.parametrize("internal,display", [
    ("Nat.add_assoc", "NaturalNumbers.Addition.Associativity"),
    ("Nat.add_comm", "NaturalNumbers.Addition.Commutativity"),
    ("Nat.mul_comm", "NaturalNumbers.Multiplication.Commutativity"),
    ("Real.le_of_lt", "RealNumbers.Order.WeakFromStrict"),
    ("Nat.succ_add", "NaturalNumbers.Addition.SuccessorOnLeft"),
])
def test_known_names(sess, internal, display):
    assert sess.env.display_name_of(internal) == display
    assert sess.env.resolve_display_name(display) == internal


def test_core_kernel_objects_are_named(sess):
    assert sess.env.display_name_of("Nat.succ") == "NaturalNumbers.Successor"
    assert sess.env.display_name_of("Eq") == "Equality"


def test_core_names_are_unique():
    values = list(CORE_NAMES.values())
    assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# discovery: find a theorem without knowing its internal identifier
# ---------------------------------------------------------------------------

def test_search_by_mathematical_words(sess):
    names = {h["name"] for h in search(sess, "Commutativity", limit=20)}
    assert "Nat.add_comm" in names


def test_search_by_humanized_phrase(sess):
    names = {h["name"] for h in search(sess, "Excluded Middle", limit=20)}
    assert "Classical.em" in names


def test_search_results_carry_title(sess):
    hits = search(sess, "Pythagorean", limit=5)
    assert hits and hits[0]["title"] == "Trigonometry · Pythagorean Identity"


def test_completions_match_mathematical_names(sess):
    names = {c["name"] for c in completions(sess, "Associativity", limit=50)}
    assert "Nat.add_assoc" in names


def test_hover_shows_title_and_statement(sess):
    h = hover(sess, "Nat.add_assoc")
    assert h["title"] == "Natural Numbers · Addition Associativity"
    assert "=" in h["type"]


def test_hover_resolves_a_mathematical_name(sess):
    h = hover(sess, "NaturalNumbers.Addition.Associativity")
    assert h["name"] == "Nat.add_assoc"


def test_theorem_list_falls_back_to_the_identifier():
    s = Session()
    s.check_source("theorem unnamed_thm (a : Nat) : a = a := by rfl", "m")
    entry = [t for t in s.theorem_list("m") if t["name"] == "unnamed_thm"][0]
    assert entry["display_name"] is None
    assert entry["title"] == "unnamed_thm"
