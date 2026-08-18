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

    page.once('dialog', dialog => dialog.accept());
    row = page.locator('#page-leads tbody tr').filter({ hasText: 'Lead CRUD Editado' });
    await row.getByTitle('Excluir').click();
    assert.equal(await page.getByText('Lead CRUD Editado', { exact: true }).count(), 0);
    assert.equal(Number(await page.locator('#leadNavCount').innerText()), initialCount);
  });

  await run('DRAWER-01 abre os quatro cadastros pelo nome sem lápis', async page => {
    const records = [
      ['Leads', 'Larissa Spinola', 'Editar Lead'],
      ['Contatos', 'Ana Berclay', 'Editar Contato'],
      ['Empresas', 'Arkos Estética', 'Editar Empresa'],
      ['Negócios', 'Implantação Arkos Estética', 'Editar Negócio']
    ];
    for (const [view, name, title] of records) {
      await goTo(page, view);
      await page.locator(`#page-${{ Leads: 'leads', Contatos: 'contacts', Empresas: 'companies', Negócios: 'deals' }[view]}`).getByRole('button', { name, exact: true }).click();
      const drawer = page.locator('#entityDrawer');
      assert.match(await drawer.getAttribute('class'), /open/);
      assert.equal(await drawer.getByRole('heading').innerText(), title);
      assert.equal(await page.locator(`#page-${{ Leads: 'leads', Contatos: 'contacts', Empresas: 'companies', Negócios: 'deals' }[view]}`).isVisible(), true);
      assert.equal(await page.getByTitle('Editar').count(), 0);
      await drawer.getByRole('button', { name: 'Cancelar' }).click();
    }
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
  });

  await run('FILTER-01 e FILTER-02 adicionam e removem campos sem alterar registros', async page => {
    await goTo(page, 'Leads');
    const before = (await stateFrom(page)).leads;
    await page.getByRole('button', { name: /Filtros/ }).click();
    const panel = page.locator('#filterDialog');
    assert.equal(await panel.getByText('Filtros salvos').isVisible(), true);
    assert.equal(await panel.getByRole('button', { name: 'Adicionar campo' }).isVisible(), true);
    await panel.locator('#addFilterField').selectOption('phone');
    await panel.getByRole('button', { name: 'Adicionar campo' }).click();
    assert.equal(await panel.locator('[data-filter-field="phone"]').count(), 1);
    await panel.locator('[data-filter-field="phone"]').getByRole('button', { name: 'Remover campo' }).click();
    assert.equal(await panel.locator('[data-filter-field="phone"]').count(), 0);
    assert.deepEqual((await stateFrom(page)).leads, before);
  });

  await run('FILTER-04, FILTER-06 e FILTER-08 combinam responsável período e etapa por E', async page => {
    await goTo(page, 'Leads');
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

    await page.getByRole('button', { name: /Filtros/ }).click();
    await panel.locator('[data-filter-field="name"] input[name="filter-value"]').fill('registro impossível');
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.equal(await page.getByText('Nenhum Lead encontrado').isVisible(), true);
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

    await panel.getByRole('button', { name: 'Redefinir' }).click();
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

  await run('BOARD-03 agrupa os registros e mostra contagens no Kanban', async page => {
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.equal(await page.locator('#page-leads .kanban-column').count(), 3);
    assert.equal(await page.locator('#page-leads .kanban-card').count(), 5);
    const contactColumn = page.locator('[data-kanban-stage="Em contato"]');
    assert.match(await contactColumn.locator('.kanban-column-head').innerText(), /3/);
  });

  await run('BOARD-04 e BOARD-05 mudam etapa comum e desfazem atomicamente', async page => {
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    const mover = page.getByLabel('Mover Implantação Arkos Estética');
    await mover.selectOption('Negociação Revisão');
    let state = await stateFrom(page);
    assert.equal(state.deals.find(deal => deal.id === 'N-16312').stage, 'Negociação Revisão');
    await page.getByRole('button', { name: 'Desfazer' }).click();
    state = await stateFrom(page);
    assert.equal(state.deals.find(deal => deal.id === 'N-16312').stage, 'Orçamentos enviados');
  });

  await run('BOARD-06 protege Faturando e o Desfazer restaura responsável', async page => {
    await goTo(page, 'Negócios');
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
  });

  await run('BOARD-07, BOARD-08 e BOARD-10 protegem Lead e mantêm Kanban móvel operável', async page => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Leads');
    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    const board = page.locator('#page-leads .kanban-board');
    assert.ok((await board.evaluate(element => element.scrollWidth)) > (await board.evaluate(element => element.clientWidth)));
    const larissa = page.getByLabel('Mover Larissa Spinola');
    page.once('dialog', dialog => dialog.accept('Sem aderência'));
    await larissa.selectOption('Lead descartado');
    let state = await stateFrom(page);
    assert.equal(state.leads.find(lead => lead.id === 'L-1048').discardReason, 'Sem aderência');

    const rayana = page.getByLabel('Mover Rayana Gomes Ramos');
    page.once('dialog', dialog => dialog.accept());
    await rayana.selectOption('Lead convertido');
    state = await stateFrom(page);
    assert.equal(state.leads.find(lead => lead.id === 'L-1047').stage, 'Lead convertido');
    assert.ok(state.deals.some(deal => deal.contact === 'Rayana Gomes Ramos' && deal.stage === 'Em Contato'));
  });

  await run('DASH-01, DASH-03 e DASH-04 oferecem escopos e campos aplicáveis', async page => {
    await goTo(page, 'Visão geral');
    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    const panel = page.locator('#filterDialog');
    const scopes = panel.locator('[data-dashboard-filter-scope]');
    assert.deepEqual(await scopes.allTextContents(), ['Todos', 'Leads', 'Negócios']);
    await scopes.filter({ hasText: 'Leads' }).click();
    assert.match((await panel.locator('#addFilterField option').allTextContents()).join(' '), /Origem/);
    assert.match((await panel.locator('#addFilterField option').allTextContents()).join(' '), /Segmento/);
    await scopes.filter({ hasText: 'Negócios' }).click();
    const dealFields = (await panel.locator('#addFilterField option').allTextContents()).join(' ');
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
  });

  await run('DASH-02, DASH-07 e DASH-08 limitam Gestor e redefinem o conjunto', async page => {
    await selectProfile(page, 'u-manager');
    await goTo(page, 'Visão geral');
    const initialOpenDeals = await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText();
    await page.getByRole('button', { name: /Filtrar painel/ }).click();
    const panel = page.locator('#filterDialog');
    const users = await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"] option').allTextContents();
    assert.deepEqual(users, ['Marcelo Martins', 'Paula Pincetta', 'Vitor Costa']);
    await panel.locator('[data-filter-field="responsibleId"] select[name="filter-value"]').selectOption(['u-paula']);
    await panel.getByRole('button', { name: 'Pesquisar' }).click();
    assert.notEqual(await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText(), initialOpenDeals);
    await page.getByRole('button', { name: /Redefinir painel/ }).click();
    assert.equal(await page.locator('#page-dashboard .stat').nth(1).locator('strong').innerText(), initialOpenDeals);
    const state = await stateFrom(page);
    assert.equal(state.ui.dashboardScopeByUser['u-manager'], 'all');
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
