# COMIN Pastifício Management System

A web-based management system for **COMIN Pastifício Artigianale**, an artisanal pasta business in Florianópolis, Brazil.

The project combines operational management with data analytics, replacing disconnected spreadsheets with a structured and traceable system.

> **Status:** Early development — project foundation and database connection completed.

## Project goals

- Centralize business data in a single system.
- Avoid duplicated manual entries.
- Preserve historical prices and costs.
- Track purchases, inventory, production batches, orders and payments.
- Calculate product costs, margins and managerial results.
- Create a reliable analytical layer for future dashboards.
- Serve as a practical portfolio project in software and analytics engineering.

## Planned modules

- Customer management
- Product and ingredient catalog
- Purchases and suppliers
- Inventory and batch traceability
- Recipes and recipe versions
- Multi-stage production
- Orders and deliveries
- Payments and accounts receivable
- Costs, margins and financial results
- Analytical models and dashboards

## Architecture

- **Language:** Python 3.12
- **Web framework:** Django 5.2 LTS
- **Operational database:** PostgreSQL 17
- **Database driver:** psycopg 3
- **Configuration:** environment variables with python-dotenv
- **Version control:** Git and GitHub
- **Planned analytics layer:** dbt and Power BI

## Design principles

- Historical sales and costs must never change retroactively.
- Inventory movements must be traceable by batch.
- Production losses and leftovers must be recorded.
- Financial and managerial results must be analyzed separately.
- Operational data should be entered only once and reused across the system.
- Credentials and real business data must not be stored in the repository.

## Current progress

- [x] Isolated Python environment
- [x] Django project created
- [x] PostgreSQL database configured
- [x] Environment variables protected
- [x] Initial Django migrations applied
- [x] Administration interface validated
- [x] Git repository and GitHub integration
- [ ] Business modules
- [ ] Custom user interface
- [ ] Automated tests
- [ ] Analytical layer
- [ ] Dashboard

## Author

**Marcel Comin**