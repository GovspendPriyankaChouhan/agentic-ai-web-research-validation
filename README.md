# Agentic AI Web Research & Entity Validation

An AI-assisted research and validation workflow for extracting structured information from U.S. government and public-sector entities.

The project uses **OpenAI GPT** and **Google Gemini** workflows to research entity records, identify fiscal-year information, validate entity identity using location and organization details, and write structured results into Google Sheets.

---

## Project Overview

The workflow was designed to handle entity research across multiple organization types where names can be ambiguous and important details must be verified against the correct entity.

The current implementation includes three entity categories:

- **Counties**
- **Higher Education**
- **Hospitals / Hospital Districts**

Each category has separate **GPT** and **Gemini** implementations, allowing the research workflow to be applied and compared across different AI models.

---

## Entity Types Covered

### 1. Counties

The county workflows research U.S. government entities using:

- Agency/entity name
- State
- Official government sources
- ACFR/CAFR documents
- Audit reports
- Budget documents
- Government websites

The workflow extracts information such as:

- Official entity name
- City
- State
- Fiscal-year start month
- County
- Address

Files:

- `187_Counties_gpt.py`
- `187_Counties_gemini.py`

---

### 2. Higher Education

The higher-education workflows research educational institutions and related government/public entities.

The workflow focuses on identifying the correct organization and extracting structured fiscal-year and location information.

Files:

- `187_HigherEd_gpt.py`
- `187_HigherEd_gemini.py`

---

### 3. Hospitals / Hospital Districts

Hospital research requires additional entity validation because similar hospital names can exist across multiple states and cities.

The hospital workflows use:

- Hospital/entity name
- City
- State
- Official hospital or district sources
- ACFR/CAFR documents
- Audit reports
- CMS / Medicare-related sources
- State filings
- Budget documents
- Bond disclosures

The workflow specifically attempts to distinguish:

- Hospitals
- Hospital districts
- Private hospital systems
- Similarly named entities in other locations

Files:

- `187_Hospitals_gpt.py`
- `187_Hospitals_gemini.py`

---

## Workflow

The overall workflow follows this pattern:

```text
Google Sheets
     │
     ▼
Read Entity Name + Location
     │
     ▼
AI Research Workflow
     │
     ├── OpenAI GPT
     │
     └── Google Gemini
     │
     ▼
Entity Verification
     │
     ├── Name
     ├── City
     ├── State
     └── Entity Type
     │
     ▼
Fiscal Year Research
     │
     ▼
Structured JSON Output
     │
     ▼
Google Sheets
     │
     ├── Official Name
     ├── City
     ├── State
     ├── Fiscal Year Start Month
     ├── County
     ├── Address
     ├── Status
     ├── Token Usage
     └── Processing Time
