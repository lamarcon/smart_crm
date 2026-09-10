const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const BASE_URL = process.env.SMART_CRM_TEST_URL || 'http://localhost:8080/';
const STORAGE_KEY = 'smart-crm-demo-v1';
const CONFIRMED_CACHE_KEY = 'smart-crm-confirmed-v1';
const LEAD_STAGES = ['Em contato', 'Lead descartado', 'Lead convertido'];
const DEAL_STAGES = [
  'Em Contato', 'Orçamento Proposta Preço', 'Orçamentos enviados',
  'Negociação Revisão', 'Pedido aprovado Consultar', 'Faturando',
  'Ganho', 'Orçamento Não Aprovado', 'Analisar falha'
];

let browser;
let passed = 0;
let failed = 0;
const apiByPage = new WeakMap();

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function durableState(source) {
  const durable = clone(source);
  delete durable.currentUserId;
  durable.ui ||= {};
  delete durable.ui.filtersByUser;
  return durable;
}

function countsFor(state) {
  return {
    users: state.users.length,
    leads: state.leads.length,
    contacts: state.contacts.length,
    companies: state.companies.length,
    deals: state.deals.length,
    quotes: state.deals.reduce((total, deal) => total + (deal.quotes || []).length, 0),
    notifications: state.notifications.length,
    customFields: Object.values(state.customFieldSchemas || {}).reduce((total, fields) => total + fields.length, 0)
  };
}

async function stateFrom(page) {
  await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting !== 'true');
  const local = JSON.parse(await page.evaluate(key => localStorage.getItem(key), STORAGE_KEY));
  const api = apiByPage.get(page);
  const writable = await page.evaluate(() => document.documentElement.dataset.workspaceWritable === 'true');
  if (api?.initialized && writable && api.assertSynchronized && !api.writeFailure) {
    assert.deepEqual(durableState(local), api.state, 'estado durável local divergiu da API confirmada');
  }
  return local;
}

async function openFresh(options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1366, height: 768 } });
  if (options.preloadState) {
    await context.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: options.preloadState });
  }
  const page = await context.newPage();
  const api = { initialized: false, version: 0, state: null, loadFailure: Boolean(options.loadFailure), writeFailure: false, writeGate: null, assertSynchronized: false, deleted: { users: [], leads: [], contacts: [], companies: [], deals: [], quotes: [], notifications: [] } };
  apiByPage.set(page, api);
  await context.route('**/api/workspace**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const workspacePaths = ['/api/workspace', '/api/workspace/bootstrap', '/api/workspace/reset', '/api/workspace/deleted', '/api/workspace/restore'];
    if (!workspacePaths.includes(url.pathname)) return route.continue();
    if (request.method() === 'GET' && url.pathname === '/api/workspace') {
      if (api.loadFailure) {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Banco de dados indisponível.' } }) });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ initialized: api.initialized, version: api.version, state: api.state })
      });
    }
    if (request.method() === 'POST' && url.pathname === '/api/workspace/bootstrap') {
      if (api.initialized) {
        return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'workspace_already_initialized', message: 'Workspace já inicializado.', currentVersion: api.version } }) });
      }
      const payload = request.postDataJSON();
      api.state = durableState(payload.state);
      api.initialized = true;
      api.version = 1;
      api.assertSynchronized = true;
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ version: api.version, counts: countsFor(api.state), state: api.state }) });
    }
    if (request.method() === 'GET' && url.pathname === '/api/workspace/deleted') {
      const module = url.searchParams.get('module');
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ module, records: clone(api.deleted[module] || []) }) });
    }
    if ((request.method() === 'PUT' && url.pathname === '/api/workspace') || (request.method() === 'POST' && url.pathname === '/api/workspace/reset')) {
      if (api.writeFailure) {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Banco de dados indisponível.', errorId: 'mock-write-failure' } }) });
      }
      if (api.writeGate) {
        const gate = api.writeGate;
        api.writeGate = null;
        await gate;
      }
      const payload = request.postDataJSON();
      if (payload.version !== api.version) {
        return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'version_conflict', message: 'Versão do workspace desatualizada.', currentVersion: api.version } }) });
      }
      const next = durableState(payload.state);
      for (const module of ['users', 'leads', 'contacts', 'companies', 'deals', 'notifications']) {
        const nextIds = new Set(next[module].map(record => record.id));
        for (const record of api.state[module].filter(record => !nextIds.has(record.id))) {
          if (!api.deleted[module].some(candidate => candidate.id === record.id)) api.deleted[module].push(clone(record));
        }
        const activeIds = new Set(next[module].map(record => record.id));
        api.deleted[module] = api.deleted[module].filter(record => !activeIds.has(record.id));
      }
      api.state = next;
      api.version += 1;
      api.assertSynchronized = true;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: api.version, counts: countsFor(api.state), state: api.state }) });
    }
    if (request.method() === 'POST' && url.pathname === '/api/workspace/restore') {
      const payload = request.postDataJSON();
      if (payload.version !== api.version) {
        return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'version_conflict', message: 'Versão do workspace desatualizada.', currentVersion: api.version } }) });
      }
      const records = api.deleted[payload.module] || [];
      const index = records.findIndex(record => record.id === payload.id);
      if (index < 0) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'record_not_found', message: 'Registro excluído não encontrado.' } }) });
      api.state[payload.module].push(records.splice(index, 1)[0]);
      api.version += 1;
      api.assertSynchronized = true;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: api.version, counts: countsFor(api.state), state: api.state }) });
    }
    return route.fulfill({ status: 405 });
  });
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('#workspaceBanner').waitFor();
  if (options.autoBootstrap !== false && !api.loadFailure) {
    const confirm = page.getByRole('button', { name: 'Confirmar migração' });
    await confirm.waitFor();
    await confirm.click();
  }
  await page.waitForFunction(() => document.documentElement.dataset.workspaceReady === 'true');
  return { context, page };
}

async function reloadReady(page, options = {}) {
  await page.reload({ waitUntil: 'domcontentloaded' });
  const api = apiByPage.get(page);
  if (options.autoBootstrap !== false && !api.loadFailure && !api.initialized) {
    await page.getByRole('button', { name: 'Confirmar migração' }).click();
  }
  await page.waitForFunction(() => document.documentElement.dataset.workspaceReady === 'true');
}

async function assertCanonicalRehydration(page) {
  const sourceApi = apiByPage.get(page);
  const expected = clone(sourceApi.state);

  await reloadReady(page);
  assert.deepEqual(durableState(await stateFrom(page)), expected, 'recarga não reidratou o estado canônico');

  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  try {
    const independent = await context.newPage();
    const mirrorApi = {
      initialized: true,
      version: sourceApi.version,
      state: expected,
      loadFailure: false,
      writeFailure: false,
      writeGate: null,
      assertSynchronized: true,
      deleted: { users: [], leads: [], contacts: [], companies: [], deals: [], quotes: [], notifications: [] }
    };
    apiByPage.set(independent, mirrorApi);
    await context.route('**/api/workspace**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === 'GET' && url.pathname === '/api/workspace') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ initialized: true, version: mirrorApi.version, state: mirrorApi.state })
        });
      }
      return route.fulfill({ status: 405 });
    });
    await independent.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await independent.locator('#workspaceBanner').waitFor();
    await independent.waitForFunction(() => document.documentElement.dataset.workspaceReady === 'true');
    assert.deepEqual(durableState(await stateFrom(independent)), expected, 'contexto independente não reidratou o estado canônico');
  } finally {
    await context.close();
  }
}

async function setMockWorkspace(page, nextState) {
  const api = apiByPage.get(page);
  api.state = durableState(nextState);
  api.initialized = true;
  api.version += 1;
  api.assertSynchronized = false;
}

function resetMockWorkspace(page) {
  const api = apiByPage.get(page);
  api.initialized = false;
  api.version = 0;
  api.state = null;
  api.loadFailure = false;
}

async function run(name, test, options = {}) {
  const { context, page } = await openFresh(options);
  try {
    await test(page);
    passed += 1;
    console.log(`PASS ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`FAIL ${name}\n${error.stack}`);
  } finally {
    await context.close();
  }
}

async function goTo(page, name) {
  await page.locator('.nav').getByRole('button', { name: new RegExp(name) }).click();
}

async function selectProfile(page, userId) {
  await page.getByLabel('Perfil demonstrativo').selectOption(userId);
}

async function visibleRows(page, entity) {
  await goTo(page, entity);
  const slug = { Leads: 'leads', Negócios: 'deals' }[entity];
  return page.locator(`#page-${slug} tbody tr`).count();
}

async function createLead(page, name, options = {}) {
  await goTo(page, 'Leads');
  await page.getByRole('button', { name: /Novo Lead/ }).click();
  const dialog = page.locator('#entityDialog');
  await dialog.getByLabel('Nome completo *').fill(name);
  await dialog.getByLabel('Empresa *').fill('Empresa de Teste');
  await dialog.getByLabel('E-mail *').fill('teste@local.invalid');
  await dialog.getByLabel('Responsável *').selectOption('u-paula');
  await dialog.getByLabel('Assistente').selectOption('u-camila');
  await dialog.getByRole('button', { name: 'Salvar registro' }).click();
  if (options.waitForSaved !== false) await page.locator('#page-leads .entity-link').filter({ hasText: name }).waitFor();
}

(async () => {
  browser = await chromium.launch({ channel: process.env.SMART_CRM_BROWSER || 'chrome', headless: true });

  await run('DBP-02 e DBP-03 exigem Admin e exibem contagens antes do bootstrap', async page => {
    const local = await stateFrom(page);
    local.currentUserId = 'u-paula';
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: local });
    resetMockWorkspace(page);
    await reloadReady(page, { autoBootstrap: false });

    const dialog = page.locator('#bootstrapDialog');
    assert.equal(await dialog.isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceWritable), 'false');
    assert.equal(await dialog.getByRole('button', { name: 'Confirmar migração' }).isDisabled(), true);
    assert.match(await dialog.innerText(), /5\s+Leads/);
    assert.match(await dialog.innerText(), /4\s+Contatos/);
    assert.match(await dialog.innerText(), /4\s+Empresas/);
    assert.match(await dialog.innerText(), /6\s+Negócios/);

    local.currentUserId = 'u-admin';
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: local });
    resetMockWorkspace(page);
    await reloadReady(page, { autoBootstrap: false });
    await page.getByRole('button', { name: 'Confirmar migração' }).click();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWritable === 'true');
    const api = apiByPage.get(page);
    assert.equal(api.version, 1);
    assert.deepEqual(countsFor(api.state), { users: 6, leads: 5, contacts: 4, companies: 4, deals: 6, quotes: 1, notifications: 3, customFields: 0 });
  }, { autoBootstrap: false });

  await run('DBP-07 carrega o banco antes de liberar escrita e ignora cache comercial alterado', async page => {
    const canonical = clone(apiByPage.get(page).state);
    const altered = await stateFrom(page);
    altered.leads[0].name = 'Nome apenas no navegador';
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: altered });
    await reloadReady(page);
    const loaded = await stateFrom(page);
    assert.equal(loaded.leads[0].name, canonical.leads[0].name);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceWritable), 'true');
  });

  await run('DBP-21 usa somente cache confirmado em leitura quando a API falha', async page => {
    const cached = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), CONFIRMED_CACHE_KEY);
    const altered = await stateFrom(page);
    altered.leads[0].name = 'Alteração não confirmada';
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: altered });
    apiByPage.get(page).loadFailure = true;
    await reloadReady(page);
    assert.equal((await stateFrom(page)).leads[0].name, cached.state.leads[0].name);
    assert.equal(await page.locator('#workspaceBanner').innerText(), 'Banco indisponível. Alterações bloqueadas.');
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceWritable), 'false');
    await page.getByRole('button', { name: /Novo Lead/ }).click();
    assert.equal(await page.locator('#entityDialog').getAttribute('open'), null);
  });

  await run('DBP-21 usa seed em leitura quando a API falha sem cache confirmado', async page => {
    const state = await stateFrom(page);
    assert.equal(state.leads[0].name, 'Larissa Spinola');
    assert.equal(await page.locator('#workspaceBanner').innerText(), 'Banco indisponível. Alterações bloqueadas.');
    assert.equal(await page.evaluate(key => localStorage.getItem(key), CONFIRMED_CACHE_KEY), null);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceWritable), 'false');
  }, { loadFailure: true });

  await run('DBP-08, DBP-09 e DBP-17 confirmam uma versão por ação durável em outro contexto', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    const beforeNotifications = api.state.notifications.length;
    await createLead(page, 'Lead confirmado pela API');
    await stateFrom(page);
    assert.equal(api.version, beforeVersion + 1);
    assert.equal(api.state.notifications.length, beforeNotifications + 1);

    const secondContext = await browser.newContext({ viewport: { width: 1366, height: 768 } });
    await secondContext.route('**/api/workspace**', route => {
      const request = route.request();
      if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/workspace') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ initialized: true, version: api.version, state: api.state }) });
      }
      return route.continue();
    });
    const secondPage = await secondContext.newPage();
    apiByPage.set(secondPage, api);
    await secondPage.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await secondPage.waitForFunction(() => document.documentElement.dataset.workspaceReady === 'true');
    assert.equal(await secondPage.locator('#page-dashboard').getByText('Lead confirmado pela API').count(), 1);
    assert.equal((await stateFrom(secondPage)).leads.some(lead => lead.name === 'Lead confirmado pela API'), true);
    await secondContext.close();
  });

  await run('DBP-09 só confirma visualmente depois da versão persistida', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    const beforeCache = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), CONFIRMED_CACHE_KEY);
    let releaseWrite;
    api.writeGate = new Promise(resolve => { releaseWrite = resolve; });

    await createLead(page, 'Lead aguardando confirmação', { waitForSaved: false });
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting === 'true');

    assert.equal(api.version, beforeVersion);
    assert.equal(await page.getByText('Lead criado com sucesso.', { exact: true }).count(), 0);
    assert.deepEqual(await page.evaluate(key => JSON.parse(localStorage.getItem(key)), CONFIRMED_CACHE_KEY), beforeCache);

    releaseWrite();
    await page.getByText('Lead criado com sucesso.', { exact: true }).waitFor();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting === 'false');

    assert.equal(api.version, beforeVersion + 1);
    assert.equal((await page.evaluate(key => JSON.parse(localStorage.getItem(key)), CONFIRMED_CACHE_KEY)).version, beforeVersion + 1);
    assert.equal(api.state.leads.some(lead => lead.name === 'Lead aguardando confirmação'), true);
  });

  await run('DBP-16 mantém busca e perfil locais sem incrementar a versão', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    await goTo(page, 'Leads');
    await page.getByPlaceholder('Buscar em leads...').fill('Larissa');
    await selectProfile(page, 'u-paula');
    const local = await stateFrom(page);
    assert.equal(api.version, beforeVersion);
    assert.equal(local.currentUserId, 'u-paula');
    assert.equal(local.ui.filtersByUser['u-admin'].leads.query, 'Larissa');
    assert.equal(Object.hasOwn(api.state, 'currentUserId'), false);
    assert.equal(Object.hasOwn(api.state.ui, 'filtersByUser'), false);
  });

  await run('DBP-22 reverte a alteração e preserva cache quando o PUT falha', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    const before = clone(api.state);
    api.writeFailure = true;
    await createLead(page, 'Lead que deve falhar', { waitForSaved: false });
    await page.getByText('Não foi possível salvar no banco.', { exact: true }).waitFor();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting === 'false');
    assert.deepEqual(durableState(await stateFrom(page)), before);
    assert.equal(api.version, beforeVersion);
    assert.equal(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).version, CONFIRMED_CACHE_KEY), beforeVersion);
  });

  await run('DBP-10 recarrega o estado canônico após conflito de versão', async page => {
    const api = apiByPage.get(page);
    api.version += 1;
    api.state.leads[0].name = 'Lead atualizado em outra sessão';
    await createLead(page, 'Lead em conflito');
    await page.getByText('Dados atualizados em outra sessão. A versão atual foi recarregada.', { exact: true }).waitFor();
    const reloaded = await stateFrom(page);
    assert.equal(reloaded.leads[0].name, 'Lead atualizado em outra sessão');
    assert.equal(reloaded.leads.some(lead => lead.name === 'Lead em conflito'), false);
  });

  await run('DBP-12 e DBP-13 listam e recuperam registro excluído com vínculos', async page => {
    const api = apiByPage.get(page);
    const initialVersion = api.version;
    await goTo(page, 'Leads');
    const row = page.locator('#page-leads tbody tr').filter({ hasText: 'Larissa Spinola' });
    page.once('dialog', dialog => dialog.accept());
    await row.getByTitle('Excluir').click();
    await stateFrom(page);
    assert.equal(api.version, initialVersion + 1);
    assert.equal(api.deleted.leads.some(lead => lead.id === 'L-1048' && lead.assistants.includes('u-camila')), true);

    await goTo(page, 'Visão geral');
    await page.getByRole('button', { name: 'Recuperar excluídos' }).click();
    const dialog = page.locator('#deletedRecordsDialog');
    await dialog.getByLabel('Módulo').selectOption('leads');
    await dialog.getByRole('button', { name: 'Recuperar L-1048' }).click();
    await stateFrom(page);
    assert.equal(api.version, initialVersion + 2);
    assert.equal((await stateFrom(page)).leads.some(lead => lead.id === 'L-1048' && lead.assistants.includes('u-camila')), true);
  });

  await run('DEMO-03 carrega massa fictícia para todos os módulos', async page => {
    const state = await stateFrom(page);
    assert.ok(state.leads.length >= 5, 'Leads fictícios ausentes');
    assert.ok(state.contacts.length >= 4, 'Contatos fictícios ausentes');
    assert.ok(state.companies.length >= 4, 'Empresas fictícias ausentes');
    assert.ok(state.deals.length >= 6, 'Negócios fictícios ausentes');
    assert.ok(state.notifications.length >= 3, 'Notificações fictícias ausentes');
  });

  await run('workspace normaliza estado legado sem perder alterações locais', async page => {
    const legacy = await stateFrom(page);
    legacy.leads[0].name = 'Lead legado preservado';
    delete legacy.ui;
    delete legacy.customFieldSchemas;
    delete legacy.moduleFieldSettings;
    legacy.users.forEach(user => { delete user.email; delete user.jobTitle; delete user.status; });
    legacy.leads.forEach(lead => { lead.createdAt = 'Hoje, 09:42'; delete lead.updatedAt; });
    legacy.contacts.forEach(contact => { delete contact.createdAt; delete contact.updatedAt; });
    legacy.companies.forEach(company => { delete company.createdAt; delete company.updatedAt; });
    legacy.deals.forEach(deal => {
      deal.updatedAt = 'Há 18 min';
      delete deal.createdAt;
      delete deal.stageChangedAt;
      delete deal.stageChangedById;
      delete deal.stageHistory;
      delete deal.wonAt;
    });
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: legacy });
    resetMockWorkspace(page);
    await reloadReady(page);

    const normalized = await stateFrom(page);
    assert.equal(normalized.leads[0].name, 'Lead legado preservado');
    assert.deepEqual(normalized.ui.viewModesByUser['u-admin'], { leads: 'list', deals: 'list' });
    assert.equal(normalized.ui.dashboardScopeByUser['u-admin'], 'all');
    assert.deepEqual(Object.keys(normalized.customFieldSchemas), ['leads', 'contacts', 'companies', 'deals']);
    assert.deepEqual(normalized.moduleFieldSettings.deals.hiddenStandardFields, []);
    assert.deepEqual(normalized.moduleFieldSettings.deals.hiddenCustomFieldKeys, []);
    assert.equal(normalized.users.every(user => user.email && user.jobTitle && user.status === 'Ativo'), true);
    for (const record of [...normalized.leads, ...normalized.contacts, ...normalized.companies]) {
      assert.equal(Number.isNaN(Date.parse(record.createdAt)), false, `${record.id} sem createdAt ISO`);
      assert.equal(Number.isNaN(Date.parse(record.updatedAt)), false, `${record.id} sem updatedAt ISO`);
    }
    for (const deal of normalized.deals) {
      assert.equal(Number.isNaN(Date.parse(deal.createdAt)), false, `${deal.id} sem createdAt ISO`);
      assert.equal(Number.isNaN(Date.parse(deal.updatedAt)), false, `${deal.id} sem updatedAt ISO`);
      assert.equal(Number.isNaN(Date.parse(deal.stageChangedAt)), false, `${deal.id} sem stageChangedAt ISO`);
      assert.equal(Array.isArray(deal.stageHistory), true, `${deal.id} sem histórico de etapa`);
    }
    assert.equal(Number.isNaN(Date.parse(normalized.deals.find(deal => deal.stage === 'Ganho').wonAt)), false);
  });

  await run('BCF-01 migra campos Bitrix legados sem exigir nova importação', async page => {
    const legacy = await stateFrom(page);
    legacy.contacts[0].bitrixId = 'LEGACY-1';
    legacy.contacts[0].bitrixEntity = 'contact';
    legacy.contacts[0].bitrixFields = [
      { name: 'ID', occurrence: 1, value: 'LEGACY-1' },
      { name: 'Nome', occurrence: 1, value: 'Ana' },
      { name: 'Sobrenome', occurrence: 1, value: 'Berclay' },
      { name: 'Cargo', occurrence: 1, value: 'Compradora' },
      { name: 'Cargo', occurrence: 2, value: 'Decisora' },
      { name: 'Observação', occurrence: 1, value: '<b>texto seguro</b>' },
      { name: 'Campo futuro', occurrence: 1, value: '' }
    ];
    delete legacy.contacts[0].customFields;
    delete legacy.contacts[0].visibleCustomFieldKeys;
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: legacy });
    resetMockWorkspace(page);
    await reloadReady(page);

    const migrated = (await stateFrom(page)).contacts.find(contact => contact.bitrixId === 'LEGACY-1');
    assert.deepEqual(migrated.customFields.map(field => [field.key, field.label, field.value]), [
      ['bitrix:cargo:2', 'Cargo (2)', 'Decisora'],
      ['bitrix:observacao:1', 'Observação', '<b>texto seguro</b>'],
      ['bitrix:campo%20futuro:1', 'Campo futuro', '']
    ]);
    assert.deepEqual(migrated.visibleCustomFieldKeys, ['bitrix:cargo:2', 'bitrix:observacao:1']);

    await goTo(page, 'Contatos');
    await page.getByRole('button', { name: 'Ana Berclay' }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.waitFor({ state: 'visible' });
    assert.deepEqual(await drawer.getByRole('tab').allTextContents(), ['Informações', 'Campos adicionais']);
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Observação').inputValue(), '<b>texto seguro</b>');
    assert.equal(await drawer.locator('#drawerCustomPanel b').count(), 0);
  });

  await run('DEMO-04 Administrador navega pelos sete destinos', async page => {
    const destinations = [
      ['Visão geral', 'Visão geral'], ['Leads', 'Leads'], ['Contatos', 'Contatos'],
      ['Empresas', 'Empresas'], ['Negócios', 'Negócios'], ['Notificações', 'Notificações'],
      ['Usuários e permissões', 'Usuários e permissões']
    ];
    assert.equal(await page.locator('.nav button:visible').count(), 7);
    for (const [button, heading] of destinations) {
      await goTo(page, button);
      assert.equal(await page.locator('#topTitle').innerText(), heading);
    }
  });

  await run('DEMO-05 busca e filtro atualizam a lista sem navegação', async page => {
    await goTo(page, 'Leads');
    const originalUrl = page.url();
    assert.equal(await page.locator('#page-leads tbody tr').count(), 5);
    await page.getByPlaceholder('Buscar em leads...').fill('Larissa');
    assert.equal(await page.locator('#page-leads tbody tr').count(), 1);
    assert.match(await page.locator('#page-leads tbody').innerText(), /Larissa Spinola/);
    assert.equal(page.url(), originalUrl);
    await page.getByPlaceholder('Buscar em leads...').fill('');
    await page.locator('#page-leads').getByLabel('Filtrar por etapa').selectOption('Lead convertido');
    assert.equal(await page.locator('#page-leads tbody tr').count(), 1);
  });

  await run('DEMO-06 CRUD altera lista e indicador de Leads', async page => {
    const initialCount = Number(await page.locator('#leadNavCount').innerText());
    await createLead(page, 'Lead CRUD Automático');
    assert.equal(Number(await page.locator('#leadNavCount').innerText()), initialCount + 1);

    let row = page.locator('#page-leads tbody tr').filter({ hasText: 'Lead CRUD Automático' });
    await row.getByRole('button', { name: 'Lead CRUD Automático' }).click();
    await page.locator('#entityDrawer').getByLabel('Nome completo *').fill('Lead CRUD Editado');
    await page.getByRole('button', { name: 'Salvar registro' }).click();
    assert.equal(await page.locator('#page-leads .entity-link').filter({ hasText: 'Lead CRUD Editado' }).count(), 1);
    assert.doesNotMatch(await page.locator('#entityDrawer').getAttribute('class'), /open/);

    await assertCanonicalRehydration(page);
    await goTo(page, 'Leads');

    page.once('dialog', dialog => dialog.accept());
    row = page.locator('#page-leads tbody tr').filter({ hasText: 'Lead CRUD Editado' });
    await row.getByTitle('Excluir').click();
    assert.equal(await page.getByText('Lead CRUD Editado', { exact: true }).count(), 0);
    assert.equal(Number(await page.locator('#leadNavCount').innerText()), initialCount);
    await assertCanonicalRehydration(page);
  });

  await run('CRREL-01 e CRREL-02 criam e persistem uma Empresa pela listagem', async page => {
    await goTo(page, 'Empresas');
    await page.getByRole('button', { name: /Novo Empresa/ }).click();
    const dialog = page.locator('#entityDialog');
    assert.equal(await dialog.getByRole('heading').innerText(), 'Novo Empresa');
    await dialog.getByLabel('Razão / nome da Empresa *').fill('Empresa Relacionada');
    await dialog.getByLabel('Cidade / UF').fill('Ribeirão Preto / SP');
    await dialog.getByLabel('Segmento').fill('Tecnologia');
    await dialog.getByLabel('Telefone').fill('(16) 3000-4000');
    await dialog.getByLabel('Responsável *').selectOption('u-paula');
    await dialog.getByRole('button', { name: 'Salvar registro' }).click();

    let company = (await stateFrom(page)).companies.find(item => item.name === 'Empresa Relacionada');
    assert.match(company.id, /^E-\d+$/);
    assert.deepEqual({ city: company.city, segment: company.segment, phone: company.phone, ownerId: company.ownerId }, {
      city: 'Ribeirão Preto / SP', segment: 'Tecnologia', phone: '(16) 3000-4000', ownerId: 'u-paula'
    });
    assert.equal(await page.locator('#page-companies tbody tr').filter({ hasText: 'Empresa Relacionada' }).count(), 1);

    await assertCanonicalRehydration(page);
    await goTo(page, 'Empresas');
    company = (await stateFrom(page)).companies.find(item => item.name === 'Empresa Relacionada');
    assert.equal(company.name, 'Empresa Relacionada');
    assert.equal(await page.locator('#page-companies tbody tr').filter({ hasText: 'Empresa Relacionada' }).count(), 1);
  });

  await run('CRREL-03 e CRREL-04 mostram Empresa e Contato nos Negócios em Lista e Kanban', async page => {
    await goTo(page, 'Negócios');
    const linkedRow = page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' });
    assert.match(await linkedRow.innerText(), /Empresa\s+Arkos Estética/);
    assert.match(await linkedRow.innerText(), /São Paulo \/ SP · \(11\) 3456-7788/);
    assert.match(await linkedRow.innerText(), /Contato\s+Ana Berclay/);
    assert.match(await linkedRow.innerText(), /ana@arkos\.com\.br · \(11\) 3456-7788/);

    const missingRow = page.locator('#page-deals tbody tr').filter({ hasText: 'Licenças Biocare' });
    assert.match(await missingRow.innerText(), /Empresa\s+Biocare Farmacêutica\s+Cadastro não localizado/);
    assert.match(await missingRow.innerText(), /Contato\s+João Vilela\s+Cadastro não localizado/);

    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    const linkedCard = page.locator('#page-deals .kanban-card[data-id="N-16312"]');
    assert.match(await linkedCard.innerText(), /Empresa\s+Arkos Estética/);
    assert.match(await linkedCard.innerText(), /Contato\s+Ana Berclay/);
  });

  await run('CRREL-05 a CRREL-08 mostram vínculos de Contatos e Empresas e estados vazios', async page => {
    await goTo(page, 'Contatos');
    let contactRow = page.locator('#page-contacts tbody tr').filter({ hasText: 'Ana Berclay' });
    assert.match(await contactRow.innerText(), /Arkos Estética/);

    await page.getByRole('button', { name: /Novo Contato/ }).click();
    let dialog = page.locator('#entityDialog');
    await dialog.getByLabel('Nome completo *').fill('Contato Normalizado');
    await dialog.getByLabel('Empresa *').fill('  arkos estética  ');
    await dialog.getByLabel('E-mail *').fill('normalizado@teste.invalid');
    await dialog.getByRole('button', { name: 'Salvar registro' }).click();

    await goTo(page, 'Empresas');
    let companyRow = page.locator('#page-companies tbody tr').filter({ hasText: 'Arkos Estética' });
    assert.match(await companyRow.innerText(), /2 contatos/);
    assert.match(await companyRow.innerText(), /Ana Berclay/);
    assert.match(await companyRow.innerText(), /Contato Normalizado/);

    await page.getByRole('button', { name: /Novo Empresa/ }).click();
    dialog = page.locator('#entityDialog');
    await dialog.getByLabel('Razão / nome da Empresa *').fill('Empresa Sem Contatos');
    await dialog.getByLabel('Responsável *').selectOption('u-vitor');
    await dialog.getByRole('button', { name: 'Salvar registro' }).click();
    companyRow = page.locator('#page-companies tbody tr').filter({ hasText: 'Empresa Sem Contatos' });
    assert.match(await companyRow.innerText(), /0 contatos/);
    assert.match(await companyRow.innerText(), /Nenhum contato/);

    const workspace = await stateFrom(page);
    workspace.deals.unshift({
      ...workspace.deals[0],
      id: 'N-EMPTY',
      title: 'Negócio Sem Empresa e Contato',
      company: '',
      contact: '',
      quotes: []
    });
    await setMockWorkspace(page, workspace);
    await reloadReady(page);
    await goTo(page, 'Negócios');
    const emptyRelationshipRow = page.locator('#page-deals tbody tr').filter({ hasText: 'Negócio Sem Empresa e Contato' });
    assert.match(await emptyRelationshipRow.innerText(), /Empresa\s+Não informado/);
    assert.match(await emptyRelationshipRow.innerText(), /Contato\s+Não informado/);
  });

  await run('DRAWER-01 abre os quatro cadastros pelo nome sem lápis', async page => {
    const records = [
      ['Leads', 'Larissa Spinola', 'Editar Lead', 'Nome completo *', 'Larissa Spinola', 'L-1048'],
      ['Contatos', 'Ana Berclay', 'Editar Contato', 'Nome completo *', 'Ana Berclay', 'C-2281'],
      ['Empresas', 'Arkos Estética', 'Editar Empresa', 'Razão / nome da Empresa *', 'Arkos Estética', 'E-802'],
      ['Negócios', 'Implantação Arkos Estética', 'Editar Negócio', 'Título do Negócio *', 'Implantação Arkos Estética', 'N-16312']
    ];
    const before = await stateFrom(page);
    for (const [view, name, title, fieldLabel, fieldValue, id] of records) {
      await goTo(page, view);
      await page.locator(`#page-${{ Leads: 'leads', Contatos: 'contacts', Empresas: 'companies', Negócios: 'deals' }[view]}`).getByRole('button', { name, exact: true }).click();
      const drawer = page.locator('#entityDrawer');
      assert.match(await drawer.getAttribute('class'), /open/);
      assert.equal(await drawer.getByRole('heading').innerText(), title);
      assert.equal(await drawer.getByLabel(fieldLabel).inputValue(), fieldValue);
      if (view === 'Contatos') {
        assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).count(), 0);
      }
      assert.match(await page.locator('#entityDrawerSubtitle').innerText(), new RegExp(id));
      await page.waitForTimeout(250);
      const box = await drawer.boundingBox();
      const viewportWidth = await page.evaluate(() => window.innerWidth);
      assert.ok(box.x > viewportWidth / 2 && Math.abs(box.x + box.width - viewportWidth) <= 20);
      assert.equal(await page.locator(`#page-${{ Leads: 'leads', Contatos: 'contacts', Empresas: 'companies', Negócios: 'deals' }[view]}`).isVisible(), true);
      assert.equal(await page.getByTitle('Editar').count(), 0);
      await drawer.getByRole('button', { name: 'Cancelar' }).click();
      assert.doesNotMatch(await drawer.getAttribute('class'), /open/);
    }
    assert.deepEqual(await stateFrom(page), before);
  });

  await run('DRAWER-04 e DRAWER-05 protegem cancelamento e alterações pendentes', async page => {
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: 'Larissa Spinola', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByLabel('Nome completo *').fill('Nome ainda não salvo');

    page.once('dialog', dialog => dialog.dismiss());
    await drawer.getByRole('button', { name: 'Cancelar' }).click();
    assert.match(await drawer.getAttribute('class'), /open/);

    page.once('dialog', dialog => dialog.accept());
    await drawer.getByRole('button', { name: 'Cancelar' }).click();
    assert.doesNotMatch(await drawer.getAttribute('class'), /open/);
    assert.equal((await stateFrom(page)).leads.find(lead => lead.id === 'L-1048').name, 'Larissa Spinola');
  });

  await run('DRAWER-06 usa a tela inteira em 390x844', async page => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: 'Larissa Spinola', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('button', { name: 'Salvar registro' }).waitFor({ state: 'visible' });
    const box = await drawer.boundingBox();
    assert.equal(Math.round(box.width), 390);
    assert.equal(await drawer.getByRole('button', { name: 'Salvar registro' }).isVisible(), true);
    assert.equal(await drawer.getByRole('button', { name: 'Cancelar' }).isVisible(), true);
  });

  await run('FILTER-03 busca livre alcança identificador e responsável', async page => {
    await goTo(page, 'Leads');
    const search = page.getByPlaceholder('Buscar em leads...');
    await search.fill('Paula Pincetta');
    assert.equal(await page.locator('#page-leads tbody tr').count(), 2);
    assert.match(await page.locator('#page-leads tbody').innerText(), /Larissa Spinola/);
    assert.match(await page.locator('#page-leads tbody').innerText(), /João Vilela/);
    await search.fill('L-1047');
    assert.equal(await page.locator('#page-leads tbody tr').count(), 1);
    assert.match(await page.locator('#page-leads tbody').innerText(), /Rayana Gomes Ramos/);
    await goTo(page, 'Negócios');
    await page.getByPlaceholder('Buscar em negócios...').fill('Ana Berclay');
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Implantação Arkos Estética/);
  });

  await run('FILTER-01 e FILTER-02 adicionam e removem campos sem alterar registros', async page => {
    await goTo(page, 'Leads');
    const before = (await stateFrom(page)).leads;
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    assert.equal(await panel.getByText('Filtros salvos').isVisible(), true);
    assert.equal(await panel.getByRole('button', { name: 'Adicionar campo' }).isVisible(), true);
    assert.deepEqual(await panel.locator('[data-filter-field]').evaluateAll(rows => rows.map(row => row.dataset.filterField)), ['name', 'stage', 'responsibleId', 'createdAt']);
    await panel.locator('#addFilterField').selectOption('phone');
    await panel.getByRole('button', { name: 'Adicionar campo' }).click();
    assert.equal(await panel.locator('[data-filter-field="phone"]').count(), 1);
    await panel.locator('[data-filter-field="phone"]').getByRole('button', { name: 'Remover campo' }).click();
    assert.equal(await panel.locator('[data-filter-field="phone"]').count(), 0);
    assert.deepEqual((await stateFrom(page)).leads, before);
  });

  await run('FILTER-04, FILTER-06 e FILTER-08 combinam responsável período e etapa por E', async page => {
    await goTo(page, 'Leads');
    const originalUrl = page.url();
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"]').selectOption(['u-paula']);
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Em contato']);
    const dateRow = panel.locator('[data-filter-field="createdAt"]');
    await dateRow.locator('select[name="filter-operator"]').selectOption('between');
    await dateRow.locator('input[name="filter-value"]').fill('2026-08-16');
    await dateRow.locator('input[name="filter-value-to"]').fill('2026-08-18');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.locator('#page-leads tbody tr').count(), 1);
    assert.match(await page.locator('#page-leads tbody').innerText(), /Larissa Spinola/);
    assert.doesNotMatch(await page.locator('#page-leads tbody').innerText(), /João Vilela/);
    assert.match(await page.locator('#page-leads .table-footer').innerText(), /1 registro\(s\) visível\(is\)/);
    assert.equal(page.url(), originalUrl);

    await page.getByRole('button', { name: /Filtros/ }).click();
    await panel.locator('[data-filter-field="name"] input[name="filter-value"]').fill('registro impossível');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.getByText('Nenhum Lead encontrado').isVisible(), true);
    assert.match(await page.locator('#page-leads .table-footer').innerText(), /0 registro\(s\) visível\(is\)/);
    await page.getByRole('button', { name: /Filtros/ }).click();
    assert.equal(await panel.locator('[data-filter-field="name"] input[name="filter-value"]').inputValue(), 'registro impossível');
    assert.equal(await panel.locator('[data-filter-field="name"] input[name="filter-value"]').isEditable(), true);
  });

  await run('FILTER-05 e FILTER-07 aplicam OU no campo e operadores monetários', async page => {
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.locator('#addFilterField').selectOption('amount');
    await panel.getByRole('button', { name: 'Adicionar campo' }).click();
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Orçamentos enviados', 'Negociação Revisão']);
    const amountRow = panel.locator('[data-filter-field="amount"]');
    await amountRow.locator('select[name="filter-operator"]').selectOption('gt');
    await amountRow.locator('input[name="filter-value"]').fill('30000');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.locator('#page-deals tbody tr').count(), 2);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Implantação Arkos Estética/);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Renovação ALS Pharma/);
  });

  await run('FILTER-06 oferece e executa todos os operadores de data', async page => {
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    const row = panel.locator('[data-filter-field="createdAt"]');
    assert.deepEqual(await row.locator('select[name="filter-operator"] option').evaluateAll(options => options.map(option => option.value)), ['any', 'exact', 'before', 'after', 'between']);
    const cases = [
      ['exact', '2026-08-17', 1],
      ['before', '2026-08-16', 3],
      ['after', '2026-08-16', 1],
      ['any', '', 5]
    ];
    for (const [operator, value, count] of cases) {
      await row.locator('select[name="filter-operator"]').selectOption(operator);
      if (value) await row.locator('input[name="filter-value"]').fill(value);
      await panel.getByRole('button', { name: 'Pesquisar' }).click();
      assert.equal(await page.locator('#page-leads tbody tr').count(), count, `operador de data ${operator}`);
      await page.getByRole('button', { name: /Filtros/ }).click();
    }
  });

  await run('FILTER-07 oferece e executa todos os operadores monetários', async page => {
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.locator('#addFilterField').selectOption('amount');
    await panel.getByRole('button', { name: 'Adicionar campo' }).click();
    const row = panel.locator('[data-filter-field="amount"]');
    assert.deepEqual(await row.locator('select[name="filter-operator"] option').evaluateAll(options => options.map(option => option.value)), ['exact', 'gt', 'lt', 'between']);
    const cases = [
      ['exact', '48500', '', 1],
      ['gt', '50000', '', 1],
      ['lt', '20000', '', 2],
      ['between', '20000', '40000', 2]
    ];
    for (const [operator, value, valueTo, count] of cases) {
      await row.locator('select[name="filter-operator"]').selectOption(operator);
      await row.locator('input[name="filter-value"]').fill(value);
      if (valueTo) await row.locator('input[name="filter-value-to"]').fill(valueTo);
      await panel.getByRole('button', { name: 'Pesquisar' }).click();
      assert.equal(await page.locator('#page-deals tbody tr').count(), count, `operador monetário ${operator}`);
      await page.getByRole('button', { name: /Filtros/ }).click();
    }
    await row.locator('select[name="filter-operator"]').selectOption('between');
    await row.locator('input[name="filter-value"]').fill('40000');
    await row.locator('input[name="filter-value-to"]').fill('20000');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.getByText('Revise o intervalo: o valor inicial deve ser menor que o final.').isVisible(), true);
    assert.equal(await panel.isVisible(), true);
  });

  await run('filtros rejeitam nome vazio e intervalo invertido e atualizam preset homônimo', async page => {
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    page.once('dialog', dialog => dialog.accept(''));
    await panel.getByRole('button', { name: 'Salvar filtro' }).click();
    assert.equal(await page.getByText('Informe um nome para salvar o filtro.').isVisible(), true);
    assert.equal((await stateFrom(page)).ui.savedFilters.length, 0);

    const date = panel.locator('[data-filter-field="createdAt"]');
    await date.locator('select[name="filter-operator"]').selectOption('between');
    await date.locator('input[name="filter-value"]').fill('2026-08-18');
    await date.locator('input[name="filter-value-to"]').fill('2026-08-16');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.getByText('Revise o intervalo: o valor inicial deve ser menor que o final.').isVisible(), true);
    assert.equal(await panel.isVisible(), true);

    await panel.getByRole('button', { name: 'Redefinir' }).click();
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Lead convertido']);
    page.once('dialog', dialog => dialog.accept('Meu filtro'));
    await panel.getByRole('button', { name: 'Salvar filtro' }).click();
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Em contato']);
    page.once('dialog', dialog => dialog.accept('Meu filtro'));
    await panel.getByRole('button', { name: 'Salvar filtro' }).click();
    const saved = (await stateFrom(page)).ui.savedFilters;
    assert.equal(saved.length, 1);
    assert.deepEqual(saved[0].filter.criteria.stage.value, ['Em contato']);
    assert.equal(Number.isNaN(Date.parse(saved[0].updatedAt)), false);
  });

  await run('FILTER-09, FILTER-10 e FILTER-11 persistem carregam excluem e redefinem presets', async page => {
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Lead convertido']);
    page.once('dialog', dialog => dialog.accept('Leads convertidos'));
    await panel.getByRole('button', { name: 'Salvar filtro' }).click();
    let state = await stateFrom(page);
    assert.equal(state.ui.savedFilters.length, 1);
    assert.equal(state.ui.savedFilters[0].name, 'Leads convertidos');
    assert.equal(state.ui.savedFilters[0].userId, 'u-admin');
    assert.equal(state.ui.savedFilters[0].scope, 'leads');
    assert.deepEqual(state.ui.savedFilters[0].filter.criteria.stage.value, ['Lead convertido']);
    assert.ok(state.ui.savedFilters[0].filter.visibleFields.includes('stage'));
    assert.equal(Number.isNaN(Date.parse(state.ui.savedFilters[0].updatedAt)), false);

    await assertCanonicalRehydration(page);
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: /Filtros/ }).click();

    await panel.getByRole('button', { name: 'Redefinir' }).click();
    assert.deepEqual(await panel.locator('[data-filter-field]').evaluateAll(rows => rows.map(row => row.dataset.filterField)), ['name', 'stage', 'responsibleId', 'createdAt']);
    assert.deepEqual(await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').evaluate(select => [...select.selectedOptions].map(option => option.value)), []);
    assert.equal(await panel.locator('[data-filter-field="name"] input[name="filter-value"]').inputValue(), '');
    await panel.getByRole('button', { name: 'Leads convertidos', exact: true }).click();
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.locator('#page-leads tbody tr').count(), 1);
    assert.match(await page.locator('#page-leads tbody').innerText(), /Marina Ferreira/);

    await reloadReady(page);
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: /Filtros/ }).click();
    assert.equal(await panel.getByRole('button', { name: 'Leads convertidos', exact: true }).isVisible(), true);
    await panel.getByRole('button', { name: 'Excluir Leads convertidos' }).click();
    state = await stateFrom(page);
    assert.equal(state.ui.savedFilters.length, 0);
  });

  await run('filtro salvo incompatível é ajustado com aviso', async page => {
    const state = await stateFrom(page);
    state.ui.savedFilters.push({
      id: 'SF-invalid', name: 'Filtro antigo', userId: 'u-admin', scope: 'leads',
      filter: { query: '', visibleFields: ['unknownField'], criteria: { unknownField: { operator: 'contains', value: 'x' } } }
    });
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: state });
    await setMockWorkspace(page, state);
    await reloadReady(page);
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.getByRole('button', { name: 'Filtro antigo', exact: true }).click();
    assert.equal(await page.getByText('Filtro ajustado: campos incompatíveis foram removidos.').isVisible(), true);
    assert.equal(await panel.locator('[data-filter-field="unknownField"]').count(), 0);
    assert.ok((await stateFrom(page)).leads.length >= 5);
  });

  await run('FILTER-12 aplica autorização antes do filtro sem apagar o registro', async page => {
    await selectProfile(page, 'u-vitor');
    await goTo(page, 'Negócios');
    await page.getByPlaceholder('Buscar em negócios...').fill('Arkos Estética');
    assert.equal(await page.locator('#page-deals tbody tr').count(), 0);
    assert.match(await page.locator('#page-deals .table-footer').innerText(), /0 registro\(s\) visível\(is\)/);
    const state = await stateFrom(page);
    assert.ok(state.deals.some(deal => deal.id === 'N-16312' && deal.responsibleId === 'u-paula'));
    assert.equal(state.ui.filtersByUser['u-vitor'].deals.query, 'Arkos Estética');
  });

  await run('BOARD-01 e BOARD-09 alternam Lista/Kanban preservando filtro e preferência', async page => {
    await goTo(page, 'Negócios');
    await page.getByPlaceholder('Buscar em negócios...').fill('Arkos');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.equal(await page.locator('#page-deals .kanban-card').count(), 1);
    assert.match(await page.locator('#page-deals .kanban-card').innerText(), /Implantação Arkos Estética/);
    await reloadReady(page);
    await goTo(page, 'Negócios');
    assert.equal(await page.locator('#page-deals .kanban-board').isVisible(), true);
    assert.equal((await stateFrom(page)).ui.viewModesByUser['u-admin'].deals, 'kanban');
    assert.equal(await page.locator('#page-deals .kanban-card').count(), 1);
    await assertCanonicalRehydration(page);
  });

  await run('BOARD-02 representa a etapa em barra segmentada na Lista', async page => {
    await goTo(page, 'Negócios');
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' });
    const progress = row.locator('.stage-progress');
    assert.equal(await progress.locator('[data-stage-segment]').count(), 9);
    assert.match(await progress.innerText(), /Orçamentos enviados/);
    assert.equal(await progress.locator('[data-stage-segment].current').count(), 1);
  });

  await run('hover na etapa de Negócio destaca o segmento e mostra seu nome', async page => {
    await goTo(page, 'Negócios');
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' });
    const segment = row.locator('[data-stage-segment="Pedido aprovado Consultar"]');
    assert.equal(await segment.getAttribute('data-stage-tooltip'), 'Pedido aprovado Consultar');
    await segment.hover();
    const visual = await segment.evaluate(element => ({
      background: getComputedStyle(element).backgroundColor,
      tooltip: getComputedStyle(element, '::after').content.replace(/^['"]|['"]$/g, ''),
      opacity: getComputedStyle(element, '::after').opacity
    }));
    assert.deepEqual(visual, { background: 'rgb(52, 64, 84)', tooltip: 'Pedido aprovado Consultar', opacity: '1' });
    assert.equal((await stateFrom(page)).deals.find(deal => deal.id === 'N-16312').stage, 'Orçamentos enviados');
  });

  await run('BOARD-03 agrupa os registros e mostra contagens no Kanban', async page => {
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.equal(await page.locator('#page-leads .kanban-column').count(), 3);
    assert.equal(await page.locator('#page-leads .kanban-card').count(), 5);
    assert.deepEqual(await page.locator('#page-leads .kanban-column-head > span:first-child').allTextContents(), LEAD_STAGES);
    assert.deepEqual(await page.locator('#page-leads .kanban-count').allTextContents(), ['3', '1', '1']);
    const contactColumn = page.locator('[data-kanban-stage="Em contato"]');
    assert.match(await contactColumn.locator('.kanban-column-head').innerText(), /3/);
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.deepEqual(await page.locator('#page-deals .kanban-column-head > span:first-child').allTextContents(), DEAL_STAGES);
    assert.deepEqual(await page.locator('#page-deals .kanban-count').allTextContents(), ['1', '0', '1', '1', '1', '1', '1', '0', '0']);
  });

  await run('BOARD-04 e BOARD-05 mudam etapa comum e desfazem atomicamente', async page => {
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    const mover = page.getByLabel('Mover Implantação Arkos Estética');
    await mover.selectOption('Negociação Revisão');
    let state = await stateFrom(page);
    const changed = state.deals.find(deal => deal.id === 'N-16312');
    assert.equal(changed.stage, 'Negociação Revisão');
    assert.deepEqual(Object.keys(changed.stageHistory.at(-1)).sort(), ['at', 'byId', 'from', 'to']);
    assert.equal(changed.stageHistory.at(-1).from, 'Orçamentos enviados');
    assert.equal(changed.stageHistory.at(-1).to, 'Negociação Revisão');
    assert.equal(changed.stageHistory.at(-1).byId, 'u-admin');
    assert.equal(Number.isNaN(Date.parse(changed.stageHistory.at(-1).at)), false);
    await page.getByRole('button', { name: 'Desfazer' }).click();
    state = await stateFrom(page);
    assert.equal(state.deals.find(deal => deal.id === 'N-16312').stage, 'Orçamentos enviados');
    await assertCanonicalRehydration(page);
  });

  await run('BOARD-06 protege Faturando e o Desfazer restaura responsável', async page => {
    await goTo(page, 'Negócios');
    const notificationsBefore = (await stateFrom(page)).notifications;
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Open Analítica' });
    const target = row.locator('[data-stage-segment="Faturando"]');
    page.once('dialog', dialog => dialog.dismiss());
    await target.click();
    let state = await stateFrom(page);
    assert.equal(state.deals.find(deal => deal.id === 'N-16309').stage, 'Em Contato');
    page.once('dialog', dialog => dialog.accept());
    await target.click();
    state = await stateFrom(page);
    assert.equal(state.deals.find(deal => deal.id === 'N-16309').responsibleId, 'u-billing');
    await page.getByRole('button', { name: 'Desfazer' }).click();
    state = await stateFrom(page);
    assert.equal(state.deals.find(deal => deal.id === 'N-16309').stage, 'Em Contato');
    assert.equal(state.deals.find(deal => deal.id === 'N-16309').responsibleId, 'u-paula');
    assert.deepEqual(state.notifications, notificationsBefore);
    assert.equal(await page.getByRole('button', { name: 'Desfazer' }).count(), 0);
  });

  await run('BOARD-06 protege todas as etapas de encerramento', async page => {
    await goTo(page, 'Negócios');
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Open Analítica' });
    for (const stage of ['Ganho', 'Orçamento Não Aprovado', 'Analisar falha']) {
      const target = row.locator(`[data-stage-segment="${stage}"]`);
      page.once('dialog', dialog => dialog.dismiss());
      await target.click();
      assert.equal((await stateFrom(page)).deals.find(deal => deal.id === 'N-16309').stage, 'Em Contato');
      page.once('dialog', dialog => dialog.accept());
      await target.click();
      const transitioned = (await stateFrom(page)).deals.find(deal => deal.id === 'N-16309');
      assert.equal(transitioned.stage, stage);
      if (stage === 'Ganho') assert.equal(Number.isNaN(Date.parse(transitioned.wonAt)), false);
      await page.getByRole('button', { name: 'Desfazer' }).click();
      assert.equal((await stateFrom(page)).deals.find(deal => deal.id === 'N-16309').stage, 'Em Contato');
    }
  });

  await run('BOARD-07, BOARD-08 e BOARD-10 protegem Lead e mantêm Kanban móvel operável', async page => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    await stateFrom(page);
    const board = page.locator('#page-leads .kanban-board');
    assert.ok((await board.evaluate(element => element.scrollWidth)) > (await board.evaluate(element => element.clientWidth)));
    const larissa = page.getByLabel('Mover Larissa Spinola');
    page.once('dialog', dialog => dialog.accept(''));
    await larissa.selectOption('Lead descartado');
    let state = await stateFrom(page);
    assert.equal(state.leads.find(lead => lead.id === 'L-1048').stage, 'Em contato');
    assert.equal(state.leads.find(lead => lead.id === 'L-1048').discardReason, undefined);
    page.once('dialog', dialog => dialog.accept('Sem aderência'));
    await larissa.selectOption('Lead descartado');
    state = await stateFrom(page);
    assert.equal(state.leads.find(lead => lead.id === 'L-1048').discardReason, 'Sem aderência');

    const rayana = page.getByLabel('Mover Rayana Gomes Ramos');
    page.once('dialog', dialog => dialog.accept());
    await rayana.selectOption('Lead convertido');
    state = await stateFrom(page);
    assert.equal(state.leads.find(lead => lead.id === 'L-1047').stage, 'Lead convertido');
    assert.ok(state.deals.some(deal => deal.contact === 'Rayana Gomes Ramos' && deal.stage === 'Em Contato'));
  });

  await run('BOARD-09 preserva filtro e Kanban também em Leads', async page => {
    await goTo(page, 'Leads');
    await page.getByPlaceholder('Buscar em leads...').fill('Larissa');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.equal(await page.locator('#page-leads .kanban-card').count(), 1);
    await reloadReady(page);
    await goTo(page, 'Leads');
    assert.equal(await page.locator('#page-leads .kanban-board').isVisible(), true);
    assert.equal(await page.locator('#page-leads .kanban-card').count(), 1);
    const state = await stateFrom(page);
    assert.equal(state.ui.viewModesByUser['u-admin'].leads, 'kanban');
    assert.equal(state.ui.filtersByUser['u-admin'].leads.query, 'Larissa');
  });

  await run('Visão geral calcula Conversão de Deals sobre os negócios visíveis', async page => {
    await goTo(page, 'Visão geral');
    const conversion = page.locator('#page-dashboard .stat').filter({ hasText: 'Conversão de Deals' });
    assert.equal(await conversion.locator('.stat-top span').first().innerText(), 'Conversão de Deals');
    assert.equal(await conversion.locator('strong').innerText(), '17%');
    assert.equal(await conversion.locator('small').innerText(), 'Negócios ganhos no conjunto visível');

    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.locator('[data-dashboard-filter-scope="deals"]').click();
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Ganho']);
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await conversion.locator('strong').innerText(), '100%');
  });

  await run('DASH-01, DASH-03 e DASH-04 oferecem escopos e campos aplicáveis', async page => {
    await goTo(page, 'Visão geral');
    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    const panel = page.locator('#filterDialog');
    const scopes = panel.locator('[data-dashboard-filter-scope]');
    assert.deepEqual(await scopes.allTextContents(), ['Todos', 'Leads', 'Negócios']);
    assert.deepEqual(await panel.locator('[data-filter-field]').evaluateAll(rows => rows.map(row => row.dataset.filterField)), ['responsibleId', 'team', 'createdAt']);
    await scopes.filter({ hasText: 'Leads' }).click();
    assert.deepEqual(await panel.locator('[data-filter-field]').evaluateAll(rows => rows.map(row => row.dataset.filterField)), ['name', 'stage', 'responsibleId', 'createdAt']);
    assert.match((await panel.locator('#addFilterField option').allTextContents()).join(' '), /Origem/);
    assert.match((await panel.locator('#addFilterField option').allTextContents()).join(' '), /Segmento/);
    await scopes.filter({ hasText: 'Negócios' }).click();
    assert.deepEqual(await panel.locator('[data-filter-field]').evaluateAll(rows => rows.map(row => row.dataset.filterField)), ['title', 'stage', 'responsibleId', 'createdAt']);
    const dealFields = (await panel.locator('#addFilterField option').allTextContents()).join(' ');
    assert.match(dealFields, /Empresa/);
    assert.match(dealFields, /Contato/);
    assert.match(dealFields, /Valor/);
    assert.match(dealFields, /Data da mudança de etapa/);
    assert.match(dealFields, /Data de ganho/);
  });

  await run('DASH-05 e DASH-06 recalculam indicadores Pipeline e movimentações pelo recorte', async page => {
    await goTo(page, 'Visão geral');
    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    const panel = page.locator('#filterDialog');
    await panel.locator('[data-dashboard-filter-scope="deals"]').click();
    await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"]').selectOption(['u-paula']);
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption(['Ganho']);
    const date = panel.locator('[data-filter-field="createdAt"]');
    await date.locator('select[name="filter-operator"]').selectOption('between');
    await date.locator('input[name="filter-value"]').fill('2026-08-12');
    await date.locator('input[name="filter-value-to"]').fill('2026-08-12');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    const dashboard = page.locator('#page-dashboard');
    assert.match(await dashboard.innerText(), /R\$\s*19\.400,00/);
    assert.match(await dashboard.locator('.pipeline').innerText(), /Ganho/);
    assert.match(await dashboard.locator('.activity-list').innerText(), /Licenças Biocare/);
    assert.doesNotMatch(await dashboard.locator('.activity-list').innerText(), /Larissa Spinola/);
    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    assert.match(await panel.locator('[data-dashboard-filter-scope="deals"]').getAttribute('class'), /active/);
    assert.deepEqual(await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"]').evaluate(select => [...select.selectedOptions].map(option => option.value)), ['u-paula']);
    assert.deepEqual(await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').evaluate(select => [...select.selectedOptions].map(option => option.value)), ['Ganho']);
    assert.equal(await panel.locator('[data-filter-field="createdAt"] input[name="filter-value"]').inputValue(), '2026-08-12');
    assert.equal(await panel.locator('[data-filter-field="createdAt"] input[name="filter-value-to"]').inputValue(), '2026-08-12');
  });

  await run('DASH-02, DASH-07 e DASH-08 limitam Gestor e redefinem o conjunto', async page => {
    await selectProfile(page, 'u-manager');
    await goTo(page, 'Visão geral');
    const initialOpenDeals = await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText();
    assert.equal(initialOpenDeals, '4');
    assert.equal(await page.locator('#page-dashboard .stat').first().locator('strong').innerText(), '3');
    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    const panel = page.locator('#filterDialog');
    const users = await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"] option').allTextContents();
    assert.deepEqual(users, ['Marcelo Martins', 'Paula Pincetta', 'Vitor Costa']);
    assert.equal(await panel.locator('[data-filter-field="team"] select[name="filter-value"]').isVisible(), true);
    assert.equal(await panel.locator('[data-filter-field="createdAt"] select[name="filter-operator"]').isVisible(), true);
    await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"]').selectOption(['u-paula']);
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.notEqual(await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText(), initialOpenDeals);
    await page.getByRole('button', { name: /Redefinir painel/ }).click();
    assert.equal(await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText(), initialOpenDeals);
    const state = await stateFrom(page);
    assert.equal(state.ui.dashboardScopeByUser['u-manager'], 'all');
  });

  await run('troca de perfil remove registro da Lista Kanban e indicadores sem apagá-lo', async page => {
    await goTo(page, 'Visão geral');
    assert.equal(await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText(), '5');
    await goTo(page, 'Negócios');
    await page.getByPlaceholder('Buscar em negócios...').fill('Conferência fiscal interna');
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.equal(await page.locator('#page-deals .kanban-card').count(), 1);

    await selectProfile(page, 'u-manager');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.doesNotMatch(await page.locator('#page-deals').innerText(), /Conferência fiscal interna/);
    await goTo(page, 'Visão geral');
    assert.equal(await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText(), '4');
    const state = await stateFrom(page);
    assert.ok(state.deals.some(deal => deal.id === 'N-16307' && deal.team === 'Faturamento'));
  });

  await run('DEMO-07 recarga preserva alterações no navegador', async page => {
    await createLead(page, 'Lead Persistente');
    await reloadReady(page);
    await goTo(page, 'Leads');
    assert.equal(await page.locator('#page-leads .entity-link').filter({ hasText: 'Lead Persistente' }).count(), 1);
    assert.ok((await stateFrom(page)).leads.some(lead => lead.name === 'Lead Persistente'));
  });

  await run('DEMO-08 restauração recompõe exatamente a massa inicial', async page => {
    const original = await stateFrom(page);
    await createLead(page, 'Lead a Restaurar');
    await goTo(page, 'Visão geral');
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: /Restaurar demo/ }).click();
    const restored = await stateFrom(page);
    assert.deepEqual(restored, original);
    assert.ok(!restored.leads.some(lead => lead.name === 'Lead a Restaurar'));
  });

  await run('DEMO-09 usa as três etapas exatas de Lead e exclui Nome', async page => {
    await goTo(page, 'Leads');
    const options = await page.locator('[data-stage-filter="leads"] option').allTextContents();
    assert.deepEqual(options.slice(1), LEAD_STAGES);
    assert.ok(!options.includes('Nome'));
  });

  await run('DEMO-10 conversão fecha Lead e cria Negócio com payload preservado', async page => {
    await goTo(page, 'Leads');
    const before = await stateFrom(page);
    const source = before.leads.find(lead => lead.name === 'Larissa Spinola');
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#page-leads tbody tr').filter({ hasText: 'Larissa Spinola' }).getByRole('button', { name: 'Converter' }).click();
    const after = await stateFrom(page);
    const converted = after.leads.find(lead => lead.id === source.id);
    const deal = after.deals.find(item => item.contact === source.name && item.company === source.company);
    assert.equal(converted.stage, 'Lead convertido');
    assert.equal(deal.stage, 'Em Contato');
    assert.equal(deal.responsibleId, source.responsibleId);
    assert.deepEqual(deal.assistants, source.assistants);
    assert.equal(deal.team, 'Vendas CMS');
    await assertCanonicalRehydration(page);
  });

  await run('DEMO-11 expõe exatamente as nove etapas de Negócio', async page => {
    await goTo(page, 'Negócios');
    const options = await page.locator('[data-stage-filter="deals"] option').allTextContents();
    assert.deepEqual(options.slice(1), DEAL_STAGES);
    assert.equal(options.length - 1, 9);
    assert.ok(!options.includes('Nome'));
  });

  await run('DEMO-12 Faturando altera equipe e cria notificações com payload', async page => {
    await goTo(page, 'Negócios');
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Open Analítica' });
    const idText = await row.innerText();
    const dealId = idText.match(/N-\d+/)[0];
    page.once('dialog', dialog => dialog.accept());
    await row.locator('[data-stage-segment="Faturando"]').click();
    const state = await stateFrom(page);
    const deal = state.deals.find(item => item.id === dealId);
    assert.equal(deal.stage, 'Faturando');
    assert.equal(deal.responsibleId, 'u-billing');
    assert.equal(deal.team, 'Faturamento');
    assert.ok(state.notifications.some(note => note.userId === 'u-billing' && note.text === 'Responsabilidade alterada automaticamente.' && note.detail.includes(dealId)));
    assert.ok(state.notifications.some(note => note.userId === 'u-admin' && note.text === 'Automação de Faturamento executada.' && note.detail.includes(dealId)));
    await assertCanonicalRehydration(page);
  });

  await run('DEMO-13 calcula orçamento e aceita PDF opcional', async page => {
    await goTo(page, 'Negócios');
    let row = page.locator('#page-deals tbody tr').filter({ hasText: 'Open Analítica' });
    await row.getByRole('button', { name: 'Orçamento', exact: true }).click();
    await page.getByLabel('Item / serviço *').fill('Serviço sem PDF');
    await page.getByLabel('Quantidade *').fill('2');
    await page.getByLabel('Valor unitário (R$) *').fill('1500');
    await page.getByLabel('Desconto (R$)').fill('250');
    assert.equal(await page.locator('#quoteTotal').innerText(), 'R$ 2.750,00');
    await page.getByRole('button', { name: 'Adicionar orçamento' }).click();
    let state = await stateFrom(page);
    let deal = state.deals.find(item => item.company === 'Open Analítica');
    assert.equal(deal.quotes.at(-1).total, 2750);
    assert.equal(deal.quotes.at(-1).pdf, '');

    row = page.locator('#page-deals tbody tr').filter({ hasText: 'Open Analítica' });
    await row.getByRole('button', { name: 'Orçamento', exact: true }).click();
    await page.getByLabel('Item / serviço *').fill('Serviço com PDF');
    await page.getByLabel('Quantidade *').fill('1');
    await page.getByLabel('Valor unitário (R$) *').fill('100');
    await page.getByLabel('Anexar PDF (opcional)').setInputFiles({ name: 'proposta-teste.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n') });
    await page.getByRole('button', { name: 'Adicionar orçamento' }).click();
    state = await stateFrom(page);
    deal = state.deals.find(item => item.company === 'Open Analítica');
    assert.equal(deal.quotes.at(-1).total, 100);
    assert.equal(deal.quotes.at(-1).pdf, 'proposta-teste.pdf');
    await assertCanonicalRehydration(page);
  });

  await run('QUOTE-01 gerencia orçamentos dentro do painel lateral do Negócio', async page => {
    await goTo(page, 'Negócios');
    assert.equal(await page.locator('#page-deals tbody [data-action="quote"]').count(), 6);
    await page.getByRole('button', { name: 'Kanban' }).click();
    assert.equal(await page.locator('#page-deals .kanban-card [data-action="quote"]').count(), 6);
    await page.getByRole('button', { name: 'Lista' }).click();

    await page.getByRole('button', { name: 'Implantação Arkos Estética' }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.waitFor({ state: 'visible' });
    assert.equal(await drawer.getByRole('tab', { name: 'Informações' }).getAttribute('aria-selected'), 'true');
    assert.equal(await drawer.getByRole('tab', { name: 'Orçamentos' }).isVisible(), true);
    await drawer.getByRole('tab', { name: 'Orçamentos' }).click();
    assert.equal(await drawer.getByRole('tab', { name: 'Orçamentos' }).getAttribute('aria-selected'), 'true');
    assert.equal(await drawer.locator('[data-drawer-quote]').count(), 1);
    const existing = drawer.locator('[data-drawer-quote]').first();
    assert.match(await existing.innerText(), /Implantação completa/);
    assert.match(await existing.innerText(), /R\$\s*48\.500,00/);
    assert.match(await existing.innerText(), /Enviado/);
    assert.match(await existing.innerText(), /proposta-arkos\.pdf/);

    await drawer.getByRole('button', { name: 'Novo orçamento' }).click();
    const quoteDialog = page.locator('#quoteDialog');
    assert.equal(await quoteDialog.locator('#quoteDealId').inputValue(), 'N-16312');
    await quoteDialog.getByLabel('Item / serviço *').fill('Orçamento pelo painel');
    await quoteDialog.getByLabel('Quantidade *').fill('2');
    await quoteDialog.getByLabel('Valor unitário (R$) *').fill('500');
    await quoteDialog.getByRole('button', { name: 'Adicionar orçamento' }).click();
    assert.match(await drawer.getAttribute('class'), /open/);
    assert.equal(await drawer.getByRole('tab', { name: 'Orçamentos' }).getAttribute('aria-selected'), 'true');
    assert.equal(await drawer.locator('[data-drawer-quote]').count(), 2);
    const added = drawer.locator('[data-drawer-quote]').last();
    assert.match(await added.innerText(), /Orçamento pelo painel/);
    assert.match(await added.innerText(), /R\$\s*1\.000,00/);
    assert.match(await added.innerText(), /Rascunho/);
    assert.match(await added.innerText(), /Sem anexo/);

    await drawer.getByRole('button', { name: 'Fechar painel' }).click();
    await page.getByRole('button', { name: 'Renovação ALS Pharma' }).click();
    await drawer.getByRole('tab', { name: 'Orçamentos' }).click();
    assert.match(await drawer.innerText(), /Nenhum orçamento cadastrado/);
    assert.equal(await drawer.getByRole('button', { name: 'Novo orçamento' }).isVisible(), true);
  });

  await run('BITRIX-01 importa uma amostra e preserva todos os campos por posição', async page => {
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();
    const dialog = page.locator('#bitrixImportDialog');
    assert.equal(await dialog.getByLabel('CSV de Negócios').isVisible(), true);
    assert.equal(await dialog.getByLabel('CSV de Contatos').isVisible(), true);
    assert.equal(await dialog.getByLabel('CSV de Empresas').isVisible(), true);
    assert.equal(await dialog.getByLabel('CSV de Leads').isVisible(), true);
    assert.equal(await dialog.getByRole('button', { name: 'Importar amostra' }).isDisabled(), true);

    const csv = '\ufeffID;Nome do negócio;Empresa;Contato;Fase;Total;Responsável;Observação;Cargo;Cargo;;;Campo vazio\n'
      + '9001;Negócio importado;Empresa Bitrix;Maria Silva;Negociação Revisão;1234.50;Paula Pincetta;"valor; preservado\ncom quebra";Comprador;Decisor;campo sem cabeçalho;segundo sem cabeçalho;\n'
      + '9002;Segundo Negócio;Empresa Dois;Contato Dois;Em Contato;99;Paula Pincetta;Importar;Comprador;Decisor;fim;fim dois;\n'
      + '9003;Terceiro Negócio;Empresa Três;Contato Três;Em Contato;199;Vitor Costa;Importar;Comprador;Decisor;fim;fim dois;\n'
      + '9004;Quarta linha ignorada;Empresa Quatro;Contato Quatro;Em Contato;299;Vitor Costa;Não importar;Comprador;Decisor;fim;fim dois;\n';
    await dialog.getByLabel('CSV de Negócios').setInputFiles({
      name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf8')
    });
    const contactCsv = '\ufeffID;Nome;Sobrenome;Empresa;Email de trabalho;Telefone de trabalho;Cargo\n'
      + '3001;Maria;Silva;Empresa Bitrix;maria@teste.invalid;11999990000;Diretora\n'
      + '3002;João;Souza;Empresa Dois;joao@teste.invalid;11999990001;Comprador\n'
      + '3003;Ana;Lima;Empresa Três;ana@teste.invalid;11999990002;Gerente\n';
    const companyCsv = '\ufeffID;Nome da Empresa;Cidade;UF.;Segmento de Mercado;Telefone de trabalho;Responsável\n'
      + '4001;Empresa Independente;Campinas;SP;Laboratórios;1933334444;Vitor Costa\n'
      + '4002;Empresa Dois;São Paulo;SP;Farmacêutico;1133334445;Paula Pincetta\n'
      + '4003;Empresa Três;Curitiba;PR;Diagnóstico;4133334446;Vitor Costa\n';
    const leadCsv = '\ufeffID;Nome completo;Nome da empresa;Email de trabalho;Telefone de trabalho;Segmento de Mercado;Origem do Lead;Etapa;Pessoa responsável\n5001;Lead Importado;Empresa Lead;lead@teste.invalid;1133335555;Diagnóstico;Site;Em contato;Vitor Costa\n';
    await dialog.getByLabel('CSV de Contatos').setInputFiles({ name: 'contact.csv', mimeType: 'text/csv', buffer: Buffer.from(contactCsv, 'utf8') });
    await dialog.getByLabel('CSV de Empresas').setInputFiles({ name: 'company.csv', mimeType: 'text/csv', buffer: Buffer.from(companyCsv, 'utf8') });
    await dialog.getByLabel('CSV de Leads').setInputFiles({ name: 'lead.csv', mimeType: 'text/csv', buffer: Buffer.from(leadCsv, 'utf8') });
    assert.equal(await dialog.getByRole('button', { name: 'Importar amostra' }).isEnabled(), true);
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 10 · Atualizados: 0 · Rejeitados: 0');

    const state = await stateFrom(page);
    const deal = state.deals.find(item => item.bitrixId === '9001');
    assert.ok(deal, 'Negócio importado não encontrado');
    assert.equal(state.deals.filter(item => item.bitrixId).length, 3);
    assert.deepEqual(state.deals.filter(item => item.bitrixId).map(item => item.bitrixId).sort(), ['9001', '9002', '9003']);
    assert.equal(state.deals.some(item => item.bitrixId === '9004'), false);
    assert.equal(deal.id, 'BX-DEAL-9001');
    assert.equal(deal.title, 'Negócio importado');
    assert.equal(deal.company, 'Empresa Bitrix');
    assert.equal(deal.contact, 'Maria Silva');
    assert.equal(deal.stage, 'Negociação Revisão');
    assert.equal(deal.amount, 1234.5);
    assert.equal(deal.responsibleId, 'u-paula');
    assert.equal(deal.bitrixFields.length, 13);
    assert.deepEqual(deal.bitrixFields.map(field => [field.name, field.occurrence, field.value]), [
      ['ID', 1, '9001'],
      ['Nome do negócio', 1, 'Negócio importado'],
      ['Empresa', 1, 'Empresa Bitrix'],
      ['Contato', 1, 'Maria Silva'],
      ['Fase', 1, 'Negociação Revisão'],
      ['Total', 1, '1234.50'],
      ['Responsável', 1, 'Paula Pincetta'],
      ['Observação', 1, 'valor; preservado\ncom quebra'],
      ['Cargo', 1, 'Comprador'],
      ['Cargo', 2, 'Decisor'],
      ['', 1, 'campo sem cabeçalho'],
      ['', 2, 'segundo sem cabeçalho'],
      ['Campo vazio', 1, '']
    ]);
    assert.deepEqual(deal.customFields.map(field => [field.key, field.label, field.value]), [
      ['bitrix:observacao:1', 'Observação', 'valor; preservado\ncom quebra'],
      ['bitrix:cargo:1', 'Cargo', 'Comprador'],
      ['bitrix:cargo:2', 'Cargo (2)', 'Decisor'],
      ['bitrix:__blank__:1', 'Campo sem nome', 'campo sem cabeçalho'],
      ['bitrix:__blank__:2', 'Campo sem nome (2)', 'segundo sem cabeçalho'],
      ['bitrix:campo%20vazio:1', 'Campo vazio', '']
    ]);
    assert.deepEqual(deal.visibleCustomFieldKeys, [
      'bitrix:observacao:1', 'bitrix:cargo:1', 'bitrix:cargo:2', 'bitrix:__blank__:1', 'bitrix:__blank__:2'
    ]);
    const contact = state.contacts.find(item => item.bitrixId === '3001');
    assert.equal(state.contacts.filter(item => item.bitrixId).length, 3);
    assert.deepEqual({ id: contact.id, name: contact.name, company: contact.company, email: contact.email, phone: contact.phone, role: contact.role, rawFields: contact.bitrixFields.length }, {
      id: 'BX-CONTACT-3001', name: 'Maria Silva', company: 'Empresa Bitrix', email: 'maria@teste.invalid', phone: '11999990000', role: 'Diretora', rawFields: 7
    });
    const company = state.companies.find(item => item.bitrixId === '4001');
    assert.equal(state.companies.filter(item => item.bitrixId).length, 3);
    assert.deepEqual({ id: company.id, name: company.name, city: company.city, segment: company.segment, phone: company.phone, ownerId: company.ownerId, rawFields: company.bitrixFields.length }, {
      id: 'BX-COMPANY-4001', name: 'Empresa Independente', city: 'Campinas / SP', segment: 'Laboratórios', phone: '1933334444', ownerId: 'u-vitor', rawFields: 7
    });
    const lead = state.leads.find(item => item.bitrixId === '5001');
    assert.deepEqual({ id: lead.id, name: lead.name, company: lead.company, email: lead.email, phone: lead.phone, segment: lead.segment, source: lead.source, stage: lead.stage, responsibleId: lead.responsibleId, rawFields: lead.bitrixFields.length }, {
      id: 'BX-LEAD-5001', name: 'Lead Importado', company: 'Empresa Lead', email: 'lead@teste.invalid', phone: '1133335555', segment: 'Diagnóstico', source: 'Site', stage: 'Em contato', responsibleId: 'u-vitor', rawFields: 9
    });

    await dialog.getByRole('button', { name: 'Fechar', exact: true }).click();
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Negócio importado' }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.waitFor({ state: 'visible' });
    assert.doesNotMatch(await drawer.innerText(), /Campos do Bitrix/);
    assert.deepEqual(await drawer.getByRole('tab').allTextContents(), ['Informações', 'Campos adicionais', 'Orçamentos']);
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.locator('[data-custom-field]').count(), 5);
    assert.equal(await drawer.getByLabel('Observação').inputValue(), 'valor; preservado\ncom quebra');
    assert.equal(await drawer.getByLabel('Cargo', { exact: true }).inputValue(), 'Comprador');
    assert.equal(await drawer.getByLabel('Cargo (2)').inputValue(), 'Decisor');
    assert.equal(await drawer.getByLabel('Campo sem nome', { exact: true }).inputValue(), 'campo sem cabeçalho');
    assert.equal(await drawer.getByLabel('Campo sem nome (2)').inputValue(), 'segundo sem cabeçalho');
    assert.equal(await drawer.getByLabel('Campo vazio').count(), 0);

    await drawer.getByLabel('Campo adicional para adicionar').selectOption({ label: 'Campo vazio' });
    await drawer.getByRole('button', { name: 'Adicionar campo' }).click();
    assert.equal(await drawer.getByLabel('Campo vazio').inputValue(), '');
    await drawer.getByLabel('Cargo (2)').fill('Decisora final');
    await drawer.getByRole('button', { name: 'Salvar registro' }).click();

    await page.getByRole('button', { name: 'Negócio importado' }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Cargo (2)').inputValue(), 'Decisora final');
    assert.equal(await drawer.getByLabel('Campo vazio').inputValue(), '');
    const edited = (await stateFrom(page)).deals.find(item => item.bitrixId === '9001');
    assert.equal(edited.customFields.find(field => field.label === 'Cargo (2)').value, 'Decisora final');
    assert.equal(edited.customFields.find(field => field.label === 'Campo vazio').value, '');
    assert.equal(edited.visibleCustomFieldKeys.includes('bitrix:campo%20vazio:1'), true);
    await assertCanonicalRehydration(page);
  });

  await run('BITRIX-02 reimporta pelo ID sem criar duplicata', async page => {
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();
    const dialog = page.locator('#bitrixImportDialog');
    const input = dialog.getByLabel('CSV de Negócios');
    const first = '\ufeffID;Nome do negócio;Empresa;Fase;Total;Observação;Campo futuro\n'
      + '9101;Primeiro;Empresa Teste;Em Contato;10;Original um;\n'
      + '9102;Segundo;Empresa Teste;Em Contato;20;Original dois;\n'
      + '9103;Terceiro;Empresa Teste;Em Contato;30;Original três;\n';
    await input.setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(first, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 3 · Atualizados: 0 · Rejeitados: 0');

    await dialog.getByRole('button', { name: 'Fechar' }).click();
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Primeiro', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    await drawer.getByLabel('Campo adicional para adicionar').selectOption({ label: 'Campo futuro' });
    await drawer.getByRole('button', { name: 'Adicionar campo' }).click();
    await drawer.getByRole('button', { name: 'Salvar registro' }).click();
    await goTo(page, 'Visão geral');
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();

    await input.setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(first, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await page.waitForFunction(() => document.getElementById('bitrixImportSummary')?.textContent.includes('Atualizados: 3'));
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 0 · Atualizados: 3 · Rejeitados: 0');

    const state = await stateFrom(page);
    assert.deepEqual(state.deals.filter(item => item.bitrixId).map(item => item.bitrixId).sort(), ['9101', '9102', '9103']);
    assert.equal(state.deals.filter(item => ['9101', '9102', '9103'].includes(item.bitrixId)).length, 3);

    const changed = '\ufeffID;Nome do negócio;Empresa;Fase;Total;Observação;Campo futuro\n'
      + '9101;Primeiro atualizado;Empresa Teste;Em Contato;11;Atualizada um;\n'
      + '9102;Segundo atualizado;Empresa Teste;Em Contato;22;Atualizada dois;\n'
      + '9103;Terceiro atualizado;Empresa Teste;Em Contato;33;Atualizada três;\n';
    await input.setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(changed, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await page.waitForFunction(() => {
      const current = JSON.parse(localStorage.getItem('smart-crm-demo-v1'));
      return current.deals.find(item => item.bitrixId === '9103')?.title === 'Terceiro atualizado';
    });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 0 · Atualizados: 3 · Rejeitados: 0');
    const updated = (await stateFrom(page)).deals.filter(item => ['9101', '9102', '9103'].includes(item.bitrixId)).sort((a, b) => a.bitrixId.localeCompare(b.bitrixId));
    assert.deepEqual(updated.map(item => [item.bitrixId, item.title, item.amount, item.customFields.find(field => field.label === 'Observação').value]), [
      ['9101', 'Primeiro atualizado', 11, 'Atualizada um'],
      ['9102', 'Segundo atualizado', 22, 'Atualizada dois'],
      ['9103', 'Terceiro atualizado', 33, 'Atualizada três']
    ]);
    assert.equal(updated.length, 3);
    assert.equal(updated[0].visibleCustomFieldKeys.includes('bitrix:campo%20futuro:1'), true);
  });

  await run('BCF-03 pesquisa e filtra campos adicionais em conjunto com campos padrão', async page => {
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();
    const dialog = page.locator('#bitrixImportDialog');
    const csv = '\ufeffID;Nome do negócio;Empresa;Fase;Total;Código interno;Campo futuro\n'
      + '9201;Primeiro Alpha;Empresa Teste;Em Contato;10;COD-ALPHA;\n'
      + '9202;Segundo Beta;Empresa Teste;Em Contato;20;COD-BETA;\n'
      + '9203;Terceiro Alpha;Empresa Teste;Em Contato;30;COD-ALPHA;\n';
    await dialog.getByLabel('CSV de Negócios').setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    await dialog.getByRole('button', { name: 'Fechar' }).click();
    await goTo(page, 'Negócios');

    const search = page.getByPlaceholder('Buscar em negócios...');
    await search.fill('cod-beta');
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Segundo Beta/);

    await search.fill('');
    await page.getByRole('button', { name: 'Primeiro Alpha' }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    await drawer.getByLabel('Campo adicional para adicionar').selectOption({ label: 'Campo futuro' });
    await drawer.getByRole('button', { name: 'Adicionar campo' }).click();
    await drawer.getByLabel('Campo futuro').fill('Buscável depois');
    await drawer.getByRole('button', { name: 'Salvar registro' }).click();
    await search.fill('buscável depois');
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Primeiro Alpha/);

    await search.fill('');
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    const availableLabels = await panel.locator('#addFilterField option').allTextContents();
    assert.equal(availableLabels.filter(label => label === 'Código interno').length, 1);
    assert.equal(availableLabels.filter(label => label === 'Campo futuro').length, 1);
    await panel.locator('#addFilterField').selectOption({ label: 'Código interno' });
    await panel.getByRole('button', { name: 'Adicionar campo' }).click();
    const customRow = panel.locator('[data-filter-field^="custom:"]');
    assert.deepEqual(await customRow.locator('select[name="filter-operator"] option').evaluateAll(options => options.map(option => option.value)), ['contains', 'exact']);
    await panel.locator('[data-filter-field="title"] input[name="filter-value"]').fill('Primeiro');
    await customRow.locator('input[name="filter-value"]').fill('cod-alpha');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Primeiro Alpha/);
    assert.doesNotMatch(await page.locator('#page-deals tbody').innerText(), /Terceiro Alpha/);

    await page.getByRole('button', { name: /Filtros/ }).click();
    await panel.locator('[data-filter-field="title"] input[name="filter-value"]').fill('');
    await customRow.locator('select[name="filter-operator"]').selectOption('exact');
    await customRow.locator('input[name="filter-value"]').fill('cod-beta');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    assert.match(await page.locator('#page-deals tbody').innerText(), /Segundo Beta/);
  });

  await run('ADM-01 Administrador gerencia campos padrão e personalizados por módulo', async page => {
    for (const module of ['Leads', 'Contatos', 'Empresas', 'Negócios']) {
      await goTo(page, module);
      assert.equal(await page.getByRole('button', { name: 'Gerenciar campos' }).count(), 1);
    }
    const manage = page.getByRole('button', { name: 'Gerenciar campos' });
    await manage.click();
    const dialog = page.locator('#fieldManagerDialog');
    await dialog.waitFor({ state: 'visible' });
    assert.equal(await dialog.getByText('Nenhum campo personalizado criado.').count(), 1);
    assert.deepEqual(await dialog.locator('[data-standard-field]').evaluateAll(inputs => inputs.map(input => [input.closest('label').textContent.trim(), input.checked])), [
      ['Título do Negócio', true], ['Empresa', true], ['Contato', true], ['Valor (R$)', true],
      ['Etapa', true], ['Responsável', true], ['Assistente', true]
    ]);

    assert.deepEqual(await dialog.locator('#customFieldType option').allTextContents(), [
      'Texto curto', 'Texto longo', 'Número', 'Moeda', 'Data', 'Sim/Não',
      'E-mail', 'Telefone', 'Link', 'Seleção única', 'Seleção múltipla'
    ]);

    const before = await stateFrom(page);
    const firstDeal = before.deals[0];
    await dialog.getByLabel('Contato').uncheck();
    await dialog.getByRole('button', { name: 'Salvar visualização' }).click();
    const drawer = page.locator('#entityDrawer');
    assert.deepEqual((await stateFrom(page)).deals.map(deal => [deal.id, deal.contact]), before.deals.map(deal => [deal.id, deal.contact]));
    for (const deal of before.deals) {
      await page.getByRole('button', { name: deal.title }).click();
      assert.equal(await drawer.getByLabel('Contato').count(), 0, `${deal.id} ainda exibiu Contato`);
      await drawer.getByRole('button', { name: 'Fechar painel' }).click();
    }

    await manage.click();
    await dialog.getByLabel('Contato').check();
    await dialog.getByRole('button', { name: 'Salvar visualização' }).click();
    await page.getByRole('button', { name: firstDeal.title }).click();
    assert.equal(await drawer.getByLabel('Contato').inputValue(), firstDeal.contact);
    await drawer.getByRole('button', { name: 'Fechar painel' }).click();

    await manage.click();
    await dialog.getByLabel('Nome do campo').fill('Número do contrato');
    await dialog.getByLabel('Tipo do campo').selectOption('text');
    await dialog.getByRole('button', { name: 'Criar campo' }).click();
    let configured = await stateFrom(page);
    assert.equal(configured.customFieldSchemas.deals.filter(field => field.label === 'Número do contrato').length, 1);
    assert.equal(configured.deals.every(deal => deal.customFields.some(field => field.label === 'Número do contrato')), true);

    await dialog.getByLabel('Nome do campo').fill('número DO CONTRATO');
    await dialog.getByRole('button', { name: 'Criar campo' }).click();
    assert.match(await dialog.locator('#fieldManagerError').innerText(), /Já existe um campo com esse nome/);
    configured = await stateFrom(page);
    assert.equal(configured.customFieldSchemas.deals.filter(field => field.label.toLocaleLowerCase('pt-BR') === 'número do contrato').length, 1);

    const schemaBeforeEmptyName = JSON.stringify((await stateFrom(page)).customFieldSchemas.deals);
    await dialog.getByLabel('Nome do campo').fill('');
    await dialog.getByRole('button', { name: 'Criar campo' }).click();
    assert.equal(await dialog.locator('#fieldManagerError').innerText(), 'Informe o nome do campo.');
    assert.equal(JSON.stringify((await stateFrom(page)).customFieldSchemas.deals), schemaBeforeEmptyName);
    await dialog.getByLabel('Nome do campo').fill('Canais comerciais');
    await dialog.getByLabel('Tipo do campo').selectOption('multiselect');
    await dialog.getByLabel('Opções').fill('Portal\nportal\nEvento');
    await dialog.getByRole('button', { name: 'Criar campo' }).click();
    assert.deepEqual((await stateFrom(page)).customFieldSchemas.deals.find(field => field.label === 'Canais comerciais').options, ['Portal', 'Evento']);

    await dialog.getByLabel('Nome do campo').fill('Prioridade comercial');
    await dialog.getByLabel('Tipo do campo').selectOption('select');
    await dialog.getByLabel('Opções').fill('   ');
    await dialog.getByRole('button', { name: 'Criar campo' }).click();
    assert.equal(await dialog.locator('#fieldManagerError').innerText(), 'Informe ao menos uma opção.');
    await dialog.getByRole('button', { name: 'Fechar', exact: true }).click();

    await page.getByRole('button', { name: 'Novo Negócio' }).click();
    const newDialog = page.locator('#entityDialog');
    await newDialog.getByLabel('Título do Negócio *').fill('Negócio com campo configurado');
    await newDialog.getByLabel('Empresa *').fill('Empresa Nova');
    await newDialog.getByLabel('Valor (R$) *').fill('100');
    await newDialog.getByLabel('Responsável *').selectOption('u-paula');
    await newDialog.getByRole('button', { name: 'Salvar registro' }).click();
    const created = (await stateFrom(page)).deals.find(deal => deal.title === 'Negócio com campo configurado');
    assert.equal(created.customFields.some(field => field.label === 'Número do contrato'), true);
    assert.equal(created.visibleCustomFieldKeys.includes(created.customFields.find(field => field.label === 'Número do contrato').key), true);

    const settingsBeforeDeniedAction = JSON.stringify((await stateFrom(page)).moduleFieldSettings.deals);
    await selectProfile(page, 'u-paula');
    await goTo(page, 'Negócios');
    assert.equal(await page.getByRole('button', { name: 'Gerenciar campos' }).count(), 0);
    assert.equal(await page.evaluate(() => openFieldManager('deals')), false);
    assert.equal(await page.locator('#fieldManagerDialog').getAttribute('open'), null);
    assert.equal(JSON.stringify((await stateFrom(page)).moduleFieldSettings.deals), settingsBeforeDeniedAction);
  });

  await run('FIELDVIS-01 combina ocultação geral e individual sem perder valores', async page => {
    const configured = await stateFrom(page);
    const schema = { key: 'test:global', label: 'Campo geral teste', type: 'text', options: [], userCreated: true };
    configured.customFieldSchemas.deals = [schema];
    configured.moduleFieldSettings.deals.hiddenCustomFieldKeys = [];
    configured.deals.forEach((deal, index) => {
      deal.customFields = [{ ...schema, value: `CTR-GLOBAL-${index + 1}` }];
      deal.visibleCustomFieldKeys = [schema.key];
    });
    configured.deals[1].visibleCustomFieldKeys = [];
    const valuesBefore = configured.deals.map(deal => deal.customFields[0].value);
    const individualVisibilityBefore = configured.deals.map(deal => [...deal.visibleCustomFieldKeys]);
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: configured });
    await setMockWorkspace(page, configured);
    await reloadReady(page);

    await goTo(page, 'Negócios');
    const manage = page.getByRole('button', { name: 'Gerenciar campos' });
    await manage.click();
    const dialog = page.locator('#fieldManagerDialog');
    const globalToggle = dialog.getByLabel('Campo geral teste');
    assert.equal(await globalToggle.isChecked(), true);
    await globalToggle.uncheck();
    await dialog.getByRole('button', { name: 'Salvar visualização' }).click();

    let saved = await stateFrom(page);
    assert.deepEqual(saved.moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key]);
    assert.deepEqual(saved.deals.map(deal => deal.customFields[0].value), valuesBefore);
    assert.deepEqual(saved.deals.map(deal => deal.visibleCustomFieldKeys), individualVisibilityBefore);

    await manage.click();
    assert.equal(await dialog.getByLabel('Campo geral teste').isChecked(), false);
    await dialog.getByRole('button', { name: 'Fechar', exact: true }).click();

    const drawer = page.locator('#entityDrawer');
    for (const deal of saved.deals.slice(0, 2)) {
      await page.getByRole('button', { name: deal.title }).click();
      assert.equal(await drawer.getByLabel('Campo geral teste').count(), 0);
      assert.equal(await drawer.locator('#drawerAddCustomField option[value="test:global"]').count(), 0);
      assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isHidden(), true);
      await drawer.getByRole('button', { name: deal.id === saved.deals[0].id ? 'Salvar registro' : 'Fechar painel' }).click();
    }
    saved = await stateFrom(page);
    assert.deepEqual(saved.deals.map(deal => deal.customFields[0].value), valuesBefore);
    assert.deepEqual(saved.deals.map(deal => deal.visibleCustomFieldKeys), individualVisibilityBefore);

    await manage.click();
    await dialog.getByLabel('Campo geral teste').check();
    await dialog.getByRole('button', { name: 'Salvar visualização' }).click();
    saved = await stateFrom(page);
    assert.deepEqual(saved.moduleFieldSettings.deals.hiddenCustomFieldKeys, []);

    await page.getByRole('button', { name: saved.deals[0].title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Campo geral teste').inputValue(), valuesBefore[0]);
    await drawer.getByRole('button', { name: 'Fechar painel' }).click();

    await page.getByRole('button', { name: saved.deals[1].title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Campo geral teste').count(), 0);
    assert.equal(await drawer.locator('#drawerAddCustomField option[value="test:global"]').count(), 1);
  });

  await run('XHIDE-01 o x oculta o campo em todos os cards sem perder dados', async page => {
    const configured = await stateFrom(page);
    const schema = { key: 'test:x-global', label: 'Campo global pelo x', type: 'text', options: [], userCreated: true };
    configured.customFieldSchemas.deals = [schema];
    configured.moduleFieldSettings.deals.hiddenCustomFieldKeys = [];
    configured.deals.forEach((deal, index) => {
      deal.customFields = [{ ...schema, value: `VALOR-X-${index + 1}` }];
      deal.visibleCustomFieldKeys = [schema.key];
    });
    configured.deals[1].visibleCustomFieldKeys = [];
    const valuesBefore = configured.deals.map(deal => deal.customFields[0].value);
    const visibilityBefore = configured.deals.map(deal => [...deal.visibleCustomFieldKeys]);
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: configured });
    await setMockWorkspace(page, configured);
    await reloadReady(page);

    await goTo(page, 'Negócios');
    const [firstDeal, secondDeal] = (await stateFrom(page)).deals;
    const drawer = page.locator('#entityDrawer');
    await page.getByRole('button', { name: firstDeal.title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    const globalHide = drawer.locator('[data-action="hide-custom-field"][data-key="test:x-global"]');
    assert.equal(await globalHide.count(), 1);
    assert.equal(await globalHide.getAttribute('aria-label'), 'Ocultar campo em todos os cadastros');
    await globalHide.click();
    await page.locator('#toastRegion').getByText('Campo Campo global pelo x ocultado em todos os cadastros.', { exact: true }).waitFor();

    let saved = await stateFrom(page);
    assert.deepEqual(saved.moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key]);
    assert.deepEqual(saved.deals.map(deal => deal.customFields[0].value), valuesBefore);
    assert.deepEqual(saved.deals.map(deal => deal.visibleCustomFieldKeys), visibilityBefore);
    assert.equal(await drawer.locator('#drawerAddCustomField option[value="test:x-global"]').count(), 0);
    assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isHidden(), true);
    assert.equal(await drawer.getByRole('tab', { name: 'Informações' }).getAttribute('aria-selected'), 'true');
    assert.equal(await page.evaluate(key => hideDrawerCustomField(key), schema.key), false);
    assert.equal(await page.evaluate(() => hideDrawerCustomField('test:inexistente')), false);
    assert.deepEqual((await stateFrom(page)).moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key]);

    await drawer.getByRole('button', { name: 'Fechar painel' }).click();
    await page.getByRole('button', { name: secondDeal.title }).click();
    assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isHidden(), true);
    assert.equal(await drawer.getByLabel('Campo global pelo x').count(), 0);
    await drawer.getByRole('button', { name: 'Fechar painel' }).click();

    await page.getByRole('button', { name: 'Gerenciar campos' }).click();
    const dialog = page.locator('#fieldManagerDialog');
    assert.equal(await dialog.getByLabel('Campo global pelo x').isChecked(), false);
    await dialog.getByLabel('Campo global pelo x').check();
    await dialog.getByRole('button', { name: 'Salvar visualização' }).click();
    assert.deepEqual((await stateFrom(page)).moduleFieldSettings.deals.hiddenCustomFieldKeys, []);
    await page.getByRole('button', { name: firstDeal.title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Campo global pelo x').inputValue(), valuesBefore[0]);
    await drawer.getByRole('button', { name: 'Fechar painel' }).click();
    await page.getByRole('button', { name: secondDeal.title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Campo global pelo x').count(), 0);
    assert.equal(await drawer.locator('#drawerAddCustomField option[value="test:x-global"]').count(), 1);
  });


  await run('XHIDE-02 restringe o x global ao Administrador', async page => {
    const configured = await stateFrom(page);
    const schema = { key: 'test:x-restrito', label: 'Campo restrito', type: 'text', options: [], userCreated: true };
    configured.customFieldSchemas.deals = [schema];
    configured.moduleFieldSettings.deals.hiddenCustomFieldKeys = [];
    configured.deals[0].responsibleId = 'u-paula';
    configured.deals[0].customFields = [{ ...schema, value: 'DADO PRESERVADO' }];
    configured.deals[0].visibleCustomFieldKeys = [schema.key];
    configured.currentUserId = 'u-paula';
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: configured });
    await setMockWorkspace(page, configured);
    await reloadReady(page);

    await goTo(page, 'Negócios');
    const firstDeal = (await stateFrom(page)).deals[0];
    await page.getByRole('button', { name: firstDeal.title }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.locator('[data-action="hide-custom-field"]').count(), 0);
    const settingsBefore = JSON.stringify((await stateFrom(page)).moduleFieldSettings.deals);
    assert.equal(await page.evaluate(key => hideDrawerCustomField(key), schema.key), false);
    assert.equal(JSON.stringify((await stateFrom(page)).moduleFieldSettings.deals), settingsBefore);
    assert.equal(await drawer.getByLabel('Campo restrito').inputValue(), 'DADO PRESERVADO');
  });
  await run('ADM-02 campos tipados preservam valores ocultação busca e filtros', async page => {
    const configured = await stateFrom(page);
    const schemas = [
      { key: 'test:text', label: 'Contrato teste', type: 'text', options: [], userCreated: true },
      { key: 'test:textarea', label: 'Escopo detalhado', type: 'textarea', options: [], userCreated: true },
      { key: 'test:number', label: 'Quantidade teste', type: 'number', options: [], userCreated: true },
      { key: 'test:money', label: 'Orçamento teste', type: 'money', options: [], userCreated: true },
      { key: 'test:date', label: 'Data teste', type: 'date', options: [], userCreated: true },
      { key: 'test:boolean', label: 'Aprovado teste', type: 'boolean', options: [], userCreated: true },
      { key: 'test:email', label: 'E-mail teste', type: 'email', options: [], userCreated: true },
      { key: 'test:phone', label: 'Telefone teste', type: 'phone', options: [], userCreated: true },
      { key: 'test:url', label: 'Link teste', type: 'url', options: [], userCreated: true },
      { key: 'test:select', label: 'Prioridade teste', type: 'select', options: ['Alta', 'Baixa'], userCreated: true },
      { key: 'test:multiselect', label: 'Produtos teste', type: 'multiselect', options: ['CRM', 'Portal'], userCreated: true }
    ];
    configured.customFieldSchemas.deals = schemas;
    configured.deals.forEach(deal => {
      deal.customFields = [...(deal.customFields || []).filter(field => !field.key.startsWith('test:')), ...schemas.map(field => ({ ...field, value: field.type === 'multiselect' ? [] : field.type === 'boolean' ? false : '' }))];
      deal.visibleCustomFieldKeys = [...new Set([...(deal.visibleCustomFieldKeys || []), ...schemas.map(field => field.key)])];
    });
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: STORAGE_KEY, value: configured });
    await setMockWorkspace(page, configured);
    await reloadReady(page);

    await goTo(page, 'Negócios');
    const firstDeal = (await stateFrom(page)).deals[0];
    await page.getByRole('button', { name: firstDeal.title }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Contrato teste').getAttribute('type'), 'text');
    assert.equal(await drawer.getByLabel('Escopo detalhado').evaluate(element => element.tagName), 'TEXTAREA');
    assert.equal(await drawer.getByLabel('Quantidade teste').getAttribute('type'), 'number');
    assert.equal(await drawer.getByLabel('Orçamento teste').getAttribute('step'), '0.01');
    assert.equal(await drawer.getByLabel('Data teste').getAttribute('type'), 'date');
    assert.equal(await drawer.getByLabel('Aprovado teste').getAttribute('type'), 'checkbox');
    assert.equal(await drawer.getByLabel('E-mail teste').getAttribute('type'), 'email');
    assert.equal(await drawer.getByLabel('Telefone teste').getAttribute('type'), 'tel');
    assert.equal(await drawer.getByLabel('Link teste').getAttribute('type'), 'url');
    assert.equal(await drawer.getByLabel('Prioridade teste').evaluate(element => element.tagName), 'SELECT');
    assert.equal(await drawer.getByLabel('Produtos teste').getAttribute('multiple'), '');

    await drawer.getByLabel('Contrato teste').fill('CTR-900');
    await drawer.getByLabel('Escopo detalhado').fill('Implantação completa');
    await drawer.getByLabel('Quantidade teste').fill('42');
    await drawer.getByLabel('Orçamento teste').fill('1234.56');
    await drawer.getByLabel('Data teste').fill('2026-09-15');
    await drawer.getByLabel('Aprovado teste').check();
    await drawer.getByLabel('E-mail teste').fill('contrato@teste.invalid');
    await drawer.getByLabel('Telefone teste').fill('+55 11 99999-0000');
    const beforeInvalidSave = JSON.stringify((await stateFrom(page)).deals.find(deal => deal.id === firstDeal.id));
    await drawer.getByLabel('Link teste').fill('link inválido');
    await drawer.getByRole('button', { name: 'Salvar registro' }).click();
    assert.equal(await drawer.getByLabel('Link teste').evaluate(element => element.checkValidity()), false);
    await drawer.waitFor({ state: 'visible' });
    assert.equal(JSON.stringify((await stateFrom(page)).deals.find(deal => deal.id === firstDeal.id)), beforeInvalidSave);
    await drawer.getByLabel('Link teste').fill('https://example.test/contrato');
    await drawer.getByLabel('Prioridade teste').selectOption('Alta');
    await drawer.getByLabel('Produtos teste').selectOption(['CRM', 'Portal']);
    await drawer.getByRole('button', { name: 'Salvar registro' }).click();

    let saved = (await stateFrom(page)).deals.find(deal => deal.id === firstDeal.id);
    const values = Object.fromEntries(saved.customFields.filter(field => field.key.startsWith('test:')).map(field => [field.key, field.value]));
    assert.equal(values['test:text'], 'CTR-900');
    assert.equal(values['test:number'], 42);
    assert.equal(values['test:money'], 1234.56);
    assert.equal(values['test:date'], '2026-09-15');
    assert.equal(values['test:boolean'], true);
    assert.equal(values['test:select'], 'Alta');
    assert.deepEqual(values['test:multiselect'], ['CRM', 'Portal']);
    assert.deepEqual(saved.customFields.filter(field => ['test:text', 'test:number', 'test:money', 'test:date', 'test:boolean', 'test:select', 'test:multiselect'].includes(field.key)).map(field => ({ key: field.key, type: field.type, value: field.value })), [
      { key: 'test:text', type: 'text', value: 'CTR-900' },
      { key: 'test:number', type: 'number', value: 42 },
      { key: 'test:money', type: 'money', value: 1234.56 },
      { key: 'test:date', type: 'date', value: '2026-09-15' },
      { key: 'test:boolean', type: 'boolean', value: true },
      { key: 'test:select', type: 'select', value: 'Alta' },
      { key: 'test:multiselect', type: 'multiselect', value: ['CRM', 'Portal'] }
    ]);

    await page.getByRole('button', { name: firstDeal.title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).click();
    assert.equal(await drawer.getByLabel('Contrato teste').inputValue(), 'CTR-900');
    assert.equal(await drawer.getByLabel('Data teste').inputValue(), '2026-09-15');
    assert.equal(await drawer.getByLabel('Prioridade teste').inputValue(), 'Alta');
    await drawer.getByRole('button', { name: 'Fechar painel' }).click();

    await page.getByPlaceholder('Buscar em negócios...').fill('CTR-900');
    assert.equal(await page.locator('#page-deals tbody tr').count(), 1);
    assert.deepEqual(await page.evaluate(() => {
      const definitions = customFilterDefinitions('deals');
      const operators = label => filterOperatorOptions(definitions.find(field => field.label === label)).map(option => option[1]);
      return {
        text: operators('Contrato teste'), textarea: operators('Escopo detalhado'), email: operators('E-mail teste'), phone: operators('Telefone teste'), url: operators('Link teste'),
        number: operators('Quantidade teste'), money: operators('Orçamento teste'), date: operators('Data teste'), boolean: operators('Aprovado teste'), select: operators('Prioridade teste'), multiselect: operators('Produtos teste')
      };
    }), {
      text: ['Contém', 'É exatamente'], textarea: ['Contém', 'É exatamente'], email: ['Contém', 'É exatamente'], phone: ['Contém', 'É exatamente'], url: ['Contém', 'É exatamente'],
      number: ['Valor exato', 'Maior que', 'Menor que', 'Entre'], money: ['Valor exato', 'Maior que', 'Menor que', 'Entre'],
      date: ['Qualquer data', 'Data exata', 'Antes de', 'Depois de', 'Entre'], boolean: ['É um de'], select: ['É um de'], multiselect: ['É um de']
    });
    await assertCanonicalRehydration(page);
  });

  await run('ADM-03 Administrador convida edita e controla acesso de funcionários', async page => {
    await goTo(page, 'Usuários e permissões');
    await page.getByRole('button', { name: 'Convidar funcionário' }).click();
    const dialog = page.locator('#userDialog');
    await dialog.getByLabel('Nome completo').fill('Juliana Lima');
    await dialog.getByLabel('E-mail').fill('juliana@teste.invalid');
    await dialog.getByLabel('Cargo profissional').fill('Consultora comercial');
    await dialog.getByLabel('Equipe').fill('Vendas CMS');
    await dialog.getByLabel('Perfil de acesso').selectOption('Vendedor');
    await dialog.getByRole('button', { name: 'Enviar convite' }).click();

    let state = await stateFrom(page);
    let juliana = state.users.find(user => user.email === 'juliana@teste.invalid');
    assert.deepEqual({ name: juliana.name, email: juliana.email, jobTitle: juliana.jobTitle, team: juliana.team, role: juliana.role, status: juliana.status }, {
      name: 'Juliana Lima', email: 'juliana@teste.invalid', jobTitle: 'Consultora comercial', team: 'Vendas CMS', role: 'Vendedor', status: 'Pendente'
    });
    assert.equal(await page.getByLabel('Perfil demonstrativo').locator('option[value="' + juliana.id + '"]').count(), 0);

    await page.getByRole('button', { name: 'Convidar funcionário' }).click();
    await dialog.getByLabel('Nome completo').fill('Juliana Duplicada');
    await dialog.getByLabel('E-mail').fill('JULIANA@TESTE.INVALID');
    await dialog.getByLabel('Cargo profissional').fill('Outro cargo');
    await dialog.getByLabel('Equipe').fill('Outra equipe');
    await dialog.getByLabel('Perfil de acesso').selectOption('Gestor');
    await dialog.getByRole('button', { name: 'Enviar convite' }).click();
    assert.match(await dialog.locator('#userDialogError').innerText(), /e-mail já está cadastrado/i);
    assert.equal((await stateFrom(page)).users.filter(user => user.email.toLocaleLowerCase('pt-BR') === 'juliana@teste.invalid').length, 1);
    await dialog.getByRole('button', { name: 'Fechar', exact: true }).click();

    const invitedAt = juliana.invitedAt;
    await page.getByRole('button', { name: 'Reenviar convite de Juliana Lima' }).click();
    juliana = (await stateFrom(page)).users.find(user => user.id === juliana.id);
    assert.equal(juliana.status, 'Pendente');
    assert.notEqual(juliana.invitedAt, invitedAt);

    await page.getByRole('button', { name: 'Editar Juliana Lima' }).click();
    await dialog.getByLabel('Cargo profissional').fill('Executiva de contas');
    await dialog.getByLabel('Equipe').fill('Vendas Enterprise');
    await dialog.getByLabel('Perfil de acesso').selectOption('Gestor');
    await dialog.getByRole('button', { name: 'Salvar funcionário' }).click();
    juliana = (await stateFrom(page)).users.find(user => user.id === juliana.id);
    assert.deepEqual([juliana.jobTitle, juliana.team, juliana.role], ['Executiva de contas', 'Vendas Enterprise', 'Gestor']);

    await page.getByRole('button', { name: 'Simular aceitação de Juliana Lima' }).click();
    assert.equal((await stateFrom(page)).users.find(user => user.id === juliana.id).status, 'Ativo');
    assert.equal(await page.getByLabel('Perfil demonstrativo').locator(`option[value="${juliana.id}"]`).count(), 1);
    await page.getByRole('button', { name: 'Desativar Juliana Lima' }).click();
    assert.equal((await stateFrom(page)).users.find(user => user.id === juliana.id).status, 'Inativo');
    assert.equal(await page.getByLabel('Perfil demonstrativo').locator(`option[value="${juliana.id}"]`).count(), 0);

    await page.getByRole('button', { name: 'Convidar funcionário' }).click();
    await dialog.getByLabel('Nome completo').fill('Rafael Teste');
    await dialog.getByLabel('E-mail').fill('rafael@teste.invalid');
    await dialog.getByLabel('Cargo profissional').fill('SDR');
    await dialog.getByLabel('Equipe').fill('Vendas CMS');
    await dialog.getByLabel('Perfil de acesso').selectOption('Vendedor');
    await dialog.getByRole('button', { name: 'Enviar convite' }).click();
    await page.getByRole('button', { name: 'Cancelar convite de Rafael Teste' }).click();
    const canceled = (await stateFrom(page)).users.find(user => user.email === 'rafael@teste.invalid');
    assert.equal(canceled.status, 'Cancelado');
    assert.equal(await page.getByLabel('Perfil demonstrativo').locator(`option[value="${canceled.id}"]`).count(), 0);

    await page.getByRole('button', { name: 'Convidar funcionário' }).click();
    await dialog.getByLabel('Nome completo').fill('Rafael Reativado');
    await dialog.getByLabel('E-mail').fill('RAFAEL@TESTE.INVALID');
    await dialog.getByLabel('Cargo profissional').fill('Consultor');
    await dialog.getByLabel('Equipe').fill('Vendas CMS');
    await dialog.getByLabel('Perfil de acesso').selectOption('Vendedor');
    await dialog.getByRole('button', { name: 'Enviar convite' }).click();
    const reinvited = (await stateFrom(page)).users.filter(user => user.email.toLocaleLowerCase('pt-BR') === 'rafael@teste.invalid');
    assert.equal(reinvited.length, 1);
    assert.deepEqual({ id: reinvited[0].id, name: reinvited[0].name, email: reinvited[0].email, jobTitle: reinvited[0].jobTitle, team: reinvited[0].team, role: reinvited[0].role, status: reinvited[0].status }, {
      id: canceled.id, name: 'Rafael Reativado', email: 'RAFAEL@TESTE.INVALID', jobTitle: 'Consultor', team: 'Vendas CMS', role: 'Vendedor', status: 'Pendente'
    });
    assert.equal(await page.evaluate(() => changeUserStatus('u-admin', 'Inativo')), false);
    assert.equal((await stateFrom(page)).users.find(user => user.id === 'u-admin').status, 'Ativo');

    await selectProfile(page, 'u-paula');
    assert.equal(await page.locator('[data-admin-nav]:visible').count(), 0);
    await page.evaluate(() => showView('admin'));
    assert.equal(await page.locator('#topTitle').innerText(), 'Visão geral');
    await assertCanonicalRehydration(page);
  });

  await run('BITRIX-02 rejeita arquivos inválidos e mantém a importação parcial', async page => {
    const before = await stateFrom(page);
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();
    const dialog = page.locator('#bitrixImportDialog');
    await dialog.getByLabel('CSV de Leads').setInputFiles({
      name: 'lead.csv', mimeType: 'text/csv', buffer: Buffer.from('\ufeffID;Nome\n;Lead sem chave\n5002;Lead válido dois\n5003;Lead válido três\n', 'utf8')
    });
    await dialog.getByLabel('CSV de Empresas').setInputFiles({
      name: 'empresa.txt', mimeType: 'text/plain', buffer: Buffer.from('ID;Nome da Empresa\n77;Inválida\n', 'utf8')
    });
    await dialog.getByLabel('CSV de Contatos').setInputFiles({
      name: 'contact-empty.csv', mimeType: 'text/csv', buffer: Buffer.from('\ufeffID;Nome\n', 'utf8')
    });
    await dialog.getByLabel('CSV de Negócios').setInputFiles({
      name: 'deal-comma.csv', mimeType: 'text/csv', buffer: Buffer.from('\ufeffID,Nome do negócio,Empresa,Fase,Total\n9004,Negócio com vírgula,"Empresa, Teste",Em Contato,30\n', 'utf8')
    });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 3 · Atualizados: 0 · Rejeitados: 3');
    assert.match(await dialog.locator('#bitrixImportDetails').innerText(), /lead.csv: ID do Bitrix ausente/);
    assert.match(await dialog.locator('#bitrixImportDetails').innerText(), /empresa.txt: selecione um arquivo CSV/);
    assert.match(await dialog.locator('#bitrixImportDetails').innerText(), /contact-empty.csv: nenhuma linha de dados/);

    const after = await stateFrom(page);
    assert.equal(after.leads.length, before.leads.length + 2);
    assert.deepEqual(after.leads.filter(item => item.bitrixId).map(item => item.bitrixId).sort(), ['5002', '5003']);
    assert.equal(after.companies.length, before.companies.length);
    assert.equal(after.contacts.length, before.contacts.length);
    assert.equal(after.deals.length, before.deals.length + 1);
    const imported = after.deals.find(item => item.bitrixId === '9004');
    assert.equal(imported.company, 'Empresa, Teste');
    assert.equal(imported.title, 'Negócio com vírgula');
  });

  await run('DEMO-14 aplica fronteiras de Administrador, Gestor, Vendedor e Assistente', async page => {
    assert.equal(await visibleRows(page, 'Negócios'), 6);
    await selectProfile(page, 'u-manager');
    assert.equal(await visibleRows(page, 'Negócios'), 5);
    assert.doesNotMatch(await page.locator('#page-deals').innerText(), /Conferência fiscal interna/);
    assert.equal(await visibleRows(page, 'Leads'), 5);

    await selectProfile(page, 'u-paula');
    assert.equal(await visibleRows(page, 'Negócios'), 3);
    assert.equal(await visibleRows(page, 'Leads'), 2);

    await selectProfile(page, 'u-camila');
    assert.equal(await visibleRows(page, 'Negócios'), 3);
    assert.equal(await visibleRows(page, 'Leads'), 2);

    await selectProfile(page, 'u-admin');
    assert.equal(await visibleRows(page, 'Negócios'), 6);
    assert.match(await page.locator('#page-deals').innerText(), /Conferência fiscal interna/);
  });

  await run('DEMO-15 mantém o aviso demonstrativo em todas as telas', async page => {
    for (const destination of ['Visão geral', 'Leads', 'Contatos', 'Empresas', 'Negócios', 'Notificações']) {
      await goTo(page, destination);
      const banner = page.getByText(/Ambiente de demonstração — dados fictícios/).first();
      assert.equal(await banner.isVisible(), true);
    }
  });

  await run('DEMO-16 preserva menu e ação principal em viewport móvel', async page => {
    await page.setViewportSize({ width: 390, height: 844 });
    const menu = page.getByRole('button', { name: 'Abrir menu' });
    assert.equal(await menu.isVisible(), true);
    await menu.click();
    assert.match(await page.locator('#sidebar').getAttribute('class'), /open/);
    await goTo(page, 'Leads');
    assert.equal(await page.getByRole('button', { name: /Novo Lead/ }).isVisible(), true);
  });

  await run('edge case recupera localStorage corrompido', async page => {
    await page.evaluate(key => localStorage.setItem(key, '{invalid-json'), STORAGE_KEY);
    await reloadReady(page);
    const recovered = await stateFrom(page);
    assert.ok(recovered.leads.length >= 5);
    assert.equal(recovered.currentUserId, 'u-admin');
  });

  await browser.close();
  console.log(`\nUI regression: ${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})().catch(async error => {
  console.error(error.stack || error);
  if (browser) await browser.close();
  process.exitCode = 1;
});
