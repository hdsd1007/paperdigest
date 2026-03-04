"""
notebook_viewer.py
------------------
Renders a .ipynb file as a standalone viewable HTML page.
Lightweight — no nbconvert dependency. Uses highlight.js for code
and markdown2 for markdown cells.
"""

import json
import base64
import html as html_mod
import markdown2


def render_notebook_html(ipynb_path: str, title: str = "Notebook") -> str:
    """Read an .ipynb file and return a self-contained HTML page."""
    with open(ipynb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    cells_html = []
    exec_count = 0

    for cell in nb.get("cells", []):
        ctype = cell.get("cell_type", "code")
        source = "".join(cell.get("source", []))

        if ctype == "markdown":
            rendered = markdown2.markdown(source, extras=[
                "fenced-code-blocks", "tables", "cuddled-lists",
            ])
            cells_html.append(f'<div class="cell cell-md">{rendered}</div>')

        elif ctype == "code":
            exec_count += 1
            escaped = html_mod.escape(source)
            cell_html = (
                f'<div class="cell cell-code">'
                f'<div class="cell-prompt">In [{exec_count}]:</div>'
                f'<pre><code class="language-python">{escaped}</code></pre>'
            )

            # Render outputs
            for out in cell.get("outputs", []):
                otype = out.get("output_type", "")
                if otype == "stream":
                    text = "".join(out.get("text", []))
                    cell_html += f'<pre class="cell-output">{html_mod.escape(text)}</pre>'
                elif otype in ("execute_result", "display_data"):
                    data = out.get("data", {})
                    if "image/png" in data:
                        b64 = data["image/png"]
                        if isinstance(b64, list):
                            b64 = "".join(b64)
                        cell_html += (
                            f'<div class="cell-img">'
                            f'<img src="data:image/png;base64,{b64.strip()}" />'
                            f'</div>'
                        )
                    elif "text/html" in data:
                        h = "".join(data["text/html"]) if isinstance(data["text/html"], list) else data["text/html"]
                        cell_html += f'<div class="cell-output-html">{h}</div>'
                    elif "text/plain" in data:
                        text = "".join(data["text/plain"]) if isinstance(data["text/plain"], list) else data["text/plain"]
                        cell_html += f'<pre class="cell-output">{html_mod.escape(text)}</pre>'
                elif otype == "error":
                    tb = "\n".join(out.get("traceback", []))
                    # Strip ANSI color codes
                    import re
                    tb = re.sub(r'\x1b\[[0-9;]*m', '', tb)
                    cell_html += f'<pre class="cell-error">{html_mod.escape(tb)}</pre>'

            cell_html += '</div>'
            cells_html.append(cell_html)

    body = "\n".join(cells_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{html_mod.escape(title)} — Notebook</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
  <style>
    :root {{
      --bg: #ffffff;
      --surface: #f7f7f7;
      --border: #e5e5e5;
      --text: #1a1a1a;
      --muted: #6b7280;
      --accent: #2563eb;
      --sans: 'DM Sans', system-ui, sans-serif;
      --mono: 'DM Mono', 'Fira Code', monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 15px;
      line-height: 1.6;
      max-width: 960px;
      margin: 0 auto;
      padding: 40px 24px 80px;
    }}
    .nb-header {{
      margin-bottom: 32px;
      padding-bottom: 20px;
      border-bottom: 2px solid var(--border);
    }}
    .nb-header h1 {{
      font-size: 24px;
      font-weight: 600;
      margin-bottom: 4px;
    }}
    .nb-header .nb-meta {{
      font-size: 13px;
      color: var(--muted);
      font-family: var(--mono);
    }}
    .cell {{
      margin-bottom: 16px;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    .cell-md {{
      padding: 16px 20px;
      background: var(--bg);
    }}
    .cell-md h1 {{ font-size: 22px; font-weight: 600; margin: 16px 0 8px; }}
    .cell-md h2 {{ font-size: 19px; font-weight: 600; margin: 14px 0 6px; }}
    .cell-md h3 {{ font-size: 16px; font-weight: 600; margin: 12px 0 4px; }}
    .cell-md p {{ margin-bottom: 10px; }}
    .cell-md ul, .cell-md ol {{ padding-left: 24px; margin-bottom: 10px; }}
    .cell-md code {{
      background: #f0f0f0;
      padding: 1px 5px;
      border-radius: 3px;
      font-family: var(--mono);
      font-size: 13px;
    }}
    .cell-md pre code {{
      display: block;
      padding: 12px;
      background: var(--surface);
      border-radius: 6px;
      overflow-x: auto;
    }}
    .cell-code {{
      background: var(--surface);
    }}
    .cell-prompt {{
      padding: 8px 16px 0;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--accent);
      font-weight: 500;
    }}
    .cell-code pre {{
      margin: 0;
      padding: 8px 16px 12px;
      background: transparent;
      overflow-x: auto;
    }}
    .cell-code pre code {{
      font-family: var(--mono);
      font-size: 13px;
      line-height: 1.5;
      background: transparent;
    }}
    .cell-output {{
      margin: 0;
      padding: 10px 16px;
      background: #fff;
      border-top: 1px solid var(--border);
      font-family: var(--mono);
      font-size: 13px;
      color: #374151;
      overflow-x: auto;
      white-space: pre-wrap;
    }}
    .cell-output-html {{
      padding: 10px 16px;
      background: #fff;
      border-top: 1px solid var(--border);
      overflow-x: auto;
    }}
    .cell-error {{
      margin: 0;
      padding: 10px 16px;
      background: #fef2f2;
      border-top: 1px solid #fecaca;
      font-family: var(--mono);
      font-size: 12px;
      color: #991b1b;
      overflow-x: auto;
      white-space: pre-wrap;
    }}
    .cell-img {{
      padding: 10px 16px;
      background: #fff;
      border-top: 1px solid var(--border);
      text-align: center;
    }}
    .cell-img img {{
      max-width: 100%;
      height: auto;
    }}
    @media (max-width: 600px) {{
      body {{ padding: 20px 12px 60px; }}
      .cell-code pre {{ padding: 8px 12px; }}
    }}
  </style>
</head>
<body>
  <div class="nb-header">
    <h1>{html_mod.escape(title)}</h1>
    <div class="nb-meta">{exec_count} code cells</div>
  </div>
  {body}
  <script>
    hljs.highlightAll();
    document.addEventListener("DOMContentLoaded", function() {{
      if (typeof renderMathInElement !== "undefined") {{
        renderMathInElement(document.body, {{
          delimiters: [
            {{left: "$$", right: "$$", display: true}},
            {{left: "$", right: "$", display: false}},
          ],
          throwOnError: false,
        }});
      }}
    }});
  </script>
</body>
</html>"""
