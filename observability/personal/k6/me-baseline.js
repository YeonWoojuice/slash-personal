import http from 'k6/http';
import { check } from 'k6';

const baseUrl = (__ENV.API_BASE_URL || '').replace(/\/$/, '');
const accessToken = __ENV.API_ACCESS_TOKEN;
if (!/^https:\/\/[^/]+$/.test(baseUrl) || !accessToken) {
  throw new Error('Supply HTTPS API_BASE_URL and a personal Cognito API_ACCESS_TOKEN.');
}
export const options = {
  scenarios: {
    me_baseline: {
      executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s',
      duration: '5m', preAllocatedVUs: 5, maxVUs: 10, gracefulStop: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    checks: ['rate==1'],
    dropped_iterations: ['count==0'],
    http_reqs: ['count==1500'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

export default function () {
  const response = http.get(`${baseUrl}/api/v1/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    tags: { name: 'GET /api/v1/me' }, timeout: '5s', redirects: 0,
  });
  let user;
  try { user = response.json('data'); } catch (_) { user = null; }
  check(response, {
    'HTTP 200': (r) => r.status === 200,
    'user response has email': () => user && typeof user.email === 'string' && user.email.length > 0,
    'active user with ID': () => user && typeof user.userId === 'string' && user.userId.length > 0 && user.status === 'ACTIVE',
  });
}

export function handleSummary(data) {
  return {
    '/results/k6-summary.json': JSON.stringify(data, null, 2),
    stdout: JSON.stringify({ metrics: data.metrics }, null, 2) + '\n',
  };
}
