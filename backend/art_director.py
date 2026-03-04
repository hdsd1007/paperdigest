"""
art_director.py
----------------
Rewrites PaperBanana diagram descriptions into pixel-perfect art-direction
specs with hex codes, px dimensions, opacity values, and zone-by-zone layout.

Dramatically improves diagram quality by giving the image generator precise
visual instructions instead of vague prose descriptions.
"""

import os
from llm_client import llm_call

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

ART_DIRECT_PROMPT = """You are an art director for academic illustrations. Your job is to rewrite
a diagram description into a PIXEL-PERFECT art-direction spec that an AI image generator
can follow exactly.

ORIGINAL DESCRIPTION:
{description}

DIAGRAM CONTEXT:
- Caption: {caption}
- Arc level: {arc_level} (1=napkin sketch, 2=mechanism, 3=blueprint)
- This is a methodology/concept diagram (NOT a statistical chart).

YOUR TASK:
Rewrite the description into art-direction format. The output must be OVERWHELMINGLY VISUAL —
every element specified with exact positions, colors, sizes, and styles.

Follow this EXACT structure:

---

Create an academic illustration of {caption}. This must be overwhelmingly visual.
Follow this art direction exactly.

CANVAS & GLOBAL SETTINGS:
- Canvas: 1200 x 800 px (or adjust to content)
- Background: #FFFFFF (pure white, no texture)
- Primary font: Inter or DM Sans (clean sans-serif)
- Color palette:
  | Role        | Hex       | Usage                    |
  |-------------|-----------|--------------------------|
  | Primary     | #2563EB   | Key elements, highlights |
  | Secondary   | #7C3AED   | Supporting elements      |
  | Accent      | #059669   | Success/output states    |
  | Neutral     | #6B7280   | Borders, arrows          |
  | Light fill  | #EFF6FF   | Background zones         |
  (Adapt colors to match the diagram's content — these are defaults)

LAYOUT:
- Zone overview: describe the overall spatial arrangement
- Specify positions using px coordinates or zone names (left third, center, etc.)
- Note any connector arrows between zones

================
ZONE 1: [Name]
================
- Position: top-left | x: 50px, y: 50px
- Dimensions: 300 x 200 px
- Shape: rounded rectangle | corner-radius: 12px
- Fill: #EFF6FF (opacity 100%)
- Border: 1.5px solid #2563EB
- Drop shadow: none (flat vector style)
- Sub-elements:
  - Icon/illustration: describe what appears inside
  - Layout within zone: centered, left-aligned, etc.
- Label: "Label Text" | 16pt | weight: 600 | color: #1F2937 | position: centered inside

(Repeat for each zone)

================
CONNECTORS
================
- Arrow 1: Zone 1 right-edge → Zone 2 left-edge
  - Shaft: 2px solid #6B7280
  - Arrowhead: 8x6px filled triangle #6B7280
  - Label (if any): "data flow" | 11pt | #6B7280 | above arrow

WHAT MUST NOT APPEAR:
- No 3D effects, no drop shadows, no photorealistic textures
- No gradients (flat fills only)
- No background patterns or decorative elements
- No text smaller than 10pt
- No more than 7 colors total

---

RULES:
1. Every shape needs: position (px or zone), dimensions, fill hex + opacity, border style, corner radius.
2. Every label needs: exact text, font size in pt, font weight, color hex, position relative to parent.
3. Every arrow needs: start point, end point, shaft width, color, arrowhead dimensions.
4. Use the ================ dividers between zones for readability.
5. Adapt the color palette to the content — don't use the defaults blindly.
6. For Arc 1 (napkin): use 2-3 large shapes, warm saturated fills, very large labels (24pt+), thick arrows (4px+).
7. For Arc 2 (mechanism): use 4-5 medium shapes, color-coded by role, labeled arrows.
8. For Arc 3 (blueprint): use 5-7 shapes with colored background zones, numbered steps, solid + dashed arrows.
9. Output ONLY the art-direction spec. No preamble, no explanation, no markdown fences."""


ART_DIRECT_PROMPT_CHART = """You are an art director for data visualizations. Your job is to rewrite
a chart description into a PIXEL-PERFECT art-direction spec that an AI image generator
can follow exactly.

ORIGINAL DESCRIPTION:
{description}

DIAGRAM CONTEXT:
- Caption: {caption}
- Arc level: 4 (statistical evidence chart)
- This is a DATA VISUALIZATION — bar chart, grouped bars, or comparison visual.

YOUR TASK:
Rewrite the description into art-direction format. The output must specify EXACT bar positions,
values, colors, and axis details so the chart is rendered precisely.

Follow this EXACT structure:

---

Create a clean statistical chart showing {caption}. This must be overwhelmingly visual.
Follow this art direction exactly.

CANVAS & GLOBAL SETTINGS:
- Canvas: 1000 x 600 px
- Background: #FFFFFF (pure white)
- Font: Inter or DM Sans (clean sans-serif)
- Chart area: 700 x 400 px, centered horizontally, 100px from top

CHART CONFIGURATION:
- Chart type: bar chart | grouped bar chart | horizontal bar chart
- Title: "Chart Title" | 18pt | weight: 700 | color: #1F2937 | centered above chart

Y-AXIS:
- Label: "Metric Name (%)" | 13pt | weight: 500 | color: #6B7280
- Range: [min] to [max] (choose range to emphasize differences)
- Grid lines: 1px dashed #E5E7EB at each major tick
- Tick labels: 12pt | color: #6B7280

X-AXIS:
- Labels below bars | 12pt | weight: 500 | color: #374151

BARS (left to right):
- Bar 1: "Label" | value: XX.X% | fill: #2563EB | width: 60px | position: x=200px
  - Value label: "XX.X%" | 14pt | weight: 700 | color: #1F2937 | 8px above bar top
- Bar 2: "Label" | value: XX.X% | fill: #9CA3AF | width: 60px | position: x=300px
  - Value label: "XX.X%" | 14pt | weight: 600 | color: #6B7280 | 8px above bar top
(Repeat for each bar — paper's method in blue, baselines in gray)

VISUAL EMPHASIS:
- Paper's method bar: #2563EB (vibrant blue), slightly wider or with a subtle highlight
- Baseline bars: #9CA3AF (medium gray) and #D1D5DB (light gray)
- Gap between bars: 20px

WHAT MUST NOT APPEAR:
- No 3D effects, no drop shadows, no gradients
- No decorative elements or background patterns
- No legend if bar labels are clear
- No text smaller than 10pt

---

RULES:
1. EXTRACT EXACT NUMBERS from the original description. Never invent values.
2. Every bar needs: label, value, fill hex, width in px, x-position.
3. Every value label needs: exact text, font size, weight, color, position relative to bar.
4. Y-axis range should emphasize differences (don't start at 0 for percentage metrics above 70%).
5. Use blue (#2563EB) for the paper's method, grays for baselines.
6. For grouped bar charts, specify group spacing and within-group spacing.
7. Output ONLY the art-direction spec. No preamble, no explanation, no markdown fences."""


# Phrases that indicate the LLM returned meta-commentary instead of a spec
_BANNED_PHRASES = [
    "I cannot",
    "I can't",
    "I'm sorry",
    "As an AI",
    "I don't have",
    "Here is a description",
    "Here's a description",
]

# Minimum length for a valid art-direction spec (chars)
_MIN_SPEC_LENGTH = 400


def art_direct_specs(
    banana_blocks: list[dict],
    iterations: int = 1,
) -> list[dict]:
    """Rewrite PaperBanana diagram descriptions into art-direction specs.

    Args:
        banana_blocks: List of dicts from generate_banana_texts(), each with
                       'text', 'filename', 'caption', 'arc_level', 'diagram_type'.
        iterations: Number of art-direction passes per diagram (default 1).

    Returns:
        The same list with 'text' fields rewritten as art-direction specs.
        On failure for any block, the original text is preserved.
    """
    if iterations <= 0:
        return banana_blocks

    result = []
    for i, block in enumerate(banana_blocks):
        original_text = block["text"]
        caption = block.get("caption", f"Diagram {i+1}")
        arc_level = block.get("arc_level", 0)
        diagram_type = block.get("diagram_type", "methodology")

        # Choose prompt variant based on diagram type / arc level
        is_chart = (diagram_type == "statistical_plot" or arc_level == 4)
        if is_chart:
            # Skip art direction for charts — PaperBanana generates matplotlib
            # code for statistical plots, not Imagen images.  The original
            # banana description (with data values and chart structure) works
            # better for code generation than pixel-position specs.
            print(f"[art_director] Block {i} ({caption}): skipped (statistical plot)")
            result.append(dict(block))
            continue
        prompt_template = ART_DIRECT_PROMPT

        current_text = original_text
        for iteration in range(iterations):
            try:
                prompt = prompt_template.format(
                    description=current_text,
                    caption=caption,
                    arc_level=arc_level,
                )
                resp = llm_call(prompt=prompt, max_tokens=4096, temperature=0.3)
                spec = resp.text.strip()

                # Validation: reject too-short or meta-commentary responses
                if len(spec) < _MIN_SPEC_LENGTH:
                    print(f"[art_director] Block {i} iteration {iteration+1}: spec too short ({len(spec)} chars), keeping previous")
                    continue

                if any(phrase.lower() in spec.lower() for phrase in _BANNED_PHRASES):
                    print(f"[art_director] Block {i} iteration {iteration+1}: banned phrase detected, keeping previous")
                    continue

                current_text = spec
                print(f"[art_director] Block {i} ({caption}): art-directed (iteration {iteration+1}, {len(spec)} chars)")

            except Exception as exc:
                print(f"[art_director] Block {i} iteration {iteration+1} failed: {exc}")
                # Keep whatever we have (original or previous iteration)

        new_block = dict(block)
        new_block["text"] = current_text
        result.append(new_block)

    return result
