# Enrichment Provider Flow Sequence

_Last updated: 2025-08-23_

This document describes the sequence of operations in the new enrichment provider system, including fallback logic and error handling.

## Sequence Diagram

```mermaid
sequenceDiagram
    participant Client
    participant Orchestrator
    participant EnrichmentRouter
    participant CompanyEnrich
    participant AnymailFinder
    participant Coresignal
    participant Snovio
    participant Database

    Client->>Orchestrator: Start enrichment pipeline
    Orchestrator->>EnrichmentRouter: Initialize with ICP config
    EnrichmentRouter->>EnrichmentRouter: Load provider tiers

    Note over EnrichmentRouter: Provider Tiers:<br/>TIER_0: CompanyEnrich, AnymailFinder<br/>TIER_2: Coresignal, Snovio

    loop For each lead record
        Orchestrator->>EnrichmentRouter: enrich_company(domain)

        Note over EnrichmentRouter: Try TIER_0 providers first

        EnrichmentRouter->>CompanyEnrich: enrich_company(domain)
        CompanyEnrich-->>EnrichmentRouter: Success + CompanyData

        alt Company enrichment successful
            EnrichmentRouter-->>Orchestrator: CompanyData + cost tracking
        else Company enrichment failed
            Note over EnrichmentRouter: Fallback to TIER_2

            EnrichmentRouter->>Coresignal: enrich_company(domain)
            Coresignal-->>EnrichmentRouter: Basic company data (free)
            EnrichmentRouter-->>Orchestrator: Fallback data + cost tracking
        end

        Orchestrator->>EnrichmentRouter: enrich_contacts(domain)

        EnrichmentRouter->>CompanyEnrich: enrich_contacts(domain)
        CompanyEnrich-->>EnrichmentRouter: Contact list + cost

        alt Contact enrichment successful
            EnrichmentRouter-->>Orchestrator: Contact list + cost tracking
        else Contact enrichment failed
            Note over EnrichmentRouter: Fallback to TIER_2

            EnrichmentRouter->>Snovio: enrich_contacts(domain)
            Snovio-->>EnrichmentRouter: Contact list + cost
            EnrichmentRouter-->>Orchestrator: Fallback data + cost tracking
        end

        Orchestrator->>EnrichmentRouter: find_email(contact)

        EnrichmentRouter->>AnymailFinder: find_email(contact)
        AnymailFinder-->>EnrichmentRouter: Email + confidence

        alt Email finding successful
            EnrichmentRouter-->>Orchestrator: Email data + cost tracking
        else Email finding failed
            Note over EnrichmentRouter: No fallback for email finding
            EnrichmentRouter-->>Orchestrator: Failure + cost tracking
        end

        Orchestrator->>Database: Store enriched data
        Database-->>Orchestrator: Confirmation

        Note over EnrichmentRouter: Update provider health metrics
        EnrichmentRouter->>EnrichmentRouter: Track success/failure rates
    end

    Orchestrator->>Client: Return enriched leads + metrics
```

## Flow Chart

```mermaid
flowchart TD
    A[Start Enrichment] --> B[Initialize Router]
    B --> C[Load Provider Tiers]
    C --> D[Process Lead Record]

    D --> E[Company Enrichment]
    E --> F{CompanyEnrich Success?}
    F -->|Yes| G[Use CompanyEnrich Data]
    F -->|No| H[Fallback to Coresignal]
    H --> I{Coresignal Success?}
    I -->|Yes| J[Use Coresignal Data]
    I -->|No| K[Mark Company Enrichment Failed]

    G --> L[Contact Enrichment]
    J --> L
    K --> L

    L --> M{CompanyEnrich Success?}
    M -->|Yes| N[Use CompanyEnrich Contacts]
    M -->|No| O[Fallback to Snovio]
    O --> P{Snovio Success?}
    P -->|Yes| Q[Use Snovio Contacts]
    P -->|No| R[Mark Contact Enrichment Failed]

    N --> S[Email Finding]
    Q --> S
    R --> S

    S --> T{AnymailFinder Success?}
    T -->|Yes| U[Use AnymailFinder Email]
    T -->|No| V[Mark Email Finding Failed]

    U --> W[Store Enriched Data]
    V --> W

    W --> X{More Leads?}
    X -->|Yes| D
    X -->|No| Y[Return Results + Metrics]

    Y --> Z[End]
```

## Provider Selection Logic

### Company Enrichment Priority

1. **CompanyEnrich** (TIER_0) - Primary provider

   - High-quality company data
   - Cost: $0.01 per company
   - Success rate: 95%

2. **Coresignal** (TIER_2) - Fallback provider
   - Basic company information
   - Cost: Free
   - Success rate: 85%

### Contact Enrichment Priority

1. **CompanyEnrich** (TIER_0) - Primary provider

   - Comprehensive contact data
   - Cost: $0.02 per contact list
   - Success rate: 95%

2. **Snovio** (TIER_2) - Fallback provider
   - Contact discovery
   - Cost: $0.01 per contact
   - Success rate: 88%

### Email Finding Priority

1. **AnymailFinder** (TIER_0) - Primary provider

   - Specialized email discovery
   - Cost: $0.012 per email
   - Success rate: 92%

2. **No fallback** - Email finding is critical
   - Mark as failed if primary fails
   - Requires manual intervention

## Error Handling

### Provider Failures

- **Authentication errors**: Log and skip provider
- **Rate limiting**: Implement exponential backoff
- **Network errors**: Retry with backoff
- **Service unavailable**: Mark provider as unhealthy

### Fallback Logic

- **Primary failure**: Automatically try fallback
- **Fallback failure**: Mark operation as failed
- **Partial success**: Return available data
- **Cost tracking**: Track all attempts

### Health Monitoring

- **Success rate tracking**: Monitor provider performance
- **Response time monitoring**: Track provider latency
- **Automatic recovery**: Re-enable healthy providers
- **Manual override**: Force provider selection

## Cost Optimization

### Smart Routing

- **Tier-based selection**: Use best provider first
- **Cost awareness**: Consider provider costs
- **Performance tracking**: Route to best performers
- **Fallback limits**: Prevent excessive fallback costs

### Caching Strategy

- **Company data**: Cache for 30 days
- **Contact data**: Cache for 14 days
- **Email data**: Cache for 7 days
- **Deduplication**: Avoid duplicate requests

## Monitoring and Alerts

### Key Metrics

- **Success rate by provider**: Track performance
- **Cost per lead**: Monitor efficiency
- **Response times**: Identify bottlenecks
- **Fallback frequency**: Measure reliability

### Alert Thresholds

- **Provider failure rate > 10%**: Investigate issues
- **Cost per lead > $0.10**: Review optimization
- **Response time > 5s**: Check provider health
- **Fallback rate > 20%**: Review primary providers

---

**Note**: This sequence diagram represents the current implementation. Future versions may include additional providers or enhanced fallback logic.
