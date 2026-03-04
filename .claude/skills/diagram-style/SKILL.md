# Diagram Style — Progressive Teaching Arc

Reference guide for the diagram generation pipeline. Use when modifying `SUMMARY_PROMPT`, `BANANA_PROMPT`, `_inject_diagram_markers` in `backend/summarizer.py`, or `diagram_gen.py`.

## Philosophy

Diagrams follow a **progressive teaching arc** — like a teacher building understanding step by step. A reader flipping through *just* the diagrams should get the whole story.

1. First the **napkin sketch** (instant intuition)
2. Then **how the pieces connect** (mechanism)
3. Then the **full blueprint** (architecture)
4. Then the **proof** (evidence with numbers)

Each diagram builds on the last. Earlier diagrams use simpler vocabulary; later ones can use technical terms because the reader earned that context.

## Arc Levels

### Arc 1 — "The Napkin" (REQUIRED)
- **Placement:** Big Picture or Core Idea section
- **Purpose:** Get the idea in 3 seconds
- **Complexity:** 2-3 shapes MAX, one visual metaphor
- **Style:** Thick rounded shapes, thick arrows, large bold labels, soft pastel fills, maximum whitespace
- **Labels:** Single everyday words — "Squeeze", "Expand", "Score"
- **Forbidden:** Math, tensors, dimensions, architecture details
- **PaperBanana `diagram_type`:** `"methodology"`

### Arc 2 — "The Mechanism" (REQUIRED if >= 3 diagrams)
- **Placement:** Core Idea section
- **Purpose:** Show how components connect — one level deeper than Arc 1
- **Complexity:** 4-5 boxes with labeled relationships
- **Style:** Clean textbook style, rounded boxes, thin arrows, sans-serif labels, soft pastel fills
- **Prerequisite variant:** If the paper assumes complex background knowledge, this slot becomes a prerequisite explainer using Arc 1 styling (2-3 shapes, everyday words)
- **PaperBanana `diagram_type`:** `"methodology"`

### Arc 3 — "The Blueprint" (OPTIONAL, >= 4 diagrams)
- **Placement:** How It Works section
- **Purpose:** Full pipeline/architecture — technical terms OK
- **Complexity:** 5-7 boxes, color zones for grouping phases
- **Style:** Detailed academic pipeline, solid + dashed arrows, step labels
- **PaperBanana `diagram_type`:** `"methodology"`

### Arc 4 — "The Evidence" (OPTIONAL, >= 2 diagrams)
- **Placement:** Results & Insights section
- **Purpose:** Chart with exact numbers from the paper
- **Style:** Clean chart, bold value labels, paper's method in blue/teal, baselines in gray
- **PaperBanana `diagram_type`:** `"statistical_plot"`

## Slot Allocation

| Diagram Count | Slots |
|---------------|-------|
| 2 | Arc 1 + Arc 4 |
| 3 | Arc 1 + Arc 2 + Arc 4 |
| 4 | Arc 1 + Arc 2 + Arc 3 + Arc 4 |
| 5-6 | Full arc + extra mechanism/prerequisite/ablation chart |

## Marker Format

Markers in the summary include the arc tag for downstream rendering:

```
[DIAGRAM: (Arc 1) a funnel squeezing raw text into a compact summary]
[DIAGRAM: (Arc 2) encoder takes input, bottleneck compresses, decoder reconstructs]
[DIAGRAM: (Arc 3) full training pipeline from data loading through loss computation]
[DIAGRAM: (Arc 4) bar chart showing Model X at 92.3% vs Baseline at 87.1%]
```

## Profiler Signals

`paper_profiler.py` provides two fields that influence diagram count:

- `num_components` (1-5): How many distinct modules the method has. +1 diagram if >= 3.
- `needs_prerequisite` (bool): Whether the paper assumes complex background knowledge. +1 diagram slot, used as Arc 2 prerequisite explainer.

Diagram count range: **2-6** (clamped in `_validate_profile`).

## Files

| File | Role |
|------|------|
| `backend/summarizer.py` | `SUMMARY_PROMPT` (arc instructions), `BANANA_PROMPT` (rendering rules), `_inject_diagram_markers` (fallback arc tags) |
| `backend/paper_profiler.py` | `num_components`, `needs_prerequisite`, diagram count guidance |
| `backend/diagram_gen.py` | Maps `diagram_type` string to PaperBanana `DiagramType` enum |
