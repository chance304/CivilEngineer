# Deployment & Infrastructure

## Deployment Options

The system supports two deployment models:

| Model | Description | Best For |
|-------|-------------|----------|
| **Cloud SaaS** | Deployed on AWS/GCP/Azure, accessed via browser | Multi-office firms, remote teams |
| **On-Premise** | Deployed on firm's own servers, self-managed | Data privacy requirements, AutoCAD .dwg output |

Both use the same Docker images. On-premise gets an additional AutoCAD worker.

---

## Local Development Stack

`docker-compose.yml` brings up all services with one command:

```yaml
version: "3.9"
services:
  api:
    build: ./infra/docker/Dockerfile.api
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://ce:ce@postgres:5432/civilengineer
      - REDIS_URL=redis://redis:6379/0
      - S3_ENDPOINT=http://minio:9000
      - S3_BUCKET=civilengineer-dev
      - S3_ACCESS_KEY=minioadmin
      - S3_SECRET_KEY=minioadmin
    depends_on: [postgres, redis, minio]
    volumes:
      - ./backend:/app
      - ./backend/knowledge_base:/app/knowledge_base

  worker:
    build: ./infra/docker/Dockerfile.worker
    environment:
      - DATABASE_URL=postgresql://ce:ce@postgres:5432/civilengineer
      - REDIS_URL=redis://redis:6379/0
      - S3_ENDPOINT=http://minio:9000
    depends_on: [postgres, redis, minio]
    volumes:
      - ./backend:/app
      - ./backend/knowledge_base:/app/knowledge_base

  frontend:
    build: ./infra/docker/Dockerfile.frontend
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - NEXT_PUBLIC_WS_URL=ws://localhost:8000
    volumes:
      - ./frontend/src:/app/src

  postgres:
    image: postgres:16
    environment:
      - POSTGRES_USER=ce
      - POSTGRES_PASSWORD=ce
      - POSTGRES_DB=civilengineer
    volumes: [postgres_data:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  minio:
    image: minio/minio
    ports: ["9000:9000", "9001:9001"]
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    command: server /data --console-address ":9001"
    volumes: [minio_data:/data]

volumes:
  postgres_data:
  minio_data:
```

---

## Production Infrastructure (Cloud)

### Architecture Diagram

```
                            Internet
                               │
                          ┌────▼────┐
                          │  CDN    │  (CloudFront / Cloudflare)
                          │ Static  │  Next.js static assets
                          └────┬────┘
                               │
                          ┌────▼────┐
                          │  Nginx  │  TLS termination + rate limiting
                          └────┬────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
         ┌────▼────┐     ┌────▼────┐     ┌────▼────┐
         │ API Pod │     │ API Pod │     │  Next.js│
         │ (x3)    │     │ (x3)    │     │  Pod(x2)│
         └────┬────┘     └────┬────┘     └─────────┘
              │               │
         ┌────▼────────────────────────────────────┐
         │            Redis Cluster                 │
         │  (job queue + pub/sub + rate limit)      │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
    ┌────▼────┐          ┌────▼────┐          ┌────▼────┐
    │ Worker  │          │ Worker  │          │ Worker  │
    │ Pod (x2)│          │ Pod (x2)│          │ Pod (x2)│
    │ General │          │ General │          │ India   │
    └────┬────┘          └─────────┘          └─────────┘
         │
    ┌────▼────────────────────────────────────────┐
    │          PostgreSQL (Primary + Replica)       │
    │    RDS Multi-AZ / CloudSQL HA                │
    └────────────────────┬────────────────────────┘
                         │
    ┌────────────────────▼────────────────────────┐
    │          S3-Compatible Object Storage         │
    │    (Plot DWGs, DXF/PDF outputs, reports)     │
    └─────────────────────────────────────────────┘
```

### Kubernetes Resources

**API Deployment** (`infra/kubernetes/api-deployment.yaml`)
```yaml
replicas: 3
resources:
  requests: { cpu: 250m, memory: 512Mi }
  limits:   { cpu: 1000m, memory: 1Gi }
autoscaling:
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

**Celery Worker Deployment** (`infra/kubernetes/worker-deployment.yaml`)
```yaml
replicas: 2
resources:
  requests: { cpu: 500m, memory: 1Gi }   # Solver is CPU-heavy
  limits:   { cpu: 2000m, memory: 4Gi }
autoscaling:
  minReplicas: 1
  maxReplicas: 8
  # Scale based on Redis queue depth (KEDA recommended)
```

**Worker Queues**
- `default` — general tasks (plot analysis, indexing)
- `design` — design jobs (solver, geometry, drawing)
- `priority` — senior engineer / urgent jobs

---

## Environment Variables

```
# Backend
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://host:6379/0
S3_ENDPOINT=https://s3.amazonaws.com   # or http://minio:9000 for local
S3_BUCKET=civilengineer-prod
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
SECRET_KEY=...                         # JWT signing key (256-bit random)
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
LITELLM_DEFAULT_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=...                  # or OPENAI_API_KEY, etc.
SENTRY_DSN=...

# Frontend
NEXT_PUBLIC_API_URL=https://api.yourfirm.civilengineer.app
NEXT_PUBLIC_WS_URL=wss://api.yourfirm.civilengineer.app
SENTRY_DSN=...
```

---

## Database Setup

### Initial Setup
```bash
# Run migrations
alembic upgrade head

# Seed initial data (first firm + admin user)
python scripts/seed_db.py \
  --firm-name "Your Firm Name" \
  --admin-email admin@yourfirm.com \
  --admin-password "ChangeMe123!"

# Index knowledge bases
python scripts/index_knowledge.py --all-jurisdictions
```

### Migration Workflow
```bash
# Create new migration after schema changes
alembic revision --autogenerate -m "add_project_jurisdiction_column"

# Review generated migration in alembic/versions/
# Apply:
alembic upgrade head

# Rollback:
alembic downgrade -1
```

---

## Nginx Configuration (`infra/nginx/nginx.conf`)

```nginx
server {
    listen 443 ssl http2;
    server_name api.civilengineer.app;

    ssl_certificate     /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Rate limiting (per IP)
    limit_req_zone $binary_remote_addr zone=api:10m rate=60r/m;
    limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;

    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://api:8000;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/v1/auth/login {
        limit_req zone=login;
        proxy_pass http://api:8000;
    }

    # WebSocket upgrade
    location /api/v1/ws {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    # File upload size
    client_max_body_size 100M;
}
```

---

## Monitoring Stack

### Prometheus Metrics (exported by API + workers)

```
civilengineer_design_jobs_total{status, jurisdiction}
civilengineer_design_job_duration_seconds{jurisdiction}
civilengineer_solver_iterations_histogram{jurisdiction}
civilengineer_active_jobs_gauge
civilengineer_plot_analysis_confidence_histogram
civilengineer_api_requests_total{method, path, status}
civilengineer_api_latency_seconds{method, path}
```

### Alerts
```
AlertRule: DesignJobFailureHigh
  condition: rate(design_jobs_total{status="failed"}[5m]) > 0.1
  message: "Design job failure rate > 10% — check solver logs"

AlertRule: SolverTooSlow
  condition: histogram_quantile(0.95, design_job_duration_seconds) > 120
  message: "95th percentile solver time > 2 minutes — scale workers"

AlertRule: QueueDepthHigh
  condition: celery_queue_length{queue="design"} > 20
  message: "Design queue backlog — consider scaling workers"

AlertRule: DatabaseConnectionFailed
  condition: up{job="postgres"} == 0
  message: "PostgreSQL connection failed — immediate action required"
```

---

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - pytest tests/ --cov=src/civilengineer --cov-report=xml
      - Upload coverage to Codecov

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - pnpm test
      - pnpm build

  build-images:
    needs: [test-backend, test-frontend]
    steps:
      - Build + push Docker images (tagged with git SHA)

  deploy-staging:
    needs: build-images
    environment: staging
    steps:
      - kubectl set image deployment/api api=$IMAGE
      - kubectl rollout status deployment/api

  deploy-production:
    needs: deploy-staging
    environment: production
    if: github.ref == 'refs/heads/main'
    steps:
      - Requires manual approval in GitHub
      - kubectl set image (blue-green deploy)
      - alembic upgrade head (migration)
      - Smoke tests
```

---

## On-Premise Deployment

For firms that need:
- AutoCAD .dwg output (requires Windows + AutoCAD license)
- Data never leaves their servers

Additional components:
1. Standard Docker Compose stack (all cloud services replaced with local equivalents)
2. One Windows Server VM running AutoCAD + the `autocad-worker` container
3. `autocad-worker` uses win32com to control AutoCAD for .dwg generation
4. All other workers use ezdxf (no Windows required)

The system auto-detects which driver to use based on `firm.settings.autocad_enabled`.

```bash
# On-premise setup
docker-compose -f docker-compose.yml -f docker-compose.onprem.yml up -d
```
