'use strict';

const runtimeUrl = 'https://cdn.jsdelivr.net/pyodide/v0.29.3/full/';
let runtime;
let queue = Promise.resolve();

async function loadRuntime() {
  importScripts(runtimeUrl + 'pyodide.js');
  const python = await loadPyodide({indexURL: runtimeUrl});
  let source = typeof embeddedOpenXml === 'string' ? embeddedOpenXml : null;
  if (source === null) {
    const response = await fetch('./openxml.py');
    if (!response.ok) throw new Error('OpenXML module unavailable');
    source = await response.text();
  }
  await python.loadPackage('lxml');
  python.FS.writeFile('/home/pyodide/openxml.py', source);
  python.runPython(`
import json
from io import BytesIO
from zipfile import BadZipFile, LargeZipFile
from lxml import etree
from openxml import Document, InvalidDocument

def process(path, payload, changes):
    try:
        document = Document(BytesIO(payload.to_py()))
        with document.archive:
            if path == 'inspect':
                return True, json.dumps(document.inspect())
            document.apply(json.loads(changes))
            return True, document.export().getvalue()
    except InvalidDocument as error:
        return False, str(error)
    except (BadZipFile, LargeZipFile, etree.XMLSyntaxError, RuntimeError, ValueError, NotImplementedError):
        return False, "Não foi possível processar o documento ou os valores informados."
`);
  return python;
}

async function processRequest({id, path, bytes, changes}) {
  try {
    runtime ??= loadRuntime();
    let python;
    try {
      python = await runtime;
    } catch (error) {
      runtime = null;
      throw error;
    }
    const process = python.globals.get('process');
    try {
      const response = process(path, new Uint8Array(bytes), changes);
      try {
        const [ok, result] = response.toJs();
        if (!ok) postMessage({id, error: result});
        else if (path === 'inspect') postMessage({id, result});
        else postMessage({id, result}, [result.buffer]);
      } finally {
        response.destroy();
      }
    } finally {
      process.destroy();
    }
  } catch (error) {
    console.error(error);
    postMessage({id, error: 'Não foi possível processar o arquivo no navegador. Confira a conexão e tente novamente.'});
  }
}

self.addEventListener('message', ({data}) => {
  queue = queue.then(() => processRequest(data));
});
