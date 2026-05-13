# JobFinder (Vahan Platform) - Agent Reference

## Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Runtime | Node.js 22.x | PM2 cluster mode for production |
| Language | JavaScript (ES6+) primary | TypeScript for new modules |
| Framework | Express.js 4.x | Main HTTP framework |
| Primary DB | PostgreSQL | Sequelize 6.x ORM, Knex.js for migrations |
| Analytics DB | ClickHouse Cloud | HTTP API, read-only from app (`lib/clickhouseAPI.js`) |
| Cache | Redis 4.x | Sessions, rate limiting, distributed locks |
| Message Queue | RabbitMQ | `amqplib` + `amqp-connection-manager` via `lib/rabbitMq/` |
| Object Storage | AWS S3 (ap-south-1) | CloudFront CDN |
| Error Tracking | Sentry (`@sentry/node` v10) | OpenTelemetry-based auto-instrumentation |
| Logging | Winston 3.x | JSON format, daily rotation, Slack alerts (`lib/logger.js`) |
| APM | Elastic APM | `elastic-apm-node` |
| Auth | JWT + cookie sessions | RBAC via `middlewares/authentication-middleware.js` |
| Templating | EJS | `views/` directory |
| Process Manager | PM2 | `ecosystem.config.js`, `ecosystem.prod.config.js`, `ecosystem.workers.config.js` |
| Package Manager | npm | `package-lock.json` is gitignored |

### Key Libraries
- `lodash`, `underscore` (utility), `moment`/`moment-timezone` (dates)
- `axios` (HTTP client), `multer` (file uploads), `exceljs`/`xlsx` (spreadsheets)
- `json-rules-engine` (business rule evaluation in `lib/ruleEngine/`)
- `puppeteer` (PDF generation), `canvas`/`jimp` (image processing)
- `firebase-admin` (push notifications)
- `zod` (schema validation, used in newer code)

---

## Architecture

### Entry Points

The application has multiple Express entry points, each running as a separate PM2 process:

| File | Purpose |
|------|---------|
| `mitraAPI.js` | **Main API server** - Mitra Leader dashboard backend. Mounts `vahan_leader/` and `hotline/` modules under `/mitra/*` routes. |
| `api.js` | Legacy API server for bot/jobseeker interactions |
| `admin.js` | Admin panel backend |
| `jobseeker-engagement.js` | Jobseeker engagement service |
| `paymentServer.js` | Payment processing server |
| `rpcServer.js` | RPC server (inter-service communication) |
| `hotline-predictive-dialer.js` | Predictive dialer for hotline telecalling |

### Top-Level Directory Structure

```
JobFinder/
  _models/              # Sequelize model definitions (376 models)
  _migrations/          # Legacy db-migrate migration files
  migrations/           # Knex migration files (1027 migrations)
  config/               # Environment-specific JSON configs (database, redis, rabbitMq, etc.)
  lib/                  # Shared libraries and business logic (largest codebase area)
  vahan_leader/         # Feature modules (MVC pattern) - newer code
  hotline/              # Hotline/telecalling feature modules (isolated subsystem)
  routes/               # Express route definitions (admin, payment)
  jobs/                 # Cron jobs and scheduled tasks
  middlewares/          # Express middleware (auth, rate-limit, cache, sentry, idempotency)
  models/               # Legacy Objection.js/Bookshelf models
  mongoModels/          # Mongoose models (Message, School)
  services/             # Standalone service modules (payment, event, razorpay, user-contact)
  domain/               # Domain enums and constants (SuiteCRM types, onboarding columns)
  errors/               # Custom error classes
  utils/                # Functional utilities (retryAsync, groupDuplicates, setDifference)
  webhooks/             # Webhook handlers (controllers/routes/services/middleware pattern)
  views/                # EJS templates for admin UI and emails
  scripts/              # One-off scripts (backfill data, reconciliation)
  standaloneProcess/    # Standalone consumer processes (SMS, LeadSquared, WhatsApp)
  experiments/          # A/B experiment framework (ExperimentManager)
  public/               # Static assets
  tasks/                # Phing task extensions
  doc/                  # Documentation
```

### `vahan_leader/` - Feature Modules (MVC Pattern)

Each module follows a consistent structure: `{feature}.routes.js`, `{feature}.controller.js`, `{feature}.service.js`, plus optional `.constants.js`, `.queries.js`, and helper files.

| Module | Route Mount | Description |
|--------|------------|-------------|
| `leads-page/` | `/mitra/leads` | Leads listing, filters, views, candidate search |
| `referral-page/` | `/mitra/referral` | Single referral submission and management |
| `bulk-upload/` | `/mitra/v2` | Bulk CSV referral upload (also has `columnMappingTemplate.service.js`) |
| `audience-builder/` | `/mitra/audienceBuilder` | Audience segmentation and targeting rules |
| `incentives/` | `/mitra/incentives` | Incentive campaign rules and calculations |
| `payout-dashboard/` | `/mitra/payoutDashboard` | Payout reporting and dashboard |
| `tc-dashboard/` | `/mitra/tcDashboard` | TC (Talent Coordinator) performance dashboard (has `.queries.js`, `.helperFunctions.js`) |
| `download-reports/` | `/mitra/downloadReports` | Report downloads and exports |
| `dc-cohorts/` | `/mitra/dc-cohorts` | DC cohort management (has `actions/`, `consumers/`, `services/` subdirs) |
| `target-campaign/` | `/mitra/campaign` | Target campaign management |
| `target-insight/` | `/mitra/target` | Target insight analytics |
| `referral-webhook/` | `/mitra/webhook` | Referral webhook processing |
| `support-bot/` | `/mitra/support` | Support bot interface |
| `vuf-page/` | `/mitra/vuf` | VUF (Vahan Universal Form) page |
| `oauth-client/` | `/mitra/oauth` | OAuth client management |
| `org-permissions/` | (service only) | Organization permissions (no routes, service only) |
| `logger/` | (internal) | Module-level logging utilities |
| `appsmith-support-tools/` | `/mitra/` | Internal support tools (milestone mapper, Swiggy SOC uniqueness) |
| `tier-progress/` | - | Tier progress tracking |
| `recruitment-events/` | - | Recruitment event management |

### `hotline/` - Telecalling Subsystem (Isolated)

The hotline subsystem is a self-contained telecalling/lead management system mounted under `/mitra/hotline*` routes. Each sub-module follows the same MVC pattern as `vahan_leader/`.

| Module | Route Mount | Description |
|--------|------------|-------------|
| `hotline-leads-listing/` | `/mitra/leadsListing` | Lead listing with query builder, v4 lead dump |
| `hotline-incentives/` | `/mitra/hotlineIncentives` | Hotline-specific incentive and payout management |
| `hotline-incoming-calls/` | `/mitra/hotlineIncomingCalls` | Incoming call handling |
| `hotline-home/` | `/mitra/hotlineHome` | Hotline dashboard home |
| `hotline-app-feature-permissions/` | `/mitra/hotlineAppFeatures` | Feature permission management |
| `hotline-candidate-profile/` | `/mitra/hotlineLeads` | Candidate profile page |
| `hotline-multi-client-referral/` | `/mitra/hotline` | Multi-client referral submission |
| `hotline-lead-scoring/` | - | Lead scoring algorithms |
| `hotline-tc-performance/` | - | TC performance metrics |
| `hotline-predictive-dialer/` | - | Predictive dialer logic |
| `hotline-notifications/` | - | Notification management |
| `kookoo-hotline/` | - | Kookoo IVR integration |
| `plivo-hotline/` | - | Plivo telephony integration |
| `third-party-calls/` | - | Third-party call integrations |
| `whatsapp-automation/` | - | WhatsApp automation flows |
| `ai-auditor/` | - | AI-based auditing |

### `lib/` - Shared Libraries

The `lib/` directory is the largest codebase area. Key subdirectories and files:

| Path | Description |
|------|-------------|
| `lib/rabbitMq/` | RabbitMQ connection management, base consumer class (Template Method pattern), message publisher, queue registry |
| `lib/constants/` | Application-wide constants (enums, Redis keys, client lists, milestones, SMS templates, call statuses) |
| `lib/translations/` | Multi-language string translations (en, hi, bnLatn, guLatn, etc.) |
| `lib/ruleEngine/` | Business rule evaluation using `json-rules-engine` |
| `lib/workflowManagement/` | Form/workflow engine (controllers, elements, workflows, userProfileData) |
| `lib/payment/` | Payment processing (Stripe, URL, utils) |
| `lib/payments-service/` | Payment service integration with queue producer |
| `lib/spreadsheet/` | Google Sheets integration and spreadsheet utilities |
| `lib/nlp/` | Text normalization and translation |
| `lib/rbac/` | Role-based access control core |
| `lib/csv-parser/` | CSV parsing utilities |
| `lib/dvara/` | Dvara financial services integration |
| `lib/uberHero/` | Uber Hero client integration |
| `lib/suitecrm/` | SuiteCRM integration |
| `lib/leadsquared/` | LeadSquared CRM event publisher |
| `lib/logger.js` | Structured Winston logger (see Conventions) |
| `lib/redis.js` | Redis client singleton |
| `lib/util.js` | General utility functions |
| `lib/sms.js` | SMS sending (Kaleyra, Plivo) |
| `lib/firebase.js` | Firebase push notifications |
| `lib/milestones.js` | Milestone tracking logic |
| `lib/bulkUpload.js` | Bulk upload processing |
| `lib/leads.js` | Lead management utilities |
| `lib/mitras.js` | Mitra (partner) management |
| `lib/incentives.js` | Incentive calculation logic |

### `jobs/` - Cron Jobs and Background Tasks

Contains 200+ cron job files. Each file is a standalone Node.js script executed by PM2/cron. Common patterns:

- **Uniqueness checks**: `singleReferralUniquenessTrigger.js`, `reRunUniquenessForClients.js`, `uniquenessPendingCron.js`
- **Communication triggers**: `sendJobAlerts.js`, `trigger-whatsapp-notification.js`, various SMS/IVR jobs
- **Data sync**: `syncOfflineLeadsAndUsers.js`, `updateMoEngageUserDataCron.js`, `uber-document-status-update.js`
- **Payout processing**: `generatePayouts.js`, `populateIncentivePayouts.js`, `hotlineIncentivesPayoutCreateJob.js`
- **Cache warming**: `cache-zepto-ssu-data.js`, `cacheZomatoCities.js`, `contentVideosCache.js`
- **Watchdogs**: `watchdog.js`, `watchdog-uniquenesscheck.js`, `watchdog-paymentQueues.js`
- **Materialized view refresh**: `refresh-mat-view-cron.js`, `update-materialized-views.js`

### `routes/` - Route Definitions

```
routes/
  admin/           # 47 admin route files (auth, leads, companies, content, channels, etc.)
  payment/         # Payment routes (payment.js)
  riderVerification.js  # Rider verification routes
```

Admin routes are mounted by `admin.js`. The `routes/admin/` directory covers admin panel functionality: user management, content uploads, lead management, scheduled interviews, company management, etc.

### Consumer Pattern (RabbitMQ)

Top-level `*Consumer.js` files are RabbitMQ consumers. They extend `lib/rabbitMq/baseConsumer.js` using the Template Method pattern:

```javascript
class MyConsumer extends BaseConsumer {
    constructor() {
        super('QUEUE_KEY', {
            serviceName: 'JF-my-consumer',
            transactionName: 'my-task',
        });
        this.initApm(apm);
    }
    async processMessage(message) {
        // Business logic here
    }
}
new MyConsumer().start();
```

Key consumers: `bulkUploadConsumer.js`, `clientIntegrationsQueueReceiver.js`, `leadScoringConsumer.js`, `referralWebhookConsumer.js`, `gupshupMessageConsumer.js`, `insightGenerationConsumer.js`, `riderVerificationConsumer.js`, `customDownloadRequestsConsumer.js`, `dcCohortBulkReferralConsumer.js`, etc.

### `_models/` and `migrations/`

- **`_models/`**: 376 Sequelize model files. Auto-loaded by `_models/index.js` which reads all `.js` files in the directory and initializes them with Sequelize. Models define PostgreSQL table schemas and associations.
- **`migrations/`**: 1027 Knex migration files (timestamped format: `YYYYMMDDHHMMSS_description.js`). Run via `npm run migrate:up`.
- **`_migrations/`**: Legacy db-migrate migration files.
- **`annotation-migrations/`**: Separate migration set for annotation DB (run via `npm run db-migrate-up`).

### `models/` - Legacy Models

Contains 21 legacy Objection.js model files (User, Job, School, Session, etc.). These predate the Sequelize models in `_models/`.

---

## Commands

All commands from `package.json` scripts:

| Command | Description |
|---------|-------------|
| `npm run lint` | Run ESLint across the project (`eslint .`) |
| `npm run format` | Auto-format with Prettier (`prettier --write "**/*.{js,json,md}"`) |
| `npm run format:check` | Check formatting without writing (`prettier --check "**/*.{js,json,md}"`) |
| `npm test` | Run Mocha tests (`NODE_ENV=testing _mocha --reporter dot --exit --no-timeout`) |
| `npm run unit-tests` | Restore test DB and run tests (`cd test && ./run.sh && cd ..`) |
| `npm run coverage` | Run tests with NYC coverage (`nyc --reporter html --reporter text npm test`) |
| `npm run migrate:up` | Run Knex migrations (`node scripts/run-migration.js`) |
| `npm run db-migrate-up` | Run annotation DB migrations up (`db-migrate` with `annotation-migrations/`) |
| `npm run db-migrate-down` | Run annotation DB migrations down |
| `npm run test:redis` | Run Redis-specific tests (`mocha test/redis-functions.test.js --timeout 10000`) |
| `npm run lint-prompts` | Lint EJS prompt templates (`ejslint` on `views/prompts/`) |

### Pre-commit Hook

Uses `husky` + `lint-staged`. On commit, runs `eslint --fix` on staged `.js` files.

---

## Conventions

### Code Style

**NOTE:** The repo has pre-existing lint violations. Do NOT run `npm run lint` or `npm run format` on the whole repo — it will flag thousands of legacy issues. Linting is applied ONLY to files you change — your new code must be clean, but you don't fix legacy code.

**Follow the existing code style of the file you're editing:**
- Match the indentation of surrounding code (most files use 4 spaces, some use 2)
- Use semicolons (`;`) at end of statements
- Use single quotes (`'`) for strings
- No trailing commas in function args or object literals
- Use `const`/`let`, avoid `var` (unless the surrounding code uses `var`)
- Arrow parens: omit for single param (`x => x`, not `(x) => x`)
- Max line width ~120 chars

**When writing NEW files** (e.g. new modules in `vahan_leader/`), follow this baseline:
```javascript
'use strict';

const logger = require('../lib/logger');

async function myFunction(param) {
    // 4-space indent, semicolons, single quotes
    const result = await someCall(param);
    return { status: true, data: result };
}

module.exports = { myFunction };
```

### Logging

Use the structured Winston logger (`lib/logger.js`):

```javascript
const logger = require('./lib/logger');

// Correct usage
logger.info('user logged in', { userId, role });
logger.error('payment processing failed', { error: err, orderId });

// Anti-patterns (DO NOT):
// logger.error(err)              -- Error as message, loses context
// logger.error('msg', err)       -- Error as second arg, silently ignored
// logger.error('msg', { error: err.toString() }) -- Drops stack trace
```

### Database Queries

- Use Sequelize ORM for all CRUD operations
- Parameterized queries required -- never interpolate user input into SQL strings
- `_models/index.js` provides a legacy operator shim (converts old `{ne: value}` to `{[Op.ne]: value}`)
- Read replicas configured via `config/database_replica.json`

### Module Pattern (vahan_leader)

New feature modules follow MVC in `vahan_leader/`:
- `{feature}.routes.js` - Express router, route definitions
- `{feature}.controller.js` - Request/response handling, input validation
- `{feature}.service.js` - Business logic, DB queries

Service functions return a standard format:
```javascript
{
    status: true/false,
    errorMessage: '' | 'error message',
    data: [] | {} | null
}
```

### Error Tracking

- Sentry v10 with OpenTelemetry auto-instrumentation
- `sentry-instrument.js` must be required before other modules
- Sentry middleware via `middlewares/sentry-middleware.js`

### Auth & RBAC

- JWT tokens for API auth
- Cookie sessions for web UI
- `middlewares/authentication-middleware.js` provides `accessGuard`
- `middlewares/hierarchy-access-middleware.js` provides `validateHierarchyAccess`
- `lib/rbac/rbac-core.js` for role-based access control

### Constants

Centralized in `lib/constants/`:
- `enums.js` - Application-wide enumerations
- `clients.js` - Client company list
- `milestones.js` - Milestone definitions
- `redisKeys.js` - Redis key patterns
- `callStatus.js` - Call status enums
- `smsTemplates.js` - SMS template strings

### File Structure Conventions

- Top-level consumer files: `{name}Consumer.js`
- Top-level uniqueness check files: `{client}UniquenessCheck.js`
- Config files: `config/{name}.json` with environment keys (`development`, `staging`, `production`)
- Cron jobs: standalone files in `jobs/`

---

## Testing

### Framework

- **Mocha** (test runner) with **Chai** (assertions) and **chai-http** (HTTP testing)
- **Sinon** for mocking/stubbing
- **Supertest** for HTTP endpoint testing
- **Proxyquire** for module stubbing
- **NYC** for code coverage

### Test Directory Structure

```
test/
  bootstrap.js          # Test setup: initializes Express app, syncs DB (force: true), flushes Redis
  mocha.opts            # Mocha options: --recursive
  run.sh                # Restores test DB from fixture SQL, then runs npm test
  fixture/
    mesl_test.sql       # Test database seed SQL
  lib/                  # Tests for lib/ modules
    chat.js
    content.js
    formIo.test.js
    leadUpload.js
    localizeContent.js
    scheduledContent.js
    scoring.js
    template.js
    user.js
  jobs/
    sendJobAlerts.js    # Tests for cron jobs
  states/               # State transition tests (21 files covering user state machine)
    applied.js
    hired.js
    interested.js
    profileCreated.js
    ...
  reminder/
    reEngageUsers.js
    reminders.js
  redis-functions.test.js  # Redis-specific tests (run separately via npm run test:redis)
  referee-template-test.js
```

### Test Setup (`bootstrap.js`)

```javascript
const express = require('express');
const app = express();
require('./../config/environment')(app, express);
const db = require('./../_models/index');
const redis = require('./../lib/redis');

beforeEach(function(done) {
    this.timeout(10000);
    db.sequelize.sync({force: true})
    .success(function() {
        redis.flushdb(function(err) {
            done();
        });
    });
});
```

Each test run:
1. Loads Express app configuration
2. Initializes Sequelize with the test DB
3. Before each test: drops and recreates all tables (`sync({force: true})`), flushes Redis

### Running Tests

```bash
# Full test suite (requires test DB)
npm test

# With DB restore + tests
npm run unit-tests

# Redis-specific tests
npm run test:redis

# With coverage
npm run coverage
```

### Test Environment Requirements

| Service | Host | Port | Database |
|---------|------|------|----------|
| PostgreSQL | localhost | 5432 | mesl_test (user: mesl) |
| Redis | localhost | 6379 | DB 0 |
| RabbitMQ | localhost | 5672 | guest/guest |

### Test Mapping

Tests mirror the source structure under `test/`:

| Source Path | Test Path |
|-------------|-----------|
| `lib/*.js` | `test/lib/*.js` |
| `jobs/*.js` | `test/jobs/*.js` |
| `lib/constants/` (state logic) | `test/states/*.js` |
| (reminder logic) | `test/reminder/*.js` |

Note: Test coverage is sparse relative to the codebase size. Most `vahan_leader/` and `hotline/` modules do not have corresponding tests.
