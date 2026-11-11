# Phase 5 - Admin Panel UI Specification

## Overview
Admin panel for managing DCs, Employees, and Allowed Numbers. Connects to existing backend APIs (100% complete).

## Pages

### 1. /dcs
- List all Data Collectors
- Create/Edit/Delete DCs
- Search and filter
- Columns: Name, Phone, Region, Status, Created By, Created At

### 2. /employees
- List all Employees
- Create/Edit/Delete Employees
- Search and filter
- Columns: Name, Phone, Department, Status, Created By, Created At

### 3. /allowed-numbers
- List allowed phone numbers by DC
- Add numbers to DC
- Remove numbers from DC
- Columns: DC Name, Phone Number, Description, Added By, Added At

## Backend APIs (All Ready)

### DCs
- GET /api/dcs
- POST /api/dcs
- PATCH /api/dcs/{dc_id}

### Employees
- GET /api/employees
- POST /api/employees
- PATCH /api/employees/{employee_id}

### Allowed Numbers
- GET /api/allowed-numbers
- POST /api/allowed-numbers
- DELETE /api/allowed-numbers/{id}

## UI Features

- Responsive design (mobile-first)
- Search/filter in each table
- Pagination (25 items per page)
- Modal forms for create/edit
- Confirmation dialogs for delete
- Loading states and error handling
- Audit trail (created_by, created_at, updated_at)
- Status indicators (active/inactive)

## Navigation

- Sidebar with links to all 3 pages
- Top bar with user info and logout
- Breadcrumb navigation
