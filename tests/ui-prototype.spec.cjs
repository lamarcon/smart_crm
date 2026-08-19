const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const BASE_URL = process.env.SMART_CRM_TEST_URL || 'http://localhost:8080/';
const STORAGE_KEY = 'smart-crm-demo-v1';
const LEAD_STAGES = ['Em contato', 'Lead descartado', 'Lead convertido'];
const DEAL_STAGES = [
  'Em Contato', 'Orçamento Proposta Preço', 'Orçamentos enviados',
  'Negociação Revisão', 'Pedido aprovado Consultar', 'Faturando',
  'Ganho', 'Orçamento Não Aprovado', 'Analisar falha'
];

let browser;
let passed = 0;
let failed = 0;

async function stateFrom(page) {
  return JSON.parse(await page.evaluate(key => localStorage.getItem(key), STORAGE_KEY));
}

async function openFresh(options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1366, height: 768 } });
  const page = await context.newPage();
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.getByText(/Ambiente de demonstração/).first().waitFor();
  return { context, page };
}

async function run(name, test) {
  const { context, page } = await openFresh();
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

async function createLead(page, name) {
  await goTo(page, 'Leads');
  await page.getByRole('button', { name: /Novo Lead/ }).click();
  const dialog = page.locator('#entityDialog');
  await dialog.getByLabel('Nome completo *').fill(name);
  await dialog.getByLabel('Empresa *').fill('Empresa de Teste');
  await dialog.getByLabel('E-mail *').fill('teste@local.invalid');
  await dialog.getByLabel('Responsável *').selectOption('u-paula');
  await dialog.getByLabel('Assistente').selectOption('u-camila');
  await dialog.getByRole('button', { name: 'Salvar registro' }).click();
  await page.locator('#page-leads .entity-link').filter({ hasText: name }).waitFor();
}

(async () => {
  browser = await chromium.launch({ channel: process.env.SMART_CRM_BROWSER || 'chrome', headless: true });

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
    await page.reload({ waitUntil: 'domcontentloaded' });

    const normalized = await stateFrom(page);
    assert.equal(normalized.leads[0].name, 'Lead legado preservado');
    assert.deepEqual(normalized.ui.viewModesByUser['u-admin'], { leads: 'list', deals: 'list' });
    assert.equal(normalized.ui.dashboardScopeByUser['u-admin'], 'all');
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

  await run('DEMO-04 navega pelos seis destinos', async page => {
    const destinations = [
      ['Visão geral', 'Visão geral'], ['Leads', 'Leads'], ['Contatos', 'Contatos'],
      ['Empresas', 'Empresas'], ['Negócios', 'Negócios'], ['Notificações', 'Notificações']
    ];
    assert.equal(await page.locator('.nav button').count(), 6);
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

    page.once('dialog', dialog => dialog.accept());
    row = page.locator('#page-leads tbody tr').filter({ hasText: 'Lead CRUD Editado' });
    await row.getByTitle('Excluir').click();
    assert.equal(await page.getByText('Lead CRUD Editado', { exact: true }).count(), 0);
    assert.equal(Number(await page.locator('#leadNavCount').innerText()), initialCount);
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

    await panel.getByRole('button', { name: 'Redefinir' }).click();
    assert.deepEqual(await panel.locator('[data-filter-field]').evaluateAll(rows => rows.map(row => row.dataset.filterField)), ['name', 'stage', 'responsibleId', 'createdAt']);
    assert.deepEqual(await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').evaluate(select => [...select.selectedOptions].map(option => option.value)), []);
    assert.equal(await panel.locator('[data-filter-field="name"] input[name="filter-value"]').inputValue(), '');
    await panel.getByRole('button', { name: 'Leads convertidos', exact: true }).click();
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.locator('#page-leads tbody tr').count(), 1);
    assert.match(await page.locator('#page-leads tbody').innerText(), /Marina Ferreira/);

    await page.reload({ waitUntil: 'domcontentloaded' });
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
    await page.reload({ waitUntil: 'domcontentloaded' });
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
    await page.reload({ waitUntil: 'domcontentloaded' });
    await goTo(page, 'Negócios');
    assert.equal(await page.locator('#page-deals .kanban-board').isVisible(), true);
    assert.equal((await stateFrom(page)).ui.viewModesByUser['u-admin'].deals, 'kanban');
    assert.equal(await page.locator('#page-deals .kanban-card').count(), 1);
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
    await page.reload({ waitUntil: 'domcontentloaded' });
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
    await page.reload({ waitUntil: 'domcontentloaded' });
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

    const csv = '\ufeffID;Nome do negócio;Empresa;Fase;Total;Responsável;Observação;Cargo;Cargo;\n'
      + '9001;Negócio importado;Empresa Bitrix;Negociação Revisão;1234.50;Paula Pincetta;"valor; preservado\ncom quebra";Comprador;Decisor;campo sem cabeçalho\n'
      + '9003;Segunda linha ignorada;Outra Empresa;Em Contato;99;Paula Pincetta;Não importar;Cargo;Cargo;fim\n';
    await dialog.getByLabel('CSV de Negócios').setInputFiles({
      name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf8')
    });
    const contactCsv = '\ufeffID;Nome;Sobrenome;Empresa;Email de trabalho;Telefone de trabalho;Cargo\n3001;Maria;Silva;Empresa Bitrix;maria@teste.invalid;11999990000;Diretora\n';
    const companyCsv = '\ufeffID;Nome da Empresa;Cidade;UF.;Segmento de Mercado;Telefone de trabalho;Responsável\n4001;Empresa Independente;Campinas;SP;Laboratórios;1933334444;Vitor Costa\n';
    const leadCsv = '\ufeffID;Nome completo;Nome da empresa;Email de trabalho;Telefone de trabalho;Segmento de Mercado;Origem do Lead;Etapa;Pessoa responsável\n5001;Lead Importado;Empresa Lead;lead@teste.invalid;1133335555;Diagnóstico;Site;Em contato;Vitor Costa\n';
    await dialog.getByLabel('CSV de Contatos').setInputFiles({ name: 'contact.csv', mimeType: 'text/csv', buffer: Buffer.from(contactCsv, 'utf8') });
    await dialog.getByLabel('CSV de Empresas').setInputFiles({ name: 'company.csv', mimeType: 'text/csv', buffer: Buffer.from(companyCsv, 'utf8') });
    await dialog.getByLabel('CSV de Leads').setInputFiles({ name: 'lead.csv', mimeType: 'text/csv', buffer: Buffer.from(leadCsv, 'utf8') });
    assert.equal(await dialog.getByRole('button', { name: 'Importar amostra' }).isEnabled(), true);
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 4 · Atualizados: 0 · Rejeitados: 0');

    const state = await stateFrom(page);
    const deal = state.deals.find(item => item.bitrixId === '9001');
    assert.ok(deal, 'Negócio importado não encontrado');
    assert.equal(state.deals.some(item => item.bitrixId === '9003'), false);
    assert.equal(deal.id, 'BX-DEAL-9001');
    assert.equal(deal.title, 'Negócio importado');
    assert.equal(deal.company, 'Empresa Bitrix');
    assert.equal(deal.stage, 'Negociação Revisão');
    assert.equal(deal.amount, 1234.5);
    assert.equal(deal.responsibleId, 'u-paula');
    assert.equal(deal.bitrixFields.length, 10);
    assert.deepEqual(deal.bitrixFields.map(field => [field.name, field.occurrence, field.value]), [
      ['ID', 1, '9001'],
      ['Nome do negócio', 1, 'Negócio importado'],
      ['Empresa', 1, 'Empresa Bitrix'],
      ['Fase', 1, 'Negociação Revisão'],
      ['Total', 1, '1234.50'],
      ['Responsável', 1, 'Paula Pincetta'],
      ['Observação', 1, 'valor; preservado\ncom quebra'],
      ['Cargo', 1, 'Comprador'],
      ['Cargo', 2, 'Decisor'],
      ['', 1, 'campo sem cabeçalho']
    ]);
    const contact = state.contacts.find(item => item.bitrixId === '3001');
    assert.deepEqual({ id: contact.id, name: contact.name, company: contact.company, email: contact.email, phone: contact.phone, role: contact.role, rawFields: contact.bitrixFields.length }, {
      id: 'BX-CONTACT-3001', name: 'Maria Silva', company: 'Empresa Bitrix', email: 'maria@teste.invalid', phone: '11999990000', role: 'Diretora', rawFields: 7
    });
    const company = state.companies.find(item => item.bitrixId === '4001');
    assert.deepEqual({ id: company.id, name: company.name, city: company.city, segment: company.segment, phone: company.phone, ownerId: company.ownerId, rawFields: company.bitrixFields.length }, {
      id: 'BX-COMPANY-4001', name: 'Empresa Independente', city: 'Campinas / SP', segment: 'Laboratórios', phone: '1933334444', ownerId: 'u-vitor', rawFields: 7
    });
    const lead = state.leads.find(item => item.bitrixId === '5001');
    assert.deepEqual({ id: lead.id, name: lead.name, company: lead.company, email: lead.email, phone: lead.phone, segment: lead.segment, source: lead.source, stage: lead.stage, responsibleId: lead.responsibleId, rawFields: lead.bitrixFields.length }, {
      id: 'BX-LEAD-5001', name: 'Lead Importado', company: 'Empresa Lead', email: 'lead@teste.invalid', phone: '1133335555', segment: 'Diagnóstico', source: 'Site', stage: 'Em contato', responsibleId: 'u-vitor', rawFields: 9
    });

    await dialog.getByRole('button', { name: 'Fechar' }).click();
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Negócio importado' }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.waitFor({ state: 'visible' });
    assert.match(await drawer.innerText(), /Campos do Bitrix/);
    assert.equal(await drawer.locator('[data-bitrix-field]').count(), 10);
    assert.equal(await drawer.locator('[data-bitrix-field="8"] dt').innerText(), 'Cargo (2)');
    assert.equal(await drawer.locator('[data-bitrix-field="8"] dd').innerText(), 'Decisor');
    assert.equal(await drawer.locator('[data-bitrix-field="9"] dt').innerText(), 'Campo sem nome');
  });

  await run('BITRIX-02 reimporta pelo ID sem criar duplicata', async page => {
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();
    const dialog = page.locator('#bitrixImportDialog');
    const input = dialog.getByLabel('CSV de Negócios');
    const first = '\ufeffID;Nome do negócio;Empresa;Fase;Total\n9002;Título inicial;Empresa Teste;Em Contato;10\n';
    await input.setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(first, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 1 · Atualizados: 0 · Rejeitados: 0');

    const second = '\ufeffID;Nome do negócio;Empresa;Fase;Total\n9002;Título atualizado;Empresa Teste;Em Contato;20\n';
    await input.setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(second, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await page.waitForFunction(() => document.getElementById('bitrixImportSummary')?.textContent.includes('Atualizados: 1'));
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 0 · Atualizados: 1 · Rejeitados: 0');

    const state = await stateFrom(page);
    const matches = state.deals.filter(item => item.bitrixId === '9002');
    assert.equal(matches.length, 1);
    assert.equal(matches[0].title, 'Título atualizado');
    assert.equal(matches[0].amount, 20);

    await input.setInputFiles({ name: 'deal.csv', mimeType: 'text/csv', buffer: Buffer.from(second, 'utf8') });
    await dialog.getByRole('button', { name: 'Importar amostra' }).click();
    await dialog.locator('#bitrixImportSummary').waitFor({ state: 'visible' });
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 0 · Atualizados: 1 · Rejeitados: 0');
    assert.equal((await stateFrom(page)).deals.filter(item => item.bitrixId === '9002').length, 1);
  });

  await run('BITRIX-02 rejeita arquivos inválidos e mantém a importação parcial', async page => {
    const before = await stateFrom(page);
    await page.getByRole('button', { name: 'Importar Bitrix' }).click();
    const dialog = page.locator('#bitrixImportDialog');
    await dialog.getByLabel('CSV de Leads').setInputFiles({
      name: 'lead.csv', mimeType: 'text/csv', buffer: Buffer.from('\ufeffID;Nome\n;Lead sem chave\n', 'utf8')
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
    assert.equal(await dialog.locator('#bitrixImportSummary').innerText(), 'Criados: 1 · Atualizados: 0 · Rejeitados: 3');
    assert.match(await dialog.locator('#bitrixImportDetails').innerText(), /lead.csv: ID do Bitrix ausente/);
    assert.match(await dialog.locator('#bitrixImportDetails').innerText(), /empresa.txt: selecione um arquivo CSV/);
    assert.match(await dialog.locator('#bitrixImportDetails').innerText(), /contact-empty.csv: nenhuma linha de dados/);

    const after = await stateFrom(page);
    assert.equal(after.leads.length, before.leads.length);
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
    await page.reload({ waitUntil: 'domcontentloaded' });
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
