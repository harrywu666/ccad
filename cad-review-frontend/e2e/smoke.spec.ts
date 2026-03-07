import { expect, test } from '@playwright/test';
import type { Route } from '@playwright/test';

const category = {
  id: 'cat-smoke',
  name: '烟感',
  color: '#222222',
  sort_order: 1,
};

const project = {
  id: 'proj-smoke',
  name: '烟感喷淋图审项目',
  category: category.id,
  tags: null,
  description: null,
  cache_version: 1,
  created_at: '2026-03-05T00:00:00Z',
  status: 'new',
  updated_at: '2026-03-05T00:00:00Z',
};

const threeLine = {
  project_id: project.id,
  summary: {
    total: 0,
    ready: 0,
    missing_png: 0,
    missing_json: 0,
    missing_all: 0,
  },
  items: [],
};

// 功能说明：设置API模拟路由，拦截并返回模拟数据用于测试
async function mockApi(page: Parameters<typeof test.beforeEach>[0]['page']) {
  const handler = async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method().toUpperCase();
    if (!path.startsWith('/api/')) {
      await route.continue();
      return;
    }

    const respond = (payload: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(payload),
      });

    if (method === 'GET' && path === '/api/categories') return respond([category]);
    if (method === 'GET' && path === '/api/projects') return respond([project]);
    if (method === 'GET' && path === `/api/projects/${project.id}`) return respond(project);
    if (method === 'GET' && path === `/api/projects/${project.id}/catalog`) return respond([]);
    if (method === 'GET' && path === `/api/projects/${project.id}/drawings`) return respond([]);
    if (method === 'GET' && path === `/api/projects/${project.id}/dwg`) return respond([]);
    if (method === 'GET' && path === `/api/projects/${project.id}/audit/results`) return respond([]);
    if (method === 'GET' && path === `/api/projects/${project.id}/audit/three-lines`) return respond(threeLine);
    if (method === 'GET' && path === `/api/projects/${project.id}/audit/status`) {
      return respond({
        project_id: project.id,
        status: 'new',
        audit_version: null,
        current_step: null,
        progress: 0,
        total_issues: 0,
        run_status: 'idle',
      });
    }

    return respond({ detail: 'mock_not_found' }, 404);
  };

  await page.route('**/*', handler);
}

// 功能说明：在每个测试用例执行前设置API模拟
test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// 功能说明：测试项目列表页面是否正常渲染，无白屏
test('project list renders without white screen', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '项目列表' })).toBeVisible();
  await expect(page.getByText('烟感喷淋图审项目')).toBeVisible();
  expect(pageErrors).toEqual([]);
});

// 功能说明：测试项目详情页面使用模拟数据正常渲染
test('project detail renders with mocked project payload', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto(`/projects/${project.id}`);
  await expect(page.getByRole('heading', { name: project.name })).toBeVisible();
  await expect(page.getByText('步骤 1: 上传图纸目录')).toBeVisible();
  expect(pageErrors).toEqual([]);
});
