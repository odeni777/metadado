'use strict';

const byId = (id) => document.getElementById(id);
const fileInput = byId('file');
const form = byId('editor');
const status = byId('status');
const dropzone = byId('dropzone');
const download = byId('download');
const mode = byId('mode');
const modeHints = {
  edit: 'Os campos alterados são gravados em uma nova cópia.',
  anon: 'Redefine autoria, datas, revisão, empresa, gerente e tempo de edição. Remove propriedades personalizadas e preserva comentários e alterações controladas.',
  clear: 'Remove todas as propriedades gerais, estendidas e personalizadas. Preserva comentários e alterações controladas.',
};
function showMode() {
  byId('mode-hint').textContent = modeHints[mode.value];
}
mode.addEventListener('change', showMode);
showMode();
const customList = byId('custom-list');
const groups = {
  core: [
    ['creator', 'Autor'], ['lastModifiedBy', 'Último modificado por'],
    ['title', 'Título'], ['subject', 'Assunto'],
    ['keywords', 'Palavras-chave'], ['category', 'Categoria'],
    ['description', 'Descrição / Comentários', 'textarea'], ['contentStatus', 'Status'],
    ['created', 'Criação (UTC)', 'date'], ['modified', 'Última modificação (UTC)', 'date'],
    ['lastPrinted', 'Última impressão (UTC)', 'date'], ['revision', 'Revisão', 'number'],
    ['identifier', 'Identificador'], ['language', 'Idioma'], ['version', 'Versão do documento'],
  ],
  app: [
    ['TotalTime', 'Tempo total de edição (minutos)', 'number'], ['Company', 'Empresa / Instituição'],
    ['Manager', 'Gerente'], ['Application', 'Aplicativo gerador'], ['AppVersion', 'Versão do aplicativo'],
    ['Template', 'Modelo'], ['Pages', 'Páginas', 'number'], ['Words', 'Palavras', 'number'],
    ['Characters', 'Caracteres', 'number'], ['CharactersWithSpaces', 'Caracteres com espaços', 'number'],
    ['Paragraphs', 'Parágrafos', 'number'], ['Lines', 'Linhas', 'number'],
    ['HyperlinkBase', 'Base de hiperlinks'], ['PresentationFormat', 'Formato da apresentação'],
    ['DocSecurity', 'Indicador de segurança', 'number'], ['Slides', 'Slides', 'number'],
    ['Notes', 'Notas', 'number'], ['HiddenSlides', 'Slides ocultos', 'number'],
    ['MMClips', 'Clipes multimídia', 'number'], ['ScaleCrop', 'Ajuste de miniatura', 'boolean'],
    ['LinksUpToDate', 'Links atualizados', 'boolean'], ['SharedDoc', 'Documento compartilhado', 'boolean'],
    ['HyperlinksChanged', 'Hiperlinks alterados', 'boolean'],
  ],
};
const typeLabels = {lpwstr: 'Texto', i4: 'Inteiro', r8: 'Decimal', bool: 'Lógico', filetime: 'Data e hora (UTC)'};
const fields = {core: [], app: []};
const rows = new Map();
let currentFile = null;
let loadVersion = 0;

function create(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function announce(message, error = false) {
  status.hidden = !message;
  status.classList.toggle('error', error);
  status.textContent = message;
}

function dateInputValue(raw) {
  if (!raw) return '';
  const source = /(?:Z|[+-]\d{2}:\d{2})$/i.test(raw) ? raw : raw + 'Z';
  const date = new Date(source);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 19);
}

function makeField(label, control) {
  const field = create('label', 'field');
  field.append(create('span', '', label), control);
  return field;
}

function selectValues(values) {
  const select = create('select');
  for (const [value, label] of Object.entries(values)) select.add(new Option(label, value));
  return select;
}

function renderFields(group, data) {
  const grid = create('div', 'field-grid');
  fields[group] = groups[group].map(([key, label, type]) => {
    const raw = data[key] || '';
    const input = type === 'boolean' ? selectValues({'': '—', true: 'Sim', false: 'Não'}) :
      create(type === 'textarea' ? 'textarea' : 'input');
    if (input.tagName === 'INPUT') {
      input.type = type === 'date' ? 'datetime-local' : type || 'text';
      if (type === 'date') input.step = '1';
      if (type === 'number') {
        input.min = '0';
        input.max = '2147483647';
      }
    }
    const field = makeField(label, input);
    input.value = type === 'date' ? dateInputValue(raw) : type === 'boolean' ?
      ({'1': 'true', '0': 'false'}[raw] || raw) : raw;
    if (raw && !input.value) field.append(create('small', '', 'Valor original: ' + raw));
    if (key === 'TotalTime') {
      const hint = create('small');
      const update = () => {
        const minutes = Number(input.value);
        hint.textContent = input.value && Number.isSafeInteger(minutes) && minutes >= 0 ?
          Math.floor(minutes / 60) + ' h ' + minutes % 60 + ' min' : 'Informe o tempo em minutos.';
      };
      input.addEventListener('input', update);
      update();
      field.append(hint);
    }
    grid.append(field);
    return {key, input, type, baseline: input.value};
  });
  byId('panel-' + group).replaceChildren(grid);
}

function refreshEmpty() {
  const empty = customList.querySelector('.empty');
  if (!customList.querySelector('.custom-row')) {
    if (!empty) customList.append(create('p', 'empty', 'Nenhuma propriedade personalizada.'));
  } else {
    empty?.remove();
  }
}

function addCustom(item = {name: '', type: 'lpwstr', value: '', editable: true}) {
  const row = create('div', 'custom-row');
  const name = create('input');
  name.maxLength = 255;
  name.value = item.name;
  const types = {...typeLabels};
  if (!Object.hasOwn(types, item.type)) types[item.type] = item.type || 'Tipo desconhecido';
  const type = selectValues(types);
  type.value = item.type;
  const value = create('input');
  const setType = (raw = '') => {
    const date = ['filetime', 'date'].includes(type.value);
    value.type = date && item.editable ? 'datetime-local' : 'text';
    value.step = date ? '1' : 'any';
    value.value = date && item.editable ? dateInputValue(raw) : raw;
    value.placeholder = type.value === 'bool' ? 'true ou false' : '';
  };
  setType(item.value);
  const initial = [name.value, type.value, value.value];
  type.addEventListener('change', () => setType());
  name.disabled = type.disabled = value.disabled = !item.editable;
  const remove = create('button', 'button secondary', 'Remover');
  remove.type = 'button';
  remove.setAttribute('aria-label', 'Remover propriedade personalizada');
  const record = {item, name, type, value, initial, removed: false};
  remove.addEventListener('click', () => {
    record.removed = true;
    row.remove();
    refreshEmpty();
  });
  row.append(makeField('Nome', name), makeField('Tipo', type), makeField('Valor', value), remove);
  customList.append(row);
  rows.set(row, record);
  refreshEmpty();
  if (item.id === undefined) name.focus();
}

function renderAdvanced(items) {
  const list = byId('advanced-list');
  list.replaceChildren();
  if (!items.length) return;
  list.append(create('h2', '', 'Estruturas adicionais'));
  for (const item of items) list.append(create('p', 'advanced-item', item.name + ' · ' + item.values.join(', ')));
}

const tabs = Array.from(document.querySelectorAll('[role=tab]'));
function selectTab(selected) {
  for (const tab of tabs) {
    const active = tab === selected;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    byId(tab.getAttribute('aria-controls')).hidden = !active;
  }
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', (event) => {
    const target = {ArrowLeft: (index + tabs.length - 1) % tabs.length,
      ArrowRight: (index + 1) % tabs.length, Home: 0, End: tabs.length - 1}[event.key];
    if (target === undefined) return;
    event.preventDefault();
    selectTab(tabs[target]);
    tabs[target].focus();
  });
});

async function send(path, file, changes) {
  if (window.processDocxLocally) return window.processDocxLocally(path, file, changes);
  const data = new FormData();
  data.append('file', file);
  if (changes) data.append('changes', JSON.stringify(changes));
  const response = await fetch('/api/' + path, {method: 'POST', body: data});
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(result.error || 'Não foi possível processar o documento.');
  }
  return response;
}

async function loadFile(file) {
  if (!file) return;
  const version = ++loadVersion;
  fileInput.value = '';
  if (!/\.docx$/i.test(file.name) || file.size > 20 * 1024 ** 2) {
    announce('Selecione um arquivo .docx de até 20 MB.', true);
    return;
  }
  announce('Lendo metadados…');
  try {
    const result = await (await send('inspect', file)).json();
    if (version !== loadVersion) return;
    currentFile = file;
    byId('filename').textContent = file.name;
    byId('filesize').textContent = new Intl.NumberFormat('pt-BR', {style: 'unit', unit: 'kilobyte',
      maximumFractionDigits: 1}).format(file.size / 1024);
    renderFields('core', result.core);
    renderFields('app', result.app);
    rows.clear();
    customList.replaceChildren();
    for (const item of result.custom) addCustom(item);
    refreshEmpty();
    renderAdvanced(result.advanced || []);
    mode.value = 'edit';
    showMode();
    selectTab(tabs[0]);
    dropzone.hidden = byId('overview').hidden = true;
    byId('file-row').hidden = form.hidden = false;
    announce('Documento carregado.');
  } catch (error) {
    if (version === loadVersion) announce(error.message, true);
  }
}

byId('choose').addEventListener('click', () => fileInput.click());
byId('replace').addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => loadFile(fileInput.files[0]));
for (const target of [dropzone, byId('file-row')]) {
  target.addEventListener('dragover', (event) => {
    event.preventDefault();
    target.classList.add('is-dragging');
  });
  target.addEventListener('dragleave', () => target.classList.remove('is-dragging'));
  target.addEventListener('drop', (event) => {
    event.preventDefault();
    target.classList.remove('is-dragging');
    loadFile(event.dataTransfer.files[0]);
  });
}
byId('add').addEventListener('click', () => addCustom());

form.addEventListener('invalid', (event) => {
  const panel = event.target.closest('[role=tabpanel]');
  if (panel) selectTab(byId(panel.getAttribute('aria-labelledby')));
}, true);

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!currentFile) return;
  const file = currentFile;
  const changes = {core: {}, app: {}, custom: [], mode: mode.value};
  for (const group of ['core', 'app']) {
    for (const {key, input, type, baseline} of fields[group]) {
      if (input.value !== baseline) changes[group][key] = type === 'date' && input.value ? input.value + 'Z' : input.value;
    }
  }
  if (mode.value === 'edit') {
    for (const {item, name, type, value, initial, removed} of rows.values()) {
      if (removed) {
        if (item.id !== undefined) changes.custom.push({id: item.id, remove: true});
      } else if (item.id === undefined || [name.value, type.value, value.value].some((entry, i) => entry !== initial[i])) {
        changes.custom.push({id: item.id, name: name.value, type: type.value,
          value: value.type === 'datetime-local' && value.value ? value.value + 'Z' : value.value});
      }
    }
  }
  download.disabled = true;
  announce('Preparando o documento…');
  try {
    const response = await send('download', file, changes);
    const url = URL.createObjectURL(await response.blob());
    const anchor = create('a');
    anchor.href = url;
    anchor.download = file.name.replace(/\.docx$/i, '-editado.docx');
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    announce('Documento pronto. O download foi iniciado.');
  } catch (error) {
    announce(error.message, true);
  } finally {
    download.disabled = false;
  }
});
