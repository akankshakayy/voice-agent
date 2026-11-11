# Phase 6 - Excel Bulk Import

## Overview
Allow admins to bulk-load Data Collectors and Employees from Excel files. Essential for production deployment when you have 100s of DCs/Employees to load.

## User Flow

1. Admin visits `/admin`
2. Clicks "📥 Bulk Import" button
3. Modal appears with 2 tabs:
   - Import DCs from Excel
   - Import Employees from Excel
4. Selects file from computer
5. Preview shows first 5 rows
6. Clicks "Import" to start
7. Progress bar shows: "Importing 245/300..."
8. Results summary: "✅ 298 created, ⚠️ 2 skipped (duplicates)"
9. Download error report (if any)

## Excel Format

### For DCs:
```
Name              | Phone        | Email                 | Region
Arun Kumar        | 9876543210   | arun@company.com      | Mumbai
Babita Singh      | 9876543211   | babita@company.com    | Delhi
```

**Required:** Name, Phone  
**Optional:** Email, Region

### For Employees:
```
Name              | Phone        | Email                 | Department
Raj Patel         | 8765432109   | raj@company.com       | Sales
Priya Sharma      | 8765432108   | priya@company.com     | Support
```

**Required:** Name, Phone  
**Optional:** Email, Department

## Backend Implementation

### New Endpoints:

1. **POST /api/bulk-load/dcs**
   - Accept: multipart/form-data (Excel file)
   - Parse Excel: openpyxl or pandas
   - Validate each row
   - Create in batches (100 at a time)
   - Return: {success: 298, skipped: 2, errors: [...]}

2. **POST /api/bulk-load/employees**
   - Same as DCs
   - Use employees table instead

3. **GET /api/bulk-load/errors**
   - Return failed rows with reasons
   - Use for error report download

## Validation Rules

### For DCs:
- Name: non-empty string (max 255)
- Phone: valid phone format (10+ digits, no spaces in stored format)
- Email: valid email format (optional)
- Region: non-empty string (optional, max 100)
- Duplicate check: skip if phone already exists

### For Employees:
- Name: non-empty string (max 255)
- Phone: valid phone format (10+ digits)
- Email: valid email format (optional)
- Department: non-empty string (optional, max 100)
- Duplicate check: skip if phone already exists

## Error Handling

### Validation Errors:
- Empty name: "Row 3: Name is required"
- Invalid phone: "Row 5: Phone must be 10+ digits"
- Invalid email: "Row 7: Email format invalid"
- Duplicate phone: "Row 12: Phone 9876543210 already exists"

### File Errors:
- Wrong format: "File must be .xlsx or .xls"
- Empty file: "File is empty"
- Missing columns: "Required column 'Phone' not found"
- Too large: "File > 5MB"

## UI Implementation

### Bulk Import Modal
- Tabs: DCs | Employees
- File input: "Choose file..."
- Preview table: Shows first 5 rows
- Progress bar: Hidden until import starts
- Results summary: Shows after import
- Error report: Downloadable CSV

### Styles
- Consistent with admin panel
- Modal size: 600px wide
- File input: Drag-and-drop support
- Preview table: 5 rows visible
- Progress: 0-100% with label

## Files to Create

1. **app/bulk_load.py** - Core logic
   - parse_excel_file()
   - validate_dc_row()
   - validate_employee_row()
   - bulk_create_dcs()
   - bulk_create_employees()
   - format_phone_number()

2. **app/main.py** - Add endpoints
   - POST /api/bulk-load/dcs
   - POST /api/bulk-load/employees
   - GET /api/bulk-load/errors (optional)

3. **static/admin.html** - Add UI
   - "📥 Bulk Import" button
   - Modal with file input
   - Preview table
   - Progress bar
   - Results summary
   - Error report download

## Testing

### Unit Tests:
- [ ] Parse Excel with valid data
- [ ] Parse Excel with missing columns
- [ ] Validate phone numbers (10+ digits)
- [ ] Validate emails (RFC format)
- [ ] Detect duplicates
- [ ] Batch creation (100 at a time)

### Integration Tests:
- [ ] Upload 500 DCs from Excel
- [ ] Verify all created in database
- [ ] Verify duplicates skipped
- [ ] Verify errors reported

### Manual Tests:
- [ ] Upload small file (5 rows)
- [ ] Upload large file (500+ rows)
- [ ] Cancel mid-import
- [ ] Download error report
- [ ] Verify data in admin panel

## Rollout Plan

1. Create bulk_load.py with core logic
2. Add endpoints to main.py
3. Add UI to admin.html
4. Test with sample Excel files
5. Deploy to production
6. Document in user guide

## Success Metrics

- Import 500 DCs in < 30 seconds
- Accurate duplicate detection
- Clear error messages
- User-friendly UI
- Download error report
