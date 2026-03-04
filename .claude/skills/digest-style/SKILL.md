---
name: digest-style
description: Reference style guide for the paper digest output. Use when modifying the summarizer prompt, orchestrator HTML template, or digest visual design. Based on Cameron R. Wolfe and Sebastian Raschka's Substack article style.
user-invocable: true
argument-hint: "[topic or section to review]"
---

# Digest Style Guide

The digest should read like a **technical Substack article** with a storytelling approach — not a structured form.
The two reference articles are:
- Cameron R. Wolfe's "Rubric RL" (cameronrwolfe.substack.com)
- Sebastian Raschka's "Beyond Standard LLMs" (magazine.sebastianraschka.com)

## Tone & Voice

- **Warm, clear, and engaging** — like explaining to a smart friend over coffee.
- Use direct address: "here's the clever part...", "you might wonder why..."
- Share brief opinions: "this is clever because...", "the limitation here is real..."
- No academic fluff. No "In this paper, the authors propose..." — just say what it does.
- Use em-dashes for elaboration, not parentheses.
- Build understanding progressively — each paragraph builds on what came before.
- Start with WHY before WHAT. Make the reader feel the problem before showing the solution.

## Structure & Flow

The article has **6 sections** that flow as a narrative arc. Fewer sections = less intimidating.

### Ideal Progression
1. **The Big Picture** — Hook + problem + motivation. 2-3 punchy opening sentences, then set the scene. What existed before? What was broken? Include a blockquote. Tease the solution.
2. **The Core Idea** — The deepest section. Start with analogies/intuition as an on-ramp, then progressively reveal the method. Fold in key design choices and their reasoning.
3. **How It Works** — Concrete step-by-step pipeline walkthrough. Numbered steps, plain English component names.
4. **Results & Insights** — Lead with the most impressive number. Cover 2-3 experiments. Include ablation findings inline. Invite chart/graph diagrams for statistics.
5. **Limitations & Future** — Honest take + forward-looking, combined. 3-5 sentences.
6. **Key Takeaways** — 3-5 bullet points. Bold the key phrase in each.

### Transitions
Every section should end with a sentence that leads into the next.

## Math Handling

- **Minimal equations.** Prefer plain English over formulas. Most ideas can be explained without math.
- At most 1-2 key equations per digest — only the paper's single most important formula.
- Use inline `$...$` for simple expressions. Avoid display math `$$...$$` unless truly necessary.
- NEVER put an "interpretation block" directly below an equation. Weave explanation into prose.
- NEVER wrap `$...$` in backticks.

## Formatting Conventions

- **Bold** key terms on first introduction
- *Italics* for paper titles and emphasis
- `code font` for model names, hyperparameters, function names (NEVER for math)
- Blockquotes (`>`) for direct quotes from the paper — always attribute
- Numbered lists for sequential processes
- Bullet lists for parallel items

## Diagrams & Figures

- Target **2-3 diagrams** per digest (quality over quantity)
- Two types:
  - **Concept diagrams** — textbook-style, analogy-based, max 4-6 boxes, plain English labels
  - **Statistics charts** — bar graphs or comparison charts showing key results with exact numbers
- At least ONE diagram should be a comparison chart when the paper has quantitative results
- Each diagram appears **immediately after** the paragraph that explains it

## Code Blocks

- Short (10-15 lines), simplified, algorithmic core only
- At most 1-2 per digest
- Appear after conceptual explanation, not before
- Use `python` language tag

## Length Calibration

- Target ~2000-2500 words (max 15-minute read)
- The Big Picture: ~300-400 words
- The Core Idea: ~600-800 words (deepest section)
- How It Works: ~400-500 words
- Results & Insights: ~350-450 words
- Limitations & Future: ~100-150 words
- Key Takeaways: ~80-120 words

## Anti-Patterns (avoid these)

- Too many sections (max 6 — keep it approachable)
- Complex equation blocks with interpretation underneath
- Dumping all figures at the end
- Starting every section from scratch with no connection
- Generic statements like "this is an important contribution"
- Listing every benchmark number without context
- Wrapping math in backticks
