"""Bulk loading from Excel files for DCs and Employees."""
import re
import time
from typing import List, Dict, Tuple
from io import BytesIO

# Try openpyxl first, fall back to other methods
try:
    from openpyxl import load_workbook
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from . import db

# Phone number validation: 10+ digits
PHONE_REGEX = re.compile(r'^\d{10,}$')
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


class BulkLoadResult:
    """Track results of bulk import operation."""

    def __init__(self):
        self.success_count = 0
        self.skip_count = 0
        self.error_count = 0
        self.errors: List[Dict] = []
        self.created_ids: List[int] = []
        self.start_time = time.time()

    def to_dict(self):
        """Return dict representation."""
        elapsed = time.time() - self.start_time
        return {
            'success': self.success_count,
            'skipped': self.skip_count,
            'errors': self.error_count,
            'total': self.success_count + self.skip_count + self.error_count,
            'elapsed_seconds': round(elapsed, 2),
            'error_details': self.errors[:50],  # Limit to first 50
            'created_ids': self.created_ids
        }

    def add_error(self, row_num: int, message: str):
        """Record an error."""
        self.error_count += 1
        self.errors.append({
            'row': row_num,
            'message': message
        })

    def add_success(self, record_id: int):
        """Record successful creation."""
        self.success_count += 1
        self.created_ids.append(record_id)

    def add_skip(self):
        """Record skipped row."""
        self.skip_count += 1


def format_phone(phone: str) -> str:
    """Extract only digits from phone number."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', str(phone).strip())
    return digits if digits else None


def validate_phone(phone: str) -> Tuple[bool, str]:
    """Validate phone number (10+ digits)."""
    if not phone:
        return False, "Phone is required"

    formatted = format_phone(phone)
    if not formatted or not PHONE_REGEX.match(formatted):
        return False, "Phone must be 10+ digits"

    return True, formatted


def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email format."""
    if not email or not email.strip():
        return True, None  # Email is optional

    if not EMAIL_REGEX.match(email.strip()):
        return False, "Email format invalid"

    return True, email.strip()


def parse_excel_file(file_content: bytes) -> Tuple[List[Dict], str]:
    """
    Parse Excel file and extract rows.
    Returns: (rows, error_message)
    """
    if not HAS_OPENPYXL:
        return [], "openpyxl not installed"

    try:
        workbook = load_workbook(BytesIO(file_content))
        sheet = workbook.active

        if not sheet:
            return [], "Excel file is empty"

        # Get header row
        header_row = []
        for cell in sheet[1]:
            if cell.value:
                header_row.append(cell.value)

        if not header_row:
            return [], "Excel file has no header row"

        # Normalize headers
        headers = [str(h).strip().lower() for h in header_row]

        # Extract data rows
        rows = []
        for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(row):  # Skip empty rows
                continue

            row_dict = {}
            for col_idx, value in enumerate(row):
                if col_idx < len(headers):
                    row_dict[headers[col_idx]] = value

            if row_dict:
                row_dict['_row_num'] = row_idx
                rows.append(row_dict)

        return rows, None

    except Exception as e:
        return [], f"Error parsing Excel: {str(e)}"


def validate_dc_row(row: Dict, existing_phones: set) -> Tuple[bool, str, Dict]:
    """
    Validate DC row from Excel.
    Returns: (is_valid, error_message, cleaned_data)
    """
    cleaned = {}
    row_num = row.get('_row_num', '?')

    # Name (required)
    name = str(row.get('name', '')).strip() if row.get('name') else ''
    if not name:
        return False, f"Row {row_num}: Name is required", {}
    if len(name) > 255:
        return False, f"Row {row_num}: Name too long (max 255)", {}
    cleaned['name'] = name

    # Phone (required, unique)
    valid, phone_or_error = validate_phone(row.get('phone'))
    if not valid:
        return False, f"Row {row_num}: {phone_or_error}", {}

    if phone_or_error in existing_phones:
        return False, f"Row {row_num}: Phone {phone_or_error} already exists", {}

    cleaned['phone'] = phone_or_error

    # Email (optional)
    valid, email_or_error = validate_email(row.get('email'))
    if not valid:
        return False, f"Row {row_num}: {email_or_error}", {}
    cleaned['email'] = email_or_error

    # Region (optional)
    region = str(row.get('region', '')).strip() if row.get('region') else ''
    if region and len(region) > 100:
        return False, f"Row {row_num}: Region too long (max 100)", {}
    cleaned['region'] = region or None

    return True, None, cleaned


def validate_employee_row(row: Dict, existing_phones: set) -> Tuple[bool, str, Dict]:
    """
    Validate Employee row from Excel.
    Returns: (is_valid, error_message, cleaned_data)
    """
    cleaned = {}
    row_num = row.get('_row_num', '?')

    # Name (required)
    name = str(row.get('name', '')).strip() if row.get('name') else ''
    if not name:
        return False, f"Row {row_num}: Name is required", {}
    if len(name) > 255:
        return False, f"Row {row_num}: Name too long (max 255)", {}
    cleaned['name'] = name

    # Phone (required, unique)
    valid, phone_or_error = validate_phone(row.get('phone'))
    if not valid:
        return False, f"Row {row_num}: {phone_or_error}", {}

    if phone_or_error in existing_phones:
        return False, f"Row {row_num}: Phone {phone_or_error} already exists", {}

    cleaned['phone'] = phone_or_error

    # Email (optional)
    valid, email_or_error = validate_email(row.get('email'))
    if not valid:
        return False, f"Row {row_num}: {email_or_error}", {}
    cleaned['email'] = email_or_error

    # Department (optional)
    department = str(row.get('department', '')).strip() if row.get('department') else ''
    if department and len(department) > 100:
        return False, f"Row {row_num}: Department too long (max 100)", {}
    cleaned['department'] = department or None

    return True, None, cleaned


def bulk_load_dcs(file_content: bytes, created_by: str) -> Dict:
    """
    Bulk load Data Collectors from Excel file.
    Returns: results dict with success/error counts
    """
    result = BulkLoadResult()

    # Parse Excel
    rows, parse_error = parse_excel_file(file_content)
    if parse_error:
        result.add_error(0, parse_error)
        return result.to_dict()

    if not rows:
        result.add_error(0, "No data rows found in Excel file")
        return result.to_dict()

    # Get existing phones
    existing = db.q("SELECT phone FROM dcs WHERE active=1")
    existing_phones = {row['phone'] for row in existing}

    # Validate and create
    for row in rows:
        is_valid, error, cleaned = validate_dc_row(row, existing_phones)

        if not is_valid:
            result.add_error(row['_row_num'], error)
            continue

        try:
            # Check again (race condition)
            exists = db.q("SELECT id FROM dcs WHERE phone=?", (cleaned['phone'],), one=True)
            if exists:
                result.add_error(row['_row_num'], f"Phone {cleaned['phone']} already exists")
                result.add_skip()
                continue

            # Create
            db.execute(
                "INSERT INTO dcs (name, phone, email, region, created_by, created_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (cleaned['name'], cleaned['phone'], cleaned['email'], cleaned['region'], created_by, time.time())
            )

            # Get new ID
            new_dc = db.q("SELECT id FROM dcs WHERE phone=?", (cleaned['phone'],), one=True)
            if new_dc:
                result.add_success(new_dc['id'])
                existing_phones.add(cleaned['phone'])

        except Exception as e:
            result.add_error(row['_row_num'], f"Database error: {str(e)}")

    return result.to_dict()


def bulk_load_employees(file_content: bytes, created_by: str) -> Dict:
    """
    Bulk load Employees from Excel file.
    Returns: results dict with success/error counts
    """
    result = BulkLoadResult()

    # Parse Excel
    rows, parse_error = parse_excel_file(file_content)
    if parse_error:
        result.add_error(0, parse_error)
        return result.to_dict()

    if not rows:
        result.add_error(0, "No data rows found in Excel file")
        return result.to_dict()

    # Get existing phones
    existing = db.q("SELECT phone FROM employees WHERE active=1")
    existing_phones = {row['phone'] for row in existing}

    # Validate and create
    for row in rows:
        is_valid, error, cleaned = validate_employee_row(row, existing_phones)

        if not is_valid:
            result.add_error(row['_row_num'], error)
            continue

        try:
            # Check again (race condition)
            exists = db.q("SELECT id FROM employees WHERE phone=?", (cleaned['phone'],), one=True)
            if exists:
                result.add_error(row['_row_num'], f"Phone {cleaned['phone']} already exists")
                result.add_skip()
                continue

            # Create
            db.execute(
                "INSERT INTO employees (name, phone, email, department, created_by, created_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (cleaned['name'], cleaned['phone'], cleaned['email'], cleaned['department'], created_by, time.time())
            )

            # Get new ID
            new_emp = db.q("SELECT id FROM employees WHERE phone=?", (cleaned['phone'],), one=True)
            if new_emp:
                result.add_success(new_emp['id'])
                existing_phones.add(cleaned['phone'])

        except Exception as e:
            result.add_error(row['_row_num'], f"Database error: {str(e)}")

    return result.to_dict()
