"""Read and update only the OpenXML property parts of a Word package."""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import PurePosixPath
import re
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from lxml import etree as ET

CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DT = "http://purl.org/dc/terms/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CORE_FIELDS = {
    "creator": DC, "lastModifiedBy": CP, "created": DT, "modified": DT,
    "lastPrinted": CP, "revision": CP, "title": DC, "subject": DC,
    "keywords": CP, "description": DC, "category": CP, "contentStatus": CP,
    "identifier": DC, "language": DC, "version": CP,
}
APP_FIELDS = (
    "TotalTime", "Company", "Manager", "Application", "AppVersion", "Pages",
    "Words", "Characters", "Paragraphs", "Lines", "CharactersWithSpaces",
    "Template", "HyperlinkBase", "PresentationFormat", "DocSecurity",
    "Slides", "Notes", "HiddenSlides", "MMClips",
    "ScaleCrop", "LinksUpToDate", "SharedDoc", "HyperlinksChanged",
)
NUMBERS = set(APP_FIELDS[5:11]) | {"revision", "TotalTime", "DocSecurity", "Slides", "Notes", "HiddenSlides", "MMClips"}
DATES = {"created", "modified", "lastPrinted"}
BOOLEAN_APP = {"ScaleCrop", "LinksUpToDate", "SharedDoc", "HyperlinksChanged"}
TYPES = {"lpwstr", "i4", "r8", "bool", "filetime"}
INTEGER_BOUNDS = {
    "i1": (-2**7, 2**7-1), "i2": (-2**15, 2**15-1),
    "i4": (-2**31, 2**31-1), "int": (-2**31, 2**31-1), "i8": (-2**63, 2**63-1),
    "ui1": (0, 2**8-1), "ui2": (0, 2**16-1), "ui4": (0, 2**32-1),
    "uint": (0, 2**32-1), "ui8": (0, 2**64-1),
}
EDITABLE_TYPES = TYPES | INTEGER_BOUNDS.keys() | {"lpstr", "bstr", "r4", "date", "decimal"}
PARTS = {
    "core": ("docProps/core.xml", CP, "coreProperties", "application/vnd.openxmlformats-package.core-properties+xml", REL + "/metadata/core-properties"),
    "app": ("docProps/app.xml", APP, "Properties", "application/vnd.openxmlformats-officedocument.extended-properties+xml", OFFICE_REL + "extended-properties"),
    "custom": ("docProps/custom.xml", CUSTOM, "Properties", "application/vnd.openxmlformats-officedocument.custom-properties+xml", OFFICE_REL + "custom-properties"),
}


class InvalidDocument(ValueError):
    pass


def q(ns, name):
    return f"{{{ns}}}{name}"


def xml(data):
    root = ET.fromstring(data, parser=ET.XMLParser(resolve_entities=False, no_network=True))
    if root.getroottree().docinfo.doctype:
        raise InvalidDocument("O pacote contém uma declaração XML não permitida.")
    return root


def serialize(root):
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def utc_date(value):
    try:
        if "T" not in value:
            raise ValueError
        date = datetime.fromisoformat(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        raise InvalidDocument("Informe uma data e hora válidas.") from None


def text_value(value):
    if not isinstance(value, str) or len(value) > 32000:
        raise InvalidDocument("Os campos devem conter texto com até 32.000 caracteres.")
    return value


def field_value(name, value):
    value = text_value(value)
    if not value:
        return value
    if name in DATES:
        return utc_date(value)
    if name in NUMBERS:
        if not re.fullmatch(r"[0-9]{1,10}", value) or int(value) > 2**31 - 1:
            raise InvalidDocument(f"{name} deve conter um número inteiro entre 0 e 2.147.483.647.")
        return str(int(value))
    if name in BOOLEAN_APP and value not in {"true", "false", "0", "1"}:
        raise InvalidDocument(f"{name} deve ser verdadeiro ou falso.")
    return value


def custom_value(kind, value):
    value = text_value(value)
    if kind in {"filetime", "date"}:
        return utc_date(value)
    if kind in INTEGER_BOUNDS:
        lower, upper = INTEGER_BOUNDS[kind]
        if not re.fullmatch(r"[+-]?[0-9]{1,20}", value) or not lower <= int(value) <= upper:
            raise InvalidDocument(f"Informe um inteiro válido para o tipo {kind}.")
        return str(int(value))
    if kind in {"r4", "r8", "decimal"}:
        pattern = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
        if kind != "decimal":
            pattern += r"(?:[eE][+-]?[0-9]+)?"
        if not re.fullmatch(pattern, value):
            raise InvalidDocument("Informe um número decimal válido, usando ponto.")
        if kind != "decimal" and abs(float(value)) > (3.402823466e38 if kind == "r4" else 1.7976931348623157e308):
            raise InvalidDocument("O número excede o limite do tipo escolhido.")
    if kind == "bool" and value not in {"true", "false", "0", "1"}:
        raise InvalidDocument("O valor lógico deve ser true ou false.")
    return value


class Document:
    def __init__(self, stream):
        self.archive = ZipFile(stream)
        try:
            self._load()
        except Exception:
            self.archive.close()
            raise

    def _load(self):
        entries = self.archive.infolist()
        self.names = set(self.archive.namelist())
        if len(entries) > 5000 or sum(entry.file_size for entry in entries) > 100 * 1024**2:
            raise InvalidDocument("O documento excede os limites do pacote (100 MB descompactados).")
        if len(entries) != len(self.names) or any(entry.flag_bits & 1 for entry in entries):
            raise InvalidDocument("O pacote contém entradas duplicadas ou protegidas por senha.")
        self.types = self.read_xml("[Content_Types].xml")
        self.rels = self.read_xml("_rels/.rels")
        if self.types is None or self.rels is None or not any(
            entry.get("ContentType") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            and (entry.get("PartName") or "").lstrip("/") in self.names
            for entry in self.types.findall(q(CT, "Override"))
        ):
            raise InvalidDocument("Selecione um documento Word .docx válido.")
        self.parts = {}
        self.paths = {}
        self.writes = {}
        for group, (default, namespace, root_name, _, relationship) in PARTS.items():
            links = [link for link in self.rels.findall(q(REL, "Relationship")) if link.get("Type") == relationship]
            if len(links) > 1:
                raise InvalidDocument("O pacote declara mais de uma parte do mesmo tipo de metadado.")
            uri = urlsplit(links[0].get("Target", "") if links else default)
            target = unquote(uri.path).lstrip("/")
            path = str(PurePosixPath(target))
            if (
                not target or path == "." or ".." in PurePosixPath(target).parts
                or uri.scheme or uri.netloc or uri.fragment or uri.query
                or path in self.paths.values() or path in {"[Content_Types].xml", "_rels/.rels"}
                or (links and links[0].get("TargetMode") == "External")
            ):
                raise InvalidDocument("O pacote contém um caminho de metadados inválido.")
            if links and path not in self.names and self.types.find(
                f"{{{CT}}}Override[@PartName='/{default}']"
            ) is not None and default != path:
                raise InvalidDocument("O pacote contém uma referência de metadados inconsistente.")
            root = self.read_xml(path)
            if root is not None and root.tag != q(namespace, root_name):
                raise InvalidDocument("O pacote contém uma parte de metadados inválida.")
            self.parts[group] = root
            self.paths[group] = path

    def read_xml(self, name):
        if name not in self.names:
            return None
        if self.archive.getinfo(name).file_size > 4 * 1024**2:
            raise InvalidDocument("Uma parte XML de metadados excede 4 MB.")
        return xml(self.archive.read(name))

    def fields(self, group):
        return CORE_FIELDS if group == "core" else dict.fromkeys(APP_FIELDS, APP)

    def custom_entries(self):
        root = self.parts["custom"]
        return [] if root is None else root.findall(q(CUSTOM, "property"))

    def inspect(self):
        result = {}
        for group in ("core", "app"):
            root = self.parts[group]
            result[group] = {} if root is None else {
                name: root.findtext(q(namespace, name), default="")
                for name, namespace in self.fields(group).items()
            }
        if self.parts["app"] is not None:
            result["advanced"] = [
                {"name": ET.QName(node).localname, "values": [
                    child.text for child in node.iter() if len(child) == 0 and child.text
                ]}
                for node in self.parts["app"] if isinstance(node.tag, str)
                and node.tag not in {q(APP, key) for key in APP_FIELDS}
            ]
        result["custom"] = []
        for index, node in enumerate(self.custom_entries()):
            child = node[0] if len(node) and isinstance(node[0].tag, str) else None
            kind = ET.QName(child).localname if child is not None else ""
            editable = child is not None and ET.QName(child).namespace == VT and kind in EDITABLE_TYPES and not len(child)
            result["custom"].append({
                "id": index, "name": node.get("name", ""), "type": kind,
                "value": (child.text or "") if editable else " ".join(node.itertext()).strip(),
                "editable": editable,
            })
        return result

    def ensure_part(self, group):
        if self.parts[group] is None:
            _, ns, name, _, _ = PARTS[group]
            nsmap = {"cp": CP, "dc": DC, "dcterms": DT, "xsi": XSI} if group == "core" else {None: ns, "vt": VT}
            self.parts[group] = ET.Element(q(ns, name), nsmap=nsmap)
        return self.parts[group]

    def register(self, group, remove=False):
        path = "/" + self.paths[group]
        _, _, _, content_type, relationship = PARTS[group]
        override = next((
            node for node in self.types.findall(q(CT, "Override"))
            if unquote(node.get("PartName", "")) == path
        ), None)
        link = next((node for node in self.rels.findall(q(REL, "Relationship")) if node.get("Type") == relationship), None)
        if remove:
            if override is not None:
                self.types.remove(override)
            if link is not None:
                self.rels.remove(link)
        else:
            if override is None:
                ET.SubElement(self.types, q(CT, "Override"), PartName=path, ContentType=content_type)
            if link is None:
                ids = {node.get("Id") for node in self.rels}
                index = 1
                while f"rId{index}" in ids:
                    index += 1
                ET.SubElement(self.rels, q(REL, "Relationship"), Id=f"rId{index}", Type=relationship, Target=path[1:])
        if remove == (override is not None):
            self.writes["[Content_Types].xml"] = serialize(self.types)
        if remove == (link is not None):
            self.writes["_rels/.rels"] = serialize(self.rels)

    def update_fields(self, group, changes):
        if not isinstance(changes, dict):
            raise InvalidDocument("Formato de campos inválido.")
        fields = self.fields(group)
        for name, raw in changes.items():
            if name not in fields:
                raise InvalidDocument("Campo de metadados desconhecido.")
            value = field_value(name, raw)
            root = self.parts[group]
            tag = q(fields[name], name)
            node = root.find(tag) if root is not None else None
            if value == (node.text or "" if node is not None else ""):
                continue
            if value:
                root = self.ensure_part(group)
                if node is None:
                    node = ET.SubElement(root, tag)
                node.text = value
                if name in {"created", "modified"}:
                    prefix = next((p for p, uri in node.nsmap.items() if p and uri == DT), None)
                    if prefix is None:
                        replacement = ET.Element(tag, nsmap={"dcterms": DT})
                        replacement.attrib.update(node.attrib)
                        replacement.text, replacement.tail = node.text, node.tail
                        root.replace(node, replacement)
                        node, prefix = replacement, "dcterms"
                    node.set(q(XSI, "type"), f"{prefix}:W3CDTF")
            else:
                root.remove(node)
            self.register(group)
            self.writes[self.paths[group]] = serialize(root)

    def update_custom(self, changes):
        if not isinstance(changes, list) or len(changes) > 1000:
            raise InvalidDocument("Formato ou quantidade de propriedades personalizadas inválidos.")
        original = self.custom_entries()
        root = self.parts["custom"]
        handled = set()
        used_pids = {node.get("pid") for node in original}
        if any(not isinstance(item, dict) for item in changes):
            raise InvalidDocument("Propriedade personalizada inválida.")
        names = {index: node.get("name", "").casefold() for index, node in enumerate(original)}
        changed_names = {}
        dirty = False
        for position, item in enumerate(changes):
            index = item.get("id")
            node = None
            if index is not None:
                if type(index) is not int or not 0 <= index < len(original) or index in handled:
                    raise InvalidDocument("Identificador de propriedade personalizada inválido.")
                handled.add(index)
                node = original[index]
            if item.get("remove") is True and node is not None:
                root.remove(node)
                names.pop(index)
                dirty = True
                continue
            name = text_value(item.get("name")).strip()
            if not name or len(name) > 255:
                raise InvalidDocument("Use nomes de 1 a 255 caracteres para propriedades personalizadas.")
            old_name = node.get("name", "") if node is not None else ""
            key = index if index is not None else len(original) + position
            if name.casefold() != names.get(key):
                changed_names[key] = name.casefold()
            names[key] = name.casefold()
            kind = text_value(item.get("type"))
            raw = text_value(item.get("value"))
            child = node[0] if node is not None and len(node) and isinstance(node[0].tag, str) else None
            if child is not None and child.tag == q(VT, kind) and not len(child) and raw == (child.text or "") and name == old_name:
                continue
            if kind not in EDITABLE_TYPES:
                raise InvalidDocument("Tipo de propriedade personalizada não editável.")
            if node is None and kind not in TYPES:
                raise InvalidDocument("Tipo inválido para uma nova propriedade personalizada.")
            if node is not None and (child is None or len(child) or child.tag not in {q(VT, t) for t in EDITABLE_TYPES}):
                raise InvalidDocument("Esta propriedade personalizada só pode ser removida.")
            value = custom_value(kind, raw)
            if node is None:
                root = self.ensure_part("custom")
                pid = 2
                while str(pid) in used_pids:
                    pid += 1
                used_pids.add(str(pid))
                node = ET.SubElement(root, q(CUSTOM, "property"), fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}", pid=str(pid))
            node.set("name", name)
            if child is None or child.tag != q(VT, kind):
                if child is not None:
                    node.remove(child)
                child = ET.SubElement(node, q(VT, kind))
            child.text = value
            dirty = True
        if changed_names:
            counts = {}
            for name in names.values():
                counts[name] = counts.get(name, 0) + 1
            if any(counts[name] > 1 for name in changed_names.values()):
                raise InvalidDocument("Os nomes das propriedades personalizadas devem ser únicos.")
        if dirty:
            self.register("custom")
            self.writes[self.paths["custom"]] = serialize(root)

    def anonymize(self):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.update_fields("core", {
            "creator": "", "lastModifiedBy": "", "revision": "1",
            "created": stamp, "modified": stamp, "lastPrinted": "",
        })
        self.update_fields("app", {"Company": "", "Manager": "", "TotalTime": "0"})
        self.remove_properties("custom")

    def remove_properties(self, *groups):
        for group in groups:
            self.register(group, remove=True)
            self.writes[self.paths[group]] = None

    def apply(self, changes):
        if not isinstance(changes, dict):
            raise InvalidDocument("Formato de alterações inválido.")
        mode = changes.get("mode", "edit")
        if mode == "clear":
            self.remove_properties("core", "app", "custom")
        elif mode in ("edit", "anon"):
            self.update_fields("core", changes.get("core", {}))
            self.update_fields("app", changes.get("app", {}))
            if mode == "anon":
                self.anonymize()
            else:
                self.update_custom(changes.get("custom", []))
        else:
            raise InvalidDocument("Modo de edição inválido.")

    def export(self):
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.comment = self.archive.comment
            for entry in self.archive.infolist():
                data = self.writes[entry.filename] if entry.filename in self.writes else self.archive.read(entry)
                if data is not None:
                    archive.writestr(entry, data)
            for name in self.writes.keys() - self.names:
                if self.writes[name] is not None:
                    archive.writestr(name, self.writes[name])
        output.seek(0)
        return output
