from zipfile import BadZipFile, LargeZipFile
import json

from flask import Flask, jsonify, render_template, request, send_file
from lxml import etree
from werkzeug.utils import secure_filename

from .openxml import Document, InvalidDocument

app = Flask(__name__)
MAX_UPLOAD = 20 * 1024**2
app.config.update(MAX_CONTENT_LENGTH=MAX_UPLOAD + 1024**2, MAX_FORM_MEMORY_SIZE=1024**2)


@app.get("/")
def index():
    return render_template("index.html")


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="O arquivo deve ter até 20 MB."), 413


@app.post("/api/inspect")
@app.post("/api/download")
def process():
    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".docx"):
        return jsonify(error="Selecione um arquivo com extensão .docx."), 400
    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > MAX_UPLOAD:
        return too_large(None)
    try:
        document = Document(upload.stream)
        with document.archive:
            if request.path == "/api/inspect":
                return jsonify(document.inspect())
            changes = json.loads(request.form.get("changes", "{}"))
            if not isinstance(changes, dict):
                raise InvalidDocument("Formato de alterações inválido.")
            mode = changes.get("mode", "edit")
            if mode == "clear":
                document.remove_properties("core", "app", "custom")
            elif mode in ("edit", "anon"):
                document.update_fields("core", changes.get("core", {}))
                document.update_fields("app", changes.get("app", {}))
                if mode == "anon":
                    document.anonymize()
                else:
                    document.update_custom(changes.get("custom", []))
            else:
                raise InvalidDocument("Modo de edição inválido.")
            output = document.export()
    except InvalidDocument as error:
        return jsonify(error=str(error)), 400
    except (BadZipFile, LargeZipFile, etree.XMLSyntaxError, RuntimeError, ValueError, NotImplementedError):
        return jsonify(error="Não foi possível processar o documento ou os valores informados."), 400
    stem = secure_filename(upload.filename[:-5]) or "documento"
    response = send_file(output, as_attachment=True, download_name=f"{stem}-editado.docx",
                         mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.after_request
def secure_responses(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
