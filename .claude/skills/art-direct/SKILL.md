---
user-invocable: true
allowed-tools:
  - Read
  - Write
---

# Art Direct

Rewrite a figure spec `.txt` file from the old loose style (bullet lists, `[square brackets]`, vague phrasing) into the exhaustive art-direction format — every shape, color, position, and visual relationship specified with exact hex codes, px dimensions, and opacity values.

## Instructions

1. Read the input file at `$ARGUMENTS[0]`.
2. Read `fig2_offline_indexing.txt` from the repository root as the canonical style reference.
3. Rewrite the input file's content into the same structural format as the style reference. The output must include **all** of the following sections in order:

   **Opening line** — a single sentence beginning with a phrase like "Create an academic illustration of …" that includes "overwhelmingly visual" and ends with "follow this art direction exactly."

   **`CANVAS & GLOBAL SETTINGS`** — canvas dimensions in pixels, background hex color, font family, flow direction, and a named color palette table with exact hex codes for every color used in the diagram.

   **`LAYOUT`** — a zone/column overview listing every zone by name with approximate x-positions in px. Mention connector arrows between adjacent zones.

   **Zone-by-zone sections** — one `================` divider per zone. Each zone must specify:
   - Position and total footprint (width × height in px)
   - Shape type, corner radius, fill (hex + opacity where relevant), border (thickness + hex), drop shadow (offset + blur + rgba)
   - Interior sub-elements described as visual metaphors (icon vignettes, faux-text lines, gradient squares, etc.)
   - Text labels with pt size, weight, and hex color
   - Any badges or pills with exact dimensions, corner radius, fill, and text styling

   **Connector arrows** — between each pair of adjacent zones, in their own `================` section. Specify shaft width, arrowhead dimensions, color, and alignment.

   **`WHAT MUST NOT APPEAR`** — a bulleted list of things explicitly banned from the diagram.

4. Enforce these constraints in the rewritten output — none of the following may appear:
   - Square brackets around labels: `[` or `]`
   - Vague delegation phrases: "be creative", "your choice", "feel free", "use your judgment", "as you see fit"
   - Page markers: `<page-N>`, `<page-1>`, etc.
   - Every visual element must be fully specified — no ambiguity left for the renderer

5. Preserve the **subject matter** from the original spec. Do not invent new content — translate the same concepts into the exhaustive visual format.

6. Write the result back to the same file path (`$ARGUMENTS[0]`), overwriting the original.

7. After writing, print a short summary for the user:
   - Number of zones created
   - Number of connector arrows
   - Hex colors in the palette
   - Confirm the `WHAT MUST NOT APPEAR` section is present
   - Confirm no `[`, `]`, "be creative", "your choice", or "feel free" in output

## Example

```
/art-direct fig3_online_pipeline.txt
```
