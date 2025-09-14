import unicodedata

def normalize_key(key: str) -> str:
    """
    Normaliza uma chave para facilitar o mapeamento: minúsculas, sem acento, underscores.
    """
    key = key.lower()
    key = unicodedata.normalize('NFD', key).encode('ascii', 'ignore').decode('utf-8')
    key = key.replace(' ', '_')
    key = ''.join(c for c in key if c.isalnum() or c == '_')
    return key

def parse_integer(value: str) -> int:
    return int(value.replace('.', '').replace(',', '').split()[0])

def parse_float_value(value: str) -> float:
    return float(value.replace(',', ''))

def to_title_case(text: str) -> str:
    return text.lower().title()

def only_digits(value: str) -> str:
    return ''.join(filter(str.isdigit, value))

def apply_mapping(parsed_data: list, field_mapping: dict) -> dict:
    header_map = field_mapping['supplier_header_mapping']

    mapped = {
        "suppliers": [],
        "supplier_users": []
    }

    for row in parsed_data:
        normalized_row = {}
        for key, value in row.items():
            normalized_row[normalize_key(key)] = value

        supplier = {}
        user = {}
        external_id = None

        for map_entry in header_map:
            column_key = normalize_key(map_entry['file_column_name'])
            value = normalized_row.get(column_key, None)

            if value is None and map_entry['required']:
                raise ValueError(f'Campo obrigatório "{map_entry["file_column_name"]}" ausente ou inválido.')

            _, table, column = map_entry['db_field'].split('.')

            # Normalização de valores
            parsed_value = value

            if value and isinstance(value, str):
                if column in ['cnpj', 'address_zipcode', 'phone']:
                    parsed_value = only_digits(value)
                elif column == 'email':
                    parsed_value = value.lower()
                elif column == 'address_state':
                    parsed_value = value.upper()
                elif column == 'name' or column.startswith('address_'):
                    parsed_value = to_title_case(value)

            if table == "suppliers":
                supplier[column] = parsed_value
                if column == "external_id":
                    external_id = parsed_value
            elif table == "supplier_users":
                user[column] = parsed_value

        if supplier and external_id:
            mapped['suppliers'].append(supplier)

        if user and user.get('email') and external_id:
            user['external_id'] = external_id
            mapped['supplier_users'].append(user)

    # Eliminar duplicados por external_id
    suppliers_dict = {}
    for supplier in mapped['suppliers']:
        suppliers_dict[supplier['external_id']] = supplier
    mapped['suppliers'] = list(suppliers_dict.values())

    # Eliminar duplicados por email
    supplier_users_dict = {}
    for user in mapped['supplier_users']:
        supplier_users_dict[user['email']] = user
    mapped['supplier_users'] = list(supplier_users_dict.values())

    # Ordenar os arrays
    mapped['suppliers'].sort(key=lambda x: x['external_id'])
    mapped['supplier_users'].sort(key=lambda x: x['email'])

    return mapped
