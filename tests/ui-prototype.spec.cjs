const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const BASE_URL = process.env.SMART_CRM_TEST_URL || 'http://localhost:8080/';
const TEST_FILTER = process.env.SMART_CRM_TEST_FILTER || '';
const TENANT_URL = new URL('cliente-a', BASE_URL).toString();
const AUTH_SESSION = {
  tenant_id: '00000000-0000-0000-0000-000000000001', tenant_slug: 'cliente-a',
  tenant_display_name: 'Cliente A', user_id: 'u-admin', user_name: 'Alexandre Martins',
  email: 'admin@cliente-a.test', role: 'Administrador'
};
const STORAGE_KEY = 'smart-crm-demo-v1';
const CONFIRMED_CACHE_KEY = 'smart-crm-confirmed-v1';
const LEAD_STAGES = ['Em contato', 'Lead descartado', 'Lead convertido'];
const DEAL_STAGES = [
  'Em Contato', 'Orçamento Proposta Preço', 'Orçamentos enviados',
  'Negociação Revisão', 'Pedido aprovado Consultar', 'Faturando',
  'Ganho', 'Orçamento Não Aprovado', 'Analisar falha'
];
const DEAL_STAGE_IDS = DEAL_STAGES.map((_, index) => `10000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`);

function defaultDealPipeline() {
  const semantics = ['open', 'open', 'open', 'open', 'open', 'open', 'won', 'lost', 'lost'];
  const colors = ['#2563EB', '#0EA5E9', '#14B8A6', '#8B5CF6', '#F59E0B', '#F97316', '#16A34A', '#DC2626', '#991B1B'];
  return {
    id: '20000000-0000-4000-8000-000000000001', name: 'Vendas CMS',
    pipelineVersion: 1, workspaceVersion: 1, defaultStageId: DEAL_STAGE_IDS[0], transferCounts: {},
    stages: DEAL_STAGES.map((name, index) => ({
      id: DEAL_STAGE_IDS[index], name, semanticType: semantics[index], color: colors[index],
      position: index, systemKey: index === 5 ? 'billing' : null, active: true,
      initial: index === 0, archivedAt: null
    }))
  };
}

function attachCanonicalDealStages(source, pipeline) {
  if (!source) return source;
  const byName = new Map(pipeline.stages.map(stage => [stage.name, stage]));
  for (const deal of source.deals || []) {
    const stage = pipeline.stages.find(candidate => candidate.id === deal.stageId) || byName.get(deal.stage);
    if (!stage) continue;
    deal.pipelineId = pipeline.id;
    deal.stageId = stage.id;
    deal.stage = stage.name;
  }
  return source;
}

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
  delete durable.ui;
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
  const api = apiByPage.get(page);
  const canonical = api?.state && !api.loadFailure ? clone(api.state) : {
    users: [], leads: [], contacts: [], companies: [], deals: [], notifications: [],
    customFieldSchemas: { leads: [], contacts: [], companies: [], deals: [] },
    moduleFieldSettings: {}
  };
  const key = uiStorageKey(api.session);
  let preferences = { filtersByUser: {}, savedFilters: [], viewModesByUser: {}, dashboardScopeByUser: {} };
  try { preferences = JSON.parse(await page.evaluate(storageKey => localStorage.getItem(storageKey), key)) || preferences; } catch (_) {}
  canonical.currentUserId = api.session.user_id;
  canonical.ui = preferences;
  const writable = await page.evaluate(() => document.documentElement.dataset.workspaceWritable === 'true');
  if (api?.initialized && writable && api.assertSynchronized && !api.writeFailure) {
    assert.deepEqual(durableState(canonical), api.state, 'estado durável em memória divergiu da API confirmada');
  }
  return canonical;
}
async function waitForMockState(page, predicate, timeoutMs = 5000) {
  const api = apiByPage.get(page);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (api.state && predicate(api.state)) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('estado canônico mockado não atingiu a condição esperada');
}

async function waitForPipelineWrites(page, count, timeoutMs = 5000) {
  const api = apiByPage.get(page);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (api.pipelineWrites.length >= count) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error(`o mock não recebeu ${count} atualização(ões) do funil`);
}

async function openFresh(options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1366, height: 768 } });
  const page = await context.newPage();
  const pipeline = clone(options.pipeline || defaultDealPipeline());
  const initialState = options.preloadState ? attachCanonicalDealStages(durableState(options.preloadState), pipeline) : null;
  const api = {
    initialized: Boolean(initialState), version: initialState ? 1 : 0, state: initialState,
    applicationVersion: options.applicationVersion || '0.3.3', versionFailure: Boolean(options.versionFailure),
    session: { ...AUTH_SESSION, ...(options.session || {}) },
    loadFailure: Boolean(options.loadFailure), writeFailure: false, writeGate: null, assertSynchronized: false,
    pipeline, pipelineFailure: Boolean(options.pipelineFailure), pipelineConflict: false,
    pipelineValidationFailure: null, pipelineServerFailure: false, pipelineWrites: [],
    pipelineHistory: clone(options.pipelineHistory || []), pipelineHistoryRequests: [],
    dealActivities: clone(options.dealActivities || {}), activityRequests: [],
    activityFailures: new Set(), activityGates: new Map(), observationWrites: [],
    observationFailuresRemaining: 0, observationByKey: new Map(), workspaceLoads: 0, workspaceWrites: [],
    companyActivities: clone(options.companyActivities || {}), companyActivityRequests: [],
    companyActivityFailures: new Set(), companyActivityGates: new Map(), companyObservationWrites: [],
    companyObservationFailuresRemaining: 0, companyObservationByKey: new Map(),
    companyDealRequests: [], companyDealFailures: new Set(), companyDealGates: new Map(),
    disableBillingAutomation: Boolean(options.disableBillingAutomation),
    deleted: { users: [], leads: [], contacts: [], companies: [], deals: [], quotes: [], notifications: [] }
  };
  apiByPage.set(page, api);
  await context.route('**/api/version', route => route.fulfill({
    status: api.versionFailure ? 503 : 200,
    contentType: 'application/json',
    body: JSON.stringify(api.versionFailure
      ? { error: { code: 'version_unavailable', message: 'Versão indisponível.' } }
      : { version: api.applicationVersion })
  }));
  await context.route('**/api/auth/session', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify(api.session)
  }));
  await context.route('**/api/deals/*/activities**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/deals\/([^/]+)\/activities$/);
    if (!match || request.method() !== 'GET') return route.continue();
    const dealId = decodeURIComponent(match[1]);
    api.activityRequests.push(request.url());
    const gate = api.activityGates.get(dealId);
    if (gate) await gate;
    if (api.activityFailures.has(dealId)) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Histórico indisponível.' } }) });
    }
    const category = url.searchParams.get('category');
    const limit = Number(url.searchParams.get('limit')) || 50;
    const offset = Number((url.searchParams.get('cursor') || '').replace(/^cursor-/, '')) || 0;
    const available = (api.dealActivities[dealId] || [])
      .filter(item => !category || item.category === category)
      .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt) || right.id - left.id);
    const items = available.slice(offset, offset + limit);
    const nextCursor = offset + limit < available.length ? `cursor-${offset + limit}` : null;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items, nextCursor }) });
  });
  await context.route('**/api/deals/*/observations', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/deals\/([^/]+)\/observations$/);
    if (!match || request.method() !== 'POST') return route.continue();
    const dealId = decodeURIComponent(match[1]);
    const payload = request.postDataJSON();
    api.observationWrites.push({ dealId, payload: clone(payload) });
    if (api.observationFailuresRemaining > 0) {
      api.observationFailuresRemaining -= 1;
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Não foi possível publicar a observação.' } }) });
    }
    let event = api.observationByKey.get(payload.idempotencyKey);
    if (!event) {
      const existing = api.dealActivities[dealId] || (api.dealActivities[dealId] = []);
      event = {
        id: Math.max(0, ...Object.values(api.dealActivities).flat().map(item => item.id)) + 1,
        category: 'observation', eventType: 'deal.observation_added',
        actor: { id: api.session.user_id, name: api.session.user_name, kind: 'user' },
        summary: 'Observação adicionada.', details: { text: payload.text.trim() },
        occurredAt: new Date(Date.UTC(2026, 9, 19, 18, existing.length, 0)).toISOString()
      };
      existing.unshift(event);
      api.observationByKey.set(payload.idempotencyKey, event);
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(event) });
  });
  await context.route('**/api/companies/*/activities**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/companies\/([^/]+)\/activities$/);
    if (!match || request.method() !== 'GET') return route.continue();
    const companyId = decodeURIComponent(match[1]);
    api.companyActivityRequests.push(request.url());
    const gate = api.companyActivityGates.get(companyId);
    if (gate) await gate;
    if (api.companyActivityFailures.has(companyId)) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Histórico indisponível.' } }) });
    }
    const category = url.searchParams.get('category');
    const limit = Number(url.searchParams.get('limit')) || 50;
    const offset = Number((url.searchParams.get('cursor') || '').replace(/^cursor-/, '')) || 0;
    const available = (api.companyActivities[companyId] || [])
      .filter(item => !category || item.category === category)
      .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt) || right.id - left.id);
    const items = available.slice(offset, offset + limit);
    const nextCursor = offset + limit < available.length ? `cursor-${offset + limit}` : null;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items, nextCursor }) });
  });
  await context.route('**/api/companies/*/observations', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/companies\/([^/]+)\/observations$/);
    if (!match || request.method() !== 'POST') return route.continue();
    const companyId = decodeURIComponent(match[1]);
    const payload = request.postDataJSON();
    api.companyObservationWrites.push({ companyId, payload: clone(payload) });
    if (api.companyObservationFailuresRemaining > 0) {
      api.companyObservationFailuresRemaining -= 1;
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Não foi possível publicar a observação.' } }) });
    }
    let event = api.companyObservationByKey.get(payload.idempotencyKey);
    if (!event) {
      const existing = api.companyActivities[companyId] || (api.companyActivities[companyId] = []);
      event = {
        id: Math.max(0, ...Object.values(api.companyActivities).flat().map(item => item.id)) + 1,
        category: 'observation', eventType: 'company.observation_added',
        actor: { id: api.session.user_id, name: api.session.user_name, kind: 'user' },
        summary: 'Observação adicionada.', details: { text: payload.text.trim() },
        occurredAt: new Date(Date.UTC(2026, 9, 19, 19, existing.length, 0)).toISOString()
      };
      existing.unshift(event);
      api.companyObservationByKey.set(payload.idempotencyKey, event);
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(event) });
  });
  await context.route('**/api/companies/*/deals', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/companies\/([^/]+)\/deals$/);
    if (!match || request.method() !== 'GET') return route.continue();
    const companyId = decodeURIComponent(match[1]);
    api.companyDealRequests.push(request.url());
    const gate = api.companyDealGates.get(companyId);
    if (gate) await gate;
    if (api.companyDealFailures.has(companyId)) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Resumo indisponível.' } }) });
    }
    const company = api.state.companies.find(candidate => candidate.id === companyId);
    if (!company) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'record_not_found', message: 'Empresa não encontrada.' } }) });
    const sessionUser = api.state.users.find(user => user.id === api.session.user_id);
    const visible = api.state.deals.filter(deal => {
      if (String(deal.company || '').trim().toLocaleLowerCase('pt-BR') !== String(company.name).trim().toLocaleLowerCase('pt-BR')) return false;
      if (api.session.role === 'Administrador') return true;
      if (api.session.role === 'Gestor') return deal.team === sessionUser?.team;
      return deal.responsibleId === api.session.user_id || (deal.assistants || []).includes(api.session.user_id);
    });
    const items = visible.map(deal => {
      const stage = api.pipeline.stages.find(candidate => candidate.id === deal.stageId);
      return {
        id: deal.id, title: deal.title, stageId: stage.id, stageName: stage.name,
        semanticType: stage.semanticType, responsibleId: deal.responsibleId,
        responsibleName: api.state.users.find(user => user.id === deal.responsibleId)?.name || null,
        amount: Number(deal.amount || 0).toFixed(2)
      };
    });
    const metric = semanticType => {
      const subset = items.filter(item => item.semanticType === semanticType);
      return { count: subset.length, amount: subset.reduce((sum, item) => sum + Number(item.amount), 0).toFixed(2) };
    };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ totalCount: items.length, open: metric('open'), won: metric('won'), lost: metric('lost'), items }) });
  });
  await context.route('**/api/deal-pipeline/history**', route => {
    const request = route.request();
    const url = new URL(request.url());
    api.pipelineHistoryRequests.push(request.url());
    if (api.session.role !== 'Administrador') {
      return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ error: { code: 'forbidden', message: 'Acesso negado.' } }) });
    }
    const before = Number(url.searchParams.get('before')) || null;
    const limit = Number(url.searchParams.get('limit')) || 50;
    const available = api.pipelineHistory.filter(item => before === null || item.id < before);
    const items = available.slice(0, limit);
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ items, nextBefore: items.length === limit ? items.at(-1).id : null })
    });
  });
  await context.route('**/api/deal-pipeline', route => {
    const request = route.request();
    if (request.method() === 'PUT') {
      const payload = request.postDataJSON();
      api.pipelineWrites.push(clone(payload));
      if (api.pipelineConflict) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'pipeline_version_conflict', message: 'Versão do funil desatualizada.', currentPipelineVersion: api.pipeline.pipelineVersion + 1 } }) });
      if (api.pipelineValidationFailure) return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: api.pipelineValidationFailure }) });
      if (api.pipelineServerFailure) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: 'Banco indisponível.' } }) });
      const beforePipeline = clone(api.pipeline);
      const previousById = new Map(api.pipeline.stages.map(stage => [stage.id, stage]));
      const transferCounts = {};
      for (const submitted of payload.stages.filter(stage => stage.archived && stage.id)) {
        const source = previousById.get(submitted.id);
        const targetId = payload.transfers?.[submitted.id];
        const target = previousById.get(targetId);
        const active = (api.state?.deals || []).filter(deal => deal.stageId === submitted.id);
        const deleted = (api.deleted.deals || []).filter(deal => deal.stageId === submitted.id);
        const total = active.length + deleted.length;
        if (total && (!target || target.id === submitted.id || !target.active)) {
          return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: { code: 'pipeline_archive_target_invalid', message: 'Escolha uma etapa ativa diferente.', path: `transfers.${submitted.id}` } }) });
        }
        transferCounts[submitted.id] = total;
        if (target) {
          for (const deal of [...active, ...deleted]) {
            deal.stageId = target.id;
            deal.pipelineId = api.pipeline.id;
            deal.stage = target.name;
          }
        }
      }
      const nextStages = payload.stages.map((stage, index) => {
        const previous = previousById.get(stage.id);
        return {
          id: stage.id || `30000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
          name: stage.name, semanticType: stage.semanticType, color: stage.color, position: index,
          systemKey: previous?.systemKey || null, active: !stage.archived, initial: stage.id === payload.defaultStageId,
          archivedAt: stage.archived ? '2026-10-01T00:00:00Z' : null
        };
      });
      api.pipeline.pipelineVersion += 1;
      if (Object.values(transferCounts).some(count => count > 0)) api.version += 1;
      api.pipeline.workspaceVersion = api.version;
      api.pipeline.defaultStageId = payload.defaultStageId;
      api.pipeline.transferCounts = transferCounts;
      api.pipeline.stages = nextStages.filter(stage => stage.active);
      api.pipelineHistory.unshift({
        id: Math.max(0, ...api.pipelineHistory.map(item => item.id)) + 1,
        pipelineId: api.pipeline.id, actorUserId: api.session.user_id,
        pipelineVersion: api.pipeline.pipelineVersion, action: 'pipeline.updated',
        actions: payload.stages.filter(stage => stage.archived).map(stage => ({ type: 'stage.archived', stageId: stage.id, transferCount: transferCounts[stage.id] || 0, targetStageId: payload.transfers?.[stage.id] || null })),
        beforeState: beforePipeline, afterState: clone(api.pipeline),
        transferSummary: Object.entries(payload.transfers || {}).map(([sourceStageId, targetStageId]) => ({ sourceStageId, targetStageId, count: transferCounts[sourceStageId] || 0 })),
        createdAt: '2026-10-01T10:30:00Z'
      });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(api.pipeline) });
    }
    return route.fulfill({
      status: api.pipelineFailure ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(api.pipelineFailure
        ? { error: { code: 'database_unavailable', message: 'Funil indisponível.' } }
        : api.pipeline)
    });
  });
  await context.route('**/api/workspace**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const workspacePaths = ['/api/workspace', '/api/workspace/bootstrap', '/api/workspace/reset', '/api/workspace/deleted', '/api/workspace/restore'];
    if (!workspacePaths.includes(url.pathname)) return route.continue();
    if (request.method() === 'GET' && url.pathname === '/api/workspace') {
      api.workspaceLoads += 1;
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
      api.state = attachCanonicalDealStages(durableState(payload.state), api.pipeline);
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
      api.workspaceWrites.push(clone(payload));
      const next = durableState(payload.state);
      for (const nextDeal of next.deals) {
        const previousDeal = api.state.deals.find(candidate => candidate.id === nextDeal.id);
        const nextStage = api.pipeline.stages.find(stage => stage.id === nextDeal.stageId);
        if (!previousDeal || previousDeal.stageId === nextDeal.stageId || nextStage?.systemKey !== 'billing' || api.disableBillingAutomation) continue;
        nextDeal.responsibleId = 'u-billing';
        nextDeal.team = 'Faturamento';
        next.notifications = next.notifications.filter(note => !(note.detail?.includes(nextDeal.id) && /Faturamento|Responsabilidade/.test(note.text)));
        const nextNotificationId = () => `NT-${Math.max(0, ...next.notifications.map(note => Number(String(note.id).split('-')[1]) || 0)) + 1}`;
        next.notifications.unshift({ id: nextNotificationId(), userId: 'u-billing', text: 'Responsabilidade alterada automaticamente.', detail: `${nextDeal.id} agora está com Equipe Faturamento`, time: 'Agora', read: false });
        next.notifications.unshift({ id: nextNotificationId(), userId: api.session.user_id, text: 'Automação de Faturamento executada.', detail: `${nextDeal.id} foi atribuído à Equipe Faturamento`, time: 'Agora', read: false });
        const events = api.dealActivities[nextDeal.id] || (api.dealActivities[nextDeal.id] = []);
        const nextActivityId = () => Math.max(0, ...Object.values(api.dealActivities).flat().map(item => item.id)) + 1;
        events.unshift({
          id: nextActivityId(), category: 'movement', eventType: 'deal.stage_changed',
          actor: { id: api.session.user_id, name: api.session.user_name, kind: 'user' },
          summary: `Etapa alterada de ${previousDeal.stage} para ${nextStage.name}.`,
          details: { fromStageId: previousDeal.stageId, fromStageName: previousDeal.stage, toStageId: nextStage.id, toStageName: nextStage.name, source: 'user' },
          occurredAt: '2026-10-19T18:00:00.000Z'
        });
        events.unshift({
          id: nextActivityId(), category: 'automation', eventType: 'deal.automation_executed',
          actor: { id: null, name: 'Sistema', kind: 'system' },
          summary: 'Automação de Faturamento executada com sucesso.',
          details: { automationKey: 'billing', automationName: 'Automação de Faturamento', result: 'success', actions: [{ type: 'responsible.changed', summary: 'Responsável alterado para Equipe Faturamento.' }, { type: 'notification.created', summary: 'Notificações emitidas.' }], failureCode: null },
          occurredAt: '2026-10-19T18:00:01.000Z'
        });
      }
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
  const tenantUrl = new URL(api.session.tenant_slug, BASE_URL).toString();
  await page.goto(tenantUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('#workspaceBanner').waitFor({ state: 'attached' });
  if (options.autoBootstrap !== false && !api.loadFailure && !api.initialized) {
    const confirm = page.getByRole('button', { name: 'Confirmar migração' });
    await confirm.waitFor();
    await confirm.click();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWritable === 'true');
  }
  await page.waitForFunction(() => document.documentElement.dataset.workspaceReady === 'true');
  return { context, page };
}

async function reloadReady(page, options = {}) {
  await page.reload({ waitUntil: 'domcontentloaded' });
  const api = apiByPage.get(page);
  if (options.autoBootstrap !== false && !api.loadFailure && !api.initialized) {
    await page.getByRole('button', { name: 'Confirmar migração' }).click();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWritable === 'true');
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
      session: { ...AUTH_SESSION },
      state: expected,
      loadFailure: false,
      writeFailure: false,
      writeGate: null,
      assertSynchronized: true,
      pipeline: clone(sourceApi.pipeline), pipelineFailure: false,
      deleted: { users: [], leads: [], contacts: [], companies: [], deals: [], quotes: [], notifications: [] }
    };
    apiByPage.set(independent, mirrorApi);
    await context.route('**/api/auth/session', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(AUTH_SESSION)
    }));
    await context.route('**/api/deal-pipeline', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(mirrorApi.pipeline)
    }));
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
    await independent.goto(TENANT_URL, { waitUntil: 'domcontentloaded' });
    await independent.locator('#workspaceBanner').waitFor({ state: 'attached' });
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
  if (TEST_FILTER && !name.includes(TEST_FILTER)) return;
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

async function openAuthPage(pathname, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  if (options.storageEntries) {
    await context.addInitScript(entries => {
      Object.entries(entries).forEach(([key, value]) => localStorage.setItem(key, value));
    }, options.storageEntries);
  }
  const authRequests = [];
  const workspaceRequests = [];
  let authenticated = options.authenticated === true;
  const session = { ...AUTH_SESSION, ...(options.session || {}) };
  if (options.cookie) {
    await context.addCookies([{
      name: '__Host-smartcrm_session', value: options.cookie, domain: 'localhost',
      path: '/', secure: true, httpOnly: true, sameSite: 'Strict'
    }]);
  }
  await context.route('**/api/auth/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    let body;
    try { body = request.postDataJSON(); } catch (_) { body = undefined; }
    authRequests.push({ method: request.method(), url: request.url(), headers: request.headers(), body });
    if (url.pathname === '/api/auth/session') {
      return authenticated
        ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session) })
        : route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unauthenticated', message: 'Autenticação necessária.' } }) });
    }
    if (url.pathname === '/api/auth/locate') {
      const identifier = body.identifier.trim().toLowerCase();
      if (options.locateFailure || identifier.includes('externo.example')) {
        return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'invalid_login', message: 'Não foi possível entrar com os dados informados.' } }) });
      }
      const slug = identifier.includes('/') ? identifier.split('/').filter(Boolean).at(-1) : identifier;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ slug, display_name: 'Cliente A' }) });
    }
    if (url.pathname === '/api/auth/login') {
      if (!options.loginSuccess) {
        return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'invalid_login', message: 'Não foi possível entrar com os dados informados.' } }) });
      }
      authenticated = true;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session) });
    }
    if (url.pathname === '/api/auth/logout') {
      authenticated = false;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ status: 404 });
  });
  await context.route('**/api/workspace**', route => {
    workspaceRequests.push(route.request().url());
    const workspaceState = options.workspaceState ? clone(options.workspaceState) : null;
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ initialized: Boolean(workspaceState), version: workspaceState ? 1 : 0, state: workspaceState })
    });
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const target = pathname === '/' ? BASE_URL : new URL(pathname.replace(/^\//, ''), BASE_URL).toString();
  if (options.cookie && pathname !== '/') {
    await page.route(target, async route => {
      const headers = { ...route.request().headers(), cookie: '' };
      await route.fulfill({ response: await route.fetch({ headers }) });
    });
  }
  await page.goto(target, { waitUntil: 'domcontentloaded' });
  return { context, page, authRequests, workspaceRequests };
}

async function runAuth(name, pathname, test, options = {}) {
  if (TEST_FILTER && !name.includes(TEST_FILTER)) return;
  const opened = await openAuthPage(pathname, options);
  try {
    await test(opened);
    passed += 1;
    console.log(`PASS ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`FAIL ${name}\n${error.stack}`);
  } finally {
    await opened.context.close();
  }
}

async function goTo(page, name) {
  await page.locator('.nav').getByRole('button', { name: new RegExp(name) }).click();
}

async function selectProfile(page, userId) {
  const api = apiByPage.get(page);
  const user = api.state.users.find(candidate => candidate.id === userId);
  assert.ok(user, `usuário ${userId} ausente do estado mockado`);
  api.session = { ...api.session, user_id: user.id, user_name: user.name, email: user.email || `${user.id}@local.invalid`, role: user.role };
  await reloadReady(page);
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

function minimalWorkspace() {
  return {
    currentUserId: 'u-admin',
    users: [
      { id: 'u-admin', name: 'Estado Local Admin', role: 'Administrador', team: 'Gestão', status: 'Ativo' },
      { id: 'u-paula', name: 'Estado Local Paula', role: 'Administrador', team: 'Vendas CMS', status: 'Ativo' }
    ],
    leads: [], contacts: [], companies: [], deals: [], notifications: [],
    customFieldSchemas: { leads: [], contacts: [], companies: [], deals: [] },
    moduleFieldSettings: {
      leads: { hiddenStandardFields: [], hiddenCustomFieldKeys: [] },
      contacts: { hiddenStandardFields: [], hiddenCustomFieldKeys: [] },
      companies: { hiddenStandardFields: [], hiddenCustomFieldKeys: [] },
      deals: { hiddenStandardFields: [], hiddenCustomFieldKeys: [] }
    },
    ui: { filtersByUser: {}, savedFilters: [], viewModesByUser: {}, dashboardScopeByUser: {} }
  };
}

function workspaceWithDeal(stage = DEAL_STAGES[2]) {
  const workspace = minimalWorkspace();
  workspace.deals.push({
    id: 'deal-pipeline-active', title: 'Negócio na etapa ocupada', company: 'Empresa Pipeline',
    contact: 'Contato Pipeline', amount: 2500, stage, responsibleId: 'u-admin', assistants: [],
    updatedAt: '1 out, 10:00', quotes: [], stageHistory: []
  });
  return workspace;
}

function pipelineAuditHistory(total = 55) {
  return Array.from({ length: total }, (_, index) => {
    const id = total - index;
    return {
      id,
      pipelineId: defaultDealPipeline().id,
      actorUserId: id === total ? 'u-admin' : 'u-paula',
      pipelineVersion: id + 1,
      action: id === total ? 'pipeline.stage_archived' : 'pipeline.updated',
      actions: [{ type: 'stage.archived', stageId: DEAL_STAGE_IDS[2], targetStageId: DEAL_STAGE_IDS[6] }],
      beforeState: { defaultStageId: DEAL_STAGE_IDS[0], stageName: 'Orçamentos enviados' },
      afterState: { defaultStageId: DEAL_STAGE_IDS[0], stageName: 'Ganho' },
      transferSummary: [{ sourceStageId: DEAL_STAGE_IDS[2], targetStageId: DEAL_STAGE_IDS[6], count: 2 }],
      createdAt: `2026-10-01T10:${String(id % 60).padStart(2, '0')}:00Z`
    };
  });
}

function dealActivitySeries(total = 52) {
  const categories = ['movement', 'automation', 'observation'];
  return Array.from({ length: total }, (_, index) => {
    const id = total - index;
    const category = categories[index % categories.length];
    const details = category === 'movement'
      ? { fromStageId: DEAL_STAGE_IDS[0], fromStageName: 'Em Contato', toStageId: DEAL_STAGE_IDS[1], toStageName: 'Orçamento Proposta Preço', source: 'user' }
      : category === 'automation'
        ? { automationKey: 'billing', automationName: 'Automação de Faturamento', result: 'success', actions: [{ type: 'responsible.changed', summary: 'Responsável alterado para Equipe Faturamento.' }], failureCode: null }
        : { text: `Observação ${id}` };
    return {
      id, category, eventType: `deal.test_${category}`,
      actor: category === 'automation'
        ? { id: null, name: 'Sistema', kind: 'system' }
        : { id: 'u-admin', name: 'Alexandre Martins', kind: 'user' },
      summary: `Evento ${id} ${category}`,
      details,
      occurredAt: new Date(Date.UTC(2026, 9, 19, 15, id, 0)).toISOString()
    };
  });
}

function companyActivitySeries(total = 52) {
  return Array.from({ length: total }, (_, index) => {
    const id = total - index;
    const category = index % 2 === 0 ? 'change' : 'observation';
    return {
      id, category, eventType: category === 'change' ? 'company.updated' : 'company.observation_added',
      actor: { id: 'u-admin', name: 'Alexandre Martins', kind: 'user' },
      summary: category === 'change' ? `Empresa atualizada ${id}` : `Observação ${id}`,
      details: category === 'change'
        ? { changes: [
          { field: 'name', label: 'Nome', before: `Arkos ${id - 1}`, after: `Arkos ${id}` },
          { field: 'phone', label: 'Telefone', before: null, after: '(11) 3456-7788' },
          { field: 'custom:commercial-secret', label: 'Segredo comercial', before: null, after: null, redacted: true }
        ] }
        : { text: `Contexto da empresa ${id}` },
      occurredAt: new Date(Date.UTC(2026, 9, 19, 16, id, 0)).toISOString()
    };
  });
}

function uiStorageKey(session) {
  return `smart-crm-ui-v1:${session.tenant_id}:${session.user_id}`;
}

async function storageEntries(page) {
  return page.evaluate(() => Object.fromEntries(
    [...Array(localStorage.length)].map((_, index) => {
      const key = localStorage.key(index);
      return [key, localStorage.getItem(key)];
    })
  ));
}
(async () => {
  browser = await chromium.launch({ channel: process.env.SMART_CRM_BROWSER || 'chrome', headless: true });
  await runAuth('MT-01 raiz exibe localizador sem consultar workspace', '/', async ({ page, authRequests, workspaceRequests }) => {
    assert.equal(await page.locator('#tenantLocator').isVisible(), true);
    assert.equal(await page.locator('#crmApp').isHidden(), true);
    assert.equal(authRequests.length, 0);
    assert.equal(workspaceRequests.length, 0);
  });

  await runAuth('MT-01 localizador normaliza slug e abre login tenant', '/', async ({ page, authRequests }) => {
    await page.getByLabel('Empresa', { exact: true }).fill('Cliente-A');
    await page.getByRole('button', { name: 'Continuar' }).click();
    await page.locator('#tenantLogin').waitFor({ state: 'visible' });
    assert.equal(new URL(page.url()).pathname, '/cliente-a');
    assert.deepEqual(authRequests.find(item => item.url.includes('/locate')).body, { identifier: 'Cliente-A' });
  });

  await runAuth('MT-01 localizador aceita URL do domínio esperado', '/', async ({ page, authRequests }) => {
    await page.getByLabel('Empresa', { exact: true }).fill('https://sc2030.brbots.com/cliente-a');
    await page.getByRole('button', { name: 'Continuar' }).click();
    await page.locator('#tenantLogin').waitFor({ state: 'visible' });
    assert.equal(new URL(page.url()).pathname, '/cliente-a');
    assert.match(authRequests[0].body.identifier, /^https:\/\/sc2030\.brbots\.com\//);
  });

  await runAuth('MT-01 localizador rejeita host externo sem redirecionar', '/', async ({ page }) => {
    await page.getByLabel('Empresa', { exact: true }).fill('https://externo.example/cliente-a');
    await page.getByRole('button', { name: 'Continuar' }).click();
    await page.locator('#locatorError').filter({ hasText: 'Não foi possível entrar' }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/');
    assert.equal(await page.locator('#locatorError').innerText(), 'Não foi possível entrar com os dados informados.');
  }, { locateFailure: true });

  await runAuth('MT-01 rota tenant sem sessão exibe login', '/cliente-a', async ({ page }) => {
    assert.equal(await page.locator('#tenantLogin').isVisible(), true);
    assert.equal(await page.locator('#crmApp').isHidden(), true);
    assert.match(await page.locator('#tenantLogin').innerText(), /cliente-a/i);
  });

  await runAuth('MT-02 sessão válida abre o shell sem tela de login', '/cliente-a', async ({ page, workspaceRequests }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#tenantLogin').isHidden(), true);
    assert.equal(workspaceRequests.length, 1);
  }, { authenticated: true });

  await runAuth('MT-01 login envia somente slug email e senha', '/cliente-a', async ({ page, authRequests }) => {
    await page.locator('#tenantLoginForm').getByLabel('E-mail').fill('ana@cliente.test');
    await page.locator('#tenantLoginForm').getByLabel('Senha').fill('senha segura 123');
    await page.getByRole('button', { name: 'Entrar' }).click();
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    const login = authRequests.find(item => item.url.includes('/login'));
    assert.deepEqual(login.body, { slug: 'cliente-a', email: 'ana@cliente.test', password: 'senha segura 123' });
    assert.equal(login.headers.authorization, undefined);
  }, { loginSuccess: true });

  await runAuth('MT-01 falha de login usa mensagem genérica', '/cliente-a', async ({ page }) => {
    await page.locator('#tenantLoginForm').getByLabel('E-mail').fill('ana@cliente.test');
    await page.locator('#tenantLoginForm').getByLabel('Senha').fill('senha incorreta 123');
    await page.getByRole('button', { name: 'Entrar' }).click();
    await page.locator('#loginError').filter({ hasText: 'Não foi possível entrar' }).waitFor();
    assert.equal(await page.locator('#loginError').innerText(), 'Não foi possível entrar com os dados informados.');
    assert.equal(await page.locator('#crmApp').isHidden(), true);
  });

  await runAuth('MT-03 sessão de outro tenant não troca a rota', '/cliente-a', async ({ page, workspaceRequests }) => {
    await page.locator('#tenantLogin').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#crmApp').isHidden(), true);
    assert.equal(workspaceRequests.length, 0);
    assert.equal(new URL(page.url()).pathname, '/cliente-a');
  }, { authenticated: true, session: { tenant_slug: 'cliente-b' } });

  await runAuth('MT-02 sessão é lida somente pelo cookie', '/cliente-a', async ({ page, authRequests }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    const sessionRequest = authRequests.find(item => item.url.includes('/session'));
    assert.match(sessionRequest.headers.cookie || '', /__Host-smartcrm_session=opaque-browser-cookie/);
    assert.equal(sessionRequest.headers.authorization, undefined);
    assert.equal(new URL(sessionRequest.url).search, '');
  }, { authenticated: true, cookie: 'opaque-browser-cookie' });

  await runAuth('MT-02 JavaScript não persiste token de sessão', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
    assert.doesNotMatch(storage, /opaque-browser-cookie|smartcrm_session|token/i);
  }, { authenticated: true, cookie: 'opaque-browser-cookie' });

  await runAuth('MT-02 logout revoga e limpa o shell em memória', '/cliente-a', async ({ page, authRequests }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'Aguardar' }).click();
    await page.getByRole('button', { name: 'Sair' }).click();
    await page.locator('#tenantLogin').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#crmApp').isHidden(), true);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.authenticated), 'false');
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceReady), 'false');
    assert.equal(authRequests.filter(item => item.url.includes('/logout')).length, 1);
  }, { authenticated: true });

  await run('HIST-08 exibe a versão canônica no rodapé autenticado', async page => {
    const version = page.locator('#appVersion');
    await version.waitFor();
    assert.equal(await version.innerText(), 'v0.3.3');
    assert.equal(await version.getAttribute('aria-label'), 'Versão instalada 0.3.3');
  });

  await run('HIST-08 falha de metadados não bloqueia a operação nem inventa versão', async page => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#appVersion').isHidden(), true);
    assert.equal(await page.locator('#page-dashboard').isVisible(), true);
  }, { preloadState: minimalWorkspace(), versionFailure: true });


  const SELLER_SESSION = {
    ...AUTH_SESSION,
    user_id: 'u-paula',
    user_name: 'Paula Identidade Servidor',
    email: 'paula@cliente-a.test',
    role: 'Vendedor'
  };
  const TENANT_B_SESSION = {
    ...SELLER_SESSION,
    tenant_id: '00000000-0000-0000-0000-000000000002',
    tenant_slug: 'cliente-b',
    tenant_display_name: 'Cliente B'
  };

  await runAuth('MT-04 identidade do servidor é exibida sem seletor editável', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#profileSelect').count(), 0);
    assert.equal(await page.locator('#sessionUserName').innerText(), SELLER_SESSION.user_name);
    assert.equal(await page.locator('#sessionUserRole').innerText(), SELLER_SESSION.role);
  }, { authenticated: true, session: SELLER_SESSION, workspaceState: minimalWorkspace() });

  await runAuth('MT-04 currentUserId e role do workspace não substituem a sessão', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('[data-admin-nav]').evaluateAll(elements => elements.every(element => element.hidden)), true);
    assert.match(await page.locator('#page-dashboard').innerText(), /perfil Vendedor/);
    assert.doesNotMatch(await page.locator('#sessionUserName').innerText(), /Estado Local/);
  }, { authenticated: true, session: SELLER_SESSION, workspaceState: minimalWorkspace() });

  await runAuth('MT-04 snapshot legado no localStorage não personifica usuário', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#sessionUserName').innerText(), SELLER_SESSION.user_name);
    assert.equal(await page.locator('[data-admin-nav]').evaluateAll(elements => elements.every(element => element.hidden)), true);
    assert.equal((await storageEntries(page))[STORAGE_KEY], undefined);
  }, {
    authenticated: true,
    session: SELLER_SESSION,
    workspaceState: minimalWorkspace(),
    storageEntries: { [STORAGE_KEY]: JSON.stringify(minimalWorkspace()) }
  });

  await runAuth('MT-03 cache comercial confirmado legado é removido', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal((await storageEntries(page))[CONFIRMED_CACHE_KEY], undefined);
  }, {
    authenticated: true,
    session: SELLER_SESSION,
    workspaceState: minimalWorkspace(),
    storageEntries: { [CONFIRMED_CACHE_KEY]: JSON.stringify({ version: 7, state: minimalWorkspace() }) }
  });

  await runAuth('MT-02 Web Storage não contém credencial sessão perfil ou snapshot comercial', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    const entries = await storageEntries(page);
    for (const value of Object.values(entries)) {
      assert.doesNotMatch(value, /opaque-browser-cookie|password|Administrador|tenant_slug|session/i);
      const parsed = JSON.parse(value);
      for (const field of ['users', 'leads', 'contacts', 'companies', 'deals', 'notifications', 'currentUserId', 'role']) {
        assert.equal(Object.hasOwn(parsed, field), false);
      }
    }
  }, { authenticated: true, session: SELLER_SESSION, workspaceState: minimalWorkspace(), cookie: 'opaque-browser-cookie' });

  await runAuth('MT-04 preferência de UI usa namespace tenant e usuário da sessão', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    await goTo(page, 'Leads');
    await page.locator('[data-search="leads"]').fill('somente preferência');
    const entries = await storageEntries(page);
    const expectedKey = uiStorageKey(SELLER_SESSION);
    assert.deepEqual(Object.keys(entries), [expectedKey]);
    const preferences = JSON.parse(entries[expectedKey]);
    assert.equal(preferences.filtersByUser['u-paula'].leads.query, 'somente preferência');
  }, { authenticated: true, session: SELLER_SESSION, workspaceState: minimalWorkspace() });

  await runAuth('MT-04 preferência adulterada não eleva perfil nem identidade', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#sessionUserRole').innerText(), 'Vendedor');
    assert.equal(await page.locator('[data-admin-nav]').evaluateAll(elements => elements.every(element => element.hidden)), true);
  }, {
    authenticated: true,
    session: SELLER_SESSION,
    workspaceState: minimalWorkspace(),
    storageEntries: { [uiStorageKey(SELLER_SESSION)]: JSON.stringify({ role: 'Administrador', currentUserId: 'u-admin', filtersByUser: {} }) }
  });

  await runAuth('MT-04 tentativa DOM de abrir admin falha fechada pela identidade imutável', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    const adminNav = page.locator('[data-view="admin"]');
    await adminNav.evaluate(element => { element.hidden = false; });
    await adminNav.click();
    assert.equal(await page.locator('#page-admin').isVisible(), false);
    assert.equal(await page.locator('#page-dashboard').isVisible(), true);
    assert.equal(await page.locator('#sessionUserRole').innerText(), 'Vendedor');
  }, { authenticated: true, session: SELLER_SESSION, workspaceState: minimalWorkspace() });

  await runAuth('MT-03 preferência do tenant A não é consumida no tenant B', '/cliente-b', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    await goTo(page, 'Leads');
    assert.equal(await page.locator('[data-search="leads"]').inputValue(), '');
    const entries = await storageEntries(page);
    assert.ok(entries[uiStorageKey(SELLER_SESSION)]);
    assert.ok(entries[uiStorageKey(TENANT_B_SESSION)]);
  }, {
    authenticated: true,
    session: TENANT_B_SESSION,
    workspaceState: minimalWorkspace(),
    storageEntries: {
      [uiStorageKey(SELLER_SESSION)]: JSON.stringify({
        filtersByUser: { 'u-paula': { leads: { query: 'A_ONLY', criteria: {} } } },
        savedFilters: [], viewModesByUser: {}, dashboardScopeByUser: {}
      })
    }
  });

  await runAuth('MT-04 preferência de outro usuário do mesmo tenant fica isolada', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    await goTo(page, 'Leads');
    assert.equal(await page.locator('[data-search="leads"]').inputValue(), '');
    const entries = await storageEntries(page);
    assert.ok(entries[uiStorageKey(AUTH_SESSION)]);
    assert.ok(entries[uiStorageKey(SELLER_SESSION)]);
  }, {
    authenticated: true,
    session: SELLER_SESSION,
    workspaceState: minimalWorkspace(),
    storageEntries: {
      [uiStorageKey(AUTH_SESSION)]: JSON.stringify({
        filtersByUser: { 'u-admin': { leads: { query: 'ADMIN_ONLY', criteria: {} } } },
        savedFilters: [], viewModesByUser: {}, dashboardScopeByUser: {}
      })
    }
  });

  await runAuth('MT-04 preferência corrompida é descartada sem conceder acesso', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    assert.equal(await page.locator('[data-admin-nav]').evaluateAll(elements => elements.every(element => element.hidden)), true);
    const value = (await storageEntries(page))[uiStorageKey(SELLER_SESSION)];
    assert.doesNotThrow(() => JSON.parse(value));
  }, {
    authenticated: true,
    session: SELLER_SESSION,
    workspaceState: minimalWorkspace(),
    storageEntries: { [uiStorageKey(SELLER_SESSION)]: '{invalid-json' }
  });

  await runAuth('MT-02 logout não deixa identidade nem dados comerciais no Web Storage', '/cliente-a', async ({ page }) => {
    await page.locator('#crmApp').waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'Sair' }).click();
    await page.locator('#tenantLogin').waitFor({ state: 'visible' });
    const entries = await storageEntries(page);
    assert.equal(await page.locator('#sessionUserName').innerText(), '');
    assert.equal(Object.keys(entries).every(key => key.startsWith('smart-crm-ui-v1:')), true);
    Object.values(entries).forEach(value => {
      assert.doesNotMatch(value, /Estado Local|opaque-browser-cookie|Administrador|tenant_slug/i);
    });
  }, { authenticated: true, session: SELLER_SESSION, workspaceState: minimalWorkspace(), cookie: 'opaque-browser-cookie' });
  await run('DBP-02 e DBP-03 permitem ao Admin confirmar contagens antes do bootstrap', async page => {
    const dialog = page.locator('#bootstrapDialog');
    assert.equal(await dialog.isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceWritable), 'false');
    assert.equal(await dialog.getByRole('button', { name: 'Confirmar migração' }).isDisabled(), false);
    assert.match(await dialog.innerText(), /5\s+Leads/);
    assert.match(await dialog.innerText(), /4\s+Contatos/);
    assert.match(await dialog.innerText(), /4\s+Empresas/);
    assert.match(await dialog.innerText(), /6\s+Negócios/);

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

  await run('DBP-21 não usa cache comercial quando a API falha', async page => {
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
      key: CONFIRMED_CACHE_KEY,
      value: { version: 9, state: apiByPage.get(page).state }
    });
    apiByPage.get(page).loadFailure = true;
    await reloadReady(page);
    assert.equal((await stateFrom(page)).leads.length, 0);
    assert.equal(await page.evaluate(key => localStorage.getItem(key), CONFIRMED_CACHE_KEY), null);
    assert.equal(await page.locator('#workspaceBanner').innerText(), 'Banco indisponível. Alterações bloqueadas.');
    assert.equal(await page.evaluate(() => document.documentElement.dataset.workspaceWritable), 'false');
    await page.getByRole('button', { name: /Novo Lead/ }).click();
    assert.equal(await page.locator('#entityDialog').getAttribute('open'), null);
  });

  await run('DBP-21 não usa seed comercial quando a API falha', async page => {
    const state = await stateFrom(page);
    assert.equal(state.leads.length, 0);
    assert.equal(state.deals.length, 0);
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
    await secondContext.route('**/api/auth/session', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(AUTH_SESSION)
    }));
    await secondContext.route('**/api/workspace**', route => {
      const request = route.request();
      if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/workspace') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ initialized: true, version: api.version, state: api.state }) });
      }
      return route.continue();
    });
    const secondPage = await secondContext.newPage();
    apiByPage.set(secondPage, api);
    await secondPage.goto(TENANT_URL, { waitUntil: 'domcontentloaded' });
    await secondPage.waitForFunction(() => document.documentElement.dataset.workspaceReady === 'true');
    assert.equal(await secondPage.locator('#page-dashboard').getByText('Lead confirmado pela API').count(), 1);
    assert.equal((await stateFrom(secondPage)).leads.some(lead => lead.name === 'Lead confirmado pela API'), true);
    await secondContext.close();
  });

  await run('DBP-09 só confirma visualmente depois da versão persistida', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    const beforeState = clone(api.state);
    let releaseWrite;
    api.writeGate = new Promise(resolve => { releaseWrite = resolve; });

    await createLead(page, 'Lead aguardando confirmação', { waitForSaved: false });
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting === 'true');

    assert.equal(api.version, beforeVersion);
    assert.equal(await page.getByText('Lead criado com sucesso.', { exact: true }).count(), 0);
    assert.deepEqual(api.state, beforeState);

    releaseWrite();
    await page.getByText('Lead criado com sucesso.', { exact: true }).waitFor();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting === 'false');

    assert.equal(api.version, beforeVersion + 1);
    assert.equal(api.state.leads.some(lead => lead.name === 'Lead aguardando confirmação'), true);
  });

  await run('DBP-16 mantém preferências namespaced e sessão sem incrementar a versão', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    await goTo(page, 'Leads');
    await page.getByPlaceholder('Buscar em leads...').fill('Larissa');
    await selectProfile(page, 'u-paula');
    const local = await stateFrom(page);
    const adminPreferences = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), uiStorageKey(AUTH_SESSION));
    assert.equal(api.version, beforeVersion);
    assert.equal(local.currentUserId, 'u-paula');
    assert.equal(adminPreferences.filtersByUser['u-admin'].leads.query, 'Larissa');
    assert.equal(Object.hasOwn(api.state, 'currentUserId'), false);
    assert.equal(Object.hasOwn(api.state, 'ui'), false);
  });

  await run('DBP-22 reverte a alteração sem gravar cache comercial quando o PUT falha', async page => {
    const api = apiByPage.get(page);
    const beforeVersion = api.version;
    const before = clone(api.state);
    api.writeFailure = true;
    await createLead(page, 'Lead que deve falhar', { waitForSaved: false });
    await page.getByText('Não foi possível salvar no banco.', { exact: true }).waitFor();
    await page.waitForFunction(() => document.documentElement.dataset.workspaceWriting === 'false');
    assert.deepEqual(durableState(await stateFrom(page)), before);
    assert.equal(api.version, beforeVersion);
    assert.equal(Object.keys(await storageEntries(page)).some(key => [STORAGE_KEY, CONFIRMED_CACHE_KEY].includes(key)), false);
  });

  await run('DBP-10 recarrega o estado canônico após conflito de versão', async page => {
    const api = apiByPage.get(page);
    const loadsBeforeConflict = api.workspaceLoads;
    api.version += 1;
    api.state.leads[0].name = 'Lead atualizado em outra sessão';
    await createLead(page, 'Lead em conflito', { waitForSaved: false });
    await page.getByText('Dados atualizados em outra sessão. A versão atual foi recarregada.', { exact: true }).waitFor();
    await page.locator('#page-leads .entity-link').filter({ hasText: 'Lead atualizado em outra sessão' }).waitFor();
    assert.equal(api.workspaceLoads, loadsBeforeConflict + 1);
    assert.equal(await page.locator('#page-leads .entity-link').filter({ hasText: 'Lead em conflito' }).count(), 0);
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
    await setMockWorkspace(page, legacy);
    await reloadReady(page);

    await page.evaluate(() => saveState());
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
    await setMockWorkspace(page, legacy);
    await reloadReady(page);

    await page.evaluate(() => saveState());
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

  await run('DEMO-04 Administrador navega pelos destinos autorizados', async page => {
    const destinations = [
      ['Visão geral', 'Visão geral'], ['Leads', 'Leads'], ['Contatos', 'Contatos'],
      ['Empresas', 'Empresas'], ['Negócios', 'Negócios'], ['Notificações', 'Notificações'],
      ['Funil de negócios', 'Funil de negócios'],
      ['Usuários e permissões', 'Usuários e permissões']
    ];
    assert.equal(await page.locator('.nav button:visible').count(), 8);
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

  await run('PCCP-04 a PCCP-07 mostram a Empresa vinculada na ficha do Contato', async page => {
    let workspace = await stateFrom(page);
    workspace.contacts.find(item => item.id === 'C-2281').company = '  arkos estética  ';
    await setMockWorkspace(page, workspace);
    await reloadReady(page);
    await goTo(page, 'Contatos');
    await page.getByRole('button', { name: 'Ana Berclay', exact: true }).click();

    let companyCard = page.locator('#drawerCompanySummary');
    await companyCard.waitFor({ state: 'visible' });
    assert.equal(await companyCard.getAttribute('hidden'), null);
    assert.match(await companyCard.innerText(), /empresa vinculada/i);
    assert.match(await companyCard.innerText(), /Arkos Estética/);
    assert.match(await companyCard.innerText(), /Médico e Hospitalar/);
    assert.ok((await companyCard.innerText()).includes('São Paulo / SP'));
    assert.ok((await companyCard.innerText()).includes('(11) 3456-7788'));
    await page.getByRole('button', { name: 'Cancelar' }).click();

    workspace = await stateFrom(page);
    workspace.contacts.find(item => item.id === 'C-2281').company = 'Empresa sem cadastro';
    await setMockWorkspace(page, workspace);
    await reloadReady(page);
    await goTo(page, 'Contatos');
    await page.getByRole('button', { name: 'Ana Berclay', exact: true }).click();
    companyCard = page.locator('#drawerCompanySummary');
    await companyCard.waitFor({ state: 'visible' });
    assert.match(await companyCard.innerText(), /Empresa sem cadastro/);
    assert.match(await companyCard.innerText(), /Cadastro não localizado/);
    await page.getByRole('button', { name: 'Cancelar' }).click();

    workspace = await stateFrom(page);
    workspace.contacts.find(item => item.id === 'C-2281').company = '';
    await setMockWorkspace(page, workspace);
    await reloadReady(page);
    await goTo(page, 'Contatos');
    await page.getByRole('button', { name: 'Ana Berclay', exact: true }).click();
    companyCard = page.locator('#drawerCompanySummary');
    await companyCard.waitFor({ state: 'visible' });
    assert.match(await companyCard.innerText(), /Nenhuma empresa vinculada/);
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
      await drawer.locator('#entityDrawerTitle').waitFor({ state: 'visible' });
      assert.equal(await drawer.locator('#entityDrawerTitle').innerText(), title);
      assert.equal(await drawer.getByLabel(fieldLabel).inputValue(), fieldValue);
      const customFieldsTab = drawer.getByRole('tab', { name: 'Campos adicionais' });
      assert.equal(await customFieldsTab.isVisible(), true);
      if (view === 'Contatos') {
        await customFieldsTab.click();
        assert.match(await drawer.locator('#drawerCustomPanel').innerText(), /Nenhum campo adicional visível\./);
        assert.equal(await drawer.locator('#drawerAddCustomField').isDisabled(), true);
        assert.equal(await drawer.getByRole('button', { name: 'Adicionar campo' }).isDisabled(), true);
      }
      if (view === 'Negócios') assert.equal(await drawer.locator('#drawerTabs [role="tab"]:visible').count(), 3);
      assert.match(await page.locator('#entityDrawerSubtitle').innerText(), new RegExp(id));
      await page.waitForTimeout(250);
      const box = await drawer.boundingBox();
      const viewportWidth = await page.evaluate(() => window.innerWidth);
      if (['Empresas', 'Negócios'].includes(view)) {
        assert.equal(Math.round(box.width), Math.min(1600, viewportWidth - 32));
        assert.equal(await drawer.getAttribute('data-layout'), 'wide');
      } else {
        assert.ok(box.x > viewportWidth / 2 && Math.abs(box.width - 560) <= 1);
        assert.equal(await drawer.getAttribute('data-layout'), 'compact');
      }
      assert.ok(Math.abs(box.x + box.width - viewportWidth) <= 1);
      assert.equal(await page.locator(`#page-${{ Leads: 'leads', Contatos: 'contacts', Empresas: 'companies', Negócios: 'deals' }[view]}`).isVisible(), true);
      assert.equal(await page.getByTitle('Editar').count(), 0);
      await drawer.getByRole('button', { name: 'Cancelar' }).click();
      assert.doesNotMatch(await drawer.getAttribute('class'), /open/);
    }
    assert.deepEqual(await stateFrom(page), before);
  });

  await run('HIST-04 cria shell amplo acessível para Negócio e Empresa sem alterar outros drawers', async page => {
    await page.setViewportSize({ width: 1800, height: 1000 });
    await goTo(page, 'Negócios');
    const dealTrigger = page.getByRole('button', { name: 'Implantação Arkos Estética', exact: true });
    await dealTrigger.click();
    const drawer = page.locator('#entityDrawer');
    await page.waitForTimeout(250);
    const dealBox = await drawer.boundingBox();
    assert.equal(Math.round(dealBox.width), 1600);
    assert.equal(Math.round(dealBox.x), 200);
    assert.equal(await drawer.getAttribute('data-entity'), 'deal');
    const dealData = drawer.getByRole('region', { name: 'Dados do negócio' });
    const dealActivity = drawer.getByRole('region', { name: 'Atividade do negócio' });
    assert.equal(await dealData.isVisible(), true);
    assert.equal(await dealActivity.isVisible(), true);
    const dealDataBox = await dealData.boundingBox();
    const dealActivityBox = await dealActivity.boundingBox();
    assert.ok(dealDataBox.x < dealActivityBox.x);
    assert.equal(await drawer.getByRole('tab', { name: 'Orçamentos' }).isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await dealTrigger.evaluate(element => document.activeElement === element), true);

    await goTo(page, 'Empresas');
    const companyTrigger = page.getByRole('button', { name: 'Arkos Estética', exact: true });
    await companyTrigger.click();
    await page.waitForTimeout(250);
    assert.equal(await drawer.getAttribute('data-entity'), 'company');
    assert.equal(await drawer.getByRole('region', { name: 'Informações da empresa' }).isVisible(), true);
    const companyWorkspace = drawer.getByRole('region', { name: 'Relacionamento da empresa' });
    assert.equal(await companyWorkspace.isVisible(), true);
    const companyTabs = companyWorkspace.getByRole('tab');
    assert.deepEqual(await companyTabs.allTextContents(), ['Negócios', 'Histórico']);
    assert.equal(await companyWorkspace.getByRole('tabpanel', { name: 'Negócios' }).isVisible(), true);
    assert.equal(await companyWorkspace.getByRole('tabpanel', { name: 'Histórico' }).isVisible(), false);
    await companyWorkspace.getByRole('tab', { name: 'Histórico' }).click();
    assert.equal(await companyWorkspace.getByRole('tabpanel', { name: 'Negócios' }).isVisible(), false);
    assert.equal(await companyWorkspace.getByRole('tabpanel', { name: 'Histórico' }).isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await companyTrigger.evaluate(element => document.activeElement === element), true);

    for (const [view, name] of [['Leads', 'Larissa Spinola'], ['Contatos', 'Ana Berclay']]) {
      await goTo(page, view);
      await page.getByRole('button', { name, exact: true }).click();
      const compactBox = await drawer.boundingBox();
      assert.equal(Math.round(compactBox.width), 560);
      assert.equal(await drawer.getAttribute('data-layout'), 'compact');
      assert.equal(await drawer.locator('#drawerSecondary').isHidden(), true);
      await page.keyboard.press('Escape');
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
    await drawer.getByRole('button', { name: 'Salvar registro' }).waitFor({ state: 'visible' });
    const box = await drawer.boundingBox();
    assert.equal(Math.round(box.width), 390);
    assert.equal(await drawer.getByRole('button', { name: 'Salvar registro' }).isVisible(), true);
    assert.equal(await drawer.getByRole('button', { name: 'Cancelar' }).isVisible(), true);
  });

  await run('HIST-04 empilha o workspace amplo no celular sem rolagem horizontal', async page => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Implantação Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    const box = await drawer.boundingBox();
    assert.equal(Math.round(box.width), 390);
    const primary = drawer.getByRole('region', { name: 'Dados do negócio' });
    const secondary = drawer.getByRole('region', { name: 'Atividade do negócio' });
    const primaryBox = await primary.boundingBox();
    const secondaryBox = await secondary.boundingBox();
    assert.ok(secondaryBox.y >= primaryBox.y + primaryBox.height - 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.equal(await drawer.getByRole('button', { name: 'Salvar registro' }).isVisible(), true);
  });

  await run('HIST-01 filtra e pagina 52 eventos do Negócio em ordem canônica', async page => {
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Implantação Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    const timeline = drawer.getByRole('feed', { name: 'Linha do tempo do negócio' });
    await timeline.locator('[data-activity-event]').first().waitFor();
    assert.equal(await timeline.locator('[data-activity-event]').count(), 50);
    assert.deepEqual(await timeline.locator('[data-activity-event]').evaluateAll(items => [items[0].dataset.activityEvent, items.at(-1).dataset.activityEvent]), ['52', '3']);
    assert.match(await timeline.locator('[data-activity-event]').first().locator('time').innerText(), /19\/10\/2026.*12:52/);
    assert.doesNotMatch(await timeline.locator('[data-activity-event]').first().locator('time').innerText(), /15:52/);
    await drawer.getByRole('button', { name: 'Carregar mais' }).click();
    await timeline.locator('[data-activity-event="1"]').waitFor();
    assert.equal(await timeline.locator('[data-activity-event]').count(), 52);
    await drawer.getByRole('button', { name: 'Automações', exact: true }).click();
    await timeline.locator('[data-category="automation"]').first().waitFor();
    assert.equal(await timeline.locator('[data-activity-event]').count(), 17);
    assert.equal(await timeline.locator('[data-activity-event]:not([data-category="automation"])').count(), 0);
    const api = apiByPage.get(page);
    assert.match(api.activityRequests.at(-1), /category=automation/);
    assert.equal(await drawer.getByRole('button', { name: 'Automações', exact: true }).getAttribute('aria-pressed'), 'true');
  }, { dealActivities: { 'N-16312': dealActivitySeries(52) } });

  await run('HIST-01 ignora resposta atrasada de outro Negócio', async page => {
    const api = apiByPage.get(page);
    const [first, second] = (await stateFrom(page)).deals.slice(0, 2);
    api.dealActivities[first.id] = [{ ...dealActivitySeries(1)[0], summary: 'Evento exclusivo antigo' }];
    api.dealActivities[second.id] = [{ ...dealActivitySeries(1)[0], id: 2, summary: 'Evento exclusivo atual' }];
    let releaseFirst;
    api.activityGates.set(first.id, new Promise(resolve => { releaseFirst = resolve; }));
    await page.evaluate(({ id }) => openEntityDrawer('deal', id), { id: first.id });
    const drawer = page.locator('#entityDrawer');
    await drawer.locator('#dealActivityStatus').filter({ hasText: 'Carregando' }).waitFor();
    await page.evaluate(({ id }) => openEntityDrawer('deal', id), { id: second.id });
    await drawer.getByText('Evento exclusivo atual').waitFor();
    releaseFirst();
    await page.waitForTimeout(100);
    assert.equal(await drawer.getByText('Evento exclusivo antigo').count(), 0);
    assert.match(await drawer.locator('#entityDrawerSubtitle').innerText(), new RegExp(second.id));
  });

  await run('HIST-04 mantém os campos utilizáveis durante erro e retry vazio', async page => {
    const api = apiByPage.get(page);
    api.activityFailures.add('N-16312');
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Implantação Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('button', { name: 'Tentar novamente' }).waitFor();
    assert.match(await drawer.locator('#dealActivityStatus').innerText(), /Não foi possível carregar/);
    assert.equal(await drawer.getByLabel('Título do Negócio *').isEnabled(), true);
    api.activityFailures.delete('N-16312');
    await drawer.getByRole('button', { name: 'Tentar novamente' }).click();
    await drawer.getByText('Nenhuma atividade encontrada.').waitFor();
    assert.equal(await drawer.getByLabel('Título do Negócio *').isEnabled(), true);
  });

  await run('HIST-03 publica observação idempotente escapada e persistente no celular', async page => {
    await page.setViewportSize({ width: 390, height: 844 });
    const api = apiByPage.get(page);
    api.observationFailuresRemaining = 1;
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Implantação Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    const input = drawer.getByLabel('Novo comentário no histórico');
    const publish = drawer.getByRole('button', { name: 'Publicar observação' });
    const unsafeText = '<img src=x onerror="window.__activityXss=1"> Retornar ao cliente';
    await input.fill(unsafeText);
    await publish.click();
    await drawer.getByText('Não foi possível publicar a observação.').waitFor();
    await publish.click();
    await drawer.locator('[data-category="observation"]').waitFor();
    assert.equal(api.observationWrites.length, 2);
    assert.equal(api.observationWrites[0].payload.idempotencyKey, api.observationWrites[1].payload.idempotencyKey);
    assert.match(await drawer.locator('[data-category="observation"]').innerText(), /<img src=x onerror=/);
    assert.equal(await drawer.locator('[data-category="observation"] img').count(), 0);
    await input.fill('Enviado pelo teclado');
    await input.press('Control+Enter');
    await drawer.getByText('Enviado pelo teclado').waitFor();
    await input.fill('Clique duplo sem duplicar');
    await publish.dblclick();
    await drawer.getByText('Clique duplo sem duplicar').waitFor();
    assert.equal(api.observationWrites.filter(write => write.payload.text === 'Clique duplo sem duplicar').length, 1);
    assert.equal(await drawer.locator('[data-category="observation"] button').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await reloadReady(page);
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Negócios');
    await page.getByRole('button', { name: 'Implantação Arkos Estética', exact: true }).click();
    await drawer.getByText('Clique duplo sem duplicar').waitFor();
    assert.equal(await drawer.locator('[data-category="observation"]').count(), 3);
  });

  await run('HIST-02 usa somente a automação de Faturamento confirmada pelo servidor', async page => {
    const api = apiByPage.get(page);
    await goTo(page, 'Negócios');
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Open Analítica' });
    const dealId = (await row.innerText()).match(/N-\d+/)[0];
    const before = (await stateFrom(page)).deals.find(deal => deal.id === dealId);
    page.once('dialog', dialog => dialog.accept());
    await row.locator('[data-stage-segment="Faturando"]').click();
    const confirmed = (await stateFrom(page)).deals.find(deal => deal.id === dealId);
    const submitted = api.workspaceWrites.at(-1).state.deals.find(deal => deal.id === dealId);
    assert.equal(submitted.responsibleId, before.responsibleId, 'o navegador não pode executar a automação de Faturamento');
    assert.equal(api.workspaceWrites.at(-1).state.notifications.some(note => note.detail?.includes(dealId) && /Faturamento|Responsabilidade/.test(note.text)), false);
    assert.deepEqual({ responsibleId: confirmed.responsibleId, team: confirmed.team }, { responsibleId: 'u-billing', team: 'Faturamento' });
    await page.getByRole('button', { name: confirmed.title, exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.locator('[data-activity-event]').first().waitFor();
    assert.equal(await drawer.locator('[data-category="movement"]').count(), 1);
    assert.equal(await drawer.locator('[data-category="automation"]').count(), 1);
    assert.match(await drawer.locator('[data-category="automation"]').innerText(), /Responsável alterado para Equipe Faturamento/);
    assert.equal((await stateFrom(page)).notifications.filter(note => note.detail?.includes(dealId) && /Faturamento|Responsabilidade/.test(note.text)).length, 2);
  });

  await run('HIST-05 mostra totais canônicos e preserva semântica após renomear e remover', async page => {
    const api = apiByPage.get(page);
    const wonDeal = api.state.deals.find(deal => deal.id === 'N-16308');
    const lostDeal = api.state.deals.find(deal => deal.id === 'N-16311');
    wonDeal.company = 'Arkos Estética';
    lostDeal.company = 'Arkos Estética';
    lostDeal.stageId = DEAL_STAGE_IDS[7];
    lostDeal.stage = DEAL_STAGES[7];
    await reloadReady(page);
    await goTo(page, 'Empresas');
    await page.getByRole('button', { name: 'Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    const summary = drawer.getByRole('group', { name: 'Resumo dos negócios da empresa' });
    await summary.waitFor();
    assert.match(await summary.locator('[data-company-metric="total"]').innerText(), /3/);
    assert.match(await summary.locator('[data-company-metric="open"]').innerText(), /1.*R\$\s*48\.500,00/s);
    assert.match(await summary.locator('[data-company-metric="won"]').innerText(), /1.*R\$\s*19\.400,00/s);
    assert.match(await summary.locator('[data-company-metric="lost"]').innerText(), /1.*R\$\s*32\.700,00/s);
    assert.deepEqual(await drawer.locator('[data-company-deal]').evaluateAll(rows => rows.map(row => row.dataset.companyDeal)), ['N-16312', 'N-16311', 'N-16308']);
    assert.match(await drawer.locator('[data-company-deal="N-16308"]').innerText(), /Ganho/);
    assert.match(await drawer.locator('[data-company-deal="N-16311"]').innerText(), /Perdido/);

    api.pipeline.stages.find(stage => stage.id === DEAL_STAGE_IDS[6]).name = 'Venda celebrada';
    wonDeal.stage = 'Venda celebrada';
    await page.evaluate(() => loadCompanyDeals('E-802'));
    await drawer.getByText('Venda celebrada').waitFor();
    assert.match(await summary.locator('[data-company-metric="won"]').innerText(), /1.*R\$\s*19\.400,00/s);
    api.state.deals = api.state.deals.filter(deal => deal.id !== 'N-16311');
    await page.evaluate(() => loadCompanyDeals('E-802'));
    await drawer.locator('[data-company-deal="N-16311"]').waitFor({ state: 'detached' });
    assert.match(await summary.locator('[data-company-metric="total"]').innerText(), /2/);
    assert.match(await summary.locator('[data-company-metric="lost"]').innerText(), /0.*R\$\s*0,00/s);
  });

  await run('HIST-05 trata erro retry e resumo vazio sem vazar Negócios restritos', async page => {
    const api = apiByPage.get(page);
    api.companyDealFailures.add('E-802');
    await page.evaluate(() => openEntityDrawer('company', 'E-802'));
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('button', { name: 'Tentar novamente' }).waitFor();
    assert.match(await drawer.locator('#companyDealsStatus').innerText(), /Não foi possível carregar/);
    api.companyDealFailures.delete('E-802');
    await drawer.getByRole('button', { name: 'Tentar novamente' }).click();
    await drawer.getByText('Nenhum Negócio visível para esta empresa.').waitFor();
    const summary = drawer.getByRole('group', { name: 'Resumo dos negócios da empresa' });
    assert.match(await summary.locator('[data-company-metric="total"]').innerText(), /0/);
    assert.equal(await drawer.locator('[data-company-deal]').count(), 0);
  }, {
    session: { user_id: 'u-vitor', user_name: 'Vitor Santos', role: 'Vendedor' },
    preloadState: (() => {
      const workspace = minimalWorkspace();
      workspace.users.push({ id: 'u-vitor', name: 'Vitor Santos', role: 'Vendedor', team: 'Vendas CMS', status: 'Ativo' });
      workspace.companies.push({
        id: 'E-802', name: 'Arkos Estética', city: 'São Paulo / SP',
        segment: 'Médico e Hospitalar', phone: '(11) 3456-7788', ownerId: 'u-paula'
      });
      return workspace;
    })()
  });

  await run('HIST-05 navega Empresa Negócio Empresa e atualiza valor confirmado', async page => {
    await goTo(page, 'Empresas');
    await page.getByRole('button', { name: 'Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.locator('[data-company-deal="N-16312"]').waitFor();
    await drawer.locator('[data-company-deal="N-16312"]').getByRole('button', { name: 'Implantação Arkos Estética' }).click();
    assert.equal(await drawer.getAttribute('data-entity'), 'deal');
    assert.equal(await drawer.getByRole('button', { name: 'Voltar à empresa' }).isVisible(), true);
    await drawer.getByLabel('Valor (R$)').fill('50000');
    await drawer.getByRole('button', { name: 'Salvar registro' }).click();
    await drawer.getByRole('tabpanel', { name: 'Negócios' }).waitFor();
    assert.equal(await drawer.getAttribute('data-entity'), 'company');
    await drawer.locator('[data-company-deal="N-16312"]').waitFor();
    assert.match(await drawer.locator('[data-company-deal="N-16312"]').innerText(), /R\$\s*50\.000,00/);
    await drawer.locator('[data-company-deal="N-16312"]').getByRole('button', { name: 'Implantação Arkos Estética' }).click();
    await drawer.getByRole('button', { name: 'Voltar à empresa' }).click();
    assert.equal(await drawer.getAttribute('data-entity'), 'company');
    assert.equal(await drawer.getByRole('tab', { name: 'Negócios' }).getAttribute('aria-selected'), 'true');
  });

  await run('HIST-06 pagina e filtra somente o histórico próprio da Empresa', async page => {
    await goTo(page, 'Empresas');
    await page.getByRole('button', { name: 'Arkos Estética', exact: true }).click();
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Histórico' }).click();
    const timeline = drawer.locator('#companyActivityTimeline');
    await timeline.locator('[data-activity-event]').first().waitFor();
    assert.equal(await timeline.locator('[data-activity-event]').count(), 50);
    assert.match(await timeline.locator('[data-activity-event]').first().innerText(), /Nome:\s+Arkos 51\s+→\s+Arkos 52/);
    assert.match(await timeline.locator('[data-activity-event]').first().innerText(), /Telefone:\s+vazio\s+→\s+\(11\) 3456-7788/);
    assert.match(await timeline.locator('[data-activity-event]').first().innerText(), /Segredo comercial:\s+conteúdo redigido/);
    assert.doesNotMatch(await timeline.locator('[data-activity-event]').first().innerText(), /segredo-antigo|segredo-novo/);
    assert.equal(await timeline.locator('[data-category="movement"], [data-category="automation"]').count(), 0);
    await drawer.getByRole('button', { name: 'Alterações', exact: true }).click();
    await timeline.locator('[data-category="change"]').first().waitFor();
    assert.equal(await timeline.locator('[data-activity-event]').count(), 26);
    assert.equal(await timeline.locator('[data-activity-event]:not([data-category="change"])').count(), 0);
    assert.match(apiByPage.get(page).companyActivityRequests.at(-1), /category=change/);
    await drawer.getByRole('button', { name: 'Tudo', exact: true }).click();
    await drawer.getByRole('button', { name: 'Carregar mais' }).click();
    await page.waitForFunction(() => document.querySelectorAll('#companyActivityTimeline [data-activity-event]').length === 52);
    assert.match(apiByPage.get(page).companyActivityRequests.at(-1), /cursor=cursor-50/);
  }, { companyActivities: { 'E-802': companyActivitySeries(52) } });

  await run('HIST-06 ignora resposta atrasada ao trocar de Empresa', async page => {
    const api = apiByPage.get(page);
    api.companyActivities['E-802'] = [{ ...companyActivitySeries(1)[0], summary: 'Histórico antigo da Arkos' }];
    api.companyActivities['E-801'] = [{ ...companyActivitySeries(1)[0], id: 2, summary: 'Histórico atual da ALS' }];
    let releaseArkos;
    api.companyActivityGates.set('E-802', new Promise(resolve => { releaseArkos = resolve; }));
    await page.evaluate(() => openEntityDrawer('company', 'E-802'));
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Histórico' }).click();
    await drawer.locator('#companyActivityStatus').filter({ hasText: 'Carregando' }).waitFor();
    await page.evaluate(() => openEntityDrawer('company', 'E-801'));
    await drawer.getByRole('tab', { name: 'Histórico' }).click();
    await drawer.getByText('Histórico atual da ALS').waitFor();
    releaseArkos();
    await page.waitForTimeout(100);
    assert.equal(await drawer.getByText('Histórico antigo da Arkos').count(), 0);
    assert.match(await drawer.locator('#entityDrawerSubtitle').innerText(), /E-801/);
  });

  await run('HIST-03 publica observação idempotente e correção imutável no celular', async page => {
    await page.evaluate(() => openEntityDrawer('company', 'E-802'));
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Histórico' }).click();
    await drawer.getByText('Nenhuma atividade encontrada.').waitFor();
    const input = drawer.getByLabel('Registrar comentário da empresa');
    await input.fill('<img src=x onerror=alert(1)> contexto');
    await input.press('Control+Enter');
    await drawer.getByText('<img src=x onerror=alert(1)> contexto', { exact: true }).waitFor();
    assert.equal(await drawer.locator('#companyActivityTimeline img').count(), 0);
    const api = apiByPage.get(page);
    api.companyObservationFailuresRemaining = 1;
    await input.fill('Correção: contato deve ocorrer amanhã.');
    await input.press('Control+Enter');
    await drawer.locator('#companyObservationError').filter({ hasText: /Não foi possível/ }).waitFor();
    await input.press('Control+Enter');
    await drawer.getByText('Correção: contato deve ocorrer amanhã.', { exact: true }).waitFor();
    assert.equal(api.companyObservationWrites.at(-2).payload.idempotencyKey, api.companyObservationWrites.at(-1).payload.idempotencyKey);
    assert.equal(await drawer.locator('[data-activity-event] button').count(), 0);
    assert.equal(await drawer.evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await reloadReady(page);
    await page.evaluate(() => openEntityDrawer('company', 'E-802'));
    await drawer.getByRole('tab', { name: 'Histórico' }).click();
    await drawer.getByText('Correção: contato deve ocorrer amanhã.', { exact: true }).waitFor();
    assert.equal(await drawer.locator('[data-category="observation"]').count(), 2);
  }, { viewport: { width: 390, height: 844 } });

  await run('HIST-06 mantém campos utilizáveis durante erro e retry vazio', async page => {
    const api = apiByPage.get(page);
    api.companyActivityFailures.add('E-802');
    await page.evaluate(() => openEntityDrawer('company', 'E-802'));
    const drawer = page.locator('#entityDrawer');
    await drawer.getByRole('tab', { name: 'Histórico' }).click();
    await drawer.getByRole('button', { name: 'Tentar novamente' }).waitFor();
    assert.equal(await drawer.getByLabel('Razão / nome da Empresa *').isEnabled(), true);
    api.companyActivityFailures.delete('E-802');
    await drawer.getByRole('button', { name: 'Tentar novamente' }).click();
    await drawer.getByText('Nenhuma atividade encontrada.').waitFor();
    assert.equal(await drawer.getByLabel('Razão / nome da Empresa *').isEnabled(), true);
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
    await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
      key: uiStorageKey(apiByPage.get(page).session), value: state.ui
    });
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
    assert.deepEqual(Object.keys(changed.stageHistory.at(-1)).sort(), ['at', 'byId', 'from', 'fromStageId', 'to', 'toStageId']);
    assert.equal(changed.stageHistory.at(-1).from, 'Orçamentos enviados');
    assert.equal(changed.stageHistory.at(-1).to, 'Negociação Revisão');
    assert.equal(changed.stageHistory.at(-1).fromStageId, DEAL_STAGE_IDS[2]);
    assert.equal(changed.stageHistory.at(-1).toStageId, DEAL_STAGE_IDS[3]);
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
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption({ label: 'Ganho' });
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
    await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').selectOption({ label: 'Ganho' });
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
    assert.deepEqual(await panel.locator('[data-filter-field="stage"] select[name="filter-value"]').evaluate(select => [...select.selectedOptions].map(option => option.value)), [DEAL_STAGE_IDS[6]]);
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
    await goTo(page, 'Negócios');
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
    await page.getByRole('button', { name: /Restaurar dados iniciais/ }).click();
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
    const importButton = page.getByRole('button', { name: 'Importar', exact: true });
    assert.equal((await importButton.textContent()).trim(), '⇩ Importar');
    await importButton.click();
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
    await page.getByRole('button', { name: 'Importar', exact: true }).click();
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
    await page.getByRole('button', { name: 'Importar', exact: true }).click();

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
    await waitForMockState(page, state => state.deals.find(item => item.bitrixId === '9103')?.title === 'Terceiro atualizado');
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
    await page.getByRole('button', { name: 'Importar', exact: true }).click();
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
      await drawer.getByRole('tab', { name: 'Campos adicionais' }).waitFor({ state: 'visible' });
      assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isVisible(), true);
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
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).waitFor({ state: 'visible' });
    assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isVisible(), true);
    assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).getAttribute('aria-selected'), 'true');
    assert.match(await drawer.locator('#drawerCustomPanel').innerText(), /Nenhum campo adicional visível\./);
    assert.equal(await page.evaluate(key => hideDrawerCustomField(key), schema.key), false);
    assert.equal(await page.evaluate(() => hideDrawerCustomField('test:inexistente')), false);
    assert.deepEqual((await stateFrom(page)).moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key]);

    await drawer.getByRole('button', { name: 'Fechar painel' }).click();
    await page.getByRole('button', { name: secondDeal.title }).click();
    await drawer.getByRole('tab', { name: 'Campos adicionais' }).waitFor({ state: 'visible' });
    assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isVisible(), true);
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
    await setMockWorkspace(page, configured);
    await reloadReady(page);
    await selectProfile(page, 'u-paula');

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
    assert.equal(await page.getByLabel('Perfil de usuário').locator('option[value="' + juliana.id + '"]').count(), 0);

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
    assert.equal(await page.locator('#profileSelect').count(), 0);
    await page.getByRole('button', { name: 'Desativar Juliana Lima' }).click();
    assert.equal((await stateFrom(page)).users.find(user => user.id === juliana.id).status, 'Inativo');
    assert.equal(await page.getByLabel('Perfil de usuário').locator(`option[value="${juliana.id}"]`).count(), 0);

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
    assert.equal(await page.getByLabel('Perfil de usuário').locator(`option[value="${canceled.id}"]`).count(), 0);

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
    await page.getByRole('button', { name: 'Importar', exact: true }).click();
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

  await run('PIPE-UI-01 usa IDs e semântica após renomear o funil canônico', async page => {
    const api = apiByPage.get(page);
    const renamed = new Map([
      [DEAL_STAGE_IDS[0], 'Entrada personalizada'],
      [DEAL_STAGE_IDS[5], 'Pronto para financeiro'],
      [DEAL_STAGE_IDS[6], 'Venda concluída'],
      [DEAL_STAGE_IDS[7], 'Venda encerrada']
    ]);
    api.pipeline.stages.forEach(stage => { if (renamed.has(stage.id)) stage.name = renamed.get(stage.id); });
    api.pipeline.pipelineVersion += 1;
    const billingDeal = api.state.deals.find(deal => deal.id === 'N-16312');
    billingDeal.responsibleId = 'u-paula';
    billingDeal.team = 'Vendas CMS';
    api.state.notifications = api.state.notifications.filter(note => !(/Faturamento/.test(note.text) && /N-16312/.test(note.detail)));
    api.state.deals.forEach(deal => {
      const stage = api.pipeline.stages.find(candidate => candidate.id === deal.stageId);
      deal.stage = stage.name;
    });
    await reloadReady(page);

    assert.equal(await page.evaluate(() => document.documentElement.dataset.pipelineReady), 'true');
    assert.equal(await page.locator('#dealNavCount').innerText(), '5');
    assert.equal(await page.locator('[data-pipeline-stage]').filter({ hasText: 'Venda concluída' }).count(), 1);
    assert.equal(await page.locator('[data-pipeline-stage]').filter({ hasText: 'Ganho' }).count(), 0);

    await goTo(page, 'Negócios');
    const initialOption = page.locator('#page-deals [data-stage-segment="Entrada personalizada"]');
    assert.ok(await initialOption.count() > 0);
    let deal = (await stateFrom(page)).deals.find(candidate => candidate.id === 'N-16312');
    assert.deepEqual({ responsibleId: deal.responsibleId, team: deal.team }, { responsibleId: 'u-paula', team: 'Vendas CMS' });
    assert.equal((await stateFrom(page)).notifications.some(note => /Faturamento/.test(note.text) && /N-16312/.test(note.detail)), false);
    assert.deepEqual(await page.evaluate(dealId => {
      const candidate = state.deals.find(deal => deal.id === dealId);
      return { open: isOpen(candidate), won: isWon(candidate), lost: isLost(candidate) };
    }, 'N-16312'), { open: true, won: false, lost: false });
    const billingTarget = page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' }).locator('[data-stage-segment="Pronto para financeiro"]');
    page.once('dialog', dialog => dialog.accept());
    await billingTarget.click();
    deal = (await stateFrom(page)).deals.find(candidate => candidate.id === 'N-16312');
    assert.deepEqual({ stageId: deal.stageId, stage: deal.stage, responsibleId: deal.responsibleId }, {
      stageId: DEAL_STAGE_IDS[5], stage: 'Pronto para financeiro', responsibleId: 'u-billing'
    });
    assert.equal((await stateFrom(page)).notifications.filter(note => /Faturamento/.test(note.text) && /N-16312/.test(note.detail)).length, 1);

    page.once('dialog', dialog => dialog.accept());
    await page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' }).locator('[data-stage-segment="Venda concluída"]').click();
    deal = (await stateFrom(page)).deals.find(candidate => candidate.id === 'N-16312');
    assert.equal(deal.stageId, DEAL_STAGE_IDS[6]);
    assert.equal(Number.isNaN(Date.parse(deal.wonAt)), false);
    assert.deepEqual(await page.evaluate(dealId => {
      const candidate = state.deals.find(deal => deal.id === dealId);
      return { open: isOpen(candidate), won: isWon(candidate), lost: isLost(candidate) };
    }, 'N-16312'), { open: false, won: true, lost: false });
    assert.equal(await page.locator('#dealNavCount').innerText(), '4');

    page.once('dialog', dialog => dialog.accept());
    await page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' }).locator('[data-stage-segment="Venda encerrada"]').click();
    deal = (await stateFrom(page)).deals.find(candidate => candidate.id === 'N-16312');
    assert.equal(deal.stageId, DEAL_STAGE_IDS[7]);
    assert.equal('wonAt' in deal, false);
    assert.deepEqual(await page.evaluate(dealId => {
      const candidate = state.deals.find(deal => deal.id === dealId);
      return { open: isOpen(candidate), won: isWon(candidate), lost: isLost(candidate) };
    }, 'N-16312'), { open: false, won: false, lost: true });
    assert.equal(await page.locator('#dealNavCount').innerText(), '4');

    await page.getByRole('button', { name: 'Novo Negócio' }).click();
    const dialog = page.locator('#entityDialog');
    assert.equal(await dialog.getByLabel('Etapa *').inputValue(), DEAL_STAGE_IDS[0]);
    await dialog.getByLabel('Título do Negócio *').fill('Negócio no início configurado');
    await dialog.getByLabel('Empresa *').fill('Empresa Pipeline');
    await dialog.getByLabel('Valor (R$) *').fill('150');
    await dialog.getByLabel('Responsável *').selectOption('u-paula');
    await dialog.getByRole('button', { name: 'Salvar registro' }).click();
    const created = (await stateFrom(page)).deals.find(candidate => candidate.title === 'Negócio no início configurado');
    assert.deepEqual({ pipelineId: created.pipelineId, stageId: created.stageId, stage: created.stage }, {
      pipelineId: api.pipeline.id, stageId: DEAL_STAGE_IDS[0], stage: 'Entrada personalizada'
    });

    await page.getByRole('button', { name: /Filtros/ }).click();
    const stageFilter = page.locator('#filterDialog [data-filter-field="stage"] select[name="filter-value"]');
    await stageFilter.selectOption({ label: 'Venda concluída' });
    assert.deepEqual(await stageFilter.evaluate(select => [...select.selectedOptions].map(option => option.value)), [DEAL_STAGE_IDS[6]]);
  });

  await run('PIPE-UI-02 bloqueia ações de Negócio sem usar etapas fixas como fallback', async page => {
    assert.equal(await page.evaluate(() => document.documentElement.dataset.pipelineReady), 'false');
    await goTo(page, 'Negócios');
    assert.match(await page.locator('#page-deals [role="alert"]').innerText(), /Funil indisponível/);
    assert.equal(await page.getByRole('button', { name: 'Novo Negócio' }).count(), 0);
    assert.equal(await page.evaluate(() => openEntityDialog('deal')), false);
    assert.match(await page.locator('#toastRegion').innerText(), /Funil indisponível/);
  }, { pipelineFailure: true });

  await run('PIPE-UI-03 mantém a ordem canônica nos consumidores do funil', async page => {
    const api = apiByPage.get(page);
    api.pipeline.stages.forEach(stage => { stage.name = `Etapa ${String(stage.position + 1).padStart(2, '0')}`; });
    api.pipeline.stages.reverse();
    api.pipeline.pipelineVersion += 1;
    api.state.deals.forEach(deal => {
      deal.stage = api.pipeline.stages.find(stage => stage.id === deal.stageId).name;
    });
    const expected = [...api.pipeline.stages].sort((left, right) => left.position - right.position);
    const expectedIds = expected.map(stage => stage.id);
    const expectedNames = expected.map(stage => stage.name);
    await reloadReady(page);

    await goTo(page, 'Visão geral');
    assert.deepEqual(await page.locator('[data-pipeline-stage]').evaluateAll(items => items.map(item => item.dataset.pipelineStage)), expectedIds);
    assert.deepEqual(await page.locator('[data-pipeline-stage] > span:first-child').allTextContents(), expectedNames);

    await goTo(page, 'Negócios');
    const row = page.locator('#page-deals tbody tr').filter({ hasText: 'Implantação Arkos Estética' });
    assert.deepEqual(await row.locator('[data-stage-segment]').evaluateAll(items => items.map(item => item.dataset.stageId)), expectedIds);
    assert.deepEqual(await row.locator('[data-stage-segment]').allTextContents(), expectedNames);
    assert.deepEqual((await page.locator('[data-stage-filter="deals"] option').allTextContents()).slice(1), expectedNames);
    assert.deepEqual((await page.locator('[data-stage-filter="deals"] option').evaluateAll(items => items.map(item => item.value))).slice(1), expectedIds);

    await page.getByRole('button', { name: /Filtros/ }).click();
    const filterOptions = page.locator('#filterDialog [data-filter-field="stage"] select[name="filter-value"] option');
    assert.deepEqual(await filterOptions.allTextContents(), expectedNames);
    assert.deepEqual(await filterOptions.evaluateAll(items => items.map(item => item.value)), expectedIds);
    await page.locator('#filterDialog').getByRole('button', { name: 'Fechar' }).click();

    await page.getByRole('button', { name: 'Novo Negócio' }).click();
    const formOptions = page.locator('#entityDialog [name="stageId"] option');
    assert.deepEqual(await formOptions.allTextContents(), expectedNames);
    assert.deepEqual(await formOptions.evaluateAll(items => items.map(item => item.value)), expectedIds);
    await page.locator('#entityDialog').getByRole('button', { name: 'Cancelar' }).click();

    await page.getByRole('button', { name: 'Kanban', exact: true }).click();
    assert.deepEqual(await page.locator('#page-deals .kanban-column').evaluateAll(items => items.map(item => item.dataset.kanbanStage)), expectedIds);
    assert.deepEqual(await page.locator('#page-deals .kanban-column-head > span:first-child').allTextContents(), expectedNames);
  });

  await run('PIPE-ADMIN-01 edita e salva o agregado versionado com ordenação acessível', async page => {
    const api = apiByPage.get(page);
    await goTo(page, 'Funil de negócios');
    const rows = page.locator('[data-pipeline-editor-stage]');
    assert.equal(await rows.count(), 9);
    assert.equal(await rows.first().locator('[data-pipeline-field="semanticType"]').isDisabled(), true);
    assert.match(await rows.nth(5).innerText(), /Automação interna: billing/);

    const originalOrder = await rows.evaluateAll(items => items.map(item => item.dataset.pipelineEditorStage));
    await page.evaluate(() => {
      const items = [...document.querySelectorAll('[data-pipeline-editor-stage]')];
      const transfer = new DataTransfer();
      items.at(-1).dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: transfer }));
      items[0].dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: transfer }));
      items[0].dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }));
    });
    const draggedOrder = await rows.evaluateAll(items => items.map(item => item.dataset.pipelineEditorStage));
    assert.equal(draggedOrder[0], originalOrder.at(-1));
    assert.equal(new Set(draggedOrder).size, 9);
    await rows.first().getByRole('button', { name: /Descer/ }).click();
    const keyboardOrder = await rows.evaluateAll(items => items.map(item => item.dataset.pipelineEditorStage));
    assert.equal(keyboardOrder[1], originalOrder.at(-1));

    const firstCanonical = page.locator(`[data-pipeline-editor-stage="${DEAL_STAGE_IDS[0]}"]`);
    await firstCanonical.locator('[data-pipeline-field="name"]').fill('Contato customizado');
    await firstCanonical.locator('[data-pipeline-field="color"]').fill('#123456');
    await page.locator(`input[name="pipeline-default-stage"][value="${DEAL_STAGE_IDS[1]}"]`).check();
    await page.getByRole('button', { name: 'Adicionar etapa' }).click();
    assert.equal(await rows.count(), 10);
    const createdRow = rows.last();
    assert.equal(await createdRow.locator('[data-pipeline-field="semanticType"]').isEnabled(), true);
    await createdRow.locator('[data-pipeline-field="name"]').fill('Qualificação jurídica');
    await createdRow.locator('[data-pipeline-field="semanticType"]').selectOption('open');
    await createdRow.locator('[data-pipeline-field="color"]').fill('#ABCDEF');

    await page.getByRole('button', { name: 'Salvar funil' }).click();
    await waitForPipelineWrites(page, 1);
    await page.getByText('Funil atualizado com sucesso.', { exact: true }).waitFor();
    assert.equal(api.pipelineWrites.length, 1);
    const payload = api.pipelineWrites[0];
    assert.equal(payload.pipelineVersion, 1);
    assert.equal(payload.workspaceVersion, 1);
    assert.equal(payload.defaultStageId, DEAL_STAGE_IDS[1]);
    assert.deepEqual(payload.stages.map(stage => stage.position), Array.from({ length: 10 }, (_, index) => index));
    assert.deepEqual(payload.stages.find(stage => stage.id === DEAL_STAGE_IDS[0]), {
      id: DEAL_STAGE_IDS[0], name: 'Contato customizado', semanticType: 'open', color: '#123456',
      position: payload.stages.findIndex(stage => stage.id === DEAL_STAGE_IDS[0]), archived: false
    });
    assert.equal(payload.stages.some(stage => stage.name === 'Qualificação jurídica' && stage.id === undefined && stage.color === '#ABCDEF'), true);
    assert.equal(api.pipeline.pipelineVersion, 2);
    assert.equal(await page.locator('[data-pipeline-editor-stage]').count(), 10);
  });

  await run('PIPE-ADMIN-02 valida limites e associa 422 à etapa afetada', async page => {
    const api = apiByPage.get(page);
    await goTo(page, 'Funil de negócios');
    const rows = page.locator('[data-pipeline-editor-stage]');
    const firstName = rows.nth(0).locator('[data-pipeline-field="name"]');
    const secondName = rows.nth(1).locator('[data-pipeline-field="name"]');
    await secondName.fill(await firstName.inputValue());
    await page.getByRole('button', { name: 'Salvar funil' }).click();
    assert.equal(api.pipelineWrites.length, 0);
    assert.equal(await page.getByText('O nome da etapa deve ser único.', { exact: true }).count(), 2);
    assert.match(await page.locator('#pipelineEditorStatus').innerText(), /Corrija/);

    await page.evaluate(() => reloadPipelineEditor());
    api.pipelineValidationFailure = { code: 'duplicate_stage_name', message: 'Nome recusado pelo servidor.', path: 'stages[0].name' };
    await page.locator('[data-pipeline-editor-stage]').first().locator('[data-pipeline-field="name"]').fill('Nome local válido');
    await page.getByRole('button', { name: 'Salvar funil' }).click();
    await waitForPipelineWrites(page, 1);
    const serverStageError = page.locator('.stage-error').filter({ hasText: 'Nome recusado pelo servidor.' });
    await serverStageError.waitFor();
    assert.equal(await serverStageError.count(), 1);
    assert.match(await page.locator('#pipelineEditorStatus').innerText(), /Nome recusado/);

    api.pipelineValidationFailure = null;
    await page.evaluate(() => {
      while (pipelineEditorDraft.stages.length < 50) addPipelineStage();
    });
    assert.equal(await page.locator('[data-pipeline-editor-stage]').count(), 50);
    assert.equal(await page.evaluate(() => addPipelineStage()), false);
    assert.match(await page.locator('#pipelineEditorStatus').innerText(), /máximo 50/);
  });

  await run('PIPE-ADMIN-03 preserva rascunho no 409 e recarrega explicitamente no móvel', async page => {
    const api = apiByPage.get(page);
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await goTo(page, 'Funil de negócios');
    const first = page.locator('[data-pipeline-editor-stage]').first();
    const serverName = api.pipeline.stages[0].name;
    await first.locator('[data-pipeline-field="name"]').fill('Rascunho local');
    api.pipelineConflict = true;
    await page.getByRole('button', { name: 'Salvar funil' }).click();
    await waitForPipelineWrites(page, 1);
    await page.getByText(/alterado em outra sessão/).waitFor();
    assert.equal(await page.getByText(/alterado em outra sessão/).count(), 1);
    assert.equal(await page.locator('[data-pipeline-editor-stage]').first().locator('[data-pipeline-field="name"]').inputValue(), 'Rascunho local');
    assert.equal(api.pipeline.stages[0].name, serverName);

    api.pipelineConflict = false;
    api.pipeline.pipelineVersion += 1;
    api.pipeline.stages[0].name = 'Versão atual do servidor';
    await page.getByRole('button', { name: 'Recarregar funil' }).click();
    await page.waitForFunction(() => document.querySelector('[data-pipeline-editor-stage] [data-pipeline-field="name"]')?.value === 'Versão atual do servidor');
    assert.equal(await page.locator('[data-pipeline-editor-stage]').first().locator('[data-pipeline-field="name"]').inputValue(), 'Versão atual do servidor');
    assert.equal(await page.locator('.pipeline-conflict').count(), 0);
    assert.equal(await page.locator('[data-pipeline-editor-stage]').first().getByRole('button', { name: /Descer/ }).isVisible(), true);
    const box = await page.locator('[data-pipeline-editor-stage]').first().boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= 390);
  }, { viewport: { width: 390, height: 844 } });

  await run('PIPE-ADMIN-04 nega a página e mutações aos demais perfis', async page => {
    assert.equal(await page.getByRole('button', { name: 'Funil de negócios' }).count(), 0);
    await page.evaluate(() => showView('pipeline-admin'));
    assert.equal(await page.locator('#page-dashboard').isVisible(), true);
    assert.equal(await page.locator('#page-pipeline-admin').isVisible(), false);
    assert.equal(await page.evaluate(() => addPipelineStage()), false);
    assert.equal(await page.evaluate(() => savePipelineEditor()), false);
  }, { session: SELLER_SESSION, preloadState: minimalWorkspace() });

  await run('PIPE-ADMIN-05 arquiva etapa vazia diretamente e preserva a versão do workspace', async page => {
    const api = apiByPage.get(page);
    await goTo(page, 'Funil de negócios');
    await page.getByRole('button', { name: `Arquivar ${DEAL_STAGES[5]}` }).click();
    await waitForPipelineWrites(page, 1);
    await page.getByText('Etapa arquivada com sucesso.', { exact: true }).waitFor();

    assert.equal(await page.locator('#pipelineArchiveDialog').isVisible(), false);
    assert.equal(api.pipelineWrites.length, 1);
    assert.equal(api.pipelineWrites[0].stages.find(stage => stage.id === DEAL_STAGE_IDS[5]).archived, true);
    assert.deepEqual(api.pipelineWrites[0].transfers, {});
    assert.equal(api.pipeline.pipelineVersion, 2);
    assert.equal(api.pipeline.workspaceVersion, 1);
    assert.equal(await page.locator('[data-pipeline-editor-stage]').count(), 8);
  }, { preloadState: minimalWorkspace() });

  await run('PIPE-ADMIN-06 exige destino e explica o efeito semântico incluindo excluídos', async page => {
    const api = apiByPage.get(page);
    api.deleted.deals.push({
      ...clone(api.state.deals[0]), id: 'deal-pipeline-deleted', deletedAt: '2026-10-01T09:00:00Z'
    });
    await goTo(page, 'Funil de negócios');
    await page.getByRole('button', { name: `Arquivar ${DEAL_STAGES[2]}` }).click();
    const dialog = page.locator('#pipelineArchiveDialog');
    await dialog.waitFor();

    assert.match(await dialog.locator('#pipelineArchiveCount').innerText(), /2 negócios/);
    assert.match(await dialog.locator('#pipelineArchiveCount').innerText(), /1 excluído/);
    const target = dialog.getByLabel('Transferir negócios para *');
    assert.equal(await target.locator(`option[value="${DEAL_STAGE_IDS[2]}"]`).count(), 0);
    assert.equal(await target.locator('option:not([value=""])').count(), 8);
    await target.selectOption(DEAL_STAGE_IDS[0]);
    assert.match(await dialog.locator('#pipelineArchiveSemantic').innerText(), /permanecem em andamento/);
    await target.selectOption(DEAL_STAGE_IDS[6]);
    assert.match(await dialog.locator('#pipelineArchiveSemantic').innerText(), /marcados como ganhos/);
    await target.selectOption(DEAL_STAGE_IDS[7]);
    assert.match(await dialog.locator('#pipelineArchiveSemantic').innerText(), /marcados como perdidos/);
    await dialog.getByRole('button', { name: 'Cancelar' }).click();
    assert.equal(await dialog.isVisible(), false);
    assert.equal(api.pipelineWrites.length, 0);
    assert.equal(await page.locator('[data-pipeline-editor-stage]').count(), 9);
  }, { preloadState: workspaceWithDeal() });

  await run('PIPE-ADMIN-07 transfere atomicamente e atualiza versões e histórico', async page => {
    const api = apiByPage.get(page);
    api.deleted.deals.push({
      ...clone(api.state.deals[0]), id: 'deal-pipeline-deleted', deletedAt: '2026-10-01T09:00:00Z'
    });
    await goTo(page, 'Funil de negócios');
    await page.getByRole('button', { name: `Arquivar ${DEAL_STAGES[2]}` }).click();
    const dialog = page.locator('#pipelineArchiveDialog');
    await dialog.getByLabel('Transferir negócios para *').selectOption(DEAL_STAGE_IDS[6]);
    await dialog.getByRole('button', { name: 'Arquivar e transferir' }).click();
    await waitForPipelineWrites(page, 1);
    await page.getByText('2 negócios transferidos e etapa arquivada.', { exact: true }).waitFor();

    assert.equal(api.pipelineWrites[0].transfers[DEAL_STAGE_IDS[2]], DEAL_STAGE_IDS[6]);
    assert.deepEqual(api.pipelineWrites[0].stages.filter(stage => !stage.archived).map(stage => stage.position), Array.from({ length: 8 }, (_, index) => index));
    assert.equal(api.pipeline.pipelineVersion, 2);
    assert.equal(api.pipeline.workspaceVersion, 2);
    assert.equal(api.version, 2);
    const localDeal = (await stateFrom(page)).deals.find(deal => deal.id === 'deal-pipeline-active');
    assert.deepEqual({ stageId: localDeal.stageId, stage: localDeal.stage }, { stageId: DEAL_STAGE_IDS[6], stage: DEAL_STAGES[6] });
    assert.equal(api.deleted.deals[0].stageId, DEAL_STAGE_IDS[6]);
    const history = page.locator('[data-pipeline-history-item]').first();
    await history.waitFor();
    assert.match(await history.innerText(), /u-admin/);
    assert.match(await history.innerText(), /pipeline.updated/);
    assert.match(await history.innerText(), /Antes/i);
    assert.match(await history.innerText(), /Depois/i);
    assert.match(await history.innerText(), /2 negócio/);
  }, { preloadState: workspaceWithDeal() });

  await run('PIPE-ADMIN-08 rejeita destino inválido e falha atômica sem corromper o estado local', async page => {
    const api = apiByPage.get(page);
    await goTo(page, 'Funil de negócios');
    await page.getByRole('button', { name: `Arquivar ${DEAL_STAGES[2]}` }).click();
    const dialog = page.locator('#pipelineArchiveDialog');
    await dialog.getByRole('button', { name: 'Arquivar e transferir' }).click();
    assert.match(await dialog.locator('#pipelineArchiveError').innerText(), /Escolha uma etapa ativa diferente/);
    assert.equal(api.pipelineWrites.length, 0);

    api.pipelineValidationFailure = {
      code: 'pipeline_archive_target_invalid', message: 'A etapa de destino ficou indisponível.',
      path: `transfers.${DEAL_STAGE_IDS[2]}`
    };
    await dialog.getByLabel('Transferir negócios para *').selectOption(DEAL_STAGE_IDS[6]);
    await dialog.getByRole('button', { name: 'Arquivar e transferir' }).click();
    await waitForPipelineWrites(page, 1);
    await dialog.getByText('A etapa de destino ficou indisponível.', { exact: true }).waitFor();
    assert.match(await dialog.locator('#pipelineArchiveError').innerText(), /A etapa de destino ficou indisponível/);
    assert.equal(await dialog.isVisible(), true);
    assert.equal(await page.locator(`[data-pipeline-editor-stage="${DEAL_STAGE_IDS[2]}"]`).count(), 1);
    assert.equal((await stateFrom(page)).deals[0].stageId, DEAL_STAGE_IDS[2]);

    api.pipelineValidationFailure = null;
    api.pipelineConflict = true;
    await dialog.getByRole('button', { name: 'Arquivar e transferir' }).click();
    await waitForPipelineWrites(page, 2);
    await dialog.getByText(/mudou em outra sessão/).waitFor();
    assert.match(await dialog.locator('#pipelineArchiveError').innerText(), /mudou em outra sessão/);
    assert.equal(api.pipeline.pipelineVersion, 1);
    assert.equal((await stateFrom(page)).deals[0].stageId, DEAL_STAGE_IDS[2]);

    api.pipelineConflict = false;
    api.pipelineServerFailure = true;
    await dialog.getByRole('button', { name: 'Arquivar e transferir' }).click();
    await waitForPipelineWrites(page, 3);
    await dialog.getByText(/Operação revertida/).waitFor();
    assert.match(await dialog.locator('#pipelineArchiveError').innerText(), /Operação revertida/);
    assert.equal(await dialog.isVisible(), true);
    assert.equal(api.pipeline.pipelineVersion, 1);
    assert.equal((await stateFrom(page)).deals[0].stageId, DEAL_STAGE_IDS[2]);
  }, { preloadState: workspaceWithDeal() });

  await run('PIPE-ADMIN-09 pagina o histórico em blocos de 50 com contexto completo', async page => {
    const api = apiByPage.get(page);
    await goTo(page, 'Funil de negócios');
    const items = page.locator('[data-pipeline-history-item]');
    await items.first().waitFor();
    assert.equal(await items.count(), 50);
    assert.match(await items.first().innerText(), /u-admin/);
    assert.match(await items.first().innerText(), /pipeline.stage_archived/);
    assert.match(await items.first().innerText(), /Antes/i);
    assert.match(await items.first().innerText(), /Depois/i);
    assert.match(await items.first().innerText(), /2 negócio/);
    assert.match(await items.first().innerText(), /01\/10\/2026/);
    await page.getByRole('button', { name: 'Histórico anterior' }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-pipeline-history-item]').length === 5);
    assert.equal(await items.count(), 5);
    assert.equal(api.pipelineHistoryRequests.some(url => url.includes('before=6') && url.includes('limit=50')), true);
    await page.getByRole('button', { name: 'Histórico mais recente' }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-pipeline-history-item]').length === 50);
    assert.equal(await items.count(), 50);
  }, { preloadState: minimalWorkspace(), pipelineHistory: pipelineAuditHistory() });

  await run('PIPE-ADMIN-10 não consulta nem expõe histórico a não administradores', async page => {
    const api = apiByPage.get(page);
    assert.equal(await page.getByRole('button', { name: 'Funil de negócios' }).count(), 0);
    await page.evaluate(() => showView('pipeline-admin'));
    assert.equal(await page.locator('#page-pipeline-admin').isVisible(), false);
    assert.equal(await page.locator('[data-pipeline-history-item]').count(), 0);
    assert.equal(api.pipelineHistoryRequests.length, 0);
  }, { session: SELLER_SESSION, preloadState: minimalWorkspace(), pipelineHistory: pipelineAuditHistory(1) });

  await run('PCCP-01 a PCCP-03 removem avisos de demonstração sem ocultar alertas operacionais', async page => {
    for (const destination of ['Visão geral', 'Leads', 'Contatos', 'Empresas', 'Negócios', 'Notificações']) {
      await goTo(page, destination);
      assert.equal(await page.locator('#workspaceStatus').isVisible(), false);
      assert.equal(await page.getByText('Ambiente local', { exact: true }).count(), 0);
      assert.equal(await page.getByText(/demonstração|demonstrativos|dados fictícios|ambiente local/i).count(), 0);
    }
    assert.equal(await page.title(), 'Smart CRM');

    const unavailableView = await openFresh({ loadFailure: true });
    const unavailable = unavailableView.page;
    await unavailable.locator('#workspaceBanner').waitFor();
    assert.equal(await unavailable.locator('#workspaceStatus').isVisible(), true);
    assert.equal(await unavailable.locator('#workspaceBanner').innerText(), 'Banco indisponível. Alterações bloqueadas.');
    await unavailableView.context.close();
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
