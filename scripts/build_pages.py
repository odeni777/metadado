"""Build the static site served from the docs directory on GitHub Pages."""

import json
from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parents[1]

from jinja2 import Environment, FileSystemLoader, select_autoescape

package = ROOT / "docxmeta"
output = ROOT / "docs"
assets = output / "static"
assets.mkdir(parents=True, exist_ok=True)

templates = Environment(
    loader=FileSystemLoader(package / "templates"),
    autoescape=select_autoescape(["html"]),
)
page = templates.get_template("index.html").render(
    browser_mode=True,
    url_for=lambda endpoint, filename: f"./static/{filename}",
)
(output / "index.html").write_text(page, encoding="utf-8")
(output / ".nojekyll").touch()
for asset in ("styles.css", "editor.js", "favicon.svg", "worker.js", "browser.js"):
    copyfile(package / "static" / asset, assets / asset)
copyfile(package / "openxml.py", assets / "openxml.py")

source = (package / "openxml.py").read_text(encoding="utf-8")
worker = (assets / "worker.js").read_text(encoding="utf-8")
worker = f"const embeddedOpenXml = {json.dumps(source)};\n{worker}"
portable = page
for asset in ("browser.js", "editor.js"):
    script = (assets / asset).read_text(encoding="utf-8")
    portable = portable.replace(
        f'<script src="./static/{asset}" defer></script>',
        f"<script>{script}</script>",
    )
scripts_start = portable.index("<script>")
scripts_end = portable.rindex("</script>") + len("</script>")
scripts = portable[scripts_start:scripts_end]
portable = portable[:scripts_start].rstrip() + portable[scripts_end:]
inline_worker = json.dumps(worker).replace("<", "\\u003c")
portable = portable.replace(
    "</body>",
    f'<script id="embedded-worker" type="application/json">{inline_worker}</script>\n{scripts}\n</body>',
)
css = (assets / "styles.css").read_text(encoding="utf-8")
portable = portable.replace('<link rel="stylesheet" href="./static/styles.css">', f"<style>{css}</style>")
portable = portable.replace('  <link rel="icon" href="./static/favicon.svg" type="image/svg+xml">\n', "")
(output / "DocxMetaEditor.html").write_text(portable, encoding="utf-8")
