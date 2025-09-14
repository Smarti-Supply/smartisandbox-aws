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


def to_title_case(text: str) -> str:
    return text.lower().title()


def only_digits(value: str) -> str:
    return ''.join(filter(str.isdigit, value))


def clean_text_id(value: str) -> str:
    """Remove sufixo '.0' e filtra apenas dígitos, retornando uma string."""
    if value is None:
        return ''
    
    value = str(value).strip()
    if value.endswith('.0'):
        value = value[:-2]

    return ''.join(filter(str.isdigit, value))


def apply_mapping(parsed_data: list, field_mapping: dict) -> dict:
    """
    Aplica mapeamento de campos definindo orders e order_items, parseando valores e eliminando duplicados.
    """
    header_map = field_mapping['supplier_header_mapping']

    # Filtrar linhas completamente vazias
    filtered_data = [row for row in parsed_data if any(v not in (None, '') for v in row.values())]
    print(f"🔍 parsed_data (após filtro): {len(filtered_data)} linhas válidas")
    if filtered_data:
        normalized_headers = [normalize_key(k) for k in filtered_data[0].keys()]
        print("🔍 Headers normalizados detectados:", normalized_headers)
    else:
        print("🔍 Nenhuma linha válida em parsed_data após filtro.")

    mapped = {
        "suppliers": [],
        "supplier_contacts": []
    }

    for row in filtered_data:
        normalized_row = {}
        for key, value in row.items():
            normalized_row[normalize_key(key)] = value

        supplier = {}
        contact = {}
        external_id = None

        for map_entry in header_map:
            column_key = normalize_key(map_entry['file_column_name'].strip())
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
                elif column == 'external_id':
                    parsed_value = clean_text_id(value)

            if table == "suppliers":
                if column == "external_id":
                    external_id = parsed_value
                supplier[column] = parsed_value
            elif table == "supplier_contacts":
                contact[column] = parsed_value

        # Verifica se supplier tem os campos obrigatórios não vazios
        is_valid_supplier = all(supplier.get(field) not in (None, '') for field in ['cnpj', 'name', 'external_id'])

        if is_valid_supplier:
            mapped['suppliers'].append(supplier)

            # Verifica se contact tem os campos obrigatórios não vazios
            is_valid_contact = all(contact.get(field) not in (None, '') for field in ['name', 'email'])

            # Adiciona contact se for válido
            if is_valid_contact:
                contact['external_id'] = external_id
                mapped['supplier_contacts'].append(contact)

    # Eliminar duplicados por external_id
    suppliers_dict = {}
    for supplier in mapped['suppliers']:
        suppliers_dict[supplier['external_id']] = supplier
    mapped['suppliers'] = list(suppliers_dict.values())

    # Eliminar duplicados por email
    supplier_contacts_dict = {}
    for contact in mapped['supplier_contacts']:
        supplier_contacts_dict[contact['email']] = contact
    mapped['supplier_contacts'] = list(supplier_contacts_dict.values())

    # Ordenar os arrays
    mapped['suppliers'].sort(key=lambda x: x['external_id'])
    mapped['supplier_contacts'].sort(key=lambda x: x['email'])

    return mapped
