# Ketchup Backend - Technical Architecture

## System Overview

The Ketchup backend is a Python-based social coordination platform that recommends events by aggregating user availability, preferences, and venue data. This document outlines the technical architecture, data flow, and key design decisions.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Server                       │
│              (REST API Gateway, Health Checks)          │
└────────────────┬────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼──────┐  ┌──────▼────────┐
│  API Clients │  │  Data Cache   │
│ (Calendar,   │  │   (Redis)     │
│  Maps)       │  └───────────────┘
└───────┬──────┘
        │
┌───────▼──────────────────┐
│  Data Normalization      │
│  & Validation            │
│  (Pydantic Schemas)      │
└───────┬──────────────────┘
        │
        ├─────────────────┬─────────────────┐
        │                 │                 │
┌───────▼────────┐ ┌─────▼──────┐  ┌──────▼────────┐
│  Firestore     │ │ BigQuery   │  │  Airflow     │
│  (Operations)  │ │(Analytics) │  │(Orchestration)│
└────────────────┘ └────────────┘  └───────────────┘
```

## Technology Stack

### Core Framework
- **FastAPI** - Async REST API framework
- **Pydantic** - Data validation and schema management
- **Python 3.10+** - Language runtime

### Data Processing
- **Pandas** - Data manipulation (future)
- **NumPy** - Numerical operations (future)
- **Scikit-learn** - ML models (Phase 2)

### External Services Integration
- **Google Calendar API** - User availability
- **Google Maps API** - Venue locations and routes

### Data Storage
- **Firestore** - Real-time operational database
- **BigQuery** - Analytics and hypothesis tracking
- **Redis** - Caching layer

### Orchestration & Monitoring
- **Apache Airflow** - Workflow orchestration
- **Langfuse** - LLM request tracing (Phase 2)
- **Prometheus** - Metrics collection (future)

### Testing & Development
- **Pytest** - Unit testing framework
- **Docker Compose** - Local development environment
- **pytest-cov** - Coverage reporting

## Data Flow

### 1. Data Ingestion Pipeline

```
External APIs → API Clients → Raw Data
    ↓
  Calendar API         GoogleCalendarClient       JSON Response
  Google Maps API  →   GoogleMapsClient      →    JSON Response
```

**Flow Details:**
- API clients handle authentication
- Automatic retries with exponential backoff
- Redis caching (24-hour TTL)
- Rate limit handling

### 2. Data Normalization Pipeline

```
Raw Data (various formats) → DataNormalizer → Canonical Schema
    ↓
  {"calendars": {...}}     normalize_calendar_data()     FreeBusyInterval[]
  {"routes": [...]}        normalize_route()             TravelRoute[]
```

**Normalization Functions:**
- `normalize_calendar_data()` - Convert Google Calendar to FreeBusyInterval
- `normalize_google_place()` - Convert Google Places to VenueMetadata
- `deduplicate_venues()` - Remove duplicate venues
- `compress_event_options()` - Optimize for token limits

### 3. Data Validation Pipeline

```
Canonical Schema → DataValidator Logic → Pass/Fail Decision
    ↓
  VenueMetadata ──> validate_venue_metadata()  ──> Stored or Rejected
  CalendarData ──> validate_calendar_intervals() ──> Stored or Rejected
  Coordinates ──> validate_location() ──────────> Stored or Rejected
```

**Validation Checks:**
- Rating: 0.0 - 5.0
- Price Level: 1 - 4
- Coordinates: Valid latitude (-90 to 90°), longitude (-180 to 180°)
- Calendar intervals: No overlaps, positive duration
- Venue deduplication: Same name + location within 100m

### 4. Data Storage Pipeline

```
Validated Data → Storage Layer → Query Services
    ↓
VenueMetadata ──→ Firestore ──→ FastAPI Endpoints
CalendarData ──→ BigQuery ──→ Analytics Queries
UserPreferences ──> Redis Cache ──> Fast Lookups
```

**Collections:**
- **Firestore:** users, groups, venues, calendar_data, votes, event_options, finalized_events, post_event_ratings
- **BigQuery:** users, venues, events, feedback, pipeline_metrics
- **Redis:** venue:*, calendar:*, route:*

## Component Details

### API Clients (`utils/api_clients.py`)

**Base Class: CachedAPIClient**
```python
class CachedAPIClient:
    - Redis caching with TTL
    - Automatic retries (exponential backoff)
    - Session pooling (HTTPAdapter)
    - Error handling and logging
```

**Google Calendar Client**
- `get_freebusy()` - Fetch user calendar availability
- `create_event()` - Create event on calendar

**Google Maps Client**
- `search_places()` - Search for venues by category
- `get_route()` - Calculate distance/duration between locations


### Data Normalizer (`utils/data_normalizer.py`)

**DataNormalizer Class**
- Converts multiple API formats to canonical Pydantic schemas
- Handles timezone conversion
- Deduplicates venues
- Compresses event options

**DataValidator Class**
- Validates schema constraints
- Checks value ranges
- Ensures data consistency
- Provides detailed error messages

### Database Client (`database/firestore_client.py`)

**FirestoreClient Class**
- CRUD operations for all entities
- Singleton pattern for resource efficiency
- Error logging and retry logic
- Collection-based organization

**Methods:**
- User operations: `create_user()`, `get_user()`, `update_user_preferences()`
- Group operations: `create_group()`, `get_group()`
- Venue operations: `store_venue_metadata()`, `get_venue()`
- Vote/feedback: `store_vote()`, `store_post_event_rating()`
- Event management: `store_event_option()`, `store_final_event()`

### Configuration Management (`config/settings.py`)

**Settings Class**
- Pydantic BaseSettings for type-safe config
- Environment variable loading
- Default values for optional settings
- Singleton instance for global access

**Configuration Categories:**
- GCP settings (project, database, credentials)
- API keys (Google)
- Redis configuration
- API resilience (timeout, retries, backoff)
- Feature flags

### Data Schemas (`models/schemas.py`)

**Core Schemas:**
- `User` - User profile and preferences
- `FreeBusyInterval` - Calendar availability
- `CalendarData` - Aggregated user calendar
- `VenueMetadata` - Normalized venue information
- `TravelRoute` - Distance/duration data
- `EventOption` - Generated event suggestion
- `Vote` - User's vote on an event
- `PostEventRating` - Post-event feedback

**Validation:**
- Field constraints (min/max values)
- Custom validators
- Type hints for all fields
- Example data in docstrings

### FastAPI Server (`api/main.py`)

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| GET | `/` | Root endpoint |
| POST | `/api/v1/calendar/extract` | Trigger calendar extraction |
| POST | `/api/v1/venues/search` | Search venues by location |
| GET | `/api/v1/pipeline/status` | Get pipeline metrics |

**Middleware:**
- CORS support for frontend
- Request logging
- Error handling

### Airflow DAG (`pipelines/airflow/dags/daily_etl_dag.py`)

**Tasks:**
1. `extract_calendar_data` - Fetch all users' calendar availability
2. `extract_venue_data` - Search for diverse venue types
3. `normalize_and_validate` - Run schema validation
4. `sync_to_bigquery` - ETL to BigQuery
5. `report_metrics` - Calculate pipeline KPIs

**Schedule:** Daily at 2 AM UTC
**Dependencies:** Linear flow with parallel extraction

## Key Design Decisions

### 1. Pydantic for Data Validation

**Why:**
- Type safety with runtime validation
- Automatic JSON serialization
- Clear error messages
- Built-in FastAPI integration

**Tradeoff:** Overhead for simple types, but catches errors early

### 2. Singleton Pattern for Clients

**Why:**
- Single database connection
- Single Redis cache
- Single API session pool

**Tradeoff:** Global state, but more efficient resource usage

### 3. Firestore for Operational Data

**Why:**
- Real-time updates
- Flexible schema
- GCP integration
- Scales horizontally

**Tradeoff:** Higher cost at scale, eventual consistency

### 4. BigQuery for Analytics

**Why:**
- Powerful SQL analytics
- Cost-effective for large datasets
- Easy hypothesis testing
- Built-in ML integration

**Tradeoff:** Eventual consistency, batch nature

### 5. Redis for Caching

**Why:**
- Fast in-memory access
- 24-hour TTL for API responses
- Reduces API costs and latency

**Tradeoff:** Memory cost, cache invalidation complexity

### 6. Airflow for Orchestration

**Why:**
- Dependency management
- Retry logic
- Monitoring and alerting
- Industry standard

**Tradeoff:** Operational complexity, requires PostgreSQL backend

## Error Handling Strategy

### Levels of Resilience

1. **API Client Level**
   - Automatic retries with exponential backoff
   - Circuit breaker pattern (ready)
   - Request timeouts

2. **Validation Level**
   - Schema validation with Pydantic
   - Business logic validation
   - Detailed error messages

3. **Data Pipeline Level**
   - Fallback values for missing data
   - Data deduplication
   - Partial success handling

4. **Application Level**
   - Graceful degradation
   - Error logging
   - User-friendly error responses

## Performance Optimizations

### Caching Strategy

```
Request → Check Redis Cache → Found → Return Cached Data
                    ↓ Not Found
                    ↓
            Call External API
                    ↓
            Store in Redis (24h TTL)
                    ↓
            Return Data to Client
```

**Cache Keys:**

- `calendar:{user_id}:{date_range}` - Calendar data
- `route:{origin}:{destination}` - Route calculations

### Parallel Processing

- Calendar extraction: Parallel per user
- Venue extraction: Parallel per category
- Data validation: Can be parallelized

### Connection Pooling

- API clients use HTTPAdapter with pool size
- Firestore client reuses connection
- Redis connection pool (built-in)

## Security Considerations

### API Key Management

- Environment variables (never in code)
- `.env` file (never in git via .gitignore)
- GCP Service Account Key (restricted access)

### Data Privacy

- Calendar data: User IDs only, no personal calendar content
- Venue data: Public information only
- Post-event ratings: Anonymized/aggregated

### Input Validation

- All inputs validated via Pydantic
- No SQL injection (Firestore queries)
- CORS protection on API endpoints

## Monitoring & Observability

### Logging

```python
import logging
logger = logging.getLogger(__name__)

logger.debug("Detailed debugging info")
logger.info("Pipeline milestone reached")
logger.warning("Unexpected condition")
logger.error("Operation failed")
```

### Metrics (Future)

- API response times
- Database query latency
- Cache hit rates
- Error rates by type
- Pipeline task duration

### Alerting (Future)

- High error rate (>5%)
- Slow API responses (>30s)
- Failed pipeline tasks
- Database connection issues

## Scalability

### Horizontal Scaling

- Stateless FastAPI instances (scale up/down)
- Redis cluster (sharding)
- Firestore auto-scaling
- BigQuery: Pay-per-query

### Vertical Scaling

- Increase worker processes
- Increase Airflow parallelism
- Increase connection pool sizes

### Bottlenecks

1. **API Rate Limits** → Solution: Caching, request batching
2. **Database Connections** → Solution: Connection pooling
3. **Memory Usage** → Solution: Streaming, pagination
4. **Network I/O** → Solution: Parallel requests, local caching

## Testing Strategy

### Unit Tests (80% coverage target)
- Individual function behavior
- Error conditions
- Edge cases

### Integration Tests
- Component interactions
- End-to-end data flows
- Database operations

### Performance Tests
- Large dataset handling
- Concurrent request handling
- Cache effectiveness

## Deployment

### Local Development
- Docker Compose (Firestore, Redis)
- Development server with hot reload
- Sqlite for development (optional)

### Staging
- GCP Cloud Run for FastAPI
- Cloud Composer for Airflow
- Managed Firestore instance
- Memorystore (Redis)

### Production
- GKE (Kubernetes) for FastAPI
- Cloud Composer for Airflow
- Firestore (multi-region)
- Memorystore Redis (HA)
- BigQuery for analytics

## Future Enhancements

### Phase 2
- LLM integration for event recommendations
- Langfuse for tracing
- Preference learning with embeddings
- RAGAS evaluations

### Phase 3
- Real-time event updates (WebSocket)
- Mobile app integration
- Advanced analytics dashboard
- ML-based demand prediction

---
