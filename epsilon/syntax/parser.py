"""Parser for the Epsilon language.

A Pratt (precedence-climbing) expression parser with a *dynamic* operator
table - `infixl 65 "⊕" := myOp` adds operators at parse time - plus command
and tactic-block parsing.

Layout rule: a construct's continuation lines must be indented strictly
deeper than the column where the construct starts. That single rule delimits
tactic blocks, multi-line expressions, and command boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

from .lexer import Token, tokenize
from . import sast as S


class ParseError(Exception):
    def __init__(self, msg: str, line: int, col: int) -> None:
        super().__init__(f"{line}:{col}: {msg}")
        self.msg, self.line, self.col = msg, line, col


@dataclass
class OpInfo:
    prec: int
    assoc: str          # "left" | "right" | "none"
    target: Optional[str] = None   # function name for user-defined ops


DEFAULT_INFIX: dict[str, OpInfo] = {
    "<->": OpInfo(20, "right"),
    "\\/": OpInfo(30, "right"),
    "/\\": OpInfo(35, "right"),
    "=":   OpInfo(50, "none"),
    "!=":  OpInfo(50, "none"),
    "==":  OpInfo(50, "none"),
    "<":   OpInfo(50, "none"),
    "<=":  OpInfo(50, "none"),
    ">":   OpInfo(50, "none"),
    ">=":  OpInfo(50, "none"),
    "∈":   OpInfo(50, "none"),
    "∉":   OpInfo(50, "none"),
    "⊆":   OpInfo(50, "none"),
    "+":   OpInfo(65, "left"),
    "-":   OpInfo(65, "left"),
    "*":   OpInfo(70, "left"),
    "/":   OpInfo(70, "left"),
    "//":  OpInfo(70, "left"),
    "%":   OpInfo(70, "left"),
    "><":  OpInfo(72, "right"),
    "∘":   OpInfo(76, "right"),
    "^":   OpInfo(80, "right"),
}
ARROW_PREC = 25            # -> is special-cased (SArrow)
PREFIX_PREC = {"-": 75, "¬": 40, "√": 85}
APP_PREC = 100

TACTIC_NAMES = {
    "intro", "intros", "exact", "apply", "assumption", "rfl", "constructor",
    "left", "right", "split", "exists", "cases", "induction", "rw",
    "rewrite", "simp", "unfold", "have", "show", "calc", "trivial",
    "contradiction", "exfalso", "decide", "norm_num", "cas", "numeric",
    "symm", "sorry", "ring", "linarith", "assumption", "clear", "all_goals",
}

COMMAND_KWS = {
    "def", "define", "axiom", "constant", "theorem", "lemma", "proposition",
    "corollary", "example", "inductive", "structure", "import", "namespace",
    "end", "open", "plot", "notation", "infixl", "infixr", "prefix", "postfix",
}


class Parser:
    def __init__(self, src: str, extra_ops: Optional[dict[str, tuple[str, int, str]]] = None):
        self.toks = tokenize(src)
        self.pos = 0
        self.infix: dict[str, OpInfo] = dict(DEFAULT_INFIX)
        self.user_prefix: dict[str, tuple[int, str]] = {}
        # operators registered earlier in the session (REPL/imports)
        self.user_ops: dict[str, tuple[str, int, str]] = {}
        if extra_ops:
            for sym, (fixity, prec, target) in extra_ops.items():
                self._register_op(fixity, prec, sym, target)
        self.min_col = 0  # layout: tokens on a new line at col <= min_col terminate

    # -- token utilities ---------------------------------------------------
    def peek(self, off: int = 0) -> Token:
        i = min(self.pos + off, len(self.toks) - 1)
        return self.toks[i]

    def next(self) -> Token:
        t = self.toks[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def at(self, kind: str, text: Optional[str] = None) -> bool:
        t = self.peek()
        return t.kind == kind and (text is None or t.text == text)

    def at_sym(self, text: str) -> bool:
        return self.at("SYM", text)

    def at_kw(self, text: str) -> bool:
        return self.at("KW", text)

    def expect(self, kind: str, text: Optional[str] = None) -> Token:
        t = self.peek()
        if t.kind != kind or (text is not None and t.text != text):
            want = text or kind
            raise ParseError(f"expected '{want}', found '{t.text or t.kind}'",
                             t.line, t.col)
        return self.next()

    def err(self, msg: str) -> ParseError:
        t = self.peek()
        return ParseError(msg, t.line, t.col)

    def _blocked(self) -> bool:
        """Layout: does the next token fall outside the current construct?"""
        t = self.peek()
        if t.kind == "EOF":
            return True
        return t.col <= self.min_col and self._starts_line(t)

    def _starts_line(self, t: Token) -> bool:
        # a token starts a line if the previous token is on an earlier line
        idx = self.pos
        if idx == 0:
            return True
        return self.toks[idx - 1].line < t.line

    def _register_op(self, fixity: str, prec: int, symbol: str, target: str) -> None:
        if fixity in ("infixl", "infixr"):
            self.infix[symbol] = OpInfo(prec, "left" if fixity == "infixl" else "right",
                                        target)
        elif fixity == "prefix":
            self.user_prefix[symbol] = (prec, target)
        self.user_ops[symbol] = (fixity, prec, target)

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------
    def parse_qualified_name(self) -> tuple[str, Token]:
        t = self.expect("IDENT")
        name = t.text
        while self.at_sym(".") and self.peek(1).kind == "IDENT":
            self.next()
            name += "." + self.next().text
        # span covers the full dotted name (qualified names never span lines)
        full = Token(t.kind, name, t.line, t.col, t.value)
        return name, full

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------
    def parse_expr(self, min_prec: int = 0) -> S.Expr:
        t = self.peek()
        lhs = self._parse_prefix()

        while True:
            if self._blocked():
                break
            tok = self.peek()

            # arrow (function type / implication)
            if tok.kind == "SYM" and tok.text == "->":
                if ARROW_PREC < min_prec:
                    break
                self.next()
                rhs = self.parse_expr(ARROW_PREC)  # right assoc
                lhs = S.SArrow(lhs=lhs, rhs=rhs, span=_join(_span_of(lhs), _span_of(rhs)))
                continue

            # infix operators
            if tok.kind == "SYM" and tok.text in self.infix:
                info = self.infix[tok.text]
                if info.prec < min_prec:
                    break
                self.next()
                nxt = info.prec + 1 if info.assoc in ("left", "none") else info.prec
                rhs = self.parse_expr(nxt)
                lhs = S.SBinOp(op=tok.text, lhs=lhs, rhs=rhs,
                               span=_join(_span_of(lhs), _span_of(rhs)))
                continue

            # juxtaposition application: f x
            if APP_PREC >= min_prec and self._can_start_atom(tok):
                arg = self._parse_prefix(app_arg=True)
                if isinstance(lhs, S.SApp):
                    lhs.args.append(arg)
                    lhs.span = _join(lhs.span, _span_of(arg))
                else:
                    lhs = S.SApp(fn=lhs, args=[arg],
                                 span=_join(_span_of(lhs), _span_of(arg)))
                continue

            break
        return lhs

    def _can_start_atom(self, t: Token) -> bool:
        if t.kind in ("IDENT", "NUM", "STR"):
            return True
        if t.kind == "KW" and t.text in ("fun", "forall", "exists", "if", "sorry", "not"):
            return True
        if t.kind == "SYM" and t.text in ("(", "⟨", "{", "λ", "∀", "∃", "_", "¬", "√"):
            return True
        return False

    def _parse_prefix(self, app_arg: bool = False) -> S.Expr:
        t = self.peek()

        # prefix operators (not consumed when parsing an application argument,
        # so `f -1` parses as (f) - (1) at the binop level)
        if not app_arg:
            if t.kind == "SYM" and t.text in PREFIX_PREC:
                self.next()
                operand = self.parse_expr(PREFIX_PREC[t.text])
                return S.SUnOp(op=t.text, operand=operand,
                               span=_join(_tok_span(t), _span_of(operand)))
            if t.kind == "SYM" and t.text in self.user_prefix:
                prec, target = self.user_prefix[t.text]
                self.next()
                operand = self.parse_expr(prec)
                return S.SApp(fn=S.SIdent(name=target, span=_tok_span(t)),
                              args=[operand],
                              span=_join(_tok_span(t), _span_of(operand)))
            if t.kind == "KW" and t.text == "not":
                self.next()
                operand = self.parse_expr(PREFIX_PREC["¬"])
                return S.SUnOp(op="¬", operand=operand,
                               span=_join(_tok_span(t), _span_of(operand)))

        return self._parse_atom()

    def _parse_atom(self) -> S.Expr:
        t = self.peek()

        if t.kind == "NUM":
            self.next()
            atom: S.Expr = S.SNum(value=t.value, is_decimal="." in t.text,
                                  span=_tok_span(t))
            return self._postfix(atom)

        if t.kind == "STR":
            self.next()
            return self._postfix(S.SStr(value=t.value, span=_tok_span(t)))

        if t.kind == "IDENT":
            name, tok0 = self.parse_qualified_name()
            atom = S.SIdent(name=name, span=_tok_span(tok0))
            return self._postfix(atom)

        if t.kind == "SYM" and t.text == "_":
            self.next()
            return self._postfix(S.SIdent(name="_", span=_tok_span(t)))

        if t.kind == "KW" and t.text == "sorry":
            self.next()
            return S.SSorry(span=_tok_span(t))

        if t.kind == "SYM" and t.text == "(":
            self.next()
            first = self.parse_expr(0)
            if self.at_sym(":"):
                self.next()
                ty = self.parse_expr(0)
                close = self.expect("SYM", ")")
                return self._postfix(S.SAscribe(
                    expr=first, ty=ty, span=_join(_tok_span(t), _tok_span(close))))
            if self.at_sym(","):
                args = [first]
                while self.at_sym(","):
                    self.next()
                    args.append(self.parse_expr(0))
                close = self.expect("SYM", ")")
                return self._postfix(S.STuple(args=args,
                                              span=_join(_tok_span(t), _tok_span(close))))
            close = self.expect("SYM", ")")
            first.span = _join(_tok_span(t), _tok_span(close))
            return self._postfix(first)

        if t.kind == "SYM" and t.text == "⟨":
            self.next()
            args = [self.parse_expr(0)]
            while self.at_sym(","):
                self.next()
                args.append(self.parse_expr(0))
            close = self.expect("SYM", "⟩")
            return self._postfix(S.SAnonCtor(args=args,
                                             span=_join(_tok_span(t), _tok_span(close))))

        if (t.kind == "SYM" and t.text == "λ") or (t.kind == "KW" and t.text == "fun"):
            self.next()
            binders = self.parse_binders(("=>", ","))
            if self.at_sym("=>"):
                self.next()
            else:
                self.expect("SYM", ",")
            body = self.parse_expr(0)
            return S.SLambda(binders=binders, body=body,
                             span=_join(_tok_span(t), _span_of(body)))

        if (t.kind == "SYM" and t.text == "∀") or (t.kind == "KW" and t.text == "forall"):
            self.next()
            binders = self.parse_binders((",",))
            self.expect("SYM", ",")
            body = self.parse_expr(0)
            return S.SForall(binders=binders, body=body,
                             span=_join(_tok_span(t), _span_of(body)))

        if (t.kind == "SYM" and t.text == "∃") or (t.kind == "KW" and t.text == "exists"):
            self.next()
            binders = self.parse_binders((",",))
            self.expect("SYM", ",")
            body = self.parse_expr(0)
            return S.SExists(binders=binders, body=body,
                             span=_join(_tok_span(t), _span_of(body)))

        if t.kind == "KW" and t.text == "if":
            self.next()
            cond = self.parse_expr(0)
            self.expect("KW", "then")
            then = self.parse_expr(0)
            self.expect("KW", "else")
            els = self.parse_expr(0)
            return S.SIf(cond=cond, then=then, els=els,
                         span=_join(_tok_span(t), _span_of(els)))

        if t.kind == "SYM" and t.text == "{":
            # set-builder { x : T | p }  (implicit binders are handled in
            # parse_binders, not here)
            self.next()
            name_tok = self.expect("IDENT")
            binder = S.SBinder(name=name_tok.text, span=_tok_span(name_tok))
            if self.at_sym(":"):
                self.next()
                binder.ty = self.parse_expr(0)
            self.expect("SYM", "|")
            pred = self.parse_expr(0)
            close = self.expect("SYM", "}")
            return S.SSetOf(binder=binder, pred=pred,
                            span=_join(_tok_span(t), _tok_span(close)))

        raise self.err(f"unexpected token '{t.text or t.kind}' in expression")

    def _postfix(self, atom: S.Expr) -> S.Expr:
        """Parenthesized call syntax f(a, b) - only when '(' hugs the callee."""
        while True:
            t = self.peek()
            if (t.kind == "SYM" and t.text == "(" and not self._blocked()
                    and self._hugs(atom, t)):
                self.next()
                args: list[S.Expr] = []
                if not self.at_sym(")"):
                    args.append(self.parse_expr(0))
                    while self.at_sym(","):
                        self.next()
                        args.append(self.parse_expr(0))
                close = self.expect("SYM", ")")
                if isinstance(atom, S.SApp):
                    atom.args.extend(args)
                    atom.span = _join(atom.span, _tok_span(close))
                else:
                    atom = S.SApp(fn=atom, args=args,
                                  span=_join(_span_of(atom), _tok_span(close)))
                continue
            break
        return atom

    def _hugs(self, atom: S.Expr, t: Token) -> bool:
        sp = _span_of(atom)
        return t.line == sp[2] and t.col == sp[3] + 1

    # ------------------------------------------------------------------
    # Binders
    # ------------------------------------------------------------------
    def parse_binders(self, stops: tuple[str, ...]) -> list[S.SBinder]:
        binders: list[S.SBinder] = []
        while True:
            t = self.peek()
            if t.kind == "SYM" and t.text in stops:
                break
            if t.kind == "SYM" and t.text in ("(", "{"):
                implicit = t.text == "{"
                close = ")" if t.text == "(" else "}"
                self.next()
                names: list[Token] = []
                while self.at("IDENT") or self.at_sym("_"):
                    names.append(self.next())
                self.expect("SYM", ":")
                ty = self.parse_expr(0)
                self.expect("SYM", close)
                for nt in names:
                    binders.append(S.SBinder(name=nt.text, ty=ty, implicit=implicit,
                                             span=_tok_span(nt)))
                continue
            if t.kind == "IDENT" or (t.kind == "SYM" and t.text == "_"):
                self.next()
                binders.append(S.SBinder(name=t.text, span=_tok_span(t)))
                continue
            break
        if not binders:
            raise self.err("expected at least one binder")
        return binders

    # ------------------------------------------------------------------
    # Proofs and tactics
    # ------------------------------------------------------------------
    def parse_proof(self, anchor_col: int) -> S.ProofLike:
        if self.at_kw("by"):
            by_tok = self.next()
            tactics = self.parse_tactic_block(anchor_col)
            return S.TacticProof(tactics=tactics, span=_tok_span(by_tok))
        term = self.parse_expr(0)
        return S.TermProof(term=term, span=_span_of(term))

    def parse_tactic_block(self, anchor_col: int) -> list[S.Tactic]:
        """Tactics after `by`: inline (same line, `;`-separated) and/or
        following lines indented deeper than anchor_col."""
        tactics: list[S.Tactic] = []
        saved = self.min_col
        self.min_col = anchor_col
        try:
            while True:
                t = self.peek()
                if t.kind == "EOF":
                    break
                if self._starts_line(t) and t.col <= anchor_col:
                    break
                if t.kind == "SYM" and t.text == ";":
                    self.next()
                    continue
                if not self._is_tactic_start(t):
                    break
                tactics.append(self.parse_tactic())
        finally:
            self.min_col = saved
        return tactics

    def _is_tactic_start(self, t: Token) -> bool:
        if t.kind == "IDENT" and (t.text in TACTIC_NAMES or True):
            # unknown names are parsed as tactics too -> better error messages
            return t.text not in COMMAND_KWS
        if t.kind == "KW" and t.text in ("exists", "calc", "sorry", "show"):
            return True
        return False

    def parse_tactic(self) -> S.Tactic:
        t = self.next()
        name = t.text
        tac = S.Tactic(name=name, span=_tok_span(t))
        saved = self.min_col
        self.min_col = t.col  # arguments must stay right of the tactic name
        try:
            if name in ("intro", "intros", "unfold", "clear"):
                while self.at("IDENT") and not self._blocked_line(t):
                    qname, _ = self.parse_qualified_name()
                    tac.idents.append(qname)
            elif name in ("exact", "apply", "show", "symm"):
                if name == "symm" and (self._blocked_line(t) or not self._can_start_atom(self.peek())):
                    pass
                else:
                    tac.terms.append(self.parse_expr(0))
            elif name == "exists":
                tac.terms.append(self.parse_expr(0))
                while self.at_sym(","):
                    self.next()
                    tac.terms.append(self.parse_expr(0))
            elif name in ("cases", "induction"):
                tac.terms.append(self.parse_expr(0))
                if self.at_kw("with"):
                    self.next()
                    if self.at_sym("|"):
                        tac.cases = self._parse_tactic_cases(t.col)
                    else:
                        while self.at("IDENT") and not self._blocked_line(t):
                            tac.idents.append(self.next().text)
            elif name in ("rw", "rewrite"):
                self.expect("SYM", "[")
                while True:
                    rev = False
                    if self.at_sym("<-"):
                        self.next()
                        rev = True
                    e = self.parse_expr(0)
                    step = S.Tactic(name="rw_step", terms=[e], reverse=rev,
                                    span=_span_of(e))
                    tac.cases.append(S.TacticCase(ctor="", tactics=[step]))
                    if self.at_sym(","):
                        self.next()
                        continue
                    break
                self.expect("SYM", "]")
                if self.at_kw("at"):
                    self.next()
                    tac.idents.append(self.next().text)
            elif name == "simp":
                if self.at_sym("["):
                    self.next()
                    while not self.at_sym("]"):
                        tac.terms.append(self.parse_expr(0))
                        if self.at_sym(","):
                            self.next()
                    self.expect("SYM", "]")
                if self.at_kw("at"):
                    self.next()
                    tac.idents.append(self.next().text)
            elif name == "have":
                hname = self.expect("IDENT").text
                tac.idents.append(hname)
                self.expect("SYM", ":")
                tac.terms.append(self.parse_expr(0))
                self.expect("SYM", ":=")
                tac.sub = self.parse_proof(t.col)
            elif name == "calc":
                tac.calc_steps, first = self._parse_calc(t.col)
                tac.terms.append(first)
            # remaining tactics take no arguments
        finally:
            self.min_col = saved
        return tac

    def _blocked_line(self, anchor: Token) -> bool:
        t = self.peek()
        if t.kind == "EOF":
            return True
        return self._starts_line(t) and t.col <= anchor.col

    def _parse_tactic_cases(self, anchor_col: int) -> list[S.TacticCase]:
        cases: list[S.TacticCase] = []
        while self.at_sym("|"):
            bar = self.next()
            ctor_tok = self.expect("IDENT")
            case = S.TacticCase(ctor=ctor_tok.text, span=_tok_span(bar))
            while self.at("IDENT"):
                case.names.append(self.next().text)
            self.expect("SYM", "=>")
            case.tactics = self.parse_tactic_block(bar.col)
            cases.append(case)
        return cases

    def _parse_calc(self, anchor_col: int) -> tuple[list, S.Expr]:
        """calc e0 op e1 := proof / _ op e2 := proof ..."""
        first = self.parse_expr(51)  # bind tighter than relations
        steps: list = []
        while True:
            t = self.peek()
            if t.kind == "SYM" and t.text in ("=", "<", "<=", ">", ">=", "!="):
                op = self.next().text
                rhs = self.parse_expr(51)
                self.expect("SYM", ":=")
                prf = self.parse_proof(t.col)
                steps.append((op, rhs, prf))
                # subsequent lines start with _ (lexed as an IDENT)
                if self.at("IDENT", "_") or self.at_sym("_"):
                    self.next()
                    continue
                break
            break
        return steps, first

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def parse_module(self) -> S.CModule:
        cmds: list[S.Command] = []
        while not self.at("EOF"):
            cmds.append(self.parse_command())
        return S.CModule(commands=cmds)

    def parse_attribute(self) -> S.SAttr:
        """`key` (a flag) or `key "value"` (a keyed attribute)."""
        tok = self.peek()
        if tok.kind not in ("IDENT", "KW"):
            raise self.err(f"expected an attribute name, found "
                           f"'{tok.text or tok.kind}'")
        self.next()
        if self.at("STR"):
            val = self.next()
            return S.SAttr(key=tok.text, value=val.value,  # type: ignore[arg-type]
                           span=_join(_tok_span(tok), _tok_span(val)))
        return S.SAttr(key=tok.text, span=_tok_span(tok))

    def parse_command(self) -> S.Command:
        doc: Optional[str] = None
        attrs: list[S.SAttr] = []
        while True:
            if self.at("DOC"):
                doc = self.next().value  # type: ignore[assignment]
                continue
            if self.at_sym("@["):
                self.next()
                while not self.at_sym("]"):
                    attrs.append(self.parse_attribute())
                    if self.at_sym(","):
                        self.next()
                        continue
                    break
                self.expect("SYM", "]")
                continue
            break

        t = self.peek()
        saved = self.min_col
        # commands own everything indented strictly deeper than their first token
        self.min_col = t.col
        try:
            cmd = self._parse_command_inner(t)
        finally:
            self.min_col = saved
        cmd.doc = doc
        cmd.attrs = attrs + cmd.attrs
        return cmd

    def _parse_command_inner(self, t: Token) -> S.Command:
        if t.kind == "KW" and t.text in ("def", "define"):
            self.next()
            name, _ = self.parse_qualified_name()
            binders: list[S.SBinder] = []
            if not (self.at_sym(":") or self.at_sym(":=")):
                binders = self.parse_binders((":", ":="))
            ty = None
            if self.at_sym(":"):
                self.next()
                ty = self.parse_expr(0)
            self.expect("SYM", ":=")
            value = self.parse_expr(0)
            return S.CDef(name=name, binders=binders, ty=ty, value=value,
                          span=_tok_span(t))

        if t.kind == "KW" and t.text == "constant":
            self.next()
            name, _ = self.parse_qualified_name()
            self.expect("SYM", ":")
            ty = self.parse_expr(0)
            return S.CConstant(name=name, ty=ty, span=_tok_span(t))

        if t.kind == "KW" and t.text == "axiom":
            self.next()
            name, _ = self.parse_qualified_name()
            binders = []
            if not self.at_sym(":"):
                binders = self.parse_binders((":",))
            self.expect("SYM", ":")
            ty = self.parse_expr(0)
            return S.CAxiom(name=name, binders=binders, ty=ty, span=_tok_span(t))

        if t.kind == "KW" and t.text in ("theorem", "lemma", "proposition",
                                         "corollary", "example"):
            self.next()
            name = ""
            if t.text != "example":
                name, _ = self.parse_qualified_name()
            binders = []
            if not self.at_sym(":"):
                binders = self.parse_binders((":",))
            self.expect("SYM", ":")
            statement = self.parse_expr(0)
            proof: Optional[S.ProofLike] = None
            if self.at_sym(":="):
                self.next()
                proof = self.parse_proof(t.col)
            return S.CTheorem(kind=t.text, name=name, binders=binders,
                              statement=statement, proof=proof, span=_tok_span(t))

        if t.kind == "KW" and t.text == "inductive":
            self.next()
            name, _ = self.parse_qualified_name()
            binders = []
            if not (self.at_sym(":") or self.at_kw("where")):
                binders = self.parse_binders((":",))
            ty = None
            if self.at_sym(":"):
                self.next()
                ty = self.parse_expr(0)
            self.expect("KW", "where")
            ctors: list[S.CInductiveCtor] = []
            while self.at_sym("|"):
                self.next()
                cname = self.expect("IDENT").text
                self.expect("SYM", ":")
                cty = self.parse_expr(0)
                ctors.append(S.CInductiveCtor(name=cname, ty=cty))
            return S.CInductive(name=name, binders=binders, ty=ty, ctors=ctors,
                                span=_tok_span(t))

        if t.kind == "KW" and t.text == "structure":
            self.next()
            name, _ = self.parse_qualified_name()
            binders = []
            if not self.at_kw("where"):
                binders = self.parse_binders(("where",)) if not self.at_kw("where") else []
            self.expect("KW", "where")
            fields: list[S.CStructureField] = []
            while self.at("IDENT"):
                ftok = self.next()
                self.expect("SYM", ":")
                saved = self.min_col
                self.min_col = ftok.col  # each field owns one (indented) line
                try:
                    fty = self.parse_expr(0)
                finally:
                    self.min_col = saved
                fields.append(S.CStructureField(name=ftok.text, ty=fty))
            return S.CStructure(name=name, binders=binders, fields=fields,
                                span=_tok_span(t))

        if t.kind == "KW" and t.text == "import":
            self.next()
            name, _ = self.parse_qualified_name()
            return S.CImport(module=name, span=_tok_span(t))

        if t.kind == "KW" and t.text == "open":
            self.next()
            name, _ = self.parse_qualified_name()
            return S.COpen(name=name, span=_tok_span(t))

        if t.kind == "KW" and t.text == "namespace":
            self.next()
            name, _ = self.parse_qualified_name()
            body: list[S.Command] = []
            saved = self.min_col
            self.min_col = 0
            try:
                while not self.at("EOF") and not self.at_kw("end"):
                    body.append(self.parse_command())
            finally:
                self.min_col = saved
            self.expect("KW", "end")
            end_name, _ = self.parse_qualified_name()
            if end_name != name:
                raise self.err(f"'end {end_name}' does not match 'namespace {name}'")
            return S.CNamespace(name=name, body=body, span=_tok_span(t))

        if t.kind == "KW" and t.text == "plot":
            self.next()
            exprs = [self.parse_expr(0)]
            var, lo, hi = "x", None, None
            while self.at_sym(","):
                # lookahead for range clause: IDENT ∈ [lo, hi]
                if (self.peek(1).kind == "IDENT"
                        and self.peek(2).kind == "SYM" and self.peek(2).text == "∈"
                        and self.peek(3).kind == "SYM" and self.peek(3).text == "["):
                    self.next()
                    var = self.next().text
                    self.next()  # ∈
                    self.next()  # [
                    lo = self.parse_expr(0)
                    self.expect("SYM", ",")
                    hi = self.parse_expr(0)
                    self.expect("SYM", "]")
                    break
                self.next()
                exprs.append(self.parse_expr(0))
            return S.CPlot(exprs=exprs, var=var, lo=lo, hi=hi, span=_tok_span(t))

        if t.kind == "KW" and t.text in ("infixl", "infixr", "prefix", "postfix"):
            self.next()
            prec_tok = self.expect("NUM")
            sym_tok = self.expect("STR")
            self.expect("SYM", ":=")
            target, _ = self.parse_qualified_name()
            self._register_op(t.text, int(prec_tok.value), sym_tok.value, target)
            return S.CNotation(fixity=t.text, precedence=int(prec_tok.value),
                               symbol=sym_tok.value, target=target, span=_tok_span(t))

        if t.kind == "SYM" and t.text == "#":
            self.next()
            sub = self.expect("IDENT").text
            if sub == "check":
                return S.CCheck(expr=self.parse_expr(0), span=_tok_span(t))
            if sub in ("eval", "simplify", "normalize"):
                c = S.CEval(expr=self.parse_expr(0), span=_tok_span(t))
                c.attrs = [S.SAttr(key=sub, span=_tok_span(t))]
                return c
            raise self.err(f"unknown directive '#{sub}'")

        raise self.err(f"expected a command, found '{t.text or t.kind}'")


# ---------------------------------------------------------------------------

def _tok_span(t: Token) -> S.Span:
    return (t.line, t.col, t.line, t.col + max(0, len(t.text) - 1))


def _span_of(e) -> S.Span:
    return getattr(e, "span", (0, 0, 0, 0))


def _join(a: S.Span, b: S.Span) -> S.Span:
    lo = min((a[0], a[1]), (b[0], b[1]))
    hi = max((a[2], a[3]), (b[2], b[3]))
    return (lo[0], lo[1], hi[0], hi[1])


def parse_module(src: str, extra_ops=None) -> S.CModule:
    return Parser(src, extra_ops).parse_module()


def parse_expression(src: str, extra_ops=None) -> S.Expr:
    p = Parser(src, extra_ops)
    e = p.parse_expr(0)
    if not p.at("EOF"):
        t = p.peek()
        raise ParseError(f"unexpected trailing input '{t.text}'", t.line, t.col)
    return e
