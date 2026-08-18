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
  await page.locator('#page-leads strong').filter({ hasText: name }).waitFor();
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
    await row.getByTitle('Editar').click();
    await page.locator('#entityDialog').getByLabel('Nome completo *').fill('Lead CRUD Editado');
    await page.getByRole('button', { name: 'Salvar registro' }).click();
    assert.equal(await page.locator('#page-leads strong').filter({ hasText: 'Lead CRUD Editado' }).count(), 1);

    page.once('dialog', dialog => dialog.accept());
    row = page.locator('#page-leads tbody tr').filter({ hasText: 'Lead CRUD Editado' });
    await row.getByTitle('Excluir').click();
    assert.equal(await page.getByText('Lead CRUD Editado', { exact: true }).count(), 0);
    assert.equal(Number(await page.locator('#leadNavCount').innerText()), initialCount);
  });

  await run('DEMO-07 recarga preserva alterações no navegador', async page => {
    await createLead(page, 'Lead Persistente');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await goTo(page, 'Leads');
    assert.equal(await page.locator('#page-leads strong').filter({ hasText: 'Lead Persistente' }).count(), 1);
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
    await row.locator('select').selectOption('Faturando');
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
    await row.getByRole('button', { name: 'Orçamento' }).click();
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
    await row.getByRole('button', { name: 'Orçamento' }).click();
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
