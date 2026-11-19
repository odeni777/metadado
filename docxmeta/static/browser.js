'use strict';

const embeddedWorker = document.getElementById('embedded-worker');
const workerUrl = embeddedWorker
  ? URL.createObjectURL(new Blob([JSON.parse(embeddedWorker.textContent)], {type: 'text/javascript'}))
  : new URL('./worker.js', document.currentScript.src);
let worker;
let nextRequest = 0;
const pending = new Map();

function getWorker() {
  if (worker) return worker;
  worker = new Worker(workerUrl);
  worker.addEventListener('message', ({data}) => {
    const request = pending.get(data.id);
    if (!request) return;
    pending.delete(data.id);
    if (data.error) request.reject(new Error(data.error));
    else request.resolve(data.result);
  });
  worker.addEventListener('error', () => {
    const error = new Error('Não foi possível iniciar o editor. Recarregue a página e tente novamente.');
    for (const request of pending.values()) request.reject(error);
    pending.clear();
    worker.terminate();
    worker = null;
  });
  return worker;
}

window.processDocxLocally = async (path, file, changes) => {
  const bytes = await file.arrayBuffer();
  const activeWorker = getWorker();
  const id = ++nextRequest;
  const result = await new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    activeWorker.postMessage({id, path, bytes, changes: JSON.stringify(changes ?? {})}, [bytes]);
  });
  return path === 'inspect'
    ? new Response(result, {headers: {'Content-Type': 'application/json'}})
    : new Response(result);
};
