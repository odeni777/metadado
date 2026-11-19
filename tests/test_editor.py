import io
import json
import unittest
from zipfile import ZipFile

from lxml import etree

from docxmeta import app
from docxmeta.openxml import CP, CT, DC, DT, OFFICE_REL, REL, VT, XSI, PARTS, q

OFFICE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PROTECTED = {
    "word/document.xml": f'<w:document xmlns:w="{OFFICE}"><w:body><w:p><w:r><w:t>Olá</w:t></w:r></w:p></w:body></w:document>'.encode(),
    "word/_rels/document.xml.rels": f'<Relationships xmlns="{REL}"/>'.encode(),
    "word/styles.xml": f'<w:styles xmlns:w="{OFFICE}"/>'.encode(),
    "word/media/image.png": b"image test bytes",
    "word/comments.xml": f'<w:comments xmlns:w="{OFFICE}"/>'.encode(),
}


def fixture(with_metadata=True):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        declarations = ['<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>']
        links = [f'<Relationship Id="rId1" Type="{OFFICE_REL}officeDocument" Target="word/document.xml"/>']
        if with_metadata:
            path, _, _, content_type, relationship = PARTS["core"]
            declarations.append(f'<Override PartName="/{path}" ContentType="{content_type}"/>')
            links.append(f'<Relationship Id="rId2" Type="{relationship}" Target="{path}"/>')
            archive.writestr(path, f'<cp:coreProperties xmlns:cp="{CP}" xmlns:dc="{DC}"><dc:creator>Ana</dc:creator><cp:revision>7</cp:revision></cp:coreProperties>')
        archive.writestr("[Content_Types].xml", f'<Types xmlns="{CT}">{"".join(declarations)}</Types>')
        archive.writestr("_rels/.rels", f'<Relationships xmlns="{REL}">{"".join(links)}</Relationships>')
        for name, data in PROTECTED.items():
            archive.writestr(name, data)
    return stream.getvalue()


class EditorTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def upload(self, endpoint, data, changes=None):
        body = {"file": (io.BytesIO(data), "original.docx")}
        if changes is not None:
            body["changes"] = json.dumps(changes)
        return self.client.post("/api/" + endpoint, data=body)

    def assert_preserved(self, data):
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            for name, expected in PROTECTED.items():
                self.assertEqual(archive.read(name), expected)
            rels = etree.fromstring(archive.read("_rels/.rels"))
            self.assertEqual(rels[0].get("Target"), "word/document.xml")
            self.assertEqual(rels[0].get("Id"), "rId1")

    def test_roundtrip_add_edit_and_remove_custom(self):
        result = self.upload("inspect", fixture()).get_json()
        self.assertEqual(result["core"]["creator"], "Ana")
        response = self.upload("download", fixture(), {
            "core": {"created": "2025-06-05T11:00:12-03:00", "title": "Relatório"},
            "app": {"TotalTime": "145"},
            "custom": [{"name": "Vigente", "type": "bool", "value": "true"}],
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True) if response.is_json else "")
        self.assertIn("original-editado.docx", response.headers["Content-Disposition"])
        result = self.upload("inspect", response.data).get_json()
        self.assertEqual(result["core"]["created"], "2025-06-05T14:00:12Z")
        self.assertEqual(result["core"]["title"], "Relatório")
        self.assertEqual(result["app"]["TotalTime"], "145")
        self.assertEqual(result["custom"][0]["value"], "true")
        with ZipFile(io.BytesIO(response.data)) as archive:
            core = etree.fromstring(archive.read("docProps/core.xml"))
            created = core.find(q(DT, "created"))
            self.assertEqual(created.nsmap[created.get(q(XSI, "type")).split(":")[0]], DT)
            custom = etree.fromstring(archive.read("docProps/custom.xml"))
            self.assertEqual(custom[0][0].tag, q(VT, "bool"))
        self.assert_preserved(response.data)
        edited = self.upload("download", response.data, {"custom": [
            {"id": 0, "name": "Revisor", "type": "lpwstr", "value": "Luís"},
        ]})
        self.assertEqual(self.upload("inspect", edited.data).get_json()["custom"][0]["value"], "Luís")
        deleted = self.upload("download", edited.data, {"custom": [{"id": 0, "remove": True}]})
        self.assertEqual(self.upload("inspect", deleted.data).get_json()["custom"], [])

    def test_anonymize_and_clear(self):
        data = self.upload("download", fixture(), {"app": {"Company": "Exemplo"}, "custom": [
            {"name": "Origem", "type": "i4", "value": "12"},
        ]}).data
        for mode in ("anon", "clear"):
            with self.subTest(mode=mode):
                response = self.upload("download", data, {"mode": mode})
                self.assertEqual(response.status_code, 200)
                self.assert_preserved(response.data)
                result = self.upload("inspect", response.data).get_json()
                self.assertEqual(result["custom"], [])
                removed = ("core", "app", "custom") if mode == "clear" else ("custom",)
                with ZipFile(io.BytesIO(response.data)) as archive:
                    for group in removed:
                        path, _, _, _, relationship = PARTS[group]
                        self.assertNotIn(path, archive.namelist())
                        self.assertNotIn(path.encode(), archive.read("[Content_Types].xml"))
                        self.assertNotIn(relationship.encode(), archive.read("_rels/.rels"))
                if mode == "anon":
                    self.assertEqual(result["core"]["creator"], "")
                    self.assertEqual(result["core"]["revision"], "1")
                    self.assertTrue(result["core"]["created"].endswith("Z"))
                    self.assertEqual(result["app"]["Company"], "")
                else:
                    self.assertEqual(result["core"], {})
                    self.assertEqual(result["app"], {})

    def test_missing_core_and_invalid_input(self):
        self.assertEqual(self.upload("inspect", b"invalid").status_code, 400)
        source = fixture(with_metadata=False)
        self.assertEqual(self.upload("download", source, {"app": {"TotalTime": "-1"}}).status_code, 400)
        result = self.upload("download", source, {"core": {"creator": "Ana"}})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.upload("inspect", result.data).get_json()["core"]["creator"], "Ana")
        self.assert_preserved(result.data)

    def test_no_edits_keep_all_inner_parts_byte_identical(self):
        original = fixture()
        updated = self.upload("download", original, {}).data
        with ZipFile(io.BytesIO(original)) as before, ZipFile(io.BytesIO(updated)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in before.namelist():
                self.assertEqual(before.read(name), after.read(name), name)
