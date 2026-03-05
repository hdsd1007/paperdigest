"""Lightweight LaTeX → Unicode converter for Substack export.

Best-effort conversion of common math expressions to Unicode characters.
Complex expressions fall back to raw LaTeX in code formatting.
No external dependencies — uses only Python stdlib.
"""

import re

# Greek letters (lowercase + uppercase)
_GREEK = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ",
    r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
    r"\pi": "π", r"\varpi": "ϖ", r"\rho": "ρ", r"\varrho": "ϱ",
    r"\sigma": "σ", r"\varsigma": "ς", r"\tau": "τ", r"\upsilon": "υ",
    r"\phi": "φ", r"\varphi": "ϕ", r"\chi": "χ", r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
    r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Upsilon": "Υ",
    r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
}

# Subscript digits and common letters
_SUBSCRIPTS = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "a": "ₐ", "e": "ₑ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ",
    "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
}

# Superscript digits and common characters
_SUPERSCRIPTS = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ",
    "i": "ⁱ", "j": "ʲ", "k": "ᵏ", "n": "ⁿ", "o": "ᵒ",
    "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
    "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "T": "ᵀ",
}

# Mathematical operators and symbols
_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷",
    r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
    r"\equiv": "≡", r"\sim": "∼", r"\simeq": "≃", r"\propto": "∝",
    r"\ll": "≪", r"\gg": "≫",
    r"\sum": "∑", r"\prod": "∏", r"\int": "∫",
    r"\partial": "∂", r"\nabla": "∇", r"\infty": "∞",
    r"\forall": "∀", r"\exists": "∃",
    r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃",
    r"\subseteq": "⊆", r"\supseteq": "⊇",
    r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅",
    r"\rightarrow": "→", r"\to": "→", r"\leftarrow": "←",
    r"\Rightarrow": "⇒", r"\Leftarrow": "⇐",
    r"\leftrightarrow": "↔", r"\Leftrightarrow": "⇔",
    r"\mapsto": "↦",
    r"\sqrt": "√", r"\circ": "∘", r"\bullet": "•",
    r"\star": "⋆", r"\ast": "∗",
    r"\langle": "⟨", r"\rangle": "⟩",
    r"\lceil": "⌈", r"\rceil": "⌉", r"\lfloor": "⌊", r"\rfloor": "⌋",
    r"\ldots": "…", r"\cdots": "⋯", r"\dots": "…",
    r"\ell": "ℓ", r"\hbar": "ℏ", r"\Re": "ℜ", r"\Im": "ℑ",
    r"\aleph": "ℵ",
    r"\neg": "¬", r"\wedge": "∧", r"\vee": "∨",
    r"\oplus": "⊕", r"\otimes": "⊗",
    r"\dagger": "†",
    r"\quad": " ", r"\qquad": "  ", r"\,": " ", r"\;": " ", r"\:": " ",
    r"\ ": " ",
}

# Patterns that indicate an expression is too complex for Unicode
_COMPLEX_PATTERNS = [
    r"\\begin\{", r"\\end\{",          # environments (align, matrix, etc.)
    r"\\frac\{[^}]*\{",                # nested fractions
    r"\\sqrt\[",                        # nth roots
    r"\\overset", r"\\underset",
    r"\\stackrel",
    r"\\overbrace", r"\\underbrace",
]


def _is_simple_enough(latex: str) -> bool:
    """Check if a LaTeX expression can be reasonably represented in Unicode."""
    for pat in _COMPLEX_PATTERNS:
        if re.search(pat, latex):
            return False
    # Deep brace nesting (more than 3 levels) is too complex
    depth = 0
    max_depth = 0
    for ch in latex:
        if ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth -= 1
    if max_depth > 3:
        return False
    return True


def _convert_scripts(text: str, table: dict, marker: str) -> str:
    """Convert subscript/superscript sequences using a character table.

    Handles both single char (e.g., _i) and braced groups (e.g., _{max}).
    """
    # Braced groups: _{...} or ^{...}
    def _replace_braced(m):
        content = m.group(1)
        converted = "".join(table.get(ch, ch) for ch in content)
        return converted

    text = re.sub(re.escape(marker) + r"\{([^}]*)\}", _replace_braced, text)

    # Single character: _x or ^x (not followed by {)
    def _replace_single(m):
        ch = m.group(1)
        return table.get(ch, marker + ch)

    text = re.sub(re.escape(marker) + r"([A-Za-z0-9+\-=()])", _replace_single, text)

    return text


def _convert_frac(text: str) -> str:
    """Convert \\frac{a}{b} to a/b."""
    # Simple fractions only — single-level braces
    def _replace(m):
        num = m.group(1)
        den = m.group(2)
        # If numerator or denominator has spaces/operators, wrap in parens
        if len(num) > 1 and not num.isalnum():
            num = f"({num})"
        if len(den) > 1 and not den.isalnum():
            den = f"({den})"
        return f"{num}/{den}"

    return re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", _replace, text)


def latex_to_unicode(raw_math: str) -> str | None:
    """Convert a LaTeX math expression to Unicode text.

    Returns the Unicode string on success, or None if the expression
    is too complex (caller should fall back to <code> display).
    """
    # Strip dollar-sign delimiters
    text = raw_math.strip()
    if text.startswith("$$"):
        text = text[2:]
        if text.endswith("$$"):
            text = text[:-2]
    elif text.startswith("$"):
        text = text[1:]
        if text.endswith("$"):
            text = text[:-1]
    text = text.strip()

    if not text:
        return ""

    if not _is_simple_enough(text):
        return None

    # Strip formatting commands that don't affect Unicode output
    for cmd in [r"\displaystyle", r"\textstyle", r"\scriptstyle",
                r"\left", r"\right", r"\bigl", r"\bigr",
                r"\Bigl", r"\Bigr", r"\biggl", r"\biggr"]:
        text = text.replace(cmd, "")

    # Unwrap text/font commands: \text{...} → ..., \mathbf{...} → ..., etc.
    for cmd in [r"\text", r"\mathrm", r"\mathbf", r"\mathit", r"\mathcal",
                r"\mathbb", r"\mathsf", r"\mathtt", r"\textbf", r"\textit",
                r"\operatorname", r"\boldsymbol", r"\bm"]:
        text = re.sub(re.escape(cmd) + r"\{([^}]*)\}", r"\1", text)

    # Convert \frac{a}{b} → a/b
    text = _convert_frac(text)

    # Replace Greek letters (longest match first to avoid partial matches)
    for cmd in sorted(_GREEK.keys(), key=len, reverse=True):
        text = text.replace(cmd, _GREEK[cmd])

    # Replace mathematical symbols
    for cmd in sorted(_SYMBOLS.keys(), key=len, reverse=True):
        text = text.replace(cmd, _SYMBOLS[cmd])

    # Convert subscripts and superscripts
    text = _convert_scripts(text, _SUBSCRIPTS, "_")
    text = _convert_scripts(text, _SUPERSCRIPTS, "^")

    # Clean up remaining LaTeX artifacts
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\\[a-zA-Z]+", "", text)  # remove unknown commands
    text = re.sub(r"\s+", " ", text).strip()

    return text
