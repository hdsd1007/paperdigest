"""
summarizer.py
-------------
Takes paper Markdown and produces:
  1. Narrative 10-minute digest (Markdown, Substack style)
  2. PaperBanana diagram descriptions
"""

import os
import json
import re
from llm_client import llm_call

NUM_DIAGRAMS = int(os.getenv("NUM_DIAGRAMS", "4"))

# ── 1. Summary prompt ────────────────────────────────────────────────────────

SUMMARY_PROMPT = """You are a science storyteller writing a Substack deep-dive. Write a narrative digest (~2000-2500 words, max 15-minute read) that takes a curious reader from "why should I care?" to solid understanding.

STORYTELLING APPROACH:
Every section starts simple enough for a smart 15-year-old, then layers in technical depth.
Follow this progression: everyday analogy → plain-English explanation → technical detail.
Start with WHY before WHAT. Make the reader feel the problem before showing the solution.
Keep it digestible — this is a magazine article, not a textbook chapter.

VOICE:
- Write like a favorite science YouTuber — enthusiastic, clear, and conversational.
- Start every major idea with a real-world analogy BEFORE any technical explanation.
- When explaining a complex mechanism, use a CONCRETE EXAMPLE with specific values
  (e.g., "Say you have 1000 images and only 10 labels...").
- Use plain English first. When you introduce a technical term, define it immediately in everyday words.
- One idea per sentence. Short paragraphs (2-3 sentences max).
- Use vivid analogies: "think of it like...", "imagine you're...", "this is similar to..."
- Direct and personal: "here's the clever part...", "you might wonder why..."
- Define every acronym on first use. No jargon without explanation.
- No filler. Every sentence should teach something or build intuition.

MATHEMATICS — KEEP IT MINIMAL:
- Prefer plain English over equations. Most ideas can be explained without formulas.
- Include AT MOST 1 equation in the entire article — only the paper's single most important formula
  (e.g., the core loss function or the main update rule). Skip everything else.
- When you DO use an equation, use ONLY simple, short LaTeX inline with $...$.
  Avoid display math ($$...$$) unless the equation truly cannot fit inline.
- Explain the intuition BEFORE the equation, then move on to the next idea.
  ANTI-PATTERN (NEVER do this):
    $$equation$$
    Here, $X$ is the ..., $Y$ is the ..., $Z$ is the ...
  Instead: explain what the equation means in plain English BEFORE showing it, then continue.
- HARD RULE: After any equation ($...$ or $$...$$), the NEXT sentence must introduce
  a NEW idea, result, or step. It must NOT define variables from the equation.
  If you catch yourself writing "where $X$ is..." or "Here, $X$ denotes...", DELETE IT
  and move on. The reader already understands from your pre-equation explanation.
- EVERY variable must be wrapped in $...$. NEVER write raw variable names inline.
  WRONG: "The model runs Nsup steps."  RIGHT: "The model runs $N_{{sup}}$ steps."
- If unsure of the LaTeX, write it in plain English instead. Bare undelimited math is forbidden.
- NEVER wrap $...$ in backticks. Write $x$ directly, NOT `$x$`.

FORMATTING:
- **Bold** key terms on first introduction.
- `code font` for model names, hyperparameters, function names only (NEVER for math).
- Blockquotes (>) for direct quotes from the paper — always attribute.
- Numbered lists for sequential processes.
- Bullet lists for parallel items.

STRUCTURE — use these exact 6 section headings (no more, no less):

## The Big Picture
Open with a hook that a non-expert would understand — connect the paper's problem to something
in everyday life. 2-3 punchy opening sentences on what this paper does and why it matters.
Then set the scene: what existed before? What was broken or missing? Use a relatable analogy
to make the reader *feel* the limitation. Include a blockquote from the paper. End by teasing
the solution.
Place [DIAGRAM: (Arc 1) description] as the LAST thing in this section (REQUIRED).
The reader sees the napkin-sketch visual metaphor before diving into the detailed explanation.

## The Core Idea
THIS IS THE MOST IMPORTANT SECTION — give it the most space.
Start at an "explain to a teenager" level, then progressively reveal depth:
1. Vivid everyday analogy (2-3 sentences) — make the reader SEE the idea
2. What the approach does (plain English, no jargon, one sentence)
3. A concrete example with made-up numbers (e.g., "Say you have 100 sentences...")
4. NOW introduce technical terms, mapping each back to the analogy
5. Key design choices and WHY they matter (bold the choice, one sentence of reasoning)
Avoid equations in this section unless absolutely essential.
Place [DIAGRAM: (Arc 2) description] showing component relationships (REQUIRED).
If the paper builds on a prerequisite concept the reader may not know (e.g. autoencoders,
attention, RL), make the Arc 2 diagram a simple prerequisite explainer instead.

## How It Works
Concrete pipeline walkthrough. Walk through the method as a numbered sequence.
Name the components, describe what each step does in plain English.
Include at most 1 equation if essential. Fold in any important design choices.
Do NOT include code blocks — code is added separately.
Place [DIAGRAM: (Arc 3) description] for the full blueprint/pipeline here (REQUIRED).

## Results & Insights
Lead with the most impressive result and explain why it's impressive.
Cover 2-3 key experiments with context. Include ablations inline — what breaks when you
remove a component? What surprised the authors? Use specific numbers.
If the paper has benchmark comparisons or performance numbers, describe them in a way
that invites a chart: "Model X achieves 92.3% vs 87.1% for the baseline — a 5.2% jump."
Place a [DIAGRAM: (Arc 4) description] marker for a comparison chart with exact numbers (REQUIRED).
If the paper has ablation studies or additional benchmarks, place a SECOND [DIAGRAM: (Arc 4) ...]
marker for an ablation or breakdown chart (ENCOURAGED — make this section visually rich).

## Limitations & Future
Honest assessment: what doesn't work, what's missing, computational cost.
Then forward-looking: what does this unlock? Who should pay attention?
Keep it tight — 3-5 sentences total.

## Key Takeaways
3-5 bullet points. Bold the key phrase in each. One sentence per bullet.
Write each takeaway so a non-expert would understand it — no unexplained jargon.

DIAGRAM MARKERS — PROGRESSIVE TEACHING ARC:
Place [DIAGRAM: (Arc N) one-sentence description] markers right after the paragraph that
explains the concept. Target {num_diagrams} markers total.

The diagrams follow a progressive teaching arc. A reader flipping through JUST the
diagrams should get the whole story — from napkin sketch to full blueprint to proof.

ARC LEVELS (each builds on the last):

**Arc 1 — "The Napkin" (REQUIRED, end of The Big Picture section):**
The instant-intuition diagram. 2-3 shapes MAX, one visual metaphor, everyday words only.
"Get the idea in 3 seconds." No math, no tensors, no architecture details.
Think: funnel, sieve, feedback loop, conveyor belt.
Place this as the LAST element of The Big Picture, right before ## The Core Idea.
Example marker: [DIAGRAM: (Arc 1) a funnel squeezing raw text into a compact summary]

**Arc 2 — "The Mechanism" (REQUIRED, Core Idea section):**
Shows how the components connect. 4-5 boxes, labeled relationships, one level deeper.
If the paper assumes a complex prerequisite (autoencoders, attention, RL), this slot
becomes a prerequisite explainer instead — use Arc 1 styling (2-3 shapes, everyday words).
Example marker: [DIAGRAM: (Arc 2) encoder takes input, bottleneck compresses, decoder reconstructs]

**Arc 3 — "The Blueprint" (REQUIRED, How It Works section):**
Full pipeline/architecture. 5-7 boxes, technical terms OK (reader earned context from Arc 1-2).
Color zones for grouping phases, solid + dashed arrows for different data paths.
Example marker: [DIAGRAM: (Arc 3) full training pipeline from data loading through loss computation]

**Arc 4 — "The Evidence" (REQUIRED, Results section):**
Always a chart with EXACT numbers from the paper. Bar chart, grouped bars, or comparison visual.
Specify bar labels, values, axis labels. Paper's method highlighted.
Example marker: [DIAGRAM: (Arc 4) bar chart showing Model X at 92.3% vs Baseline at 87.1%]

SLOT ALLOCATION:
- ALWAYS include all 4 arcs: Arc 1 + Arc 2 + Arc 3 + Arc 4 (minimum 4 diagrams).
- 5-6 diagrams: Full arc + extra Arc 4 ablation/breakdown chart in Results (encouraged)
- Results & Insights should be the most visually rich section — 2 charts if data supports it

SECTION PLACEMENT (all 4 arcs REQUIRED):
- **The Big Picture:** MUST contain Arc 1 as its last element (visual hook before the explanation).
- **The Core Idea:** MUST contain Arc 2 (mechanism or prerequisite explainer).
- **How It Works:** MUST contain Arc 3 (full blueprint/pipeline).
- **Results & Insights:** MUST contain Arc 4 (evidence chart with exact numbers).

LENGTH CALIBRATION (strict — target 2000-2500 words, max 15-minute read):
- The Big Picture: ~300-400 words
- The Core Idea: ~600-800 words (deepest section)
- How It Works: ~400-500 words
- Results & Insights: ~350-450 words
- Limitations & Future: ~100-150 words
- Key Takeaways: ~80-120 words

OUTPUT RULES:
- Output ONLY valid Markdown.
- Do NOT number diagrams — just use [DIAGRAM: ...] inline.
- Include at least 2-3 blockquotes from the paper.
- NEVER wrap $...$ in backticks — write math directly, not inside `code` spans.
- NEVER put an equation interpretation block below an equation. Weave it into prose.
- Code snippets (added later) will be pseudo-code style — do NOT include code blocks yourself.

{abstract_block}{table_block}{profile_notes}Paper text (may be truncated at 120 000 chars):
{paper_markdown}"""


REQUIRED_SECTIONS = [
    "## The Big Picture",
    "## The Core Idea",
    "## How It Works",
    "## Results & Insights",
    "## Limitations & Future",
    "## Key Takeaways",
]


def _validate_summary(summary: str, profile: dict | None = None, has_tables: bool = False) -> tuple[bool, list[str]]:
    """Programmatic quality checks on a generated summary.

    Returns (is_valid, list_of_issues).
    """
    issues: list[str] = []

    # 1. Word count between 1200-3000
    word_count = len(summary.split())
    if word_count < 1200:
        issues.append(f"Too short ({word_count} words, min 1200)")
    elif word_count > 3000:
        issues.append(f"Too long ({word_count} words, max 3000)")

    # 2. All 6 required section headings present
    for heading in REQUIRED_SECTIONS:
        if heading not in summary:
            issues.append(f"Missing section: {heading}")

    # 3. Enough [DIAGRAM:] markers — use profile target, floor of 4
    target_diagrams = 4
    if profile and "num_diagrams" in profile:
        target_diagrams = max(4, profile["num_diagrams"])
    diagram_count = _count_diagram_markers(summary)
    if diagram_count < target_diagrams:
        issues.append(f"Too few diagram markers ({diagram_count}, need at least {target_diagrams})")

    # 4. Big Picture section must have at least one [DIAGRAM:] marker (Arc 1)
    big_picture_match = re.search(
        r"## The Big Picture\n(.*?)(?=\n## |\Z)", summary, re.DOTALL
    )
    if big_picture_match:
        big_picture_text = big_picture_match.group(1)
        if not re.search(r"\[DIAGRAM:\s*.+?\]", big_picture_text):
            issues.append("The Big Picture section is missing a [DIAGRAM:] marker (Arc 1 required at end)")

    # 5. Check for [TABLE:] markers when tables were provided
    if has_tables:
        table_count = len(re.findall(r"\[TABLE:\s*\d+\]", summary))
        if table_count == 0:
            issues.append("Tables were provided but no [TABLE: N] markers found in summary")

    # 6. Heuristic for undelimited math — doubled-letter variable patterns outside code/math
    #    e.g. "zz", "yy", "xx" that indicate bare variable names
    stripped = re.sub(r'\$.*?\$', '', summary)           # remove inline math
    stripped = re.sub(r'```.*?```', '', stripped, flags=re.DOTALL)  # remove code blocks
    stripped = re.sub(r'`[^`]+`', '', stripped)           # remove inline code
    if re.search(r'(?<![a-zA-Z])([a-z])\1(?![a-zA-Z])', stripped):
        issues.append("Possible undelimited math variables (doubled letters like 'zz' outside math)")

    return (len(issues) == 0, issues)


def generate_summary(
    paper_markdown: str,
    profile: dict | None = None,
    abstract: str = "",
    table_descriptions: str = "",
) -> str:
    """Returns the narrative digest as Markdown.

    Args:
        paper_markdown: Full paper text in Markdown.
        profile: Optional profile dict from paper_profiler.profile_paper().
                 Steers diagram count and adds profile notes to the prompt.
        abstract: Extracted abstract text (used to craft story-like opening).
        table_descriptions: Formatted table descriptions for placement markers.
    """
    truncated = paper_markdown[:120_000]

    # Determine diagram count: profile overrides env default
    num_diagrams = NUM_DIAGRAMS
    if profile and "num_diagrams" in profile:
        num_diagrams = profile["num_diagrams"]

    # Build profile notes block
    profile_notes = ""
    if profile:
        from paper_profiler import build_profile_notes
        notes = build_profile_notes(profile)
        if notes:
            profile_notes = notes + "\n\n"

    # Build abstract block
    abstract_block = ""
    if abstract:
        abstract_block = (
            f"ABSTRACT (use this to craft your opening):\n{abstract}\n\n"
            "Use this abstract to craft \"The Big Picture\" as a story-like narrative — not a literal copy\n"
            "but a simplified, engaging retelling. Weave in the key result highlights and why this matters.\n"
            "A non-expert should understand the opening without any technical background.\n\n"
        )

    # Build table block
    table_block = ""
    if table_descriptions:
        table_block = (
            f"IMPORTANT TABLES (place these in Results & Insights):\n{table_descriptions}\n\n"
            "RULES for table placement:\n"
            "- ONLY use [TABLE: 1] and [TABLE: 2] markers. Do NOT use any other table numbers.\n"
            "- Place [TABLE: 1] BEFORE [TABLE: 2] in the document (chronological order).\n"
            "- Place each marker on its own line, right after the paragraph discussing those results.\n"
            "- Do NOT include raw markdown tables (| header | ... |) — only the [TABLE: N] markers.\n\n"
        )

    prompt = SUMMARY_PROMPT.format(
        paper_markdown=truncated,
        num_diagrams=num_diagrams,
        profile_notes=profile_notes,
        abstract_block=abstract_block,
        table_block=table_block,
    )

    result = llm_call(prompt=prompt, max_tokens=12288, temperature=0.4)
    summary = result.text

    _has_tables = bool(table_descriptions)

    # Validate — retry once if issues found
    valid, issues = _validate_summary(summary, profile, has_tables=_has_tables)
    if not valid:
        # Retry with issues appended
        issues_block = "\n".join(f"- {issue}" for issue in issues)
        retry_prompt = (
            prompt
            + f"\n\nPREVIOUS ATTEMPT HAD ISSUES:\n{issues_block}\n"
            + "Please fix these issues in your response."
        )

        try:
            retry_result = llm_call(prompt=retry_prompt, max_tokens=12288, temperature=0.4)
            retry_summary = retry_result.text
            retry_valid, retry_issues = _validate_summary(retry_summary, profile, has_tables=_has_tables)

            if retry_valid:
                summary = retry_summary
            elif len(retry_issues) < len(issues):
                summary = retry_summary
        except Exception:
            pass

    # Ensure enough diagram markers even if LLM under-produced them
    summary = _inject_diagram_markers(summary, num_diagrams)
    return summary


def _inject_diagram_markers(summary: str, target: int) -> str:
    """If the summary has fewer [DIAGRAM:] markers than target, insert generic
    markers at the end of sections that don't already have one.

    Sections eligible for injection (in priority order):
      The Core Idea, How It Works, Results & Insights, The Big Picture
    """
    current = _count_diagram_markers(summary)
    if current >= target:
        return summary

    needed = target - current

    # Sections where a diagram adds the most value, in priority order
    section_diagram_hints = [
        ("## The Big Picture", "(Arc 1) simple intuitive illustration using an everyday analogy — 2-3 shapes max, plain English labels, napkin style"),
        ("## The Core Idea", "(Arc 2) how the key components connect — 4-5 boxes showing relationships"),
        ("## How It Works", "(Arc 3) step-by-step pipeline or full architecture blueprint of the method"),
        ("## Results & Insights", "(Arc 4) bar chart comparing key performance metrics with exact numbers"),
    ]

    lines = summary.split("\n")
    result_lines = list(lines)

    for section_heading, hint in section_diagram_hints:
        if needed <= 0:
            break

        # Find this section's heading and the next ## heading
        sec_start = None
        sec_end = None
        for i, line in enumerate(result_lines):
            if line.strip().startswith(section_heading):
                sec_start = i
            elif sec_start is not None and line.strip().startswith("## ") and i > sec_start:
                sec_end = i
                break
        if sec_start is None:
            continue
        if sec_end is None:
            sec_end = len(result_lines)

        # Check if this section already has a diagram marker
        section_text = "\n".join(result_lines[sec_start:sec_end])
        if re.search(r"\[DIAGRAM:\s*.+?\]", section_text):
            continue

        # Insert marker before the next section heading
        marker = f"\n[DIAGRAM: {hint}]\n"
        result_lines.insert(sec_end, marker)
        needed -= 1

    return "\n".join(result_lines)


# ── 2. PaperBanana descriptions ──────────────────────────────────────────────

BANANA_PROMPT = """You are writing visual descriptions for PaperBanana, an AI diagram generator
that uses Gemini image generation to produce high-quality scientific illustrations.

Given the research paper AND summary below, write EXACTLY {num_diagrams} descriptions —
one per [DIAGRAM: (Arc N) ...] marker in the summary, in order.

Return a JSON array with {num_diagrams} objects:
  - "filename": short slug, e.g. "method_overview"
  - "caption": 2-3 sentence descriptive caption. First sentence: what the diagram shows.
    Second sentence: why this matters or what insight it gives. Third (optional): a key
    takeaway or connection to the paper's contribution. NOT a single generic line.
  - "text": 300-500 word SPATIALLY EXPLICIT description of EXACTLY what to draw (see rules below)
  - "arc_level": integer 1-4 matching the (Arc N) tag in the marker
  - "diagram_type": "statistical_plot" for Arc 4, "methodology" for all others

CRITICAL DESCRIPTION QUALITY RULES:
Your "text" field is the SINGLE INPUT that determines the quality of the generated image.
A vague description = a vague diagram. A spatially explicit description = a crisp diagram.

1. USE ZONE-BASED LAYOUT: Divide the canvas into named zones (left third, center, right third;
   top half, bottom half). Place each element in a specific zone.
2. SPECIFY EXACT POSITIONS: "In the left third of the canvas...", "Centered horizontally at
   the top...", "In the bottom-right quadrant..."
3. DESCRIBE EVERY VISUAL ELEMENT: Shape type, size (large/medium/small), fill color (use
   specific colors like "#4A90D9 blue" or "soft pastel mint #B8E6C8"), border style, corner
   radius, shadow.
4. LABEL EVERY ELEMENT: Specify the exact text, font weight (bold/regular), font size
   (large/medium/small), color, and position relative to the shape (inside, above, below).
5. DESCRIBE EVERY ARROW/CONNECTION: Start point, end point, thickness, color, style
   (solid/dashed), arrowhead type, any label on the arrow.
6. ALWAYS END with a style suffix line (specified per arc below).

PROGRESSIVE COMPLEXITY PHILOSOPHY:
Think of explaining to a child who grows up through the article. Arc 1 is a 5-year-old.
Arc 2 is a curious teenager. Arc 3 is a college student. Arc 4 is a scientist checking results.
Each diagram builds on the vocabulary established by the previous ones.

CREATIVE FREEDOM:
The arc levels and spatial rules are a SCAFFOLD, not a cage. Within each arc:
- Surprise the viewer — use unexpected but accurate metaphors, playful compositions, and bold visual storytelling.
- Go beyond the suggested examples. A funnel and a sieve are starting points — invent your own metaphors that fit the paper's specific idea.
- Vary layouts across diagrams — not every diagram needs to be left-to-right boxes with arrows. Consider radial layouts, nested shapes, visual timelines, split-screen comparisons, or layered compositions when they better tell the story.
- Use color creatively — the palettes below are defaults, not mandates. If a warm sunset gradient or a cool ocean palette better captures the paper's theme, use it.
- Make each diagram feel like a unique piece of visual storytelling, not a template fill-in.
The only hard constraint: the diagram must be TECHNICALLY ACCURATE to the paper's content.

GLOBAL STYLE RULES (apply to ALL arcs):
- Pure white background always.
- No 3D effects, no drop shadows, no photorealistic textures.
- Flat vector style with crisp edges.
- Each arc should look VISUALLY DISTINCT from the others — different color temperature,
  different layout orientation, different visual personality.

Each marker contains an (Arc N) tag. Match your rendering style to the arc:

ARC 1 — "The Napkin" (explain it to a 5-year-old):
- Imagine explaining this paper's core idea to a child using toys, food, or everyday objects.
- 2-3 shapes MAX. Use real-world visual metaphors: a sieve filtering pebbles, a chef tasting
  soup, a detective with a magnifying glass, a factory assembly line, stacking blocks,
  a teacher grading papers, pouring water through a funnel.
- The metaphor must be TECHNICALLY ACCURATE — it should map onto what the model actually does,
  not just be decorative. If the paper compresses information, draw a funnel. If it selects
  the best option, draw someone picking the ripest fruit from a basket.
- Be inventive — these are EXAMPLES, not an exhaustive list. Create a metaphor that uniquely fits THIS paper.
- SPATIAL LAYOUT: Always left-to-right, centered vertically on a pure white canvas. Each
  element occupies roughly one-third of the horizontal space, with generous whitespace between.
- SHAPES: Large rounded rectangles (corner radius ~20px) or circles, with thick 3px borders.
- FILLS: Warm, saturated tones — sunny yellow (#F7DC6F), coral orange (#F0876A), sky blue
  (#5DADE2), grass green (#58D68D). ONE color per shape. Bold and cheerful.
- LABELS: Single everyday words in VERY LARGE bold sans-serif text (24pt+), centered inside
  each shape. Dark gray (#2C3E50) text.
- ARROWS: Thick (4-5px) dark gray arrows with large triangular arrowheads between shapes.
- NO math, NO tensors, NO architecture details, NO technical terms whatsoever.
- STYLE SUFFIX (always include at end): "Illustrated children's book style. Pure white
  background. Bold rounded shapes with warm, saturated fills. Thick playful arrows. Very
  large friendly sans-serif labels. Generous whitespace. Whimsical but accurate. Maximum
  simplicity. No gradients, no shadows, no textures, no 3D effects. Crisp vector edges."
- If the marker describes a prerequisite concept, use this same style.

ARC 2 — "The Mechanism" (curious teenager level):
- Now the reader has intuition from Arc 1. Introduce the actual component names, but keep
  labels in plain English (1-3 words each). No math yet.
- 4-5 boxes showing how parts connect. Show data flow direction.
- Don't just draw boxes-and-arrows — consider visual metaphors like gears interlocking, puzzle pieces snapping together, or a relay race passing a baton, if they better convey the mechanism.
- SPATIAL LAYOUT: Either top-to-bottom or left-to-right flow. Specify which. Elements evenly
  spaced with clear whitespace between them. Main flow along one axis.
- SHAPES: Rounded rectangles with 2px borders, medium size. Group related boxes with a
  light-colored background zone rectangle behind them.
- FILLS: Color-code by role — light blue (#AED6F1) for inputs, light green (#A9DFBF) for
  processing, light orange (#F5CBA7) for the key novel step, light teal (#A3E4D7) for outputs.
- LABELS: 1-3 word labels in bold sans-serif (16-18pt), centered inside each box. Dark gray text.
- ARROWS: Thin (2px) dark gray arrows with small arrowheads. Add short 1-2 word labels on
  arrows if they carry specific information (e.g., "features", "loss signal").
- STYLE SUFFIX (always include at end): "Modern infographic style. Pure white background.
  Rounded boxes with bold, vibrant fills and thin borders. Crisp connecting arrows with labels.
  Clean sans-serif typography. Visual storytelling — each box should feel like a step in a story.
  No gradients, no shadows, no textures. Crisp clean edges."

ARC 3 — "The Blueprint" (college student level):
- The reader earned full context from Arc 1-2. Now show the complete picture.
- 5-7 boxes with technical terms, dimensionality annotations if helpful.
- This is your chance to be architecturally expressive — use creative groupings, visual hierarchy, or layered depth to make the pipeline feel alive rather than a flat flowchart.
- SPATIAL LAYOUT: Multi-row or multi-column layout. Use colored background zone rectangles
  to group phases (e.g., blue zone = encoder, green zone = decoder). Specify zone boundaries.
- SHAPES: Rectangular boxes with slight rounding, 1-2px borders. Smaller boxes for sub-components.
- FILLS: Muted academic colors — steel blue (#5DADE2), sage green (#58D68D), warm amber (#F4D03F),
  coral (#EC7063). Use lighter versions for background zones.
- LABELS: Technical terms OK, 1-4 words, medium sans-serif (14-16pt). Step numbers (①②③) or
  phase labels above zone rectangles.
- ARROWS: Solid 2px arrows for main data flow, dashed 1px arrows for auxiliary paths (skip
  connections, gradients, feedback loops). Arrow labels for tensor shapes if relevant.
- STYLE SUFFIX (always include at end): "Technical blueprint style. Pure white background.
  Color-coded zones with muted fills grouping pipeline phases. Solid arrows for main data flow,
  dashed arrows for auxiliary paths. Numbered steps. Sans-serif font throughout. No gradients,
  no shadows, no textures. Conference-paper-quality figure. Clean professional edges."

ARC 4 — "The Evidence" (scientist checking results):
- This MUST be a data visualization, NOT a methodology diagram. Show NUMBERS, not concepts.
- Bar chart, grouped bar chart, or comparison visual with EXACT numbers from the paper.
- SPATIAL LAYOUT: Chart centered on canvas. Y-axis on the left, X-axis at the bottom.
  Bars evenly spaced. Title centered above the chart area.
- BARS: Specify exact order left-to-right. Paper's method bar in vibrant blue (#2E86C1),
  baselines in medium gray (#95A5A6) and light gray (#BDC3C7). Bar width should be consistent.
- VALUE LABELS: Exact numbers displayed ABOVE each bar in bold sans-serif (14pt). Dark text.
- AXES: Y-axis with clear tick marks and label (e.g., "Accuracy (%)"). X-axis with bar names.
  Choose Y-axis range to emphasize differences (don't always start at 0 for percentages).
- Keep to 3-5 bars max. Group related comparisons.
- STYLE SUFFIX (always include at end): "Clean flat vector chart. Pure white background. Bold
  value labels above bars. Paper's method highlighted in blue, baselines in gray. Clear axis
  labels. Sans-serif font throughout. No gradients, no 3D effects. Crisp clean edges.
  Professional data visualization style."

BAD example (too vague, no spatial info): "A diagram showing Multi-Head Self-Attention with
Q[B,H,S,D], K[B,H,S,D], V[B,H,S,D] tensors, MatMul, Scale, Softmax, concat, LayerNorm."

GOOD Arc 1 example (spatially explicit, 300+ words): "A horizontal scene on a pure white
canvas, divided into three equal zones left-to-right. In the LEFT ZONE: a large rounded
rectangle (corner radius 20px, fill: soft sky blue #AED6F1, border: 3px #2C3E50) containing
a simple illustration of a jigsaw puzzle with 2-3 missing pieces. Below the shape, centered,
the label 'Puzzle' in very large bold sans-serif text (24pt, dark gray #2C3E50). A thick
dark gray arrow (5px, #2C3E50, large triangular arrowhead) extends from the right edge of
this shape toward the CENTER ZONE. In the CENTER ZONE: a large rounded rectangle (same style,
fill: soft peach #F5CBA7) containing a simple illustration of a child's hand trying to fit
a puzzle piece. Below it, the label 'Try & Guess' in very large bold sans-serif (24pt, dark
gray). Another thick arrow extends rightward to the RIGHT ZONE. In the RIGHT ZONE: a large
rounded rectangle (same style, fill: soft mint green #A9DFBF) containing a completed jigsaw
puzzle illustration. Below it, the label 'Solved!' in very large bold sans-serif (24pt, dark
gray). All three shapes are the same size, vertically centered on the canvas, with equal
spacing between them. Flat vector illustration style. Pure white background. Thick rounded
shapes with soft pastel fills. Thick bold arrows. Very large bold sans-serif labels. Maximum
whitespace. Clean, minimal, explain-to-a-child level. No gradients, no shadows, no textures,
no 3D effects. Crisp vector edges."

GOOD Arc 4 example (spatially explicit, chart with numbers): "A vertical bar chart centered on
a pure white canvas. Title 'Performance Comparison' in bold sans-serif (18pt, dark gray) centered
at the top. Y-axis on the left labeled 'Accuracy (%)' in sans-serif (14pt), ranging from 75%
to 95% with gridlines at 5% intervals. Three bars arranged left-to-right with equal spacing:
Bar 1 (leftmost): labeled 'This Paper' on the X-axis, filled vibrant blue (#2E86C1), height
reaching 92.3%, with bold value label '92.3%' (14pt, dark gray) positioned above the bar.
Bar 2 (center): labeled 'Previous Best' on the X-axis, filled medium gray (#95A5A6), height
87.1%, value label '87.1%' above. Bar 3 (rightmost): labeled 'Baseline', filled light gray
(#BDC3C7), height 81.5%, value label '81.5%' above. Clean flat vector chart. Pure white
background. Bold value labels above bars. Paper's method highlighted in blue, baselines in gray.
Clear axis labels. Sans-serif font throughout. No gradients, no 3D effects. Crisp clean edges.
Professional data visualization style."

IMPORTANT:
- Each "text" MUST be 300-500 words. Shorter descriptions produce vague, low-quality images.
- Return ONLY the raw JSON array. No markdown fences, no preamble.

Paper text:
{paper_markdown}

Summary with diagram markers:
{summary}"""


def _count_diagram_markers(text: str) -> int:
    """Count [DIAGRAM: ...] markers in the summary."""
    return len(re.findall(r"\[DIAGRAM:\s*.+?\]", text))


def _extract_json_array(raw: str) -> list[dict] | None:
    """Robustly extract a JSON array from LLM output.

    Handles markdown fences, preamble text, trailing garbage,
    and truncated output (salvages complete objects from incomplete arrays).
    Returns None if no valid JSON array can be found.
    """
    # Strategy 1: strip markdown fences (handle nested backticks properly)
    text = raw.strip()
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Strategy 2: find the first [ and last ] to extract the array
    first_bracket = text.find('[')
    last_bracket = text.rfind(']')
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = text[first_bracket:last_bracket + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Strategy 3: try the whole text as-is
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strategy 4: salvage truncated output — find all complete JSON objects
    # This handles the case where the LLM output was cut off mid-array
    if first_bracket != -1:
        array_content = text[first_bracket + 1:]
        objects = []
        depth = 0
        obj_start = None
        for i, ch in enumerate(array_content):
            if ch == '{':
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and obj_start is not None:
                    obj_str = array_content[obj_start:i + 1]
                    try:
                        obj = json.loads(obj_str)
                        if isinstance(obj, dict):
                            objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    obj_start = None
        if objects:
            print(f"[summarizer] salvaged {len(objects)} complete objects from truncated JSON")
            return objects

    return None


def generate_banana_texts(paper_markdown: str, summary: str = "") -> list[dict]:
    """Returns list of dicts: [{filename, caption, text}, ...]"""
    # Use actual marker count from summary, falling back to NUM_DIAGRAMS
    num_diagrams = _count_diagram_markers(summary) if summary else NUM_DIAGRAMS
    if num_diagrams == 0:
        num_diagrams = NUM_DIAGRAMS

    truncated = paper_markdown[:60_000]
    summary_truncated = summary[:30_000]
    prompt = BANANA_PROMPT.format(
        paper_markdown=truncated,
        summary=summary_truncated,
        num_diagrams=num_diagrams,
    )

    # Try up to 2 attempts — retry if JSON parsing fails
    for attempt in range(2):
        try:
            result = llm_call(
                prompt=prompt,
                max_tokens=16384,
                temperature=0.2,
            )
        except Exception as exc:
            print(f"[summarizer] banana LLM call failed (attempt {attempt+1}): {exc}")
            continue

        raw = result.text.strip()
        parsed = _extract_json_array(raw)

        if parsed and len(parsed) > 0:
            # Validate each block has required keys
            valid = []
            for block in parsed:
                if isinstance(block, dict) and "text" in block:
                    block.setdefault("filename", f"diagram_{len(valid)+1}")
                    block.setdefault("caption", "Diagram")
                    valid.append(block)
            if valid:
                if len(valid) < num_diagrams:
                    print(f"[summarizer] banana returned {len(valid)} of {num_diagrams} blocks")
                return valid

        # Log the failure with a snippet of what came back
        snippet = raw[:300].replace('\n', ' ')
        print(f"[summarizer] banana JSON parse failed (attempt {attempt+1}): {snippet}...")
        # On retry, append a nudge to the prompt
        if attempt == 0:
            prompt += "\n\nIMPORTANT: Your previous response was not valid JSON. Return ONLY a raw JSON array — no markdown fences, no explanation."

    print(f"[summarizer] banana fallback: returning {num_diagrams} generic diagrams")
    fallback_names = [
        ("core_idea", "Core idea of the proposed method"),
        ("method_mechanism", "How the method works"),
        ("architecture_overview", "Architecture overview"),
        ("results_comparison", "Key results comparison"),
    ]
    fallbacks = []
    for i in range(num_diagrams):
        fname, cap = fallback_names[i] if i < len(fallback_names) else (f"diagram_{i+1}", f"Diagram {i+1}")
        fallbacks.append({
            "filename": fname,
            "caption": cap,
            "text": paper_markdown[:500],
        })
    return fallbacks